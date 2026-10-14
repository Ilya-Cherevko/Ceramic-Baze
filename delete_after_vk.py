"""
delete_after_vk.py — удаляет объекты из VK Storage, загруженные ПОСЛЕ указанной даты.

ВНИМАНИЕ: сначала запускать с DRY_RUN = True. Убедиться в списке. Потом — False.
"""

import boto3
from datetime import datetime, timezone

# ====== НАСТРОЙКИ — ЗАМЕНИТЕ НА СВОИ ======
VK_ENDPOINT   = "https://hb.ru-msk.vkcloud-storage.ru"
VK_ACCESS_KEY = "jWFdwcbzVDMHxKiwtWBrz6"
VK_SECRET_KEY = "fwAeWPAF59mRHVcGjQ8W9vLHeW3T1c2cPCXgz9Edn3ZB"
VK_BUCKET     = "ceramic-images"

# Всё, что загружено ПОСЛЕ этой даты — удаляется.
CUTOFF = datetime(2026, 9, 25, 0, 0, 0, tzinfo=timezone.utc)

DRY_RUN = False   # True — только показать, False — удалить
# =========================================

s3 = boto3.client(
    "s3",
    endpoint_url=VK_ENDPOINT,
    aws_access_key_id=VK_ACCESS_KEY,
    aws_secret_access_key=VK_SECRET_KEY,
    region_name="ru-msk",
)

to_delete = []
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=VK_BUCKET):
    for obj in page.get("Contents", []):
        if obj["LastModified"] > CUTOFF:
            to_delete.append((obj["Key"], obj["LastModified"], obj["Size"]))

total_mb = sum(o[2] for o in to_delete) / (1024 * 1024)
print(f"К удалению: {len(to_delete)} объектов")
print(f"Общий размер: {total_mb:.2f} MB ({total_mb/1024:.2f} GB)")

# Первые 30 — для проверки
for key, lm, size in to_delete[:30]:
    print(f"  {lm.strftime('%Y-%m-%d %H:%M')} | {size:>10} | {key}")
if len(to_delete) > 30:
    print(f"  ... и ещё {len(to_delete) - 30}")

if DRY_RUN:
    print("\nDRY_RUN = True — ничего не удалено.")
    print("Убедитесь, что список правильный, поставьте DRY_RUN = False и запустите снова.")
else:
    # Удаляем пачками по 1000 — лимит S3 API
    for i in range(0, len(to_delete), 1000):
        chunk = [{"Key": k} for k, _, _ in to_delete[i:i+1000]]
        s3.delete_objects(Bucket=VK_BUCKET, Delete={"Objects": chunk})
        print(f"  удалено {min(i + 1000, len(to_delete))} / {len(to_delete)}")
    print("\nГотово. Мусор удалён.")

    # ТЕСТ: удалить только первый файл
# if not DRY_RUN and to_delete:
 #    test_key = to_delete[0][0]
 #    print(f"\nТЕСТ: удаляю {test_key}")
 #    s3.delete_object(Bucket=VK_BUCKET, Key=test_key)
 #    print("Готово. Проверьте, что файла больше нет:")
 #    print(f"  https://ceramic-images.hb.ru-msk.vkcloud-storage.ru/{test_key}")