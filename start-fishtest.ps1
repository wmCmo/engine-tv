# Start the Fishtest worker, monitor and TV together. Anything already running is left alone
# (especially the TV: two TVs would mean two commentators talking over each other).
#   fishtest        worker + monitor + TV
#   fishtest tv     the TV only (starts the monitor too if it isn't running)
#   fishtest stop   stop the worker gracefully (places fish.exit, like the Worker Manager app's stop)
#   fishtest worker the worker and monitor only, no TV (what the phone remote uses)
#   fishtest tvoff  close the TV
#   fishtest remote print the phone remote's URL and PIN
# Works in both Windows PowerShell 5.1 and PowerShell 7.
param([ValidateSet('all', 'tv', 'stop', 'worker', 'tvoff', 'remote')][string]$Mode = 'all')

# Locations, overridable with environment variables (FISHTEST_WORKER / FISHTEST_PYTHON / MSYS2_ROOT)
$project = $PSScriptRoot  # this repository (monitor, TV)
$worker = if ($env:FISHTEST_WORKER) { $env:FISHTEST_WORKER } else { 'C:\fishtest\worker' }  # the Fishtest worker itself
$msys = if ($env:MSYS2_ROOT) { $env:MSYS2_ROOT } else { 'C:\msys64' }
$port = 8787
$tvUrl = "http://127.0.0.1:$port/tv"
$tvProfile = Join-Path $env:LOCALAPPDATA 'fishtest-tv-edge'
# Python for the monitor: avoid the Microsoft Store python.exe stub in WindowsApps
$python = $env:FISHTEST_PYTHON
if (-not $python) {
    $python = Get-Command python -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch 'WindowsApps' } | Select-Object -First 1 -ExpandProperty Source
}
if (-not $python) { $python = 'py' }

function Test-Monitor {
    try { $c = New-Object Net.Sockets.TcpClient('127.0.0.1', $port); $c.Close(); return $true } catch { return $false }
}

function Get-Running([string]$pattern, [string]$name) {
    Get-CimInstance Win32_Process -Filter "Name LIKE '$name'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $pattern }
}

# The worker's python runs under MSYS2 and its command line is often unreadable from PowerShell,
# so Get-Running 'worker\.py' misses it. Use the worker's own lock file instead: openlock writes
# the holder's PID to it, and we confirm that PID is still a python3 process.
function Test-Worker {
    $lock = Join-Path $worker 'fishtest_worker.lock'
    $lockPid = Get-Content $lock -TotalCount 1 -ErrorAction SilentlyContinue
    if ($lockPid -match '^\d+$') {
        $p = Get-Process -Id ([int]$lockPid) -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -like 'python3*') { return $true }
    }
    return [bool](Get-Running 'worker\.py' 'python3%')
}

# Stop: at its next report the worker finds fish.exit, sends its finished games, then stops
# (only the few games in progress are lost; the server hands the rest to other PCs). The worker deletes fish.exit itself
if ($Mode -eq 'stop') {
    if (-not (Test-Worker)) {
        Write-Host '  worker   not running' -ForegroundColor DarkGray
        return
    }
    New-Item -Path (Join-Path $worker 'fish.exit') -ItemType File -Force | Out-Null
    Write-Host '  worker   stopping gracefully (fish.exit, same as the Worker Manager app)...' -ForegroundColor Green
    for ($i = 0; $i -lt 300 -and (Test-Worker); $i++) { Start-Sleep -Seconds 1 }
    if (Test-Worker) {
        Write-Host '  worker   still finishing after 5 min; it will stop at its next report' -ForegroundColor Yellow
    } else {
        Write-Host "  worker   stopped after ${i}s. Monitor and TV keep running (close them, or Alt+F4 the TV)" -ForegroundColor Green
    }
    return
}

# Close the TV: end only the Edge with the TV's own profile, with its child processes (your normal Edge is untouched)
if ($Mode -eq 'tvoff') {
    $tv = Get-Running 'fishtest-tv-edge' 'msedge.exe'
    if (-not $tv) {
        Write-Host '  tv       not open' -ForegroundColor DarkGray
        return
    }
    $tv | ForEach-Object { & taskkill.exe /PID $_.ProcessId /T /F 2>$null | Out-Null }
    Write-Host '  tv       closed' -ForegroundColor Green
    return
}

