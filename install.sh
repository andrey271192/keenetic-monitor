#!/bin/bash
set -e

echo ""
echo "============================================"
echo "   Keenetic Monitor Installer v4.0"
echo "============================================"
echo ""

INSTALL_DIR="/opt/keenetic-monitor"
REPO="https://github.com/andrey271192/keenetic-monitor.git"

if [ -n "$ADMIN_PASSWORD" ] || [ -n "$TG_TOKEN" ]; then
    echo ">>> АВТОМАТИЧЕСКИЙ РЕЖИМ"
else
    echo ">>> ИНТЕРАКТИВНЫЙ РЕЖИМ"
    read -p "Пароль админки [admin]: " ADMIN_PASSWORD
    ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
    read -p "Telegram Bot Token: " TG_TOKEN
    read -p "Telegram Chat ID: " TG_CHAT
    read -p "SMTP Host [smtp.gmail.com]: " SMTP_HOST
    SMTP_HOST="${SMTP_HOST:-smtp.gmail.com}"
    read -p "SMTP Port [587]: " SMTP_PORT
    SMTP_PORT="${SMTP_PORT:-587}"
    read -p "SMTP Email (отправитель): " SMTP_USER
    read -p "SMTP Password: " SMTP_PASS
    read -p "Email получателя: " SMTP_TO
fi

echo ""
echo ">>> Установка зависимостей..."
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git curl

echo ">>> Остановка старых сервисов..."
systemctl stop keenetic speed-server 2>/dev/null || true
systemctl disable keenetic speed-server 2>/dev/null || true

echo ">>> Клонирование проекта..."
rm -rf "$INSTALL_DIR"
git clone "$REPO" "$INSTALL_DIR"

echo ">>> Python окружение..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

echo ">>> Создание .env..."
cat > "$INSTALL_DIR/.env" << ENVEOF
ADMIN_PASSWORD=${ADMIN_PASSWORD:-admin}
TELEGRAM_TOKEN=${TG_TOKEN:-}
TELEGRAM_CHAT_ID=${TG_CHAT:-}
SMTP_HOST=${SMTP_HOST:-smtp.gmail.com}
SMTP_PORT=${SMTP_PORT:-587}
SMTP_USER=${SMTP_USER:-}
SMTP_PASS=${SMTP_PASS:-}
SMTP_TO=${SMTP_TO:-}
ENVEOF
chmod 600 "$INSTALL_DIR/.env"

echo ">>> Создание сервисов..."
cat > /etc/systemd/system/keenetic.service << EOF
[Unit]
Description=Keenetic Monitor Dashboard
After=network.target speed-server.service

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/main.py
Restart=always
RestartSec=5
User=root
EnvironmentFile=$INSTALL_DIR/.env

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/speed-server.service << EOF
[Unit]
Description=Keenetic Speed Server
After=network.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/speed_server.py
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

echo ">>> Запуск сервисов..."
systemctl daemon-reload
systemctl enable keenetic speed-server
systemctl restart speed-server
sleep 2
systemctl restart keenetic
sleep 3

SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_IP")

echo ""
echo "============================================"
echo "   Установка завершена!"
echo "============================================"
echo ""
systemctl is-active keenetic     && echo "  ✅ keenetic OK (порт 8000)"     || echo "  ❌ keenetic FAILED"
systemctl is-active speed-server && echo "  ✅ speed-server OK (порт 5000)" || echo "  ❌ speed-server FAILED"
echo ""
echo "  🌐 Дашборд:    http://$SERVER_IP:8000"
echo "  ⚡ Speed API:  http://$SERVER_IP:5000/api/all"
echo "  🔑 Логин:      admin / ${ADMIN_PASSWORD:-admin}"
echo ""
echo "  На каждом Windows PC настрой два скрипта:"
echo "  check_sites.ps1    — каждые 15 мин (Task Scheduler)"
echo "  speedtest_client.ps1 — каждые 4 часа (Task Scheduler)"
echo ""
echo "  В обоих скриптах укажи:"
echo "  \$SERVER      = \"http://$SERVER_IP:5000\""
echo "  \$ROUTER_NAME = \"имя_роутера\""
echo ""
