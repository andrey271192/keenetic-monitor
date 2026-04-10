#!/bin/bash

echo "🧹 Keenetic Monitor Uninstall"

APP_DIR="/opt/keenetic-monitor"

# ========= STOP SERVICE =========
echo "⛔ Останавливаем сервис..."
systemctl stop keenetic 2>/dev/null

echo "❌ Отключаем автозапуск..."
systemctl disable keenetic 2>/dev/null

# ========= REMOVE SERVICE =========
echo "🗑 Удаляем systemd сервис..."
rm -f /etc/systemd/system/keenetic.service

systemctl daemon-reload

# ========= REMOVE APP =========
echo "🗑 Удаляем файлы приложения..."
rm -rf $APP_DIR

# ========= OPTIONAL CLEAN =========
read -p "Удалить Python зависимости? (y/n): " yn
if [ "$yn" = "y" ]; then
    pip3 uninstall -y fastapi uvicorn httpx 2>/dev/null
fi

# ========= DONE =========
echo ""
echo "✅ Keenetic Monitor полностью удалён!"
