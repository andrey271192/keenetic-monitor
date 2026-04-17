# =============================================================
#   check_sites.ps1 — проверка сайтов каждые 15 минут
#   Keenetic Monitor v4.0
#
#   НАСТРОЙКА:
#   1. Укажи SERVER, ROUTER_NAME, ROUTER_SSH_HOST, ROUTER_SSH_USER
#   2. Добавь в Task Scheduler: каждые 15 минут
# =============================================================

# ===== НАСТРОЙКИ (меняй для каждого объекта) =====
$SERVER          = "http://YOUR_SERVER_IP:5000"
$ROUTER_NAME     = "home"           # имя как в мониторе
$ROUTER_SSH_HOST = "192.168.88.1"   # IP роутера в локальной сети
$ROUTER_SSH_USER = "root"           # SSH логин роутера (обычно root)
$ROUTER_SSH_KEY  = "$env:USERPROFILE\.ssh\id_rsa"  # путь к SSH ключу
# =================================================

$PC_NAME = $env:COMPUTERNAME
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
$log = "check_sites.log"

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] $msg" | Tee-Object -FilePath $log -Append | Write-Host
}

Write-Log "[$ROUTER_NAME] Starting site check..."

# ===== ПРОВЕРКА САЙТОВ =====
function Check-Site($url, $name) {
    try {
        $start = Get-Date
        $resp = Invoke-WebRequest $url -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -lt 400) {
            $ms = [math]::Round(((Get-Date) - $start).TotalMilliseconds, 0)
            Write-Log "${name}: OK (${ms}ms)"
            return @{ ok = $true; ms = $ms }
        }
    } catch {}
    Write-Log "${name}: FAIL"
    return @{ ok = $false; ms = 0 }
}

$youtube  = Check-Site "https://www.youtube.com"  "YouTube"
$netflix  = Check-Site "https://www.netflix.com"  "Netflix"
$telegram = Check-Site "https://web.telegram.org" "Telegram"

# Внешний IP
try { $ip = (Invoke-RestMethod "https://api.ipify.org" -TimeoutSec 5).Trim() }
catch { $ip = "unknown" }

# ===== ОТПРАВКА НА СЕРВЕР =====
$body = @{
    router_name  = $ROUTER_NAME
    ip           = $ip
    time         = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    youtube_ok   = $youtube.ok
    youtube_ms   = $youtube.ms
    netflix_ok   = $netflix.ok
    netflix_ms   = $netflix.ms
    telegram_ok  = $telegram.ok
    telegram_ms  = $telegram.ms
} | ConvertTo-Json -Depth 3

$restart_neo = $false

try {
    $result = Invoke-RestMethod -Uri "$SERVER/push_sites" -Method Post `
        -Body $body -ContentType "application/json" -TimeoutSec 15
    Write-Log "Server: status=$($result.status) restart_neo=$($result.restart_neo)"
    $restart_neo = $result.restart_neo
} catch {
    Write-Log "Failed to send to server: $_"
}

# ===== ПЕРЕЗАПУСК NEO ЧЕРЕЗ SSH =====
if ($restart_neo) {
    Write-Log "Restarting neo via SSH on $ROUTER_SSH_HOST..."
    try {
        # Перезапускаем neo
        $ssh_cmd = "ssh -i `"$ROUTER_SSH_KEY`" -o StrictHostKeyChecking=no -o ConnectTimeout=10 ${ROUTER_SSH_USER}@${ROUTER_SSH_HOST} '/opt/etc/init.d/S99hrneo restart'"
        $output = cmd /c $ssh_cmd 2>&1
        Write-Log "SSH result: $output"

        # Ждём 2 минуты пока neo поднимается
        Write-Log "Waiting 120 sec for neo to start..."
        Start-Sleep -Seconds 120

        # Повторная проверка сайтов
        Write-Log "Re-checking sites after restart..."
        $yt2  = Check-Site "https://www.youtube.com"  "YouTube"
        $nf2  = Check-Site "https://www.netflix.com"  "Netflix"
        $tg2  = Check-Site "https://web.telegram.org" "Telegram"

        # Отправляем результат повторной проверки
        $body2 = @{
            router_name  = $ROUTER_NAME
            ip           = $ip
            time         = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            youtube_ok   = $yt2.ok
            youtube_ms   = $yt2.ms
            netflix_ok   = $nf2.ok
            netflix_ms   = $nf2.ms
            telegram_ok  = $tg2.ok
            telegram_ms  = $tg2.ms
        } | ConvertTo-Json -Depth 3

        Invoke-RestMethod -Uri "$SERVER/push_sites" -Method Post `
            -Body $body2 -ContentType "application/json" -TimeoutSec 15 | Out-Null
        Write-Log "Post-restart check sent"

    } catch {
        Write-Log "SSH restart failed: $_"
    }
}

Write-Log "Done."

# Ротация лога — оставляем последние 500 строк
if (Test-Path $log) {
    $lines = Get-Content $log
    if ($lines.Count -gt 500) {
        $lines | Select-Object -Last 500 | Set-Content $log
    }
}
