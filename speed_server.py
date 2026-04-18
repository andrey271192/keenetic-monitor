"""
speed_server.py — сервер данных мониторинга. Порт 5000.
"""
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse

import sys
sys.path.insert(0, str(Path(__file__).parent))
import config as cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("speed-server")

_speed_history: dict = {}
_sites_data: dict = {}
_restart_queue: dict = {}


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _save_speed():
    cfg.SPEED_FILE.write_text(json.dumps(_speed_history, indent=2, ensure_ascii=False), encoding="utf-8")

def _save_sites():
    cfg.SITES_FILE.write_text(json.dumps(_sites_data, indent=2, ensure_ascii=False), encoding="utf-8")

def _save_restart():
    cfg.RESTART_FILE.write_text(json.dumps(_restart_queue, indent=2, ensure_ascii=False), encoding="utf-8")


def _cleanup_old_speed():
    cutoff = (datetime.now() - timedelta(days=cfg.SPEED_HISTORY_DAYS)).strftime("%Y-%m-%d")
    changed = False
    for router in list(_speed_history.keys()):
        before = len(_speed_history[router])
        _speed_history[router] = [
            r for r in _speed_history[router]
            if r.get("time", "")[:10] >= cutoff
        ]
        if len(_speed_history[router]) > cfg.SPEED_MAX_PER_ROUTER:
            _speed_history[router] = _speed_history[router][-cfg.SPEED_MAX_PER_ROUTER:]
        if len(_speed_history[router]) != before:
            changed = True
    if changed:
        _save_speed()


