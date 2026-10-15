"""
cleanup_vk.py — удаляет из VK Storage "мусорные" файлы, которых нет в кеше.

Что НЕ удаляется:
  - всё, что есть в vk_uploaded.json (наши правильные загрузки);
  - файлы, загруженные до 25.09.2026 (старые, от 24.09);
  - .emptyFolderPlaceholder.

Режим: DRY_RUN = True — только показать список.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# ========== НАСТРОЙКИ ==========
VK_ENDPOINT   = "https://hb.ru-msk.vkcloud-storage.ru"
VK_ACCESS_KEY = "jW"
VK_SECRET_KEY = "fw"
VK_BUCKET     = "ceramic-images"

CACHE_FILE = "vk_uploaded.json"

# Всё, что загружено РАНЬШЕ этой даты, не трогаем (старые от 24.09)
SAFE_BEFORE = datetime(2026, 9, 25, 0, 0, 0, tzinfo=timezone.utc)

DRY_RUN = True   # True — только показать, False — удалить
# ===============================

s3 = boto3.client(
    "s3",
    endpoint_url=VK_ENDPOINT,
    aws_access_key_id=VK_ACCESS_KEY,
    aws_secret_access_key=VK_SECRET_KEY,
    region_name="ru-msk",
)


def main():
    # 1. Загружаем кеш — «белый список» наших ключей
    if not Path(CACHE_FILE).exists():
        print(f"ОШИБКА: {CACHE_FILE} не найден. Не могу определить, что удалять.")
        return

    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)

    whitelist = set(cache.values())   # URL источника → ключ, нам нужны только ключи
    print(f"В кеше правильных ключей: {len(whitelist)}")

    # 2. Собираем все объекты из VK
    all_objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=VK_BUCKET):
        for obj in page.get("Contents", []):
            all_objects.append(obj)
    print(f"Всего объектов в VK: {len(all_objects)}")

    # 3. Определяем, что удалять
    to_delete = []
    kept_whitelist = 0
    kept_old = 0
    kept_placeholder = 0

    for obj in all_objects:
        key = obj["Key"]
        lm = obj["LastModified"]

        # Служебный файл
        if key.endswith(".emptyFolderPlaceholder"):
            kept_placeholder += 1
            continue

        # Правильные из кеша
        if key in whitelist:
            kept_whitelist += 1
            continue

        # Старые (от 24.09)
        if lm < SAFE_BEFORE:
            kept_old += 1
            continue

        # Всё остальное — мусор
        to_delete.append((key, lm, obj["Size"]))

    # 4. Сводка
    total_mb = sum(o[2] for o in to_delete) / (1024 * 1024)
    print(f"\nОставляем:")
    print(f"  из кеша (новые правильные): {kept_whitelist}")
    print(f"  старые (до 25.09):          {kept_old}")
    print(f"  .emptyFolderPlaceholder:    {kept_placeholder}")
    print(f"\nК удалению (мусор): {len(to_delete)} файлов, {total_mb:.2f} MB")

    # Примеры
    print("\nПервые 30 объектов к удалению:")
    for key, lm, size in to_delete[:30]:
        print(f"  {lm.strftime('%Y-%m-%d %H:%M')} | {size:>10} | {key}")
    if len(to_delete) > 30:
        print(f"  ... и ещё {len(to_delete) - 30}")

    if DRY_RUN:
        print("\nDRY_RUN = True — ничего не удалено.")
        print("Если список правильный — поставьте DRY_RUN = False и запустите снова.")
        return

    # 5. Удаление пачками по 1000
    print("\nУдаление...")
    for i in range(0, len(to_delete), 1000):
        chunk = [{"Key": k} for k, _, _ in to_delete[i:i+1000]]
        s3.delete_objects(Bucket=VK_BUCKET, Delete={"Objects": chunk})
        print(f"  удалено {min(i + 1000, len(to_delete))} / {len(to_delete)}")
    print("\nГотово. Мусор удалён.")


if __name__ == "__main__":
    main()