import os

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://ggestrktvjleraztlawi.supabase.co"
)
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

BASE_URL = "https://zakaz.altacera.ru/load"

# Регион в API: "Самарская обл" (не "Самарская область")
TARGET_REGION = "Самарская обл"

# Склад для остатков. Пока пусто — берём из территории.
# После диагностики пропишем сюда нужный depot_id.
MANUAL_DEPOT_ID = ""

# True — только логи, ничего не пишем и не удаляем
DRY_RUN = True