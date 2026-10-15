"""
main.py — синхронизация каталога с AltaCera (Самарская область).

Режимы:
  DRY_RUN = True  — только логи, ничего не пишем и не удаляем
  DRY_RUN = False — реальное удаление совпадающих и upsert новых

Картинки:
  - Если URL есть в vk_uploaded.json — пишем VK-URL
  - Иначе — оставляем URL AltaCera (fallback)
"""

import csv
import io
import json
import re
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests
from supabase import create_client, Client

from config import (
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    BASE_URL,
    TARGET_REGION,
    DRY_RUN,
    MANUAL_DEPOT_ID,
    SUPPLIER_ID,
)

# ========== 1. Инициализация Supabase ==========
print("SUPABASE_URL set:", bool(SUPABASE_URL))
print("SERVICE_KEY set:", bool(SUPABASE_SERVICE_KEY))
print("SERVICE_KEY len:", len(SUPABASE_SERVICE_KEY or ""))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ========== 2. VK-кеш (какие картинки уже загружены в VK) ==========
VK_CACHE_FILE = "vk_uploaded.json"
VK_PUBLIC_PREFIX = "https://ceramic-images.hb.ru-msk.vkcloud-storage.ru"

vk_cache = {}   # URL источника → ключ в VK
if Path(VK_CACHE_FILE).exists():
    with open(VK_CACHE_FILE, "r", encoding="utf-8") as f:
        vk_cache = json.load(f)
    print(f"VK-кеш загружен: {len(vk_cache)} записей")
else:
    print(f"VK-кеш НЕ найден ({VK_CACHE_FILE}) — все картинки останутся с URL AltaCera")


def vk_url(original_url: str) -> str:
    """Возвращает VK-URL, если картинка уже загружена. Иначе — исходный."""
    key = vk_cache.get(original_url)
    if key:
        return f"{VK_PUBLIC_PREFIX}/{key}"
    return original_url


# ========== 3. Список файлов API ==========
FILES = [
    "territory_json.zip",
    "category_json.zip",
    "tovar_json.zip",
    "balance_json.zip",
    "price_json.zip",
    "picture_json.zip",
]


def download_and_extract():
    data = {}
    for fname in FILES:
        print(f"Скачиваю {fname}...")
        r = requests.get(f"{BASE_URL}/{fname}", timeout=180)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            json_name = z.namelist()[0]
            with z.open(json_name) as f:
                data[fname.replace("_json.zip", "")] = json.load(f)
        print(f"  OK, записей: {len(data[fname.replace('_json.zip', '')])}")
    return data


# ========== 4. Диагностика ==========
def debug_territories(territory_data):
    print("=== Все территории (полный список) ===")
    for t in territory_data:
        areas = ", ".join(a.get("area", "") for a in t.get("territory", []))
        print(
            f"  price_list={t.get('price_list')!r} | "
            f"type_price={t.get('type_price')!r} | "
            f"depot={t.get('depot')!r} | "
            f"price_id={t['type_price_id']} | "
            f"depot_id={t['depot_id']} | "
            f"areas=[{areas}]"
        )


def debug_balances(data):
    print("=== Остатки по складам (free_balance > 0) ===")
    counter = Counter()
    for b in data["balance"]:
        if b.get("free_balance", 0) > 0:
            counter[b["depot_id"]] += 1

    depot_names = {t["depot_id"]: t.get("depot") for t in data["territory"]}
    for depot_id, cnt in counter.most_common():
        print(f"  {cnt:>7} позиций | {depot_names.get(depot_id, '(нет в territory)')} | {depot_id}")


def debug_prices(data):
    print("=== Цены по прайсам ===")
    for pl in data["price"]:
        cnt = len(pl["price_list"])
        print(f"  {cnt:>7} позиций | price_id={pl['type_price_id']}")


# ========== 5. Параметры Самары ==========
def get_territory_params(territory_data):
    price_id = None
    for t in territory_data:
        for area in t.get("territory", []):
            if area.get("area") == TARGET_REGION:
                price_id = t["type_price_id"]
                break

    if not price_id:
        raise ValueError(f"Регион не найден: {TARGET_REGION}")

    if MANUAL_DEPOT_ID:
        print(f"Использую MANUAL_DEPOT_ID={MANUAL_DEPOT_ID}")
        return {"type_price_id": price_id, "depot_id": MANUAL_DEPOT_ID}

    for t in territory_data:
        for area in t.get("territory", []):
            if area.get("area") == TARGET_REGION:
                return {"type_price_id": t["type_price_id"], "depot_id": t["depot_id"]}

    raise ValueError(f"Не удалось определить depot_id для {TARGET_REGION}")


# ========== 6. Извлечение размера ==========
def extract_size(tovar_item):
    m = re.search(
        r"(\d+(?:[.,]\d+)?)\s*[\*x×х]\s*(\d+(?:[.,]\d+)?)",
        tovar_item.get("tovar", "")
    )
    if m:
        w = m.group(1).replace(",", ".")
        h = m.group(2).replace(",", ".")
        return f"{w}x{h}"
    return None


