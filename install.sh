#!/bin/bash

set -e

echo "🚀 Keenetic Monitor Installer"

APP_DIR="/opt/keenetic-monitor"

# ========= INSTALL =========
echo "📦 Установка зависимостей..."
apt update -y
apt install -y python3 python3-pip python3-venv git snmp curl

# ========= CLONE / UPDATE =========
if [ -d "$APP_DIR/.git" ]; then
    echo "⚠️ Найден установленный проект, обновляем..."
    cd $APP_DIR
    git pull
else
    echo "📦 Клонируем репозиторий..."
    rm -rf $APP_DIR
    mkdir -p $APP_DIR
    cd $APP_DIR
    git clone https://github.com/andrey271192/keenetic-monitor.git .
fi

# ========= VENV =========
echo "🐍 Создаём виртуальное окружение..."
cd $APP_DIR
python3 -m venv venv
source venv/bin/activate

echo "📦 Установка Python зависимостей..."
pip install --upgrade pip
pip install -r requirements.txt

# ========= INPUT =========
echo ""
echo "🔧 Настройка..."

read -p "Telegram TOKEN (можно пусто): " TG_TOKEN
read -p "Telegram CHAT_ID (можно пусто): " TG_CHAT

read -p "SMTP HOST (Enter = пропустить): " SMTP_HOST
read -p "SMTP USER: " SMTP_USER
read -p "SMTP PASS: " SMTP_PASS
read -p "SMTP TO: " SMTP_TO

read -p "Speed monitor URL (Enter = пропустить): " SPEED_URL

# ========= ROUTERS =========
echo ""
echo "📡 Добавление роутеров (можно много)"

ROUTERS="["

while true; do
    read -p "Добавить роутер? (y/n): " yn
    [ "$yn" != "y" ] && break

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
echo "⚙️ Создаём config.py..."

cat > $APP_DIR/config.py <<EOF
ROUTERS = $ROUTERS

CHECK_INTERVAL = 300

TELEGRAM_TOKEN = "$TG_TOKEN"
TELEGRAM_CHAT_ID = "$TG_CHAT"

SMTP_HOST = "$SMTP_HOST"
SMTP_PORT = 465
SMTP_USER = "$SMTP_USER"
SMTP_PASS = "$SMTP_PASS"
SMTP_FROM = "$SMTP_USER"
SMTP_TO = "$SMTP_TO"

STATUS_FILE = "$APP_DIR/status.json"

SPEED_MONITOR_URL = "$SPEED_URL"
SPEED_UPDATE_INTERVAL = 60
EOF

# ========= SERVICE =========
echo "⚙️ Настройка systemd..."

cat > /etc/systemd/system/keenetic.service <<EOF
[Unit]
Description=Keenetic Monitor
After=network.target

[Service]
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/main.py
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

# ========= DONE =========
IP=$(curl -s ifconfig.me || echo "SERVER_IP")

echo ""
echo "✅ Установка завершена!"
echo "🌐 Открой: http://$IP:8000"
