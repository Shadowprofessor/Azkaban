# Starts Azkaban on real data: agent (capture proxy + socket) and the dashboard/website.
#
#     powershell -ExecutionPolicy Bypass -File scripts\start.ps1
#
# Opens two windows and the dashboard in your browser. Close the windows to stop.
# You still point traffic at the proxy yourself (it is your device; that is the consent).

$root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $root
function Info($m) { Write-Host "  $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "  !! $m" -ForegroundColor Yellow }

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Warn ".env created from the example: put NVIDIA_API_KEY in it" }
if (Select-String -Path ".env.example" -Pattern "^NVIDIA_API_KEY=nvapi-" -Quiet) {
    Warn ".env.example contains a real key. It is tracked by git, so it would be published."
    Warn "Put the key in .env only and leave NVIDIA_API_KEY= empty in .env.example."
}

# Python agent deps (once)
python -c "import mitmproxy, websockets, onnxruntime" 2>$null
if ($LASTEXITCODE -ne 0) { Info "installing the agent (first run only)..."; python -m pip install -e "azkaban-agent[dev]" }

# Dashboard deps. Checks for the vite launcher, not just the folder: a node_modules
# copied from another OS (or an interrupted install) exists but cannot run.
if (-not (Test-Path "dashboard\node_modules\.bin\vite.cmd")) {
    Info "installing the dashboard (first run, or repairing a broken install)..."
    if (Test-Path "dashboard\node_modules") { Remove-Item -Recurse -Force "dashboard\node_modules" }
    Push-Location dashboard; npm install --no-audit --no-fund; Pop-Location
}

# Extension build (once), so it can be loaded
if (-not (Test-Path "azkaban-extension\.output\chrome-mv3\manifest.json")) {
    Info "building the extension (first run only)..."
    Push-Location azkaban-extension; if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }; npm run build; Pop-Location
}

# Anything left from an earlier start holds our ports and makes the new one fail.
# Stop only our own kinds of process on exactly our ports: python (agent, ghostprint)
# and node (the website). Anything else listening there is reported, never touched.
$ports = 8787, 8080, 8765, 5173
$old = Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue |
       Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $old) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p -and ($p.ProcessName -like "python*" -or $p.ProcessName -eq "node")) {
        Info "stopping an earlier $($p.ProcessName) (pid $procId) that still holds a port"
        Stop-Process -Id $procId -Force
    } elseif ($p) {
        Warn "a port Azkaban needs is used by $($p.ProcessName) (pid $procId). Close it first."
    }
}
Start-Sleep -Milliseconds 800

Info "checking the reasoning model..."
python -m azkaban_agent nim-check

# Both servers log to logs\ so a failure can be read afterwards (and by a helper session)
# instead of only flashing past in a window that may close or hide.
New-Item -ItemType Directory -Force -Path "$root\logs" | Out-Null
$agentLog = "$root\logs\agent.log"
$dashLog  = "$root\logs\dashboard.log"
"" | Set-Content -Encoding utf8 $agentLog
"" | Set-Content -Encoding utf8 $dashLog

$gpLog = "$root\logs\ghostprint.log"
"" | Set-Content -Encoding utf8 $gpLog

# Each service runs from its own small generated .ps1 in logs\. That avoids nesting
# quotes through Start-Process, which breaks on a path with a space ("Sachit Sharma").
# Output is shown in the window AND appended to the log. "$_" turns stderr records into
# plain text, so ordinary Python log lines are not shown as red NativeCommandError.
function Launch($name, $title, $dir, $command, $log) {
    $file = "$root\logs\run-$name.ps1"
    @(
        "`$Host.UI.RawUI.WindowTitle = '$title'"
        "`$env:PYTHONUNBUFFERED = '1'; `$env:PYTHONIOENCODING = 'utf-8'"
        "`$env:GHOSTPRINT_RETURN_URL = 'http://127.0.0.1:5173/'"
        "Set-Location -LiteralPath '$dir'"
        "$command 2>&1 | ForEach-Object { `"`$_`" } | Tee-Object -FilePath '$log' -Append"
    ) | Set-Content -Encoding utf8 $file
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$file`"")
}
Launch "agent"      "Azkaban agent"      $root              "python -m azkaban_agent capture --i-own-this-device" $agentLog
Launch "ghostprint" "Azkaban ghostprint" $root              "python -m ghostprint live --port 8765"               $gpLog
Launch "website"    "Azkaban website"    "$root\dashboard"  "npm run dev"                                          $dashLog

# Do not claim success until both ports actually answer.
function PortUp($port) {
    try { $c = New-Object Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $port); $c.Close(); return $true } catch { return $false }
}
$agentUp = $false; $dashUp = $false; $gpUp = $false
for ($i = 0; $i -lt 60; $i++) {
    if (-not $agentUp) { $agentUp = PortUp 8787 }
    if (-not $gpUp)    { $gpUp    = PortUp 8765 }
    if (-not $dashUp)  { $dashUp  = PortUp 5173 }
    if ($agentUp -and $dashUp -and $gpUp) { break }
    Start-Sleep -Milliseconds 500
}
if ($agentUp) { Info "agent is up:      ws://127.0.0.1:8787  (capture proxy 127.0.0.1:8080)" } else { Warn "agent did NOT start. Last lines of logs\agent.log:"; Get-Content $agentLog -Tail 15 }
if ($gpUp)    { Info "ghostprint is up: http://127.0.0.1:8765 (accounts, breach scan, site checks)" } else { Warn "ghostprint did NOT start. Last lines of logs\ghostprint.log:"; Get-Content $gpLog -Tail 15 }
if ($dashUp)  { Info "website is up:    http://127.0.0.1:5173"; Start-Process "http://127.0.0.1:5173" } else { Warn "website did NOT start. Last lines of logs\dashboard.log:"; Get-Content $dashLog -Tail 15 }

Write-Host ""
Write-Host "To see YOUR traffic:" -ForegroundColor Green
Write-Host "  1. Windows Settings > Network > Proxy > Manual: 127.0.0.1  port 8080"
Write-Host "  2. Open http://mitm.it and install the Windows certificate (once)"
Write-Host "  3. chrome://extensions > Developer mode > Load unpacked >"
Write-Host "     $root\azkaban-extension\.output\chrome-mv3"
Write-Host "  4. In the website: tick the box, I confirm and continue, then Start local audit"
Write-Host ""
Write-Host "When done: turn the Windows proxy OFF again, or your internet stops when the agent stops." -ForegroundColor Yellow