def _auto_register(router_name: str, router_url: str = ""):
    """Добавляет роутер в config.py если его там нет."""
    try:
        cfg_path = cfg.BASE_DIR / "config.py"
        text = cfg_path.read_text(encoding="utf-8")
        if f'"{router_name}"' in text:
            return
        m = re.search(r'(ROUTERS\s*=\s*\[)(.*?)(\])', text, re.DOTALL)
        if not m:
            return
        start, middle, end = m.groups()
        url = router_url or f"http://{router_name}"
        new_line = f'    {{"name": "{router_name}", "url": "{url}", "user": "admin", "pass": "keenetic"}}'
        new_middle = f"{middle.rstrip()},\n{new_line}\n" if middle.strip() else f"\n{new_line}\n"
        cfg_path.write_text(text.replace(m.group(0), f"{start}{new_middle}{end}"), encoding="utf-8")
        logger.info(f"Auto-registered router: {router_name}")
    except Exception as e:
        logger.error(f"Auto-register failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _speed_history, _sites_data, _restart_queue
    _speed_history = _load_json(cfg.SPEED_FILE, {})
    _sites_data    = _load_json(cfg.SITES_FILE, {})
    _restart_queue = _load_json(cfg.RESTART_FILE, {})
    _cleanup_old_speed()
    logger.info(f"Speed server started. Routers: {list(_speed_history.keys())}")
    yield


app = FastAPI(title="Keenetic Speed Server", lifespan=lifespan)


@app.post("/push_speed")
async def push_speed(data: dict) -> JSONResponse:
    router = data.get("router_name", "").strip()
    if not router:
        return JSONResponse({"status": "error", "detail": "router_name required"}, status_code=400)

    _auto_register(router, data.get("router_url", ""))

    record = {
        "time":         data.get("time", datetime.now().strftime("%Y-%m-%d %H:%M")),
        "download_vpn": round(float(data.get("download_vpn", 0)), 1),
        "upload_vpn":   round(float(data.get("upload_vpn", 0)), 1),
        "ping_vpn":     round(float(data.get("ping_vpn", 0)), 1),
        "download_ru":  round(float(data.get("download_ru", 0)), 1),
        "ping_ru":      round(float(data.get("ping_ru", 0)), 1),
        "ip":           data.get("ip", ""),
    }

    if router not in _speed_history:
        _speed_history[router] = []
    _speed_history[router].append(record)
    if len(_speed_history[router]) > cfg.SPEED_MAX_PER_ROUTER:
        _speed_history[router] = _speed_history[router][-cfg.SPEED_MAX_PER_ROUTER:]
    _save_speed()
    logger.info(f"Speed: {router} VPN={record['download_vpn']}Mbps RU={record['download_ru']}Mbps")
    return JSONResponse({"status": "ok", "router": router, "records": len(_speed_history[router])})


@app.post("/push_sites")
async def push_sites(data: dict) -> JSONResponse:
    router = data.get("router_name", "").strip()
    if not router:
        return JSONResponse({"status": "error", "detail": "router_name required"}, status_code=400)

    _auto_register(router, data.get("router_url", ""))

    record = {
        "time":         data.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "ip":           data.get("ip", ""),
        "youtube_ok":   bool(data.get("youtube_ok", False)),
        "youtube_ms":   round(float(data.get("youtube_ms", 0)), 0),
        "netflix_ok":   bool(data.get("netflix_ok", False)),
        "netflix_ms":   round(float(data.get("netflix_ms", 0)), 0),
        "telegram_ok":  bool(data.get("telegram_ok", False)),
        "telegram_ms":  round(float(data.get("telegram_ms", 0)), 0),
    }

    _sites_data[router] = record
    _save_sites()

    needs_restart = _restart_queue.get(router, False)
    if needs_restart:
        _restart_queue[router] = False
        _save_restart()
        logger.info(f"Restart command sent to {router}")

    logger.info(
        f"Sites: {router} "
        f"YT={'OK' if record['youtube_ok'] else 'FAIL'} "
        f"NF={'OK' if record['netflix_ok'] else 'FAIL'} "
        f"TG={'OK' if record['telegram_ok'] else 'FAIL'}"
    )

    return JSONResponse({
        "status": "ok",
        "router": router,
        "restart_neo": needs_restart,
        "any_fail": not (record["youtube_ok"] and record["netflix_ok"] and record["telegram_ok"]),
    })


@app.get("/api/speed/{router_name}")
async def api_speed(router_name: str) -> JSONResponse:
    history = _speed_history.get(router_name, [])
    return JSONResponse({"router": router_name, "history": history})


@app.get("/api/sites/{router_name}")
async def api_sites(router_name: str) -> JSONResponse:
    data = _sites_data.get(router_name)
    if not data:
        return JSONResponse({"status": "no_data"}, status_code=404)
    return JSONResponse(data)


@app.get("/api/all")
async def api_all() -> JSONResponse:
    return JSONResponse({
        "speed": {r: v[-1] if v else None for r, v in _speed_history.items()},
        "sites": _sites_data,
        "restart_queue": _restart_queue,
    })


@app.post("/api/request_restart/{router_name}")
async def request_restart(router_name: str) -> JSONResponse:
    _restart_queue[router_name] = True
    _save_restart()
    return JSONResponse({"status": "ok", "router": router_name})


@app.post("/api/cleanup")
async def cleanup() -> JSONResponse:
    _cleanup_old_speed()
    return JSONResponse({"status": "ok"})


# --- Страница статистики скорости ---

@app.get("/stats/{router_name}", response_class=HTMLResponse)
async def stats_page(router_name: str):
    history = _speed_history.get(router_name, [])
    if not history:
        return HTMLResponse(f"<h2>Нет данных для {router_name}</h2>")

    labels = json.dumps([r["time"][-5:] for r in history])
    vpn_dl = json.dumps([r["download_vpn"] for r in history])
    ru_dl  = json.dumps([r["download_ru"] for r in history])
    pings  = json.dumps([r["ping_vpn"] for r in history])

    last = history[-1]

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Статистика — {router_name}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0d1117; color: #e6edf3; font-family: -apple-system, sans-serif; padding: 24px; }}
h1 {{ font-size: 20px; margin-bottom: 6px; }}
.sub {{ font-size: 13px; color: #8b949e; margin-bottom: 24px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 14px; text-align: center; }}
.card .lbl {{ font-size: 11px; color: #8b949e; margin-bottom: 4px; }}
.card .val {{ font-size: 24px; font-weight: 600; }}
.card .unit {{ font-size: 11px; color: #8b949e; }}
.vpn {{ color: #3fb950; }} .ru {{ color: #58a6ff; }} .ping {{ color: #d2a8ff; }}
.chart-box {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
.chart-box h3 {{ font-size: 13px; color: #8b949e; margin-bottom: 12px; }}
a {{ color: #58a6ff; font-size: 13px; text-decoration: none; }}
</style>
</head>
<body>
<a href="http://{{}}/"> ← На главную</a>
<br><br>
<h1>📊 Статистика скорости — {router_name}</h1>
<div class="sub">Данные за 7 дней · {len(history)} записей · Последнее: {last['time']}</div>

<div class="cards">
  <div class="card"><div class="lbl">⬇ VPN Download</div><div class="val vpn">{last['download_vpn']:.0f}<span class="unit"> Mbps</span></div></div>
  <div class="card"><div class="lbl">⬆ VPN Upload</div><div class="val vpn">{last['upload_vpn']:.0f}<span class="unit"> Mbps</span></div></div>
  <div class="card"><div class="lbl">🏓 VPN Ping</div><div class="val ping">{last['ping_vpn']:.0f}<span class="unit"> ms</span></div></div>
  <div class="card"><div class="lbl">⬇ RU канал</div><div class="val ru">{last['download_ru']:.0f}<span class="unit"> Mbps</span></div></div>
  <div class="card"><div class="lbl">🏓 RU Ping</div><div class="val ping">{last['ping_ru']:.0f}<span class="unit"> ms</span></div></div>
</div>

<div class="chart-box">
  <h3>Скорость загрузки (Mbps)</h3>
  <canvas id="speedChart" height="80"></canvas>
</div>
<div class="chart-box">
  <h3>Ping (ms)</h3>
  <canvas id="pingChart" height="60"></canvas>
</div>

<script>
const labels = {labels};
const vpn_dl = {vpn_dl};
const ru_dl  = {ru_dl};
const pings  = {pings};

new Chart(document.getElementById('speedChart'), {{
  type: 'line',
  data: {{
    labels,
    datasets: [
      {{ label: 'VPN Download', data: vpn_dl, borderColor: '#3fb950', backgroundColor: '#3fb95022', tension: 0.3, pointRadius: 3 }},
      {{ label: 'RU канал',     data: ru_dl,  borderColor: '#58a6ff', backgroundColor: '#58a6ff22', tension: 0.3, pointRadius: 3 }},
    ]
  }},
  options: {{ plugins: {{ legend: {{ labels: {{ color: '#8b949e' }} }} }}, scales: {{ x: {{ ticks: {{ color: '#8b949e', maxTicksLimit: 10 }}, grid: {{ color: '#21262d' }} }}, y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }} }} }} }}
}});

new Chart(document.getElementById('pingChart'), {{
  type: 'line',
  data: {{
    labels,
    datasets: [
      {{ label: 'VPN Ping', data: pings, borderColor: '#d2a8ff', backgroundColor: '#d2a8ff22', tension: 0.3, pointRadius: 3 }},
    ]
  }},
  options: {{ plugins: {{ legend: {{ labels: {{ color: '#8b949e' }} }} }}, scales: {{ x: {{ ticks: {{ color: '#8b949e', maxTicksLimit: 10 }}, grid: {{ color: '#21262d' }} }}, y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }} }} }} }}
}});
</script>
</body></html>"""
    return HTMLResponse(html)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
