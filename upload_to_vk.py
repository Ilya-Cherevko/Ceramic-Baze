"""
upload_to_vk.py — загрузка картинок AltaCera в VK Cloud Storage.

Работает локально. Не трогает БД. Пишет кеш vk_uploaded.json.
Можно прервать и продолжить — прогресс сохраняется после каждой коллекции.
"""

import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
from pathlib import Path
from collections import defaultdict

import boto3
import requests
from botocore.exceptions import ClientError

# ========== 1. НАСТРОЙКИ VK ==========
VK_ENDPOINT   = "https://hb.ru-msk.vkcloud-storage.ru"
VK_ACCESS_KEY = "jW"
VK_SECRET_KEY = "fw"
VK_BUCKET     = "ceramic-images"
VK_PREFIX     = "ceramic-images/catalog"      # префикс ключа в бакете
VK_PUBLIC     = "https://ceramic-images.hb.ru-msk.vkcloud-storage.ru"

# ========== 2. НАСТРОЙКИ API ==========
BASE_URL = "https://zakaz.altacera.ru/load"

# ========== 3. ФАЙЛЫ ==========
CACHE_FILE = "vk_uploaded.json"     # URL источника → ключ VK
LOG_FILE   = "upload.log"

# ========== 4. ЧТО ГРУЗИМ ==========
# Ограничение по коллекциям (для теста). Пусто = всё.
# Формат: [(brand, collection), ...]
TEST_COLLECTIONS = [
    ("Alma Ceramica", "Almond"),
    ("Alma Ceramica", "Alpina"),
    ("Alma Ceramica", "Amsterdam"),
    ("New Trend", "Fly"),
    ("New Trend", "Candy"),
    ("New Trend", "Chicago"),
    ("AltaCera", "Fern"),
    ("AltaCera", "Sanders"),
    ("Delacora", None),     # первая попавшаяся
    ("LCM", None),          # первая попавшаяся
]

# ========== 5. Инициализация S3 ==========
s3 = boto3.client(
    "s3",
    endpoint_url=VK_ENDPOINT,
    aws_access_key_id=VK_ACCESS_KEY,
    aws_secret_access_key=VK_SECRET_KEY,
    region_name="ru-msk",
)


