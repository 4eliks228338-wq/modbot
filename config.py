import os
from datetime import timedelta
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Токен бота (рекомендуется хранить в .env или вставить сюда)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# Список ID модераторов/администраторов, которым бот будет слать алерты в ЛС
# Пример: MODERATOR_USER_IDS = [123456789012345678, 987654321098765432]
raw_mod_ids = os.getenv("MODERATOR_USER_IDS", "")
MODERATOR_USER_IDS = [int(i.strip()) for i in raw_mod_ids.split(",") if i.strip().isdigit()]

# ID роли модераторов (если указано, бот может отправлять в ЛС всем участникам с этой ролью)
raw_mod_role = os.getenv("MODERATOR_ROLE_ID", "")
MODERATOR_ROLE_ID = int(raw_mod_role) if raw_mod_role.isdigit() else None

# (Опционально) ID закрытого канала для модераторов на сервере, если хотите дублировать алерты туда
raw_report_ch = os.getenv("REPORT_CHANNEL_ID", "")
REPORT_CHANNEL_ID = int(raw_report_ch) if raw_report_ch.isdigit() else None

# Названия специальных каналов
POLITICS_CHANNEL_KEYWORD = os.getenv("POLITICS_CHANNEL", "дискуссии-не-самых-умных")
FLOOD_CHANNEL_KEYWORD = os.getenv("FLOOD_CHANNEL", "деревенский-туалет")

# Игнорировать сообщения других ботов
IGNORE_BOTS = True

# Система наказаний по варнам (в соответствии с правилами сервера)
# Discord API поддерживает таймаут до 28 дней
WARN_DURATIONS = {
    1: timedelta(minutes=10),      # 1 варн - 10 минут
    2: timedelta(hours=1),         # 2 варн - 1 час
    3: timedelta(days=1),          # 3 варн - 1 день
    4: timedelta(days=7),          # 4 варн - 1 неделя
    5: timedelta(days=28),         # 5 варн - ~1 месяц (максимум таймаута в Discord API)
    6: "BAN_1_MONTH"               # 6 варн - бан на 1 месяц
}
