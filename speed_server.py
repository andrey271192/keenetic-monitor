"""
speed_server.py — сервер данных мониторинга. Порт 5000.

Эндпоинты:
  POST /push_speed  — данные speedtest (каждые 4ч с Windows PC)
  POST /push_sites  — статус сайтов + запрос на restart (каждые 15мин)
  GET  /api/speed/{router}  — история speedtest роутера
  GET  /api/sites/{router}  — последний статус сайтов
  GET  /api/all             — все данные
"""
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

import sys
sys.path.insert(0, str(Path(__file__).parent))
import config as cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("speed-server")

# Данные в памяти
_speed_history: dict = {}   # {router_name: [список записей]}
_sites_data: dict = {}      # {router_name: последние данные сайтов}
_restart_queue: dict = {}   # {router_name: True/False}


# --- Загрузка / сохранение ---

def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _save_speed():
    cfg.SPEED_FILE.write_text(
        json.dumps(_speed_history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _save_sites():
    cfg.SITES_FILE.write_text(
        json.dumps(_sites_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _save_restart():
    cfg.RESTART_FILE.write_text(
        json.dumps(_restart_queue, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _cleanup_old_speed():
    """Удаляет записи speedtest старше 7 дней."""
    cutoff = (datetime.now() - timedelta(days=cfg.SPEED_HISTORY_DAYS)).strftime("%Y-%m-%d")
    changed = False
    for router in list(_speed_history.keys()):
        before = len(_speed_history[router])
        _speed_history[router] = [
            r for r in _speed_history[router]
            if r.get("time", "")[:10] >= cutoff
        ]
        # Также ограничиваем максимум
        if len(_speed_history[router]) > cfg.SPEED_MAX_PER_ROUTER:
            _speed_history[router] = _speed_history[router][-cfg.SPEED_MAX_PER_ROUTER:]
        if len(_speed_history[router]) != before:
            changed = True
    if changed:
        _save_speed()
        logger.info("Speed history cleanup done")


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


# --- Приём данных speedtest (каждые 4ч) ---

@app.post("/push_speed")
async def push_speed(data: dict) -> JSONResponse:
    router = data.get("router_name", "").strip()
    if not router:
        return JSONResponse({"status": "error", "detail": "router_name required"}, status_code=400)

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

    # Обрезаем если превышен лимит
    if len(_speed_history[router]) > cfg.SPEED_MAX_PER_ROUTER:
        _speed_history[router] = _speed_history[router][-cfg.SPEED_MAX_PER_ROUTER:]

    _save_speed()
    logger.info(f"Speed: {router} VPN={record['download_vpn']}Mbps RU={record['download_ru']}Mbps")

    return JSONResponse({"status": "ok", "router": router, "records": len(_speed_history[router])})


# --- Приём статуса сайтов (каждые 15мин) ---

@app.post("/push_sites")
async def push_sites(data: dict) -> JSONResponse:
    router = data.get("router_name", "").strip()
    if not router:
        return JSONResponse({"status": "error", "detail": "router_name required"}, status_code=400)

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

    # Проверяем нужен ли restart
    needs_restart = _restart_queue.get(router, False)
    if needs_restart:
        # Сбрасываем флаг — PC получил команду
        _restart_queue[router] = False
        _save_restart()
        logger.info(f"Restart command sent to {router}")

    any_fail = not (record["youtube_ok"] and record["netflix_ok"] and record["telegram_ok"])
    logger.info(
        f"Sites: {router} "
        f"YT={'OK' if record['youtube_ok'] else 'FAIL'} "
        f"NF={'OK' if record['netflix_ok'] else 'FAIL'} "
        f"TG={'OK' if record['telegram_ok'] else 'FAIL'}"
        f"{' → restart_neo=true' if needs_restart else ''}"
    )

    return JSONResponse({
        "status": "ok",
        "router": router,
        "restart_neo": needs_restart,
        "any_fail": any_fail,
    })


# --- API для чтения данных ---

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


# --- Ручной запрос restart (из веб-интерфейса) ---

@app.post("/api/request_restart/{router_name}")
async def request_restart(router_name: str) -> JSONResponse:
    _restart_queue[router_name] = True
    _save_restart()
    logger.info(f"Manual restart requested for {router_name}")
    return JSONResponse({"status": "ok", "router": router_name, "restart_queued": True})


# --- Cleanup старых данных ---

@app.post("/api/cleanup")
async def cleanup() -> JSONResponse:
    _cleanup_old_speed()
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
