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

# An agent left running from an earlier start holds 8787/8080 and makes the new one fail.
# Stop only Python processes listening on exactly those ports: those are Azkaban agents.
$old = Get-NetTCPConnection -LocalPort 8787,8080 -State Listen -ErrorAction SilentlyContinue |
       Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $old) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -like "python*") {
        Info "stopping an earlier agent (pid $procId) that still holds the ports"
        Stop-Process -Id $procId -Force
    } elseif ($p) {
        Warn "port 8787/8080 is used by $($p.ProcessName) (pid $procId), not Azkaban. Close it first."
    }
}
Start-Sleep -Milliseconds 500

Info "checking the reasoning model..."
python -m azkaban_agent nim-check

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; python -m azkaban_agent capture --i-own-this-device"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\dashboard'; npm run dev"
Start-Sleep -Seconds 6
Start-Process "http://127.0.0.1:5173"

Write-Host ""
Write-Host "Running. To see YOUR traffic:" -ForegroundColor Green
Write-Host "  1. Windows Settings > Network > Proxy > Manual: 127.0.0.1  port 8080"
Write-Host "  2. Open http://mitm.it and install the Windows certificate (once)"
Write-Host "  3. chrome://extensions > Developer mode > Load unpacked >"
Write-Host "     $root\azkaban-extension\.output\chrome-mv3"
Write-Host "  4. In the dashboard: accept, then Start local audit"
Write-Host ""
Write-Host "When done: turn the Windows proxy OFF again, or your internet stops when the agent stops." -ForegroundColor Yellow