# Monitor: listen on all interfaces so a phone on the LAN can open it.
# Other devices need the PIN (127.0.0.1 doesn't). Runs in a minimized window; closing it stops the monitor
function Start-Monitor {
    if (Test-Monitor) {
        Write-Host "  monitor  already running on :$port" -ForegroundColor DarkGray
        return
    }
    Start-Process -FilePath $python -ArgumentList @('monitor.py', '--host', '0.0.0.0', '--worker', "`"$worker`"") -WorkingDirectory $project -WindowStyle Minimized
    Write-Host "  monitor  starting on :$port (minimized window)" -ForegroundColor Green
}

# Remote: print the Wi-Fi IP and the PIN. The monitor creates the PIN in tv-cache\remote-pin.txt on first start
if ($Mode -eq 'remote') {
    Start-Monitor
    for ($i = 0; $i -lt 60 -and -not (Test-Monitor); $i++) { Start-Sleep -Milliseconds 500 }
    $pinFile = Join-Path $project 'tv-cache\remote-pin.txt'
    $pin = if (Test-Path $pinFile) { (Get-Content $pinFile -TotalCount 1).Trim() } else { '(not created yet; restart the monitor)' }
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -notmatch 'vEthernet|Loopback' -and $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' }
    Write-Host ''
    Write-Host '  Open on your phone (same Wi-Fi):' -ForegroundColor Green
    foreach ($ip in $ips) { Write-Host ("    http://{0}:{1}/remote   ({2})" -f $ip.IPAddress, $port, $ip.InterfaceAlias) }
    Write-Host "  PIN: $pin" -ForegroundColor Yellow
    Write-Host ''
    return
}

# 0. Updates: only for things that don't update themselves
#    - the worker asks Fishtest for the current version at start and while running, and updates and restarts itself
#    - Stockfish's history (for merge detection) is refreshed when the monitor starts
#    - Edge and Ollama update themselves
#    - Ollama models (commentary, scouting reports) don't update themselves, so pull them here.
#      About a second when up to date; a new version can be several GB, so it runs in the background and never delays the TV
$models = @($env:NARRATOR_MODEL, $env:BRIEF_MODEL, 'qwen3:8b') | Where-Object { $_ } | Select-Object -Unique
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    foreach ($m in $models) {
        Start-Process -FilePath 'ollama' -ArgumentList @('pull', $m) -WindowStyle Hidden
    }
    Write-Host "  models   checking for updates in the background ($($models -join ', '))" -ForegroundColor Green
} else {
    Write-Host '  models   ollama not found; the TV will run without commentary' -ForegroundColor Yellow
}
if ($Mode -in 'all', 'worker') {
    Write-Host '  worker   updates itself when it starts (asks Fishtest for the current version)' -ForegroundColor DarkGray
}

# 1. Worker: run worker.py in MSYS2's ucrt64 environment as usual (no window; output in log.txt)
if ($Mode -in 'all', 'worker') {
    if (Test-Worker) {
        Write-Host '  worker   already running' -ForegroundColor DarkGray
    } else {
        # No window: output goes to log.txt (the monitor shows it). Twice (2 and 8 Nov 2026) the worker
        # froze for hours mid-task with its output going to a terminal tab: alive, idle, never reporting.
        # Started like msys2_shell.cmd -ucrt64 would, but with CreateNoWindow so no console exists at all.
        $log = Join-Path $worker 'log.txt'
        if (Test-Path $log) { Move-Item $log "$log.previous" -Force }
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = Join-Path $msys 'usr\bin\bash.exe'
        $psi.Arguments = '-lc "exec env/bin/python3 -u worker.py >> log.txt 2>&1"'
        $psi.WorkingDirectory = $worker
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.EnvironmentVariables['MSYSTEM'] = 'UCRT64'
        $psi.EnvironmentVariables['CHERE_INVOKING'] = '1'
        [void][System.Diagnostics.Process]::Start($psi)
        Write-Host "  worker   started in the background (output: $log)" -ForegroundColor Green
    }
}

# 2. Monitor
Start-Monitor
if ($Mode -eq 'worker') { return }

# 3. TV: open it once the port answers (opening it earlier shows a connection error that needs a reload).
#    Its own profile means autoplay (the commentary voice) works even while your normal Edge is open
if (Get-Running 'fishtest-tv-edge' 'msedge.exe') {
    Write-Host '  tv       already open (Alt+F4 closes it)' -ForegroundColor DarkGray
    return
}
for ($i = 0; $i -lt 60 -and -not (Test-Monitor); $i++) { Start-Sleep -Milliseconds 500 }
if (-not (Test-Monitor)) {
    Write-Host "  tv       monitor did not answer on :$port within 30 s; not opening the TV" -ForegroundColor Red
    return
}
Start-Process -FilePath 'msedge' -ArgumentList @(
    '--kiosk', $tvUrl, '--edge-kiosk-type=fullscreen', '--autoplay-policy=no-user-gesture-required',
    "--user-data-dir=`"$tvProfile`"", '--no-first-run'
)
Write-Host '  tv       opened fullscreen (Alt+F4 closes it)' -ForegroundColor Green
