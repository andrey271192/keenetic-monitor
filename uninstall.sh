#!/bin/bash

echo "🧹 Keenetic Monitor Uninstall"

APP_DIR="/opt/keenetic-monitor"

systemctl stop keenetic 2>/dev/null
systemctl disable keenetic 2>/dev/null

rm -f /etc/systemd/system/keenetic.service
systemctl daemon-reload

rm -rf $APP_DIR

echo "✅ Полностью удалено!"
