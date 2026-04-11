import asyncio
import json
import os
import sys
import datetime
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
# ВНИМАНИЕ: реальный URL удалён, оставьте пустым или укажите свой
SPEED_MONITOR_URL = ""   # замените на ваш endpoint
SPEED_UPDATE_INTERVAL = 60

# ========= DEFAULT MAPPING (будет перезаписан из файла) =========
# Примеры общих названий, не содержащие реальных адресов
DEFAULT_MAPPING = {
    "router1": "Квартира 1",
    "router2": "Офис",
    "router3": "Дача",
    "router4": "Студия",
}

# Загружаем маппинг из файла, если он есть
if os.path.exists(MAPPING_FILE):
    with open(MAPPING_FILE, "r") as f:
        NAME_MAPPING = json.load(f)
else:
    NAME_MAPPING = DEFAULT_MAPPING.copy()

# ========= AUTH =========
ADMIN_USER = "admin"
ADMIN_PASSWORD = "changeme"   # измените пароль при первом запуске
sessions = {}

# ========= CONFIG =========
sys.path.insert(0, BASE_DIR)
try:
    import config
    ROUTERS = config.ROUTERS
    CHECK_INTERVAL = getattr(config, 'CHECK_INTERVAL', 300)
    TELEGRAM_TOKEN = getattr(config, 'TELEGRAM_TOKEN', '')
    TELEGRAM_CHAT_ID = getattr(config, 'TELEGRAM_CHAT_ID', '')
    STATUS_FILE = getattr(config, 'STATUS_FILE', os.path.join(BASE_DIR, "status.json"))
    # SMTP
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
previous_status = {}
last_youtube_status = {}

# ========= EMAIL =========
async def send_email(subject, body):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS or not SMTP_TO:
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM if SMTP_FROM else SMTP_USER
        msg['To'] = SMTP_TO
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info(f"📧 Email sent: {subject}")
    except Exception as e:
        logger.error(f"Email error: {e}")

