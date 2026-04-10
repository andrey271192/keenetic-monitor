#!/bin/bash

echo "🚀 Installing Keenetic Monitor..."

apt update
apt install -y python3 python3-venv python3-pip git

# Клонируем проект
cd /opt
rm -rf keenetic-monitor
git clone https://github.com/YOUR_USERNAME/keenetic-monitor.git
cd keenetic-monitor

# Виртуальное окружение
python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

# systemd
cp speedmonitor.service /etc/systemd/system/

systemctl daemon-reexec
systemctl daemon-reload
systemctl enable speedmonitor
systemctl restart speedmonitor

echo "✅ Installed!"
echo "🌐 Open: http://YOUR_SERVER_IP:8000"
