# =============================================================
#   speedtest_client.ps1 — speedtest каждые 4 часа
#   Keenetic Monitor v4.0
#
#   НАСТРОЙКА:
#   1. Укажи SERVER и ROUTER_NAME
#   2. Положи speedtest.exe в ту же папку
#   3. Task Scheduler: каждые 4 часа
# =============================================================

# ===== НАСТРОЙКИ =====
$SERVER      = "http://YOUR_SERVER_IP:5000"
$ROUTER_NAME = "home"
# =====================

$PC_NAME = $env:COMPUTERNAME
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
$log = "speedtest.log"

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] $msg" | Tee-Object -FilePath $log -Append | Write-Host
}

Write-Log "[$ROUTER_NAME] Starting speedtest..."

# ===== VPN SPEEDTEST =====
$vpn_dl = 0; $vpn_ul = 0; $vpn_ping = 0
try {
    $json = .\speedtest.exe --accept-license --format=json 2>$null | ConvertFrom-Json
    if ($json -and $json.download) {
        $vpn_dl   = [math]::Round(($json.download.bandwidth * 8) / 1000000, 1)
        $vpn_ul   = [math]::Round(($json.upload.bandwidth * 8) / 1000000, 1)
        $vpn_ping = [math]::Round($json.ping.latency, 1)
    }
    Write-Log "VPN: DL=$vpn_dl UL=$vpn_ul Ping=$vpn_ping"
} catch {
    Write-Log "VPN speedtest failed: $_"
}
if ($vpn_dl -gt 10000) { $vpn_dl = 0 }
if ($vpn_ul -gt 10000) { $vpn_ul = 0 }

# ===== RU CHANNEL (Selectel) =====
$ru_dl = 0; $ru_ping = 0
try {
    $raw = curl.exe -o NUL -s -w "%{speed_download}" "https://speedtest.selectel.ru/100MB" 2>$null
    $raw = ($raw -replace "[^\d\.]", "").Trim()
    if ($raw -ne "") {
        $ru_dl = [math]::Round(([double]$raw * 8) / 1000000, 1)
    }
    Write-Log "RU: DL=$ru_dl"
} catch {
    Write-Log "RU test failed: $_"
}
if ($ru_dl -gt 10000) { $ru_dl = 0 }
try {
    $ru_ping = (Test-Connection speedtest.selectel.ru -Count 1 -ErrorAction Stop).ResponseTime
} catch { $ru_ping = 0 }

# ===== ВНЕШНИЙ IP =====
try { $ip = (Invoke-RestMethod "https://api.ipify.org" -TimeoutSec 5).Trim() }
catch { $ip = "unknown" }

# ===== ОТПРАВКА =====
$body = @{
    router_name  = $ROUTER_NAME
    pc           = $PC_NAME
    ip           = $ip
    time         = (Get-Date -Format "yyyy-MM-dd HH:mm")
    download_vpn = $vpn_dl
    upload_vpn   = $vpn_ul
    ping_vpn     = $vpn_ping
    download_ru  = $ru_dl
    ping_ru      = $ru_ping
} | ConvertTo-Json -Depth 3

try {
    $result = Invoke-RestMethod -Uri "$SERVER/push_speed" -Method Post `
        -Body $body -ContentType "application/json" -TimeoutSec 15
    Write-Log "Sent OK: records=$($result.records)"
} catch {
    Write-Log "Failed to send: $_"
}

Write-Log "Done."

# Ротация лога
if (Test-Path $log) {
    $lines = Get-Content $log
    if ($lines.Count -gt 200) {
        $lines | Select-Object -Last 200 | Set-Content $log
    }
}
