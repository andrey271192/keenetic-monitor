"""
Keenetic Monitor — сервис для проверки доступности роутеров Keenetic
с веб-интерфейсом, аутентификацией и возможностью добавлять/удалять устройства.
"""

import asyncio
import json
import os
import re
import secrets
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import uvicorn
from fastapi import FastAPI, Form, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from keenetic_api import KeeneticClient
import logging
import importlib

# ----------------------------------------------------------------------
# Конфигурация
# ----------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.py"
MAPPING_FILE = BASE_DIR / "mapping.json"

# Загружаем пользовательские настройки
sys.path.insert(0, str(BASE_DIR))
try:
    import config as user_config
except ImportError:
    user_config = None

def _get_attr(name: str, default: Any) -> Any:
    return getattr(user_config, name, default) if user_config else default

ROUTERS: List[Dict] = _get_attr("ROUTERS", [])
CHECK_INTERVAL: int = _get_attr("CHECK_INTERVAL", 60)
STATUS_FILE: Path = Path(_get_attr("STATUS_FILE", BASE_DIR / "status.json"))

ADMIN_USER: str = "admin"
ADMIN_PASSWORD: str = "admin"   # измените на надёжный пароль

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("keenetic-monitor")

# ----------------------------------------------------------------------
# Управление маппингом имён
# ----------------------------------------------------------------------

class NameMapping:
    """Загружает и сохраняет отображаемые имена роутеров."""

    def __init__(self, file_path: Path):
        self._file = file_path
        self._data: Dict[str, str] = self._load()

    def _load(self) -> Dict[str, str]:
        if self._file.exists():
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Не удалось загрузить mapping: {e}")
        return {}

    def save(self) -> None:
        """Сохраняет текущий маппинг в файл."""
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get(self, tech_name: str) -> str:
        """Возвращает отображаемое имя или техническое, если маппинга нет."""
        return self._data.get(tech_name, tech_name)

    def set(self, tech_name: str, display_name: str) -> None:
        self._data[tech_name] = display_name

    def delete(self, tech_name: str) -> None:
        self._data.pop(tech_name, None)

    def all(self) -> Dict[str, str]:
        return self._data.copy()

    def update_from_text(self, text: str) -> None:
        """Обновляет маппинг из строк вида 'ключ: значение' (построчно)."""
        new_mapping = {}
        for line in text.strip().splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            new_mapping[key.strip()] = val.strip()
        if new_mapping:
            self._data = new_mapping
            self.save()


name_mapping = NameMapping(MAPPING_FILE)

# ----------------------------------------------------------------------
# Управление сессиями аутентификации
# ----------------------------------------------------------------------

_sessions: Dict[str, str] = {}   # token -> username

def get_current_user(request: Request) -> Optional[str]:
    token = request.cookies.get("session")
    return _sessions.get(token)

def require_auth(request: Request) -> None:
    if get_current_user(request) is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

# ----------------------------------------------------------------------
# Работа с роутерами
# ----------------------------------------------------------------------

@dataclass
class RouterStatus:
    name: str
    online: bool
    url: str

async def check_single_router(router: Dict) -> RouterStatus:
    """Проверяет доступность одного роутера через KeeneticClient."""
    client = KeeneticClient(router["url"], router["user"], router["pass"])
    try:
        ok = await client.check_connection()
        return RouterStatus(name=router["name"], online=ok, url=router["url"])
    finally:
        await client.close()

async def reload_router_config() -> None:
    """Перезагружает список роутеров из config.py."""
    global ROUTERS
    if user_config:
        importlib.reload(user_config)
        ROUTERS = getattr(user_config, "ROUTERS", [])
        logger.info(f"Конфигурация перезагружена. Роутеров: {len(ROUTERS)}")

# ----------------------------------------------------------------------
# Фоновый воркер
# ----------------------------------------------------------------------

async def worker() -> None:
    """Фоновая задача: периодически проверяет статус роутеров и пишет в файл."""
    while True:
        try:
            results = await asyncio.gather(*(check_single_router(r) for r in ROUTERS))
            STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = [{"name": s.name, "online": s.online, "url": s.url} for s in results]
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.exception("Ошибка в фоновом воркере")
        await asyncio.sleep(CHECK_INTERVAL)