# ========== 7. Нормализация ==========
def normalize(s: str) -> str:
    s = (s or "").lower().strip()
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("ё", "е")
    s = re.sub(r"\s+", "", s)
    return s


def normalize_collection_name(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    if " / " in s:
        s = s.split(" / ")[-1]
    s = re.sub(r"\s*\d+(?:[.,]\d+)?\s*[\*x×х]\s*\d+(?:[.,]\d+)?\s*$", "", s)
    s = re.sub(
        r"\s*\((?:керамогранит|плитка|керамика|мозаика)\)\s*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    return " ".join(s.split()).strip()


# ========== 8. Сборка коллекций ==========
def build_collections(data, price_id, depot_id):
    collections = {}
    tovars = {}

    # 8.1 Бренды и коллекции
    skipped_folders = 0
    for item in data["category"]:
        if item.get("deleted") or item.get("archive"):
            continue
        if item.get("is_folder"):
            skipped_folders += 1
            continue
        if not item.get("parent") or not item.get("parent_id"):
            continue

        raw_collection = item["category"]
        clean_collection = normalize_collection_name(raw_collection)
        collections[item["category_id"]] = {
            "brand_id": item["parent_id"],
            "brand": item["parent"],
            "collection": clean_collection,
            "collection_raw": raw_collection,
            "category_id": item["category_id"],
            "tovars": [],
            "sizes": set(),
            "has_keramogranit": False,
        }

    print(f"Пропущено папок (is_folder=True): {skipped_folders}")
    print(f"Коллекций после фильтра: {len(collections)}")

    # 8.2 Товары
    for item in data["tovar"]:
        if item.get("deleted") or item.get("archive"):
            continue
        if item.get("not_unload_site"):
            continue
        if item.get("status") == "Снято с производства":
            continue

        cat_id = item.get("category_id")
        if cat_id not in collections:
            continue

        size_str = extract_size(item)
        if size_str:
            collections[cat_id]["sizes"].add(size_str)

        tovar_name = item.get("tovar", "")

        collection_item = (item.get("collection_item") or "").lower()
        if "керамогранит" in collection_item:
            collections[cat_id]["has_keramogranit"] = True

        tovars[item["tovar_id"]] = {
            "tovar_id": item["tovar_id"],
            "artikul": item.get("artikul", ""),
            "name": item.get("name_for_site") or tovar_name,
            "size": size_str,
            "collection_id": cat_id,
        }
        collections[cat_id]["tovars"].append(item["tovar_id"])

    # 8.3 Цены
    prices = {}
    for pl in data["price"]:
        if pl["type_price_id"] != price_id:
            continue
        for p in pl["price_list"]:
            val = round(p["price"]) if p["price"] else 0
            if val > 0:
                prices[p["tovar_id"]] = val

    # 8.4 Остатки
    balances = {}
    for b in data["balance"]:
        if b["depot_id"] != depot_id:
            continue
        balances[b["tovar_id"]] = b["free_balance"]

    # 8.5 Картинки
    pictures = {}
    for pic in data["picture"]:
        pictures[pic["uid"]] = pic.get("images", [])

    return collections, tovars, prices, balances, pictures


# ========== 9. Строки каталога ==========
def build_catalog_rows(collections, tovars, prices, balances, pictures):
    rows = []
    vk_replaced = 0
    vk_fallback = 0

    for cat_id, col in collections.items():
        valid_tovars = []
        for tid in col["tovars"]:
            if tid not in tovars:
                continue
            fb = balances.get(tid, 0)
            if fb <= 0:
                continue
            price = prices.get(tid)

            t = tovars[tid]
            t["price"] = price
            t["free_balance"] = fb

            # Заменяем URL картинок на VK (если есть в кеше)
            raw_images = pictures.get(tid, [])
            vk_images = []
            for u in raw_images:
                vk_u = vk_url(u)
                if vk_u != u:
                    vk_replaced += 1
                else:
                    vk_fallback += 1
                vk_images.append(vk_u)
            t["images"] = vk_images

            valid_tovars.append(t)

        if not valid_tovars:
            continue

        valid_prices = [v["price"] for v in valid_tovars if v["price"]]
        col_price = round(sum(valid_prices) / len(valid_prices)) if valid_prices else None

        size_str = ", ".join(sorted(col["sizes"]))
        category = "Keramogranit" if col["has_keramogranit"] else "Plitka"

        # Интерьеры коллекции тоже через VK
        raw_col_images = pictures.get(cat_id, [])
        col_images = []
        for u in raw_col_images:
            vk_u = vk_url(u)
            if vk_u != u:
                vk_replaced += 1
            else:
                vk_fallback += 1
            col_images.append(vk_u)

        rows.append({
            "supplier_id": SUPPLIER_ID,
            "supplier_category_id": cat_id,
            "supplier_parent_id": col["brand_id"],
            "country": "Россия",
            "name": col["brand"],
            "collection": col["collection"],
            "category": category,
            "size": size_str,
            "price": col_price,
            "tovars": json.dumps([{
                "tovar_id": v["tovar_id"],
                "artikul": v["artikul"],
                "name": v["name"],
                "size": v["size"],
                "price": v["price"],
                "free_balance": v["free_balance"],
                "images": v["images"],
            } for v in valid_tovars], ensure_ascii=False),
            "interiors": json.dumps(col_images, ensure_ascii=False),
        })

    print(f"=== Замена URL на VK ===")
    print(f"  Заменено на VK:     {vk_replaced}")
    print(f"  Осталось AltaCera:  {vk_fallback}")

    return rows


# ========== 10. Экспорт старой базы ==========
def export_old_to_csv():
    resp = (
        supabase.table("catalog")
        .select("*")
        .is_("supplier_id", "null")
        .execute()
    )
    if not resp.data:
        print("Нечего экспортировать.")
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"old_catalog_backup_{ts}.csv"
    with open(fname, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=resp.data[0].keys())
        writer.writeheader()
        writer.writerows(resp.data)
    print(f"Экспортировано {len(resp.data)} строк в {fname}")


# ========== 11. Удаление совпадающих старых ==========
def delete_matched_old_rows(new_rows, dry_run=True):
    new_keys = {
        (normalize(r["name"]), normalize(r["collection"]))
        for r in new_rows
    }
    print(f"Пар (name, collection) в новой выгрузке: {len(new_keys)}")

    resp = (
        supabase.table("catalog")
        .select("id, name, collection")
        .is_("supplier_id", "null")
        .execute()
    )
    old_rows = resp.data
    print(f"Старых записей без supplier_id: {len(old_rows)}")

    matched = [
        row for row in old_rows
        if (normalize(row["name"]), normalize(row["collection"])) in new_keys
    ]

    print(f"К удалению (совпали с AltaCera): {len(matched)}")

    if matched:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"to_delete_{ts}.csv"
        with open(fname, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "name", "collection"])
            writer.writeheader()
            writer.writerows(matched)
        print(f"Список к удалению выгружен в {fname}")

    brand_counts = Counter(row["name"] for row in matched)
    print("Удаляемые по брендам:")
    for brand, cnt in brand_counts.most_common():
        print(f"  {cnt:>4} | {brand}")

    if dry_run:
        print("DRY_RUN = True — удаление пропущено.")
        return matched

    ids = [row["id"] for row in matched]
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        supabase.table("catalog").delete().in_("id", chunk).execute()
        print(f"  удалено {i + len(chunk)} / {len(ids)}")
    print("Удаление завершено.")
    return matched


# ========== 12. Upsert ==========
def upsert_catalog(rows):
    if not rows:
        print("Нет данных для записи")
        return
    print(f"Пишу {len(rows)} записей...")

    # Upsert пачками по 100 — чтобы не упираться в лимиты
    total = 0
    for i in range(0, len(rows), 100):
        chunk = rows[i:i + 100]
        result = supabase.table("catalog").upsert(
            chunk,
            on_conflict="supplier_category_id"
        ).execute()
        total += len(result.data)
        print(f"  записано {total} / {len(rows)}")
    print(f"Готово, вернулось {total} записей")


# ========== 13. Главный поток ==========
def main():
    print("=== Старт синхронизации AltaCera ===")

    data = download_and_extract()

    debug_territories(data["territory"])
    debug_balances(data)
    debug_prices(data)

    params = get_territory_params(data["territory"])
    print(f"Параметры Самары: price_id={params['type_price_id']}, depot_id={params['depot_id']}")

    collections, tovars, prices, balances, pictures = build_collections(
        data, params["type_price_id"], params["depot_id"]
    )
    rows = build_catalog_rows(collections, tovars, prices, balances, pictures)
    print(f"Новых строк к upsert: {len(rows)}")

    # Сводка по категориям
    cat_counter = Counter(r["category"] for r in rows)
    print("=== Сводка по категориям ===")
    for c, n in cat_counter.most_common():
        print(f"  {n:>4} | {c}")

    print("=== Примеры собранных коллекций ===")
    for r in rows[:8]:
        tv = json.loads(r["tovars"])
        it = json.loads(r["interiors"])
        print(
            f"  {r['name']} | {r['collection']} | category={r['category']} | "
            f"size={r['size'][:60]} | price={r['price']} | "
            f"tovars={len(tv)} | interiors={len(it)}"
        )

    export_old_to_csv()
    delete_matched_old_rows(rows, dry_run=DRY_RUN)

    if DRY_RUN:
        print("DRY_RUN = True — upsert пропущен.")
    else:
        upsert_catalog(rows)

    print("=== Готово ===")


if __name__ == "__main__":
    main()