"""
config.py — список роутеров и настройки.
Секреты хранятся в .env
"""
from pathlib import Path

BASE_DIR = Path(__file__).parent

# Роутеры — добавляй через веб /admin
ROUTERS = []

# Интервал проверки доступности роутеров (секунды)
CHECK_INTERVAL = 300

# Файлы данных
STATUS_FILE    = BASE_DIR / "status.json"
SPEED_FILE     = BASE_DIR / "speed_data.json"    # история speedtest {router: [записи]}
SITES_FILE     = BASE_DIR / "sites_data.json"     # последний статус сайтов {router: данные}
RESTART_FILE   = BASE_DIR / "restart_queue.json"  # очередь команд restart {router: bool}

# История speedtest
SPEED_HISTORY_DAYS = 7        # хранить 7 дней
SPEED_MAX_PER_ROUTER = 7 * 6  # макс записей на роутер (7 дней × 6 записей в день)
