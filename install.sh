#!/bin/bash

echo "🚀 Keenetic Monitor Installer"

APP_DIR="/opt/keenetic-monitor"

# ========= INSTALL =========
apt update -y
apt install -y python3 python3-pip git snmp

mkdir -p $APP_DIR
cd $APP_DIR

echo "📦 Клонируем репозиторий..."
git clone https://github.com/andrey271192/keenetic-monitor.git .

echo "📦 Установка зависимостей..."
pip3 install -r requirements.txt

# ========= INPUT =========
echo ""
echo "🔧 Настройка..."

read -p "Telegram TOKEN (можно пусто): " TG_TOKEN
read -p "Telegram CHAT_ID (можно пусто): " TG_CHAT

read -p "SMTP HOST (например smtp.gmail.com): " SMTP_HOST
read -p "SMTP USER: " SMTP_USER
read -p "SMTP PASS: " SMTP_PASS
read -p "SMTP TO: " SMTP_TO

read -p "Speed monitor URL (например http://IP:5000/api/latest): " SPEED_URL

# ========= ROUTERS =========
echo ""
echo "📡 Добавление роутеров (можно много)"

ROUTERS="["

while true; do
    read -p "Добавить роутер? (y/n): " yn
    if [ "$yn" != "y" ]; then break; fi

    read -p "Название: " NAME
    read -p "URL: " URL
    read -p "Логин [admin]: " USER
    USER=${USER:-admin}
    read -p "Пароль: " PASS

    ROUTERS="$ROUTERS
    {\"name\": \"$NAME\", \"url\": \"$URL\", \"user\": \"$USER\", \"pass\": \"$PASS\"},"
done

ROUTERS="${ROUTERS%,}"
ROUTERS="$ROUTERS]"

# ========= CONFIG =========
cat > $APP_DIR/config.py <<EOF
ROUTERS = $ROUTERS

CHECK_INTERVAL = 300

TELEGRAM_TOKEN = "$TG_TOKEN"
TELEGRAM_CHAT_ID = "$TG_CHAT"

SMTP_HOST = "$SMTP_HOST"
SMTP_PORT = 465
SMTP_USER = "$SMTP_USER"
SMTP_PASS = "$SMTP_PASS"
SMTP_TO = "$SMTP_TO"

SPEED_MONITOR_URL = "$SPEED_URL"
SPEED_UPDATE_INTERVAL = 60
EOF

# ========= SERVICE =========
cat > /etc/systemd/system/keenetic.service <<EOF
[Unit]
Description=Keenetic Monitor
After=network.target

[Service]
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 main.py
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

# ========= START =========
systemctl daemon-reexec
systemctl daemon-reload
systemctl enable keenetic
systemctl restart keenetic

echo ""
echo "✅ Установка завершена!"
echo "🌐 Открой: http://SERVER_IP:8000"
