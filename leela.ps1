# Start / stop the Lc0 training client and the lc0-viz dashboard, in the style of `fishtest`.
#   leela            client (training games only) + dashboard; skips whatever is already running
#   leela stop       stop the client and lc0.exe, freeing the GPU (the dashboard keeps running)
#   leela stop all   also stop the dashboard (and the Net explorer's helper with it)
#   leela dashboard  just the dashboard
#   leela status     what's running, GPU load, dashboard URLs
# Works in Windows PowerShell 5.1 and PowerShell 7.
param(
    [ValidateSet('start', 'stop', 'dashboard', 'status')][string]$Mode = 'start',
    [ValidateSet('', 'all')][string]$What = ''
)

# Locations. The client folder is the newest lc0 release in Downloads that has lc0-training-client.exe
# (override with LC0_CLIENT_DIR); the phone address comes from `tailscale serve status` (see README).
$client = $env:LC0_CLIENT_DIR
if (-not $client) {
    $client = Get-ChildItem (Join-Path $HOME 'Downloads\lc0-*\lc0-training-client.exe') -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime | Select-Object -Last 1 -ExpandProperty DirectoryName
}
if (-not $client) { Write-Host '  no lc0 training client found in Downloads; set LC0_CLIENT_DIR' -ForegroundColor Red; return }
$viz = $PSScriptRoot
$port = 8765
$tailnetUrl = $null
if (Get-Command tailscale -ErrorAction SilentlyContinue) {
    # the https://<pc>.<tailnet>.ts.net:<port> entry that proxies to this dashboard, if one is set up
    $serve = (tailscale serve status 2>$null) -join "`n"
    $m = [regex]::Match($serve, "(https://\S+?:\d+)[^\n]*\n\|-- / proxy http://127\.0\.0\.1:$port")
    if ($m.Success) { $tailnetUrl = $m.Groups[1].Value + '/stats' }
}
$phone = if ($tailnetUrl) { "   phone: $tailnetUrl" } else { '' }
$python = $env:LC0VIZ_PYTHON
if (-not $python) {
    $python = Get-Command python -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch 'WindowsApps' } | Select-Object -First 1 -ExpandProperty Source
}
if (-not $python) { $python = 'py' }

function Get-Client { Get-Process -Name 'lc0-training-client' -ErrorAction SilentlyContinue }
function Get-Lc0 {
    # only the lc0.exe from the client's folder, never some other copy (e.g. one a GUI is using)
    Get-Process -Name 'lc0' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($client, 'OrdinalIgnoreCase') }
}
function Test-Dashboard {
    try { $c = New-Object Net.Sockets.TcpClient('127.0.0.1', $port); $c.Close(); return $true } catch { return $false }
}
function Get-Dashboard {
    Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'lc0viz\.py|networker\.py' }
}
function Show-Gpu {
    $g = nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu --format=csv,noheader,nounits 2>$null
    if ($g) {
        $u, $mu, $mt, $p, $t = ($g -split ',') | ForEach-Object { $_.Trim() }
        Write-Host ("  gpu      {0}% busy, {1:N1} / {2:N1} GB VRAM, {3:N0} W, {4:N0} C" -f $u, ($mu / 1024), ($mt / 1024), [double]$p, [double]$t) -ForegroundColor Gray
    }
}

if ($Mode -eq 'status') {
    $c = Get-Client; $l = Get-Lc0
    if ($c) {
        $up = (Get-Date) - $c.StartTime
        Write-Host ("  client   running, up {0}h {1}m{2}" -f [int]$up.TotalHours, $up.Minutes, $(if ($l) { '' } else { ' (lc0.exe not running: between games or downloading a net)' })) -ForegroundColor Green
    } else { Write-Host '  client   not running' -ForegroundColor DarkGray }
    if (Test-Dashboard) { Write-Host "  dashboard http://127.0.0.1:$port/stats$phone" -ForegroundColor Green }
    else { Write-Host '  dashboard not running' -ForegroundColor DarkGray }
    Show-Gpu
    return
}

if ($Mode -eq 'stop') {
    # The client has no graceful exit: finished training games are already uploaded (each one goes up as
    # soon as it ends), so stopping only loses the ~32 games in progress, which the server never sees.
    $c = Get-Client; $l = Get-Lc0
    if (-not $c -and -not $l) {
        Write-Host '  client   not running' -ForegroundColor DarkGray
    } else {
        # kill the client first so it can't start a fresh lc0.exe, then lc0.exe itself
        foreach ($p in @($c) + @($l)) { if ($p) { & taskkill.exe /PID $p.Id /T /F 2>$null | Out-Null } }
        for ($i = 0; $i -lt 20 -and ((Get-Client) -or (Get-Lc0)); $i++) { Start-Sleep -Milliseconds 500 }
        if ((Get-Client) -or (Get-Lc0)) { Write-Host '  client   could not be stopped (started from an admin shell? stop it there)' -ForegroundColor Red }
        else { Write-Host '  client   stopped; the GPU is free (games in progress are dropped, finished ones were already uploaded)' -ForegroundColor Green }
    }
    if ($What -eq 'all') {
        $d = Get-Dashboard
        if ($d) { $d | ForEach-Object { & taskkill.exe /PID $_.ProcessId /T /F 2>$null | Out-Null }; Write-Host '  dashboard stopped (games are no longer being saved)' -ForegroundColor Green }
        else { Write-Host '  dashboard not running' -ForegroundColor DarkGray }
    } elseif (Test-Dashboard) {
        Write-Host '  dashboard still running (light: no GPU). `leela stop all` stops it too' -ForegroundColor DarkGray
    }
    Start-Sleep -Seconds 1
    Show-Gpu
    return
}

# start: dashboard first, so it is already collecting when the first game finishes
if (Test-Dashboard) {
    Write-Host "  dashboard already running on :$port" -ForegroundColor DarkGray
} else {
    Start-Process -FilePath $python -ArgumentList @('-u', 'lc0viz.py', '--client-dir', "`"$client`"") -WorkingDirectory $viz -WindowStyle Minimized
    for ($i = 0; $i -lt 40 -and -not (Test-Dashboard); $i++) { Start-Sleep -Milliseconds 500 }
    if (Test-Dashboard) { Write-Host "  dashboard started (minimized window; closing it stops saving games)" -ForegroundColor Green }
    else { Write-Host "  dashboard did not answer on :$port within 20 s; check its window" -ForegroundColor Red }
}
if ($Mode -eq 'dashboard') {
    Write-Host "  open     http://127.0.0.1:$port/stats$phone" -ForegroundColor Gray
    return
}

if (Get-Client) {
    Write-Host '  client   already running' -ForegroundColor DarkGray
} else {
    # -train-only: training games (counted on Active Users); without it the client also takes match games
    Start-Process -FilePath (Join-Path $client 'lc0-training-client.exe') -ArgumentList '-train-only' -WorkingDirectory $client -WindowStyle Minimized
    Write-Host '  client   started (training games only, minimized window)' -ForegroundColor Green
}
Write-Host "  open     http://127.0.0.1:$port/stats$phone" -ForegroundColor Gray
