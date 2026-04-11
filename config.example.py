# ========= ROUTERS =========
ROUTERS = [
    {
        "name": "router1",
        "url": "http://192.168.1.1",
        "user": "admin",
        "pass": "password"
    },
    {
        "name": "router2",
        "url": "http://192.168.0.1",
        "user": "admin",
        "pass": "password"
    }
]

# ========= INTERVAL =========
CHECK_INTERVAL = 60  # проверка каждые 60 сек

# ========= TELEGRAM =========
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# ========= SMTP =========
SMTP_HOST = ""
SMTP_PORT = 465
SMTP_USER = ""
SMTP_PASS = ""
SMTP_FROM = ""
SMTP_TO = ""

# ========= SYSTEM =========
STATUS_FILE = "/opt/keenetic-monitor/status.json"

# ========= SPEED =========
SPEED_MONITOR_URL = ""
SPEED_UPDATE_INTERVAL = 60
