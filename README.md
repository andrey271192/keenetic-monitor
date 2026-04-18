# 📡 Keenetic Monitor v4.0

Система мониторинга роутеров Keenetic с проверкой сайтов, speedtest статистикой и автоматическим перезапуском HydraRoute Neo.

![Version](https://img.shields.io/badge/version-4.0-green)
![Platform](https://img.shields.io/badge/platform-Ubuntu-orange)
![Python](https://img.shields.io/badge/python-3.10+-blue)

---

## 🚀 Возможности

- 📡 ONLINE/OFFLINE статус каждого роутера
- 🎬 Проверка YouTube / Netflix / Telegram каждые 15 минут
- 🔄 Автоматический перезапуск **HydraRoute Neo** через SSH при недоступности сайтов
- ⚡ Speedtest VPN + RU канал каждые 4 часа
- 📊 График скорости за 7 дней в каждой карточке
- 🔔 Уведомления Telegram + Email при падении и восстановлении
- 🗑 Автоочистка истории speedtest (старше 7 дней)
- 🔑 Авторизация в веб-интерфейсе
- ➕ Добавление/удаление роутеров через веб

---

## 🏗️ Архитектура

```
Каждые 15 мин (check_sites.ps1):
  Windows PC → проверяет YouTube/Netflix/Telegram
             → POST /push_sites → сервер отвечает {restart_neo: true/false}
             → если restart_neo=true → SSH на роутер → S99hrneo restart
             → ждёт 2 мин → повторная проверка → отправляет результат

Каждые 4 часа (speedtest_client.ps1):
  Windows PC → speedtest VPN + RU
             → POST /push_speed → сохраняется в историю (7 дней)

Сервер (main.py порт 8000):
  → дашборд с карточками роутеров
  → уведомления при изменении статуса сайтов

Сервер (speed_server.py порт 5000):
  → принимает данные с Windows PC
  → хранит историю speedtest
  → управляет очередью restart_neo
```

---

## ⚡ Установка сервера (1 команда)

```bash
apt-get install -y python3 python3-pip python3-venv python3.12-venv git curl
```

```bash
curl -sL https://raw.githubusercontent.com/andrey271192/keenetic-monitor/main/install.sh | bash
```

---

## 🖥️ Настройка Windows PC

На каждом объекте настроить **два скрипта** в Task Scheduler.

### check_sites.ps1 — каждые 15 минут

```powershell
$SERVER          = "http://IP_СЕРВЕРА:5000"
$ROUTER_NAME     = "home"
$ROUTER_SSH_HOST = "192.168.88.1"
$ROUTER_SSH_USER = "root"
$ROUTER_SSH_KEY  = "$env:USERPROFILE\.ssh\id_rsa"
```

### speedtest_client.ps1 — каждые 4 часа

```powershell
$SERVER      = "http://IP_СЕРВЕРА:5000"
$ROUTER_NAME = "home"
```

### SSH ключ для роутера (один раз на каждом PC)

```powershell
# На Windows PC:
ssh-keygen -t rsa -b 2048 -f "$env:USERPROFILE\.ssh\id_rsa"
```

```sh
# На роутере — добавить публичный ключ:
cat >> /opt/etc/dropbear/authorized_keys << 'EOF'
(вставь содержимое id_rsa.pub)
EOF
chmod 600 /opt/etc/dropbear/authorized_keys
```

---

## 🔒 Безопасность

Секреты хранятся в `.env` — не попадает в Git:

```
ADMIN_PASSWORD=your_password
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
SMTP_USER=...
SMTP_PASS=...
SMTP_TO=...
```

---

## 🔔 Уведомления

| Событие | Сообщение |
|---------|-----------|
| Сайт упал | ❌ YouTube недоступен — Андрей Квартира → перезапускаю neo |
| Сайт восстановлен | ✅ YouTube снова работает — Андрей Квартира |

---

## 🌐 Доступ

```
http://SERVER_IP:8000         — дашборд
http://SERVER_IP:8000/admin   — управление роутерами
http://SERVER_IP:8000/mapping — редактирование имён
http://SERVER_IP:5000/api/all — все данные (JSON)
```

---

## 🔧 Управление

```bash
systemctl restart keenetic
systemctl restart speed-server
journalctl -u keenetic -f
journalctl -u speed-server -f
```

---

## 📁 Структура

```
keenetic-monitor/
├── main.py               # Дашборд (порт 8000)
├── speed_server.py       # Speed сервер (порт 5000)
├── keenetic_api.py       # API клиент Keenetic
├── notifier.py           # Уведомления
├── config.py             # Настройки
├── install.sh            # Установщик
├── check_sites.ps1       # Windows: сайты каждые 15 мин
├── speedtest_client.ps1  # Windows: speedtest каждые 4 часа
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## 📄 Лицензия

MIT