# ----------------------------------------------------------------------
# FastAPI приложение
# ----------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(worker())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Keenetic Monitor", lifespan=lifespan)

# ----------------------------------------------------------------------
# Эндпоинты аутентификации
# ----------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_form() -> str:
    return """
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><title>Вход</title></head>
    <body style="background:#0a0c10;color:#e1e4e8;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;">
        <div style="background:#161b22;padding:2rem;border-radius:12px;width:300px;">
            <h2>Вход в систему</h2>
            <form method="post">
                <input name="username" placeholder="Логин" style="width:100%;margin:8px 0;padding:8px;border-radius:6px;border:1px solid #2d333b;background:#0a0c10;color:white;">
                <input name="password" type="password" placeholder="Пароль" style="width:100%;margin:8px 0;padding:8px;border-radius:6px;border:1px solid #2d333b;background:#0a0c10;color:white;">
                <button type="submit" style="background:#238636;border:none;padding:8px 16px;border-radius:6px;color:white;cursor:pointer;">Войти</button>
            </form>
        </div>
    </body>
    </html>
    """

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)) -> RedirectResponse:
    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        token = secrets.token_urlsafe(32)
        _sessions[token] = username
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("session", token, httponly=True, max_age=3600*24*7)
        return response
    raise HTTPException(status_code=401, detail="Неверные учётные данные")

@app.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/")
    response.delete_cookie("session")
    return response

# ----------------------------------------------------------------------
# Основная страница (дашборд)
# ----------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    # Загружаем текущий статус
    statuses: List[Dict] = []
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                statuses = json.load(f)
        except Exception:
            pass

    is_auth = get_current_user(request) is not None
    online_count = sum(1 for r in statuses if r.get("online"))

    # Генерируем HTML
    html_lines = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<title>Keenetic Monitor</title>',
        '<style>',
        'body{background:#0a0c10;color:#e1e4e8;font-family:sans-serif;padding:20px}',
        '.card{background:#161b22;padding:15px;margin-bottom:10px;border-radius:8px}',
        '.online{color:#2ecc71} .offline{color:#e74c3c}',
        '.admin-panel{background:#161b22;padding:20px;margin-bottom:20px;border-radius:8px}',
        'input,button{padding:8px;margin:4px;border-radius:6px;border:1px solid #2d333b;background:#0a0c10;color:white}',
        'button{background:#238636;cursor:pointer}',
        'a{color:#58a6ff;text-decoration:none}',
        '</style></head><body>',
        f'<h1>📡 Keenetic Monitor</h1>',
        f'<div>Всего: {len(statuses)} | Онлайн: {online_count}</div>'
    ]

    if is_auth:
        html_lines.extend([
            '<div class="admin-panel">',
            '<h2>➕ Добавить роутер</h2>',
            '<form method="post" action="/add">',
            '<input name="name" placeholder="техническое имя" required>',
            '<input name="url" placeholder="http://192.168.1.1" required>',
            '<input name="user" placeholder="логин" value="admin">',
            '<input name="passwd" type="password" placeholder="пароль">',
            '<button type="submit">Добавить</button>',
            '</form>',
            '<h2>➖ Удалить роутер</h2>',
            '<form method="post" action="/delete">',
            '<input name="name" placeholder="техническое имя" required>',
            '<button type="submit">Удалить</button>',
            '</form>',
            '<p><a href="/mapping">✏️ Редактировать отображаемые имена</a></p>',
            '<p><a href="/logout">🚪 Выйти</a></p>',
            '</div>'
        ])
    else:
        html_lines.append('<p><a href="/login">🔑 Войти для управления</a></p>')

    for r in statuses:
        tech_name = r.get("name", "unknown")
        display = name_mapping.get(tech_name)
        status = r.get("online", False)
        cls = "online" if status else "offline"
        status_text = "ONLINE" if status else "OFFLINE"
        url = r.get("url", "#")
        html_lines.append(
            f'<div class="card">'
            f'<b>{display}</b><br>'
            f'<span class="{cls}">{status_text}</span><br>'
            f'<a href="{url}" target="_blank">Открыть</a>'
            f'</div>'
        )

    html_lines.append("</body></html>")
    return HTMLResponse(content="\n".join(html_lines))

# ----------------------------------------------------------------------
# Управление маппингом (только для админа)
# ----------------------------------------------------------------------

@app.get("/mapping", response_class=HTMLResponse)
async def mapping_editor(request: Request, _=Depends(require_auth)) -> HTMLResponse:
    rows = "\n".join(f"{k}: {v}" for k, v in name_mapping.all().items())
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><title>Редактор имён</title>
    <style>
        body{{background:#0a0c10;color:#e1e4e8;font-family:sans-serif;padding:20px}}
        textarea{{width:100%;background:#161b22;color:white;border:1px solid #2d333b;padding:8px}}
        button{{background:#238636;border:none;padding:8px 16px;border-radius:6px;cursor:pointer}}
    </style>
    </head>
    <body>
        <h1>📝 Редактирование имён роутеров</h1>
        <form method="post" action="/mapping">
            <textarea name="data" rows="20" cols="80">{rows}</textarea><br>
            <button type="submit">Сохранить</button>
        </form>
        <p>Формат: <code>техническое_имя: отображаемое_имя</code> (каждая пара на новой строке)</p>
        <p><a href="/">← На главную</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/mapping")
async def save_mapping(data: str = Form(...), _=Depends(require_auth)) -> RedirectResponse:
    name_mapping.update_from_text(data)
    return RedirectResponse("/mapping", status_code=303)

# ----------------------------------------------------------------------
# Добавление / удаление роутеров
# ----------------------------------------------------------------------

def _update_config_file(new_router_line: str, delete_name: Optional[str] = None) -> bool:
    """
    Обновляет файл config.py: добавляет новую строку в список ROUTERS
    или удаляет роутер по имени.
    Возвращает True при успехе.
    """
    if not CONFIG_PATH.exists():
        logger.error(f"Файл {CONFIG_PATH} не найден")
        return False

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Ищем определение ROUTERS = [ ... ]
    pattern = r'(ROUTERS\s*=\s*\[)(.*?)(\])'
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        logger.error("Не найдена переменная ROUTERS в config.py")
        return False

    start, middle, end = match.groups()

    if delete_name:
        # Удаляем строку, содержащую "name": "delete_name"
        lines = middle.splitlines()
        new_lines = []
        for line in lines:
            if f'"{delete_name}"' not in line:
                new_lines.append(line)
        new_middle = "\n".join(new_lines).strip()
    else:
        # Добавляем новую запись
        if middle.strip():
            new_middle = f"{middle.rstrip()},\n{new_router_line}"
        else:
            new_middle = f"\n{new_router_line}\n"

    new_content = content.replace(match.group(0), f"{start}{new_middle}{end}")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True

@app.post("/add")
async def add_router(
    name: str = Form(...),
    url: str = Form(...),
    user: str = Form(...),
    passwd: str = Form(...),
    _=Depends(require_auth)
) -> RedirectResponse:
    """Добавляет новый роутер в config.py."""
    # Экранируем кавычки в значениях
    safe_name = name.replace('"', '\\"')
    safe_url = url.replace('"', '\\"')
    safe_user = user.replace('"', '\\"')
    safe_pass = passwd.replace('"', '\\"')

    new_router = f'    {{"name": "{safe_name}", "url": "{safe_url}", "user": "{safe_user}", "pass": "{safe_pass}"}}'
    if _update_config_file(new_router):
        await reload_router_config()
    return RedirectResponse("/", status_code=303)

@app.post("/delete")
async def delete_router(name: str = Form(...), _=Depends(require_auth)) -> RedirectResponse:
    """Удаляет роутер из config.py по имени."""
    if _update_config_file(delete_name=name):
        await reload_router_config()
        # Также удаляем маппинг для этого имени, если он есть
        name_mapping.delete(name)
        name_mapping.save()
    return RedirectResponse("/", status_code=303)

# ----------------------------------------------------------------------
# Запуск
# ----------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
