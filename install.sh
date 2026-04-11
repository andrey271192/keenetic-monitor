#!/bin/bash

set -e

echo "🚀 Keenetic Monitor Installer"

INSTALL_DIR="/opt/keenetic-monitor"

# ========= УСТАНОВКА =========
echo "📦 Установка зависимостей..."
apt update
apt install -y python3 python3-pip python3-venv git curl

# ========= ОЧИСТКА =========
echo "🧹 Очистка старой версии..."
systemctl stop keenetic 2>/dev/null || true
systemctl disable keenetic 2>/dev/null || true
rm -rf $INSTALL_DIR

mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

# ========= КЛОНИРОВАНИЕ =========
echo "📥 Клонируем проект..."
git clone https://github.com/andrey271192/keenetic-monitor.git .

# ========= VENV =========
echo "🐍 Создаём venv..."
python3 -m venv venv

# ❗ ВАЖНО — используем прямой python
echo "📦 Установка Python зависимостей..."
$INSTALL_DIR/venv/bin/python -m pip install --upgrade pip
$INSTALL_DIR/venv/bin/python -m pip install fastapi uvicorn httpx python-multipart

# ========= CONFIG =========
echo "⚙️ Создаём config.py..."

cat > config.py <<EOF
ROUTERS = []

CHECK_INTERVAL = 60

TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

SMTP_HOST = ""
SMTP_PORT = 465
SMTP_USER = ""
SMTP_PASS = ""
SMTP_FROM = ""
SMTP_TO = ""

STATUS_FILE = "/opt/keenetic-monitor/status.json"

SPEED_MONITOR_URL = ""
SPEED_UPDATE_INTERVAL = 60
EOF

# ========= SYSTEMD =========
echo "⚙️ Создаём сервис..."

cat > /etc/systemd/system/keenetic.service <<EOF
[Unit]
Description=Keenetic Monitor
After=network.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/main.py
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

# ========= ЗАПУСК =========
echo "🔄 Перезапуск systemd..."
systemctl daemon-reexec
systemctl daemon-reload
systemctl enable keenetic

# 🔥 фикс блокировки
systemctl reset-failed keenetic

systemctl restart keenetic

echo ""
echo "✅ Установка завершена!"
echo "🌐 Открой: http://$(curl -s ifconfig.me):8001"
