"""
inventory_vk.py — инвентаризация бакета VK Storage.
Только смотрит, ничего не удаляет. Сохраняет CSV со всеми объектами.
"""

import boto3
import csv
from collections import Counter

# ====== НАСТРОЙКИ — ЗАМЕНИТЕ НА СВОИ ======
VK_ENDPOINT   = "https://hb.ru-msk.vkcloud-storage.ru"
VK_ACCESS_KEY = "jWFdwcbzVDMHxKiwtWBrz6"
VK_SECRET_KEY = "fwAeWPAF59mRHVcGjQ8W9vLHeW3T1c2cPCXgz9Edn3ZB"
VK_BUCKET     = "ceramic-images"

CSV_OUT = "vk_inventory.csv"
# =========================================

s3 = boto3.client(
    "s3",
    endpoint_url=VK_ENDPOINT,
    aws_access_key_id=VK_ACCESS_KEY,
    aws_secret_access_key=VK_SECRET_KEY,
    region_name="ru-msk",
)

rows = []
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=VK_BUCKET):
    for obj in page.get("Contents", []):
        rows.append({
            "key": obj["Key"],
            "last_modified": obj["LastModified"].isoformat(),
            "size": obj["Size"],
        })

print(f"Всего объектов: {len(rows)}")
total_mb = sum(r["size"] for r in rows) / (1024 * 1024)
print(f"Общий размер: {total_mb:.2f} MB")

by_day = Counter(r["last_modified"][:10] for r in rows)
print("\nРаспределение по датам загрузки:")
for day in sorted(by_day, reverse=True):
    cnt = by_day[day]
    size_mb = sum(r["size"] for r in rows if r["last_modified"][:10] == day) / (1024 * 1024)
    print(f"  {day} | {cnt:>6} файлов | {size_mb:>8.2f} MB")

with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["key", "last_modified", "size"])
    writer.writeheader()
    writer.writerows(rows)

print(f"\nПолный список сохранён в {CSV_OUT}")