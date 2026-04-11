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

# ========= BASE =========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.py")
MAPPING_FILE = os.path.join(BASE_DIR, "mapping.json")

# ========= CONFIG =========
sys.path.insert(0, BASE_DIR)
try:
    import config
except:
    config = None

ROUTERS = getattr(config, "ROUTERS", [])
CHECK_INTERVAL = getattr(config, "CHECK_INTERVAL", 60)
STATUS_FILE = getattr(config, "STATUS_FILE", os.path.join(BASE_DIR, "status.json"))

# ========= MAPPING =========
try:
    with open(MAPPING_FILE, "r") as f:
        NAME_MAPPING = json.load(f)
except:
    NAME_MAPPING = {}

# ========= AUTH =========
ADMIN_USER = "admin"
ADMIN_PASSWORD = "admin"
sessions = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========= CORE =========
def reload_config():
    global ROUTERS
    try:
        if config:
            importlib.reload(config)
            ROUTERS = config.ROUTERS
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

async def worker():
    while True:
        try:
            results = await asyncio.gather(*(check_router(r) for r in ROUTERS))
            os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
            with open(STATUS_FILE, "w") as f:
                json.dump(results, f, indent=2)
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
    <html><body style="background:#0a0c10;color:white;font-family:sans-serif">
    <h2>Вход</h2>
    <form method="post">
    <input name="username"><br><br>
    <input name="password" type="password"><br><br>
    <button>Войти</button>
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

@app.get("/logout")
async def logout():
    r = RedirectResponse("/")
    r.delete_cookie("session")
    return r

# ========= DASHBOARD =========
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    data = []
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE) as f:
                data = json.load(f)
        except:
            pass

    is_auth = get_current_user(request) is not None

    html = f"""
    <html>
    <head>
    <meta charset="utf-8">
    <title>Keenetic Monitor</title>
    <style>
    body {{background:#0a0c10;color:white;font-family:sans-serif;padding:20px}}
    .card {{background:#161b22;padding:15px;margin-bottom:10px;border-radius:8px}}
    .online {{color:#2ecc71}}
    .offline {{color:#e74c3c}}
    </style>
    </head>
    <body>

    <h1>📡 Keenetic Monitor</h1>
    <div>Всего: {len(data)} | Онлайн: {sum(1 for r in data if r.get('online'))}</div>
    """

    if is_auth:
        html += """
        <h2>➕ Добавить</h2>
        <form method="post" action="/add">
        <input name="name" placeholder="name"><br>
        <input name="url" placeholder="url"><br>
        <input name="user" value="admin"><br>
        <input name="passwd" placeholder="password"><br>
        <button>Добавить</button>
        </form>

        <h2>➖ Удалить</h2>
        <form method="post" action="/delete">
        <input name="name" placeholder="name">
        <button>Удалить</button>
        </form>

        <a href="/logout">Выйти</a>
        """
    else:
        html += '<a href="/login">Войти</a>'

    for r in data:
        name = NAME_MAPPING.get(r.get("name"), r.get("name"))
        status = r.get("online", False)
        cls = "online" if status else "offline"

        html += f"""
        <div class="card">
        <b>{name}</b><br>
        <span class="{cls}">{'ONLINE' if status else 'OFFLINE'}</span><br>
        <a href="{r.get('url')}" target="_blank">Открыть</a>
        </div>
        """

    html += "</body></html>"
    return HTMLResponse(content=html)

# ========= ADD =========
@app.post("/add")
async def add_router(name: str = Form(...), url: str = Form(...), user: str = Form(...), passwd: str = Form(...), _=Depends(require_auth)):
    try:
        with open(CONFIG_PATH, "r") as f:
            content = f.read()

        new_router = f'    {{"name": "{name}", "url": "{url}", "user": "{user}", "pass": "{passwd}"}}'

        match = re.search(r'(ROUTERS\s*=\s*\[)(.*?)(\])', content, re.DOTALL)

        if match:
            start, middle, end = match.groups()

            if middle.strip():
                new_content = content.replace(match.group(0), f'{start}{middle.rstrip()},\n{new_router}{end}')
            else:
                new_content = content.replace(match.group(0), f'{start}\n{new_router}\n{end}')

            with open(CONFIG_PATH, "w") as f:
                f.write(new_content)

            reload_config()

    except Exception as e:
        logger.error(e)

    return RedirectResponse("/", 303)

# ========= DELETE =========
@app.post("/delete")
async def delete_router(name: str = Form(...), _=Depends(require_auth)):
    try:
        with open(CONFIG_PATH, "r") as f:
            lines = f.readlines()

        new_lines = []
        for line in lines:
            if f'"{name}"' not in line:
                new_lines.append(line)

        with open(CONFIG_PATH, "w") as f:
            f.writelines(new_lines)

        reload_config()

    except Exception as e:
        logger.error(e)

    return RedirectResponse("/", 303)

# ========= RUN =========
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