# ========== 6. Утилиты ==========
def slugify(s: str) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    s = unicodedata.normalize("NFKD", s)
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    s = "".join(translit.get(c, c) for c in s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def load_cache() -> dict:
    if Path(CACHE_FILE).exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def log(msg: str):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def normalize_collection(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    if " / " in s:
        s = s.split(" / ")[-1]
    s = re.sub(r"\s*\d+(?:[.,]\d+)?\s*[\*x×х]\s*\d+(?:[.,]\d+)?\s*$", "", s)
    s = re.sub(r"\s*\((?:керамогранит|плитка|керамика|мозаика)\)\s*$", "", s, flags=re.IGNORECASE)
    return " ".join(s.split()).strip()


# ========== 7. Скачивание API ==========
def download_zip(fname: str):
    r = requests.get(f"{BASE_URL}/{fname}", timeout=180)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open(z.namelist()[0]) as f:
            return json.load(f)


# ========== 8. VK — проверка существования и загрузка ==========
def vk_exists(key: str) -> bool:
    try:
        s3.head_object(Bucket=VK_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def vk_upload(url: str, key: str) -> str:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    s3.put_object(
        Bucket=VK_BUCKET,
        Key=key,
        Body=r.content,
        ContentType=r.headers.get("Content-Type", "image/jpeg"),
    )
    return f"{VK_PUBLIC}/{key}"


# ========== 9. Основной процесс ==========
def main():
    log("=== Старт загрузки картинок в VK ===")

    cache = load_cache()
    log(f"Кеш загружен: {len(cache)} записей")

    log("Скачиваю category_json...")
    categories = download_zip("category_json.zip")
    log(f"  категорий: {len(categories)}")

    log("Скачиваю tovar_json...")
    tovars = download_zip("tovar_json.zip")
    log(f"  товаров: {len(tovars)}")

    log("Скачиваю picture_json...")
    pictures = download_zip("picture_json.zip")
    log(f"  изображений: {len(pictures)}")

    # Карта: category_id → (brand, collection_clean)
    cat_map = {}
    for item in categories:
        if item.get("deleted") or item.get("archive"):
            continue
        if item.get("is_folder"):
            continue
        if not item.get("parent") or not item.get("parent_id"):
            continue
        cat_map[item["category_id"]] = {
            "brand": item["parent"],
            "brand_slug": slugify(item["parent"]),
            "collection": normalize_collection(item["category"]),
            "collection_slug": slugify(normalize_collection(item["category"])),
        }

    # Карта: tovar_id → category_id
    tovar_to_cat = {}
    for item in tovars:
        if item.get("deleted") or item.get("archive"):
            continue
        tovar_to_cat[item["tovar_id"]] = item.get("category_id")

    # Карта: tovar_id → artikul
    tovar_to_artikul = {}
    for item in tovars:
        tovar_to_artikul[item["tovar_id"]] = item.get("artikul", "") or item["tovar_id"][:8]

    # Карта: uid → [images]
    pic_map = {p["uid"]: p.get("images", []) for p in pictures}

    # Собираем план загрузки: [(url, key, brand, collection)]
    tasks = []
    for tovar_id, cat_id in tovar_to_cat.items():
        if cat_id not in cat_map:
            continue
        c = cat_map[cat_id]
        imgs = pic_map.get(tovar_id, [])
        artikul = tovar_to_artikul.get(tovar_id, tovar_id[:8])
        for n, url in enumerate(imgs, start=1):
            ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
            if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".jfif"):
                ext = ".jpg"
            key = f"{VK_PREFIX}/{c['brand_slug']}/{c['collection_slug']}/{artikul}_{n:02d}{ext}"
            tasks.append({
                "url": url,
                "key": key,
                "brand": c["brand"],
                "collection": c["collection"],
            })

    log(f"Всего картинок для загрузки: {len(tasks)}")

    # Фильтр по TEST_COLLECTIONS (если задан)
    if TEST_COLLECTIONS:
        allowed = set()
        for brand, coll in TEST_COLLECTIONS:
            if coll is None:
                allowed.add(("__any__", brand))
            else:
                allowed.add((brand, coll))
        def is_allowed(t):
            for brand, coll in TEST_COLLECTIONS:
                if coll is None and t["brand"] == brand:
                    return True
                if t["brand"] == brand and t["collection"] == coll:
                    return True
            return False
        tasks = [t for t in tasks if is_allowed(t)]
        log(f"После фильтра TEST_COLLECTIONS: {len(tasks)} картинок")

    # Загрузка
    uploaded_total = 0
    skipped_cache = 0
    skipped_exists = 0
    errors = 0

    # Группируем по (brand, collection) — для логов
    by_collection = defaultdict(list)
    for t in tasks:
        by_collection[(t["brand"], t["collection"])].append(t)

    for (brand, collection), items in sorted(by_collection.items()):
        coll_uploaded = 0
        coll_skipped = 0
        coll_errors = 0
        for t in items:
            url = t["url"]
            key = t["key"]

            # 1. Кеш
            if url in cache:
                skipped_cache += 1
                coll_skipped += 1
                continue

            # 2. head_object
            try:
                if vk_exists(key):
                    cache[url] = key
                    skipped_exists += 1
                    coll_skipped += 1
                    continue
            except Exception as e:
                log(f"  [WARN] head_object {key}: {e}")

            # 3. Загрузка
            try:
                vk_upload(url, key)
                cache[url] = key
                uploaded_total += 1
                coll_uploaded += 1
            except Exception as e:
                errors += 1
                coll_errors += 1
                log(f"  [ERR] {url}: {e}")

        # Сохранение кеша после каждой коллекции
        save_cache(cache)
        log(f"  {brand} / {collection}: +{coll_uploaded} загружено, "
            f"{coll_skipped} пропущено, {coll_errors} ошибок  "
            f"(кеш: {len(cache)})")

    log("\n=== Итог ===")
    log(f"  Загружено:       {uploaded_total}")
    log(f"  Пропущено (кеш): {skipped_cache}")
    log(f"  Пропущено (VK):  {skipped_exists}")
    log(f"  Ошибок:          {errors}")
    log(f"  Всего в кеше:    {len(cache)}")
    log("=== Готово ===")


if __name__ == "__main__":
    main()