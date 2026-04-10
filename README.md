📡 Keenetic Monitor

Keenetic Monitor — это система мониторинга роутеров Keenetic с поддержкой:
	•	📡 статуса устройств
	•	⚡ скорости (VPN / RU канал)
	•	🎬 проверки YouTube (индикатор VPN)
	•	🔔 уведомлений (Telegram + Email)
	•	🧠 авто-обнаружения SNMP (WireGuard)
	•	🛠 веб-интерфейса управления

  🚀 Возможности

📊 Мониторинг
	•	ONLINE / OFFLINE роутеров
	•	VPN скорость (Speedtest)
	•	Российский канал (Yandex)
	•	Ping
	•	Проверка YouTube

🔔 Уведомления
	•	Telegram (бот)
	•	Email (SMTP)
	•	Авто-алерты:
	•	❌ YouTube упал → VPN не работает
	•	✅ YouTube восстановился

⚙️ Управление
	•	Добавление/удаление роутеров
	•	Редактирование отображаемых имён
	•	Автоматическая синхронизация

⸻

🧩 Требования
	•	Ubuntu / Debian сервер
	•	Python 3.10+
	•	Открытый порт: 8000

⚡ УСТАНОВКА (1 КОМАНДА)
apt install -y snmp snmp-mibs-downloader
curl -sL https://raw.githubusercontent.com/andrey271192/keenetic-monitor/main/install.sh | bash

📜 Управление
systemctl restart keenetic
systemctl status keenetic
journalctl -u keenetic -f


🧠 В ПРОЦЕССЕ УСТАНОВКИ

Ты введёшь:

🤖 Telegram (опционально)
	•	TOKEN
	•	CHAT_ID

📧 Email (опционально)
	•	SMTP (например Gmail)
	•	логин / пароль
	•	кому отправлять

📡 Speed Monitor

http://IP:5000/api/latest

🌐 Роутеры (можно сколько угодно)

Название
URL (http://ip)
Логин
Пароль

🌍 ДОСТУП К ПАНЕЛИ

После установки:

http://SERVER_IP:8000
admin / admin

🔧 УПРАВЛЕНИЕ

➕ Добавить роутер

через веб-интерфейс

➖ Удалить

там же

✏️ Имена
/mapping

🔄 УПРАВЛЕНИЕ СЕРВИСОМ
systemctl status keenetic
systemctl restart keenetic
systemctl stop keenetic

📜 ЛОГИ

journalctl -u keenetic -f

🧪 ПРОВЕРКА TELEGRAM
python3 -c "import requests; requests.post('https://api.telegram.org/botTOKEN/sendMessage', json={'chat_id':'CHAT_ID','text':'TEST'})"

⚠️ ЧАСТЫЕ ПРОБЛЕМЫ

❌ Telegram не шлёт
	•	неверный TOKEN
	•	бот не написал первым

⸻

❌ Email не шлёт
	•	Gmail требует app password

⸻

❌ SNMP не работает
apt install snmp

📁 СТРУКТУРА ПРОЕКТА
keenetic-monitor/
├── main.py
├── keenetic_api.py
├── config.py
├── mapping.json
├── requirements.txt
└── install.sh





