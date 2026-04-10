import asyncio
import json
import os
import sys
from fastapi import FastAPI, Form, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
from contextlib import asynccontextmanager
from keenetic_api import KeeneticClient
import logging
import httpx
import re
import importlib
import secrets
from urllib.parse import urlparse
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ========= BASE =========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.py")
MAPPING_FILE = os.path.join(BASE_DIR, "mapping.json")

# ========= SPEED =========
# 🔥 теперь берётся из config
sys.path.insert(0, BASE_DIR)
try:
    import config
    SPEED_MONITOR_URL = getattr(config, "SPEED_MONITOR_URL", "")
    SPEED_UPDATE_INTERVAL = getattr(config, "SPEED_UPDATE_INTERVAL", 60)
except:
    SPEED_MONITOR_URL = ""
    SPEED_UPDATE_INTERVAL = 60

# ========= DEFAULT MAPPING =========
DEFAULT_MAPPING = {}

if os.path.exists(MAPPING_FILE):
    with open(MAPPING_FILE, "r") as f:
        NAME_MAPPING = json.load(f)
else:
    NAME_MAPPING = DEFAULT_MAPPING.copy()

# ========= AUTH =========
ADMIN_USER = "admin"
ADMIN_PASSWORD = "admin"  # 🔥 дефолт (поменяют сами)
sessions = {}

# ========= CONFIG =========
try:
    ROUTERS = config.ROUTERS
    CHECK_INTERVAL = getattr(config, 'CHECK_INTERVAL', 300)
    TELEGRAM_TOKEN = getattr(config, 'TELEGRAM_TOKEN', '')
    TELEGRAM_CHAT_ID = getattr(config, 'TELEGRAM_CHAT_ID', '')
    STATUS_FILE = getattr(config, 'STATUS_FILE', os.path.join(BASE_DIR, "status.json"))

    SMTP_HOST = getattr(config, 'SMTP_HOST', '')
    SMTP_PORT = getattr(config, 'SMTP_PORT', 465)
    SMTP_USER = getattr(config, 'SMTP_USER', '')
    SMTP_PASS = getattr(config, 'SMTP_PASS', '')
    SMTP_FROM = getattr(config, 'SMTP_FROM', '')
    SMTP_TO = getattr(config, 'SMTP_TO', '')

except:
    ROUTERS = []
    CHECK_INTERVAL = 300
    TELEGRAM_TOKEN = ''
    TELEGRAM_CHAT_ID = ''
    STATUS_FILE = os.path.join(BASE_DIR, "status.json")
    SMTP_HOST = SMTP_PORT = SMTP_USER = SMTP_PASS = SMTP_FROM = SMTP_TO = ''

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

speed_data = {}
last_youtube_status = {}

# ========= EMAIL =========
async def send_email(subject, body):
    if not SMTP_HOST:
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM or SMTP_USER
        msg['To'] = SMTP_TO
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

    except Exception as e:
        logger.error(e)

# ========= TELEGRAM =========
async def send_telegram(message):
    if not TELEGRAM_TOKEN:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": message}
            )
    except:
        pass

# ========= CORE =========
async def check_router(router):
    client = KeeneticClient(router['url'], router['user'], router['pass'])
    try:
        ok = await client.check_connection()
        return {"name": router['name'], "online": ok, "url": router['url']}
    finally:
        await client.close()

async def fetch_speed_stats():
    global speed_data
    if not SPEED_MONITOR_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(SPEED_MONITOR_URL)
            if r.status_code == 200:
                speed_data = r.json()
    except:
        pass

async def worker():
    last_speed_update = datetime.now() - timedelta(seconds=SPEED_UPDATE_INTERVAL)

    while True:
        try:
            results = await asyncio.gather(*(check_router(r) for r in ROUTERS))
            os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)

            with open(STATUS_FILE, "w") as f:
                json.dump(results, f)

            if (datetime.now() - last_speed_update).total_seconds() >= SPEED_UPDATE_INTERVAL:
                await fetch_speed_stats()
                last_speed_update = datetime.now()

        except Exception as e:
            logger.error(e)

        await asyncio.sleep(CHECK_INTERVAL)

# ========= APP =========
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(worker())
    yield

app = FastAPI(lifespan=lifespan)

# ========= LOGIN =========
@app.get("/login", response_class=HTMLResponse)
async def login_form():
    return """
    <html><body>
    <form method="post">
    <input name="username">
    <input name="password" type="password">
    <button>Login</button>
    </form>
    </body></html>
    """

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        token = secrets.token_urlsafe(32)
        sessions[token] = username
        r = RedirectResponse("/", 303)
        r.set_cookie("session", token)
        return r
    return HTMLResponse("error", 401)

# ========= DASHBOARD =========
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return "<h1>Keenetic Monitor работает 🚀</h1>"

# ========= RUN =========
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
