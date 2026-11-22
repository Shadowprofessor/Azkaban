# Publishes v1 and checks the parts the cloud session cannot reach.
#
# Run it as a FILE from the repo root (do not paste it line by line):
#     powershell -ExecutionPolicy Bypass -File scripts\finish-v1.ps1
#
# 1. pushes main to GitHub (the only branch the project ships from)
# 2. calls NVIDIA NIM for real and reports which Nemotron models your key may use
# 3. installs Playwright Chromium and runs the extension's browser checks
# It is written so that pasting it still works: every else is on its brace's line.

$failed = @()
function Step($n) { Write-Host ""; Write-Host "=== $n ===" -ForegroundColor Cyan }
function Good($m) { Write-Host "  OK  $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  !!  $m" -ForegroundColor Red }

if (-not (Test-Path ".git")) { Bad "Run this from the repo root (C:\Users\...\Azkaban)."; return }

Step "1/3  publish main"
git fetch origin
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "main") { git checkout main }
git push origin main
if ($LASTEXITCODE -eq 0) { Good "pushed main" } else { Bad "push failed; read the git message above (auth: run 'gh auth login')"; $failed += "push" }

Step "2/3  Nemotron on NVIDIA NIM"
if (Test-Path ".env") {
    python -m azkaban_agent nim-check
    if ($LASTEXITCODE -eq 0) { Good "a Nemotron model answered" } else { Bad "no Nemotron model answered; see the table above"; $failed += "nemotron" }
} else {
    Bad ".env missing: copy .env.example to .env and set NVIDIA_API_KEY"; $failed += "nemotron"
}

Step "3/3  extension browser checks"
Push-Location azkaban-extension
if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }
npm run build
npx playwright install chromium
if ($LASTEXITCODE -eq 0) {
    npm run test:score
    if ($LASTEXITCODE -eq 0) { Good "score + live popup checks passed" } else { Bad "phase 8 browser check failed"; $failed += "e2e" }
} else {
    Bad "playwright could not install chromium"; $failed += "playwright"
}
Pop-Location

Step "summary"
if ($failed.Count -eq 0) { Good "all done" } else { Bad ("needs attention: " + ($failed -join ", ")) }
Write-Host ""
Write-Host "Run on real data:" -ForegroundColor Yellow
Write-Host "  terminal 1:  python -m azkaban_agent capture --i-own-this-device"
Write-Host "  then:        Windows proxy -> 127.0.0.1:8080, open http://mitm.it and install the certificate"
Write-Host "  terminal 2:  cd dashboard; npm install; npm run dev     (http://127.0.0.1:5173)"
Write-Host "  chrome:      chrome://extensions -> Load unpacked -> azkaban-extension\.output\chrome-mv3"
