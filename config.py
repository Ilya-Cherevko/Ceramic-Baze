import os

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://ggestrktvjleraztlawi.supabase.co"
)
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

BASE_URL = "https://zakaz.altacera.ru/load"

# Регион в API: "Самарская обл" (не "Самарская область")
TARGET_REGION = "Самарская обл"

# Склад для остатков: Склад Казань (самый наполненный в Поволжье)
MANUAL_DEPOT_ID = "d1666584-d536-11ec-80f8-00155d5d5700"

# True — только логи, ничего не пишем и не удаляем
DRY_RUN = True