# 🖥️ Настройка Windows PC — пошаговая инструкция

## Что нужно на каждом объекте
- Windows PC с интернетом
- Доступ к роутеру по локальной сети (192.168.88.1)

---

## Шаг 1 — Создай папку

Создай папку:
```
C:\speedtest-monitor\
```

---

## Шаг 2 — Скопируй файлы в папку

Положи в папку `C:\speedtest-monitor\` эти файлы:
- `check_sites.ps1`
- `speedtest_client.ps1`
- `run_check_sites.bat`
- `run_speedtest.bat`
- `plink.exe` — скачай с **putty.org** → Downloads → plink.exe
- `speedtest.exe` — скачай с **speedtest.net/apps/cli** → Windows → распакуй

---

## Шаг 3 — Настрой скрипты

Открой `check_sites.ps1` в блокноте и измени:
```powershell
$SERVER          = "http://89.124.112.9:5000"   # IP сервера — не менять
$ROUTER_NAME     = "home"        # имя объекта (уникальное, без пробелов)
$ROUTER_SSH_HOST = "192.168.88.1" # IP роутера в локальной сети
$ROUTER_SSH_USER = "root"
$ROUTER_SSH_PASS = "keenetic"    # пароль SSH роутера
```

Открой `speedtest_client.ps1` в блокноте и измени:
```powershell
$SERVER      = "http://89.124.112.9:5000"   # IP сервера — не менять
$ROUTER_NAME = "home"        # то же имя что в check_sites.ps1
```

---

## Шаг 4 — Прими SSH ключ роутера (один раз)

Открой PowerShell и выполни:
```powershell
cd C:\speedtest-monitor
.\plink.exe -ssh -pw "keenetic" root@192.168.88.1 "echo SSH_OK"
```

Появится вопрос `Store key in cache? (y/n)` — нажми **y** и Enter.

Должно вывести `SSH_OK` — значит SSH работает.

---

## Шаг 5 — Проверь скрипты вручную

Открой PowerShell:
```powershell
cd C:\speedtest-monitor

# Проверка сайтов
powershell -ExecutionPolicy Bypass -File check_sites.ps1

# Speedtest
powershell -ExecutionPolicy Bypass -File speedtest_client.ps1
```

В логе должно быть:
```
YouTube: OK
Netflix: OK
Telegram: OK
Server: status=ok
Done.
```

---

## Шаг 6 — Добавь в Task Scheduler

Открой **PowerShell от имени администратора** и выполни:

```powershell
$dir = "C:\speedtest-monitor"

# Проверка сайтов — каждые 15 минут
$a1 = New-ScheduledTaskAction -Execute "$dir\run_check_sites.bat"
$t1 = New-ScheduledTaskTrigger -Daily -At "00:00"
$s1 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$p1 = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest
Register-ScheduledTask -TaskName "Keenetic Check Sites" -Action $a1 -Trigger $t1 -Settings $s1 -Principal $p1 -Force

# Вручную добавь повторение каждые 15 минут:
# Task Scheduler → Keenetic Check Sites → Триггеры → Изменить
# Повторять задачу каждые: 15 минут, в течение: Бессрочно

# Speedtest — каждые 4 часа
$a2 = New-ScheduledTaskAction -Execute "$dir\run_speedtest.bat"
$t2 = New-ScheduledTaskTrigger -Daily -At "00:00"
$s2 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$p2 = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest
Register-ScheduledTask -TaskName "Keenetic Speedtest" -Action $a2 -Trigger $t2 -Settings $s2 -Principal $p2 -Force

# Вручную добавь повторение каждые 4 часа:
# Task Scheduler → Keenetic Speedtest → Триггеры → Изменить
# Повторять задачу каждые: 4 часа, в течение: Бессрочно
```

---

## Шаг 7 — Настрой повторение в Task Scheduler

1. Открой **Планировщик задач** (Task Scheduler)
2. Найди задачу **Keenetic Check Sites**
3. Правой кнопкой → **Свойства** → вкладка **Триггеры**
4. Выбери триггер → **Изменить**
5. Поставь галочку **Повторять задачу каждые:** → укажи `15 минут`
6. **В течение:** → выбери `Бессрочно`
7. Нажми **OK**

Повтори то же для **Keenetic Speedtest** — но укажи `4 часа`.

---

## Проверка через дашборд

Открой в браузере: `http://89.124.112.9:8000`

Через несколько минут в карточке роутера появятся:
- ✓ YouTube / Netflix / Telegram
- Скорость VPN и RU канала

---

## Для каждого нового объекта

Скопируй папку `C:\speedtest-monitor\` на новый PC и измени только:
```powershell
$ROUTER_NAME     = "dacha"         # новое уникальное имя
$ROUTER_SSH_HOST = "192.168.88.1"  # IP роутера этого объекта
$ROUTER_SSH_PASS = "keenetic"      # пароль если отличается
```

Повтори шаги 4-7.
