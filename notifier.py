"""
notifier.py — уведомления Telegram + Email.
Отслеживает состояние каждого сайта на каждом роутере отдельно.
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Optional

import httpx

logger = logging.getLogger("notifier")

# {router_name: {"youtube": bool|None, "netflix": bool|None, "telegram": bool|None}}
_prev_states: Dict[str, Dict[str, Optional[bool]]] = {}


def _e(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


async def send_telegram(message: str) -> bool:
    token = _e("TELEGRAM_TOKEN")
    chat_id = _e("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
            )
            return r.json().get("ok", False)
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def send_email(subject: str, body: str) -> bool:
    host     = _e("SMTP_HOST", "smtp.gmail.com")
    port     = int(_e("SMTP_PORT", "587"))
    user     = _e("SMTP_USER")
    password = _e("SMTP_PASS")
    to       = _e("SMTP_TO")
    if not all([user, password, to]):
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = user
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(user, to, msg.as_string())
        return True
    except Exception as e:
        logger.error(f"Email error: {e}")
        return False


async def notify(subject: str, body: str):
    """Отправляет и в Telegram и на Email."""
    await send_telegram(f"🔔 <b>{subject}</b>\n{body}")
    send_email(f"[Keenetic Monitor] {subject}", body)


async def check_and_notify(
    router_name: str,
    display_name: str,
    sites_data: dict
) -> bool:
    """
    Проверяет изменение статуса сайтов и шлёт уведомления.
    Возвращает True если хотя бы один сайт недоступен (нужен restart).
    """
    if router_name not in _prev_states:
        _prev_states[router_name] = {
            "youtube": None, "netflix": None, "telegram": None
        }

    prev = _prev_states[router_name]
    any_fail = False

    checks = [
        ("youtube",  sites_data.get("youtube_ok"),  "YouTube",  "🎬"),
        ("netflix",  sites_data.get("netflix_ok"),  "Netflix",  "🎬"),
        ("telegram", sites_data.get("telegram_ok"), "Telegram", "✈️"),
    ]

    for key, current_ok, site_name, icon in checks:
        if current_ok is None:
            continue

        if not current_ok:
            any_fail = True

        prev_ok = prev.get(key)

        if prev_ok is None:
            prev[key] = current_ok
            continue

        t = sites_data.get("time", "")

        if prev_ok and not current_ok:
            await notify(
                f"❌ {site_name} недоступен — {display_name}",
                f"{icon} {site_name} не открывается\n"
                f"Объект: {display_name}\n"
                f"Время: {t}\n"
                f"→ Перезапускаю neo автоматически..."
            )
            prev[key] = False

        elif not prev_ok and current_ok:
            ms = sites_data.get(f"{key}_ms", 0)
            await notify(
                f"✅ {site_name} восстановлен — {display_name}",
                f"{icon} {site_name} снова работает\n"
                f"Объект: {display_name}\n"
                f"Время отклика: {ms:.0f}ms\n"
                f"Время: {t}"
            )
            prev[key] = True

    return any_fail
