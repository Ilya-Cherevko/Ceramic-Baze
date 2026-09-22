import os

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://ggestrktvjleraztlawi.supabase.co"
)
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

BASE_URL = "https://zakaz.altacera.ru/load"
TARGET_REGION = "Самарская область"

# Режим прогона: True — ничего не удаляем и не пишем (только смотрим логи)
DRY_RUN = True