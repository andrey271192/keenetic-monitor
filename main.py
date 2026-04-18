"""
Keenetic Monitor v4.0 — дашборд.
Карточка каждого роутера: статус + сайты + последний speedtest + мини-график.
"""
import asyncio
import importlib
import json
import logging
import os
import re
import secrets
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from keenetic_api import KeeneticClient
from notifier import check_and_notify, notify

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR))
import config as _cfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger("keenetic-monitor")

ADMIN_USER     = "admin"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
MAPPING_FILE   = BASE_DIR / "mapping.json"

# ----------------------------------------------------------------------
# Маппинг имён
# ----------------------------------------------------------------------

class NameMapping:
    def __init__(self, path: Path):
        self._file = path
        self._data: Dict[str, str] = self._load()

    def _load(self) -> Dict[str, str]:
        if self._file.exists():
            try:
                return json.loads(self._file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def save(self):
        self._file.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get(self, key: str) -> str:
        return self._data.get(key, key)

    def delete(self, key: str):
        self._data.pop(key, None)

    def all(self) -> Dict[str, str]:
        return self._data.copy()

    def update_from_text(self, text: str):
        new = {}
        for line in text.strip().splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            new[k.strip()] = v.strip()
        if new:
            self._data = new
            self.save()


name_mapping = NameMapping(MAPPING_FILE)

# ----------------------------------------------------------------------
# Сессии
# ----------------------------------------------------------------------

_sessions: Dict[str, str] = {}


def get_current_user(request: Request) -> Optional[str]:
    return _sessions.get(request.cookies.get("session", ""))

# ----------------------------------------------------------------------
# Данные
# ----------------------------------------------------------------------

_router_statuses: List[Dict] = []


def _load_sites() -> Dict:
    if _cfg.SITES_FILE.exists():
        try:
            return json.loads(_cfg.SITES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _load_speed() -> Dict:
    if _cfg.SPEED_FILE.exists():
        try:
            return json.loads(_cfg.SPEED_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

# ----------------------------------------------------------------------
# Воркеры
# ----------------------------------------------------------------------

async def _check_router(r: Dict) -> Dict:
    client = KeeneticClient(r["url"], r["user"], r["pass"])
    try:
        ok = await client.check_connection()
        return {
            "name":    r["name"],
            "url":     r["url"],
            "online":  ok,
            "checked": datetime.now().strftime("%H:%M"),
        }
    finally:
        await client.close()


async def router_worker():
    global _router_statuses
    while True:
        try:
            importlib.reload(_cfg)
            if _cfg.ROUTERS:
                results = await asyncio.gather(*[_check_router(r) for r in _cfg.ROUTERS])
                _router_statuses = list(results)
                _cfg.STATUS_FILE.write_text(
                    json.dumps(_router_statuses, indent=2, ensure_ascii=False)
                )
        except Exception:
            logger.exception("Router worker error")
        await asyncio.sleep(_cfg.CHECK_INTERVAL)


async def alert_worker():
    """Следит за изменением sites_data и шлёт уведомления."""
    _seen: Dict[str, str] = {}
    while True:
        try:
            sites = _load_sites()
            for router_name, data in sites.items():
                t = data.get("time", "")
                if _seen.get(router_name) != t:
                    _seen[router_name] = t
                    display = name_mapping.get(router_name)
                    await check_and_notify(router_name, display, data)
        except Exception:
            logger.exception("Alert worker error")
        await asyncio.sleep(30)


async def cleanup_worker():
    """Раз в сутки запускает очистку старых данных speedtest."""
    while True:
        await asyncio.sleep(86400)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post("http://localhost:5000/api/cleanup")
            logger.info("Cleanup triggered")
        except Exception:
            logger.exception("Cleanup worker error")

# ----------------------------------------------------------------------
# App
# ----------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    t1 = asyncio.create_task(router_worker())
    t2 = asyncio.create_task(alert_worker())
    t3 = asyncio.create_task(cleanup_worker())
    yield
    t1.cancel(); t2.cancel(); t3.cancel()


app = FastAPI(title="Keenetic Monitor v4", lifespan=lifespan)

# ----------------------------------------------------------------------
# CSS
# ----------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }

.header { background: #161b22; border-bottom: 1px solid #30363d; padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 10; }
.header-title { font-size: 18px; font-weight: 600; }
.header-links a { color: #58a6ff; text-decoration: none; font-size: 13px; margin-left: 16px; }

.container { max-width: 1400px; margin: 0 auto; padding: 24px; }

.stats-bar { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
.pill { background: #161b22; border: 1px solid #30363d; border-radius: 99px; padding: 5px 14px; font-size: 12px; }
.pill .n { font-weight: 600; }
.pill.ok .n { color: #3fb950; }
.pill.fail .n { color: #f85149; }
.pill.warn .n { color: #d29922; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 14px; }

/* Карточка */
.card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; overflow: hidden; }
.card.offline { border-color: #f8514944; }
.card-header { padding: 12px 14px 10px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #21262d; }
.card-name { font-size: 14px; font-weight: 500; }
.badge { font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 99px; }
.badge.on { background: #1a3a2a; color: #3fb950; }
.badge.off { background: #3a1a1a; color: #f85149; }

.card-body { padding: 10px 14px; }

/* Сайты */
.sites { display: flex; gap: 6px; margin-bottom: 10px; }
.sb { flex: 1; text-align: center; padding: 4px 2px; border-radius: 6px; font-size: 11px; font-weight: 500; }
.sb.ok  { background: #1a3a2a; color: #3fb950; }
.sb.fail{ background: #3a1a1a; color: #f85149; }
.sb.unk { background: #21262d; color: #8b949e; }

/* Скорость */
.speed-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; margin-bottom: 8px; }
.si { text-align: center; }
.si .sl { font-size: 10px; color: #8b949e; }
.si .sv { font-size: 15px; font-weight: 600; }
.si .su { font-size: 10px; color: #8b949e; }
.sv.vpn { color: #3fb950; }
.sv.ru  { color: #58a6ff; }
.sv.ping{ color: #d2a8ff; }

/* Мини-график VPN скорости */
.sparkline { height: 32px; margin-bottom: 6px; display: flex; align-items: flex-end; gap: 2px; }
.spark-bar { flex: 1; background: #238636; border-radius: 2px 2px 0 0; min-height: 2px; opacity: 0.8; }

.card-meta { font-size: 11px; color: #8b949e; display: flex; justify-content: space-between; }
.card-meta a { color: #58a6ff; text-decoration: none; }
.divider { height: 1px; background: #21262d; margin: 8px 0; }
.no-data { font-size: 11px; color: #8b949e; padding: 4px 0 8px; }

/* Логин */
.login-wrap { display: flex; justify-content: center; align-items: center; min-height: 100vh; }
.login-box { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 32px; width: 320px; }
.login-box h2 { margin-bottom: 20px; }
.login-box input { width: 100%; margin-bottom: 12px; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 9px 12px; color: #e6edf3; font-size: 14px; display: block; }
.login-box input:focus { outline: none; border-color: #58a6ff; }
.btn { background: #238636; border: none; border-radius: 6px; padding: 8px 18px; color: white; font-size: 13px; cursor: pointer; }
.btn.danger { background: #da3633; }

.admin-card { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 18px; margin-bottom: 14px; }
.admin-card h3 { font-size: 13px; color: #8b949e; margin-bottom: 12px; }
.form-row { display: flex; gap: 8px; flex-wrap: wrap; }
.form-row input { background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 7px 12px; color: #e6edf3; font-size: 13px; min-width: 150px; }
"""

# ----------------------------------------------------------------------
# HTML helpers
# ----------------------------------------------------------------------

def _base(content: str, is_auth: bool = False, title: str = "Keenetic Monitor") -> str:
    nav = '<a href="/login">🔑 Войти</a>'
    if is_auth:
        nav = '<a href="/admin">⚙️ Управление</a><a href="/mapping">✏️ Имена</a><a href="/logout">Выйти</a>'
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{CSS}</style>
<meta http-equiv="refresh" content="60">
</head>
<body>
<div class="header">
  <div class="header-title">📡 Keenetic Monitor</div>
  <div class="header-links">{nav}</div>
</div>
<div class="container">{content}</div>
</body></html>"""


def _sparkline(history: List[Dict]) -> str:
    if not history:
        return ""
    vals = [r.get("download_vpn", 0) for r in history[-14:]]
    if not vals or max(vals) == 0:
        return ""
    mx = max(vals)
    bars = ""
    for v in vals:
        h = max(2, int((v / mx) * 30))
        bars += f'<div class="spark-bar" style="height:{h}px" title="{v} Mbps"></div>'
    return f'<div class="sparkline">{bars}</div>'


def _site_badge(ok: Optional[bool], name: str, ms: float = 0) -> str:
    if ok is None:
        return f'<div class="sb unk">{name}</div>'
    if ok:
        ms_str = f" {ms:.0f}ms" if ms else ""
        return f'<div class="sb ok">✓ {name}{ms_str}</div>'
    return f'<div class="sb fail">✗ {name}</div>'


def _router_card(router: Dict, sites: Optional[Dict], speed_history: List[Dict]) -> str:
    name    = router.get("name", "")
    display = name_mapping.get(name)
    online  = router.get("online", False)
    url     = router.get("url", "#")
    checked = router.get("checked", "")

    card_cls  = "card" if online else "card offline"
    badge_cls = "badge on" if online else "badge off"
    badge_txt = "● ONLINE" if online else "● OFFLINE"

    # Сайты
    if sites:
        t = sites.get("time", "")[:16]
        ip = sites.get("ip", "")
        sites_html = f"""
<div class="sites">
  {_site_badge(sites.get('youtube_ok'), 'YouTube', sites.get('youtube_ms', 0))}
  {_site_badge(sites.get('netflix_ok'), 'Netflix', sites.get('netflix_ms', 0))}
  {_site_badge(sites.get('telegram_ok'), 'Telegram', sites.get('telegram_ms', 0))}
</div>"""
        sites_meta = f'<span>{t}</span>'
        sites_ip = f'<span style="color:#58a6ff">{ip}</span>'
    else:
        sites_html = '<div class="no-data">📊 Нет данных о сайтах</div>'
        sites_meta = f'<span>Роутер проверен: {checked}</span>'
        sites_ip = ""

    # Speedtest — последняя запись
    last_speed = speed_history[-1] if speed_history else None
    if last_speed:
        spark = _sparkline(speed_history)
        speed_html = f"""
<div class="divider"></div>
{spark}
<div class="speed-row">
  <div class="si"><div class="sl">⬇ VPN</div><div class="sv vpn">{last_speed.get('download_vpn', 0):.0f}<span class="su"> Mbps</span></div></div>
  <div class="si"><div class="sl">⬇ RU</div><div class="sv ru">{last_speed.get('download_ru', 0):.0f}<span class="su"> Mbps</span></div></div>
  <div class="si"><div class="sl">🏓 Ping</div><div class="sv ping">{last_speed.get('ping_vpn', 0):.0f}<span class="su"> ms</span></div></div>
</div>"""
        speed_time = f'<span>{last_speed.get("time", "")[:16]}</span>'
    else:
        speed_html = ""
        speed_time = ""

    return f"""
<div class="{card_cls}">
  <div class="card-header">
    <div class="card-name">{display}</div>
    <span class="{badge_cls}">{badge_txt}</span>
  </div>
  <div class="card-body">
    {sites_html}
    {speed_html}
    <div class="divider"></div>
    <div class="card-meta">
      <span>{sites_meta} {sites_ip}</span>
      <span>{"<a href=\'http://89.124.112.9:5000/stats/" + name + "\' target=\'_blank\'>📊 График</a> · " if speed_history else ""}<a href="{url}" target="_blank">Открыть →</a></span>
    </div>
  </div>
</div>"""

# ----------------------------------------------------------------------
# Маршруты
# ----------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(_base("""
<div class="login-wrap"><div class="login-box">
  <h2>Вход</h2>
  <form method="post" action="/login">
    <input name="username" placeholder="Логин" autocomplete="username">
    <input name="password" type="password" placeholder="Пароль">
    <button class="btn" type="submit" style="width:100%">Войти</button>
  </form>
</div></div>""", title="Вход"))


@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        token = secrets.token_urlsafe(32)
        _sessions[token] = username
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("session", token, httponly=True, max_age=3600 * 24 * 7)
        return resp
    return RedirectResponse("/login?err=1", status_code=303)


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/")
    resp.delete_cookie("session")
    return resp


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    is_auth = bool(get_current_user(request))
    sites_all = _load_sites()
    speed_all = _load_speed()
    statuses  = _router_statuses

    if not statuses:
        return HTMLResponse(_base(
            '<div style="color:#8b949e;padding:40px 0">⏳ Роутеры ещё проверяются...</div>',
            is_auth=is_auth
        ))

    online    = sum(1 for r in statuses if r.get("online"))
    offline   = len(statuses) - online
    with_data = sum(1 for r in statuses if r.get("name") in sites_all)

    pills = f"""<div class="stats-bar">
  <div class="pill ok">Всего: <span class="n">{len(statuses)}</span></div>
  <div class="pill ok">Онлайн: <span class="n">{online}</span></div>
  <div class="pill fail">Офлайн: <span class="n">{offline}</span></div>
  <div class="pill warn">Данные PC: <span class="n">{with_data}</span></div>
</div>"""

    sorted_r = sorted(
        statuses,
        key=lambda x: (not x.get("online"), name_mapping.get(x.get("name", "")))
    )

    cards = ""
    for r in sorted_r:
        rname = r.get("name", "")
        cards += _router_card(
            r,
            sites_all.get(rname),
            speed_all.get(rname, [])
        )

    return HTMLResponse(_base(pills + f'<div class="grid">{cards}</div>', is_auth=is_auth))


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)

    importlib.reload(_cfg)
    routers_list = "".join(
        f'<div style="font-size:13px;padding:3px 0;color:#8b949e">'
        f'<b style="color:#e6edf3">{r["name"]}</b> — {r["url"]}</div>'
        for r in _cfg.ROUTERS
    )

    content = f"""
<div style="margin-bottom:16px"><a href="/" style="color:#58a6ff;font-size:13px">← На главную</a></div>
<div class="admin-card">
  <h3>➕ Добавить роутер</h3>
  <form method="post" action="/add">
    <div class="form-row">
      <input name="name" placeholder="Имя (без пробелов)" required>
      <input name="url" placeholder="http://192.168.1.1" required>
      <input name="user" placeholder="Логин" value="admin">
      <input name="passwd" type="password" placeholder="Пароль">
      <button class="btn" type="submit">Добавить</button>
    </div>
  </form>
</div>
<div class="admin-card">
  <h3>➖ Удалить роутер</h3>
  <form method="post" action="/delete">
    <div class="form-row">
      <input name="name" placeholder="Техническое имя" required>
      <button class="btn danger" type="submit">Удалить</button>
    </div>
  </form>
</div>
<div class="admin-card">
  <h3>📋 Текущие роутеры</h3>
  {routers_list or '<div style="color:#8b949e;font-size:13px">Нет роутеров</div>'}
</div>"""
    return HTMLResponse(_base(content, is_auth=True, title="Управление"))


@app.get("/mapping", response_class=HTMLResponse)
async def mapping_page(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    rows = "\n".join(f"{k}: {v}" for k, v in name_mapping.all().items())
    content = f"""
<div style="margin-bottom:16px"><a href="/" style="color:#58a6ff;font-size:13px">← На главную</a></div>
<div class="admin-card">
  <h3>Формат: техническое_имя: Красивое название</h3>
  <form method="post" action="/mapping">
    <textarea name="data" rows="25" style="width:100%;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:12px;font-family:monospace;font-size:13px;resize:vertical;margin-bottom:12px">{rows}</textarea>
    <button class="btn" type="submit">Сохранить</button>
  </form>
</div>"""
    return HTMLResponse(_base(content, is_auth=True, title="Имена"))


@app.post("/mapping")
async def save_mapping(request: Request, data: str = Form(...)):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    name_mapping.update_from_text(data)
    return RedirectResponse("/mapping", status_code=303)


def _update_config(new_line: str = "", delete_name: str = "") -> bool:
    cfg_path = BASE_DIR / "config.py"
    text = cfg_path.read_text(encoding="utf-8")
    m = re.search(r'(ROUTERS\s*=\s*\[)(.*?)(\])', text, re.DOTALL)
    if not m:
        return False
    start, middle, end = m.groups()
    if delete_name:
        lines = [l for l in middle.splitlines() if f'"{delete_name}"' not in l]
        new_middle = "\n".join(lines)
    else:
        new_middle = f"{middle.rstrip()},\n{new_line}\n" if middle.strip() else f"\n{new_line}\n"
    cfg_path.write_text(text.replace(m.group(0), f"{start}{new_middle}{end}"), encoding="utf-8")
    return True


@app.post("/add")
async def add_router(
    request: Request,
    name: str = Form(...), url: str = Form(...),
    user: str = Form(...), passwd: str = Form(...),
):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    line = f'    {{"name": "{name}", "url": "{url}", "user": "{user}", "pass": "{passwd}"}}'
    _update_config(new_line=line)
    importlib.reload(_cfg)
    return RedirectResponse("/admin", status_code=303)


@app.post("/delete")
async def delete_router(request: Request, name: str = Form(...)):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    _update_config(delete_name=name)
    name_mapping.delete(name)
    name_mapping.save()
    importlib.reload(_cfg)
    return RedirectResponse("/admin", status_code=303)


@app.get("/api/status")
async def api_status():
    return JSONResponse({
        "routers": _router_statuses,
        "sites":   _load_sites(),
        "updated": datetime.now().isoformat(),
    })


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