# ========= TELEGRAM =========
async def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        async with httpx.AsyncClient() as client:
            await client.post(url, json=data, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")

# ========= FIX SPEED =========
def clean_speed(val):
    try:
        val = float(val)
        if val <= 0 or val > 10000:
            return 0
        return round(val, 2)
    except:
        return 0

def clean_ping(val):
    try:
        return round(float(val), 2)
    except:
        return 0

# ========= CORE =========
def reload_config():
    global ROUTERS
    try:
        importlib.reload(config)
        ROUTERS = config.ROUTERS
        logger.info(f"🔄 Перезагрузка конфига: {len(ROUTERS)} роутеров")
    except Exception as e:
        logger.error(e)

def get_current_user(request: Request):
    token = request.cookies.get("session")
    return sessions.get(token)

def require_auth(request: Request):
    if not get_current_user(request):
        raise HTTPException(status_code=303, headers={"Location": "/login"})

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
                logger.info(f"📡 Обновлены данные скорости: {len(speed_data)} ПК")
            else:
                logger.warning(f"Ошибка получения скорости: HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"Ошибка получения скорости: {e}")

async def worker():
    global previous_status, last_youtube_status

    last_speed_update = datetime.now() - timedelta(seconds=SPEED_UPDATE_INTERVAL)
    await fetch_speed_stats()
    last_speed_update = datetime.now()

    # Инициализируем last_youtube_status
    for pc, info in speed_data.items():
        last_youtube_status[pc] = info.get('youtube_ok', False)

    while True:
        try:
            # Проверка роутеров
            results = await asyncio.gather(*(check_router(r) for r in ROUTERS))
            os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
            with open(STATUS_FILE, "w") as f:
                json.dump(results, f, indent=2)

            # Обновляем скорость, если пришло время
            if (datetime.now() - last_speed_update).total_seconds() >= SPEED_UPDATE_INTERVAL:
                await fetch_speed_stats()
                last_speed_update = datetime.now()

                # Отслеживаем изменения YouTube
                for pc, info in speed_data.items():
                    current_yt = info.get('youtube_ok', False)
                    prev_yt = last_youtube_status.get(pc, None)
                    if prev_yt is not None and current_yt != prev_yt:
                        if not current_yt:
                            msg_tg = f"⚠️ <b>{pc}</b>\n❌ YouTube недоступен (VPN отключён?)"
                            msg_email = f"YouTube недоступен для {pc}. Возможно, VPN упал."
                            await send_telegram(msg_tg)
                            await send_email(f"VPN отключён: {pc}", msg_email)
                        else:
                            msg_tg = f"✅ <b>{pc}</b>\n✅ YouTube снова доступен (VPN включён)"
                            msg_email = f"YouTube снова доступен для {pc}. VPN работает."
                            await send_telegram(msg_tg)
                            await send_email(f"VPN включён: {pc}", msg_email)
                    last_youtube_status[pc] = current_yt

        except Exception as e:
            logger.error(e)

        await asyncio.sleep(CHECK_INTERVAL)

# ========= APP =========
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(worker())
    yield

app = FastAPI(lifespan=lifespan)

# ========= AUTH =========
@app.get("/login", response_class=HTMLResponse)
async def login_form():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Вход</title></head>
    <body style="font-family:sans-serif;background:#0a0c10;color:#e1e4e8;display:flex;justify-content:center;align-items:center;height:100vh;margin:0">
        <div style="background:#161b22;padding:20px;border-radius:8px;width:300px">
            <h2>Вход</h2>
            <form method="post">
                <input type="text" name="username" placeholder="Логин" style="width:100%;margin:8px 0;padding:8px;background:#0a0c10;border:1px solid #2d333b;color:#e1e4e8;border-radius:4px">
                <input type="password" name="password" placeholder="Пароль" style="width:100%;margin:8px 0;padding:8px;background:#0a0c10;border:1px solid #2d333b;color:#e1e4e8;border-radius:4px">
                <button type="submit" style="width:100%;background:#238636;color:white;border:none;padding:8px;border-radius:4px">Войти</button>
            </form>
        </div>
    </body>
    </html>
    """

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        token = secrets.token_urlsafe(32)
        sessions[token] = username
        r = RedirectResponse("/", status_code=303)
        r.set_cookie("session", token, httponly=True, max_age=3600*24*7)
        return r
    return HTMLResponse("Неверные логин или пароль", status_code=401)

@app.get("/logout")
async def logout():
    r = RedirectResponse("/")
    r.delete_cookie("session")
    return r

# ========= УПРАВЛЕНИЕ МАППИНГОМ =========
@app.get("/mapping", response_class=HTMLResponse)
async def mapping_page(request: Request, _=Depends(require_auth)):
    rows = "\n".join([f"{k}: {v}" for k, v in NAME_MAPPING.items()])
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset='utf-8'>
        <title>Редактирование имён</title>
        <style>
            body {{ font-family: sans-serif; background: #0a0c10; color: #e1e4e8; padding: 20px; }}
            textarea {{ width: 100%; background: #161b22; color: #e1e4e8; border: 1px solid #2d333b; padding: 8px; }}
            button {{ background: #238636; color: white; border: none; padding: 8px 16px; cursor: pointer; }}
            a {{ color: #58a6ff; text-decoration: none; }}
        </style>
    </head>
    <body>
        <h1>📝 Редактирование имён роутеров</h1>
        <form action="/mapping" method="post">
            <textarea name="data" rows="25" cols="80">{rows}</textarea><br><br>
            <button type="submit">Сохранить</button>
        </form>
        <p>Формат: <code>техническое_имя: отображаемое_имя</code> (каждая пара на новой строке)</p>
        <p><a href="/">← На главную</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/mapping")
async def save_mapping(data: str = Form(...), _=Depends(require_auth)):
    global NAME_MAPPING
    new_mapping = {}
    for line in data.strip().splitlines():
        if ':' not in line:
            continue
        key, val = line.split(':', 1)
        new_mapping[key.strip()] = val.strip()
    if new_mapping:
        NAME_MAPPING = new_mapping
        with open(MAPPING_FILE, "w") as f:
            json.dump(NAME_MAPPING, f, indent=2, ensure_ascii=False)
    return RedirectResponse("/mapping", status_code=303)

# ========= DASHBOARD =========
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    data = []
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            data = json.load(f)

    current_user = get_current_user(request)
    is_auth = current_user is not None

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset='utf-8'>
    <title>Keenetic Monitor</title>
    <meta http-equiv="refresh" content="300">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0c10; color: #e1e4e8; padding: 20px; margin: 0; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid #2d333b; }}
        h1 {{ margin: 0; font-size: 24px; color: #58a6ff; }}
        .stats {{ background: #161b22; padding: 12px 20px; border-radius: 8px; display: flex; gap: 20px; }}
        .stats span {{ color: #58a6ff; font-weight: bold; margin: 0 5px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 16px; }}
        .card {{ background: #161b22; border-radius: 8px; padding: 16px; border: 1px solid #2d333b; transition: 0.2s; }}
        .card:hover {{ border-color: #58a6ff; transform: translateY(-2px); }}
        .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid #2d333b; padding-bottom: 8px; }}
        .card-header h2 {{ margin: 0; font-size: 16px; font-weight: 600; }}
        .card-header a {{ color: #e1e4e8; text-decoration: none; }}
        .card-header a:hover {{ color: #58a6ff; text-decoration: underline; }}
        .status-badge {{ padding: 4px 8px; border-radius: 20px; font-size: 12px; font-weight: 500; cursor: pointer; background: #238636; color: #fff; }}
        .status-offline {{ background: #da3633; }}
        .error {{ color: #da3633; font-size: 13px; padding: 8px 0; }}
        .admin-panel {{ background: #161b22; border-radius: 8px; padding: 20px; margin-bottom: 30px; border: 1px solid #2d333b; }}
        .form-group {{ margin-bottom: 15px; }}
        .form-group label {{ display: block; margin-bottom: 5px; color: #8b949e; font-size: 14px; }}
        .form-group input, .form-group select {{ width: 100%; padding: 8px 12px; background: #0a0c10; border: 1px solid #2d333b; color: #e1e4e8; border-radius: 6px; }}
        .btn {{ padding: 8px 16px; border-radius: 6px; font-size: 14px; font-weight: 500; cursor: pointer; border: none; }}
        .btn-primary {{ background: #238636; color: #fff; }}
        .btn-danger {{ background: #da3633; color: #fff; }}
        .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #2d333b; text-align: right; color: #8b949e; font-size: 12px; }}
        .speed-stats {{ margin-top: 12px; padding-top: 8px; border-top: 1px solid #2d333b; font-size: 13px; }}
        .speed-stats div:first-child {{ font-size: 12px; color: #8b949e; margin-bottom: 6px; }}
        .speed-values {{ display: flex; gap: 16px; margin-top: 6px; }}
        .speed-values span {{ font-weight: 500; }}
        .timestamp {{ font-size: 10px; color: #6e7681; margin-top: 4px; }}
        .auth-links {{ margin-left: auto; display: flex; gap: 15px; align-items: center; }}
        .auth-links a {{ color: #58a6ff; text-decoration: none; }}
        .auth-links a:hover {{ text-decoration: underline; }}
        .nav-links {{ margin: 10px 0; }}
        .nav-links a {{ margin-right: 20px; color: #58a6ff; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📡 Keenetic Monitor</h1>
        <div class="stats">
            <div>Всего: <span>{len(data)}</span></div>
            <div>Онлайн: <span>{sum(1 for r in data if r.get('online'))}</span></div>
        </div>
        <div class="auth-links">
            {'<a href="/logout">Выйти</a>' if is_auth else '<a href="/login">Войти</a>'}
        </div>
    </div>"""

    if is_auth:
        router_names = [r.get('name', '') for r in data if r.get('name') != 'Unknown']
        html += f"""
    <div class="admin-panel">
        <h2>📋 Управление роутерами</h2>
        <div class="row">
            <div>
                <h3>➕ Добавить роутер</h3>
                <form action="/add" method="post">
                    <div class="form-group"><label>Название:</label><input type="text" name="name" required></div>
                    <div class="form-group"><label>URL:</label><input type="text" name="url" required></div>
                    <div class="form-group"><label>Логин:</label><input type="text" name="user" value="admin"></div>
                    <div class="form-group"><label>Пароль:</label><input type="password" name="passwd"></div>
                    <button type="submit" class="btn btn-primary">Добавить</button>
                </form>
            </div>
            <div>
                <h3>➖ Удалить роутер</h3>
                <form action="/delete" method="post">
                    <div class="form-group"><label>Выберите роутер:</label>
                        <select name="name">
                            <option value="">-- Выберите --</option>"""
        for name in router_names:
            html += f'<option value="{name}">{name}</option>'
        html += f"""
                        </select>
                    </div>
                    <button type="submit" class="btn btn-danger">Удалить</button>
                </form>
            </div>
        </div>
        <div class="nav-links">
            <a href="/mapping">✏️ Редактировать отображаемые имена</a>
        </div>
    </div>"""
    else:
        html += '<div class="admin-panel"><p>🔒 Для управления роутерами <a href="/login">войдите</a>.</p></div>'

    html += '<div class="grid">'

    for r in data:
        original_name = r.get('name', 'Unknown')
        online = r.get('online', False)
        url = r.get('url', '#')
        status_class = "status-online" if online else "status-offline"
        status_text = "ONLINE" if online else "OFFLINE"
        display_name = NAME_MAPPING.get(original_name, original_name)

        # Поиск скорости
        speed_info = None
        speed_info = speed_data.get(original_name)
        if not speed_info:
            reverse_mapping = {v: k for k, v in NAME_MAPPING.items()}
            if original_name in reverse_mapping:
                tech_name = reverse_mapping[original_name]
                speed_info = speed_data.get(tech_name)
        if not speed_info and url and url != '#':
            try:
                parsed = urlparse(url)
                ip = parsed.hostname
                for pc, info in speed_data.items():
                    if info.get('ip') == ip:
                        speed_info = info
                        break
            except:
                pass

        vpn_dl = clean_speed(speed_info.get("download_vpn", 0)) if speed_info else 0
        vpn_ul = clean_speed(speed_info.get("upload_vpn", 0)) if speed_info else 0
        vpn_ping = clean_ping(speed_info.get("ping_vpn", 0)) if speed_info else 0
        ru_dl = clean_speed(speed_info.get("download_ru", 0)) if speed_info else 0
        ru_ping = clean_ping(speed_info.get("ping_ru", 0)) if speed_info else 0
        yt_ok = bool(speed_info.get("youtube_ok", False)) if speed_info else False
        yt_text = "✅ YouTube" if yt_ok else "❌ YouTube"
        ts = speed_info.get("time", "") if speed_info else ""

        pc_in_flask = speed_info.get("pc", original_name) if speed_info else original_name
        # Ссылка на детальную страницу (адрес удалён, оставлен плейсхолдер)
        speed_link = "#"   # здесь можно указать ваш endpoint, если он есть

        html += f"""
        <div class="card">
            <div class="card-header">
                <h2><a href="{url}" target="_blank">{display_name}</a></h2>
                <a href="{url}" target="_blank" class="status-badge {status_class}">{status_text} ↗</a>
            </div>"""

        if speed_info:
            html += f"""
            <a href="{speed_link}" target="_blank" style="text-decoration:none; color:inherit;">
                <div class="speed-stats">
                    <div>📡 VPN (speedtest)</div>
                    <div class="speed-values">
                        <span>⬇️ {vpn_dl} Mbps</span>
                        <span>⬆️ {vpn_ul} Mbps</span>
                        <span>⏱️ {vpn_ping} ms</span>
                    </div>
                </div>
                <div class="speed-stats">
                    <div>🇷🇺 Российский канал (Yandex)</div>
                    <div class="speed-values">
                        <span>⬇️ {ru_dl} Mbps</span>
                        <span>⏱️ {ru_ping} ms</span>
                    </div>
                </div>
                <div class="timestamp">{ts}</div>
            </a>
            <div style="margin-top:8px; font-size:12px;">{yt_text}</div>
            """
        else:
            html += '<div class="speed-stats"><div>📡 Нет данных о скорости</div></div>'

        html += "</div>"

    if os.path.exists(STATUS_FILE):
        mod_time = datetime.fromtimestamp(os.path.getmtime(STATUS_FILE))
        html += f"""
    </div>
    <div class="footer">
        Последнее обновление: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</body>
</html>"""
    else:
        html += "</div></body></html>"

    return HTMLResponse(content=html)

# ========= ADD =========
@app.post("/add")
async def add_router(name: str = Form(...), url: str = Form(...), user: str = Form(...), passwd: str = Form(...), _=Depends(require_auth)):
    try:
        with open(CONFIG_PATH, "r") as f:
            content = f.read()
        new_router = f'    {{"name": "{name}", "url": "{url}", "user": "{user}", "pass": "{passwd}"}}'
        match = re.search(r'(ROUTERS\s*=\s*\[)(.*?)(\])', content, re.DOTALL)
        if not match:
            logger.error("ROUTERS not found")
            return RedirectResponse("/", 303)
        start, middle, end = match.groups()
        if middle.strip():
            new_content = content.replace(match.group(0), f'{start}{middle.rstrip()},\n{new_router}{end}')
        else:
            new_content = content.replace(match.group(0), f'{start}\n{new_router}\n{end}')
        with open(CONFIG_PATH, "w") as f:
            f.write(new_content)
        reload_config()
        logger.info(f"✅ Добавлен роутер: {name}")
    except Exception as e:
        logger.error(f"Ошибка добавления: {e}")
    return RedirectResponse("/", 303)

# ========= DELETE =========
@app.post("/delete")
async def delete_router(name: str = Form(...), _=Depends(require_auth)):
    try:
        with open(CONFIG_PATH, "r") as f:
            lines = f.readlines()
        new_lines = []
        skip = False
        for line in lines:
            if f'"{name}"' in line:
                skip = True
                continue
            if skip and line.strip().endswith(','):
                skip = False
                continue
            if not skip:
                new_lines.append(line)
        with open(CONFIG_PATH, "w") as f:
            f.writelines(new_lines)
        reload_config()
        logger.info(f"✅ Удален роутер: {name}")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
    return RedirectResponse("/", 303)

# ========= RUN =========
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
