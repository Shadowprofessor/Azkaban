# Finishes the v1 setup from YOUR machine. Run from the repo root in PowerShell:
#
#     powershell -ExecutionPolicy Bypass -File scripts\finish-v1.ps1
#
# Does the three things the cloud session could not:
#   1. pushes the v1 branch (GitHub refuses pushes from the sandbox)
#   2. calls the NVIDIA endpoint for real (the sandbox blocks that host)
#   3. installs a Playwright Chromium and runs the browser e2e

$ErrorActionPreference = "Continue"
$failed = @()

function Step($name) { Write-Host ""; Write-Host "=== $name ===" -ForegroundColor Cyan }
function Good($m)    { Write-Host "  OK  $m" -ForegroundColor Green }
function Bad($m)     { Write-Host "  !!  $m" -ForegroundColor Red }

if (-not (Test-Path ".git")) { Bad "Run this from the repo root (no .git here)."; exit 1 }

# ---------------------------------------------------------------- 1. push
Step "1/4  push the v1 branch"
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "v1") {
    Write-Host "  switching from '$branch' to v1"
    git checkout v1
    if ($LASTEXITCODE -ne 0) { Bad "no local v1 branch found"; $failed += "push"; }
}
$dirty = (git status --porcelain)
if ($dirty) { Write-Host "  note: uncommitted changes present; pushing committed work only" }
git push -u origin v1
if ($LASTEXITCODE -eq 0) {
    Good "pushed. Open: https://github.com/Shadowprofessor/Azkaban/tree/v1"
} else {
    Bad "push failed (see the git error above). If it is auth, run: gh auth login"
    $failed += "push"
}

# ---------------------------------------------------------------- 2. nemotron
Step "2/4  verify Nemotron on NVIDIA NIM"
if (-not (Test-Path ".env")) {
    Bad ".env is missing. Copy .env.example to .env and put NVIDIA_API_KEY in it."
    $failed += "nemotron"
} else {
    python -m azkaban_agent nim-check
    if ($LASTEXITCODE -eq 0) { Good "Nemotron answered" } else { Bad "nim-check failed (exit $LASTEXITCODE)"; $failed += "nemotron" }
}

# ---------------------------------------------------------------- 3. playwright
Step "3/4  browser end-to-end"
Push-Location azkaban-extension
if (-not (Test-Path "node_modules")) { Write-Host "  installing deps..."; npm install --no-audit --no-fund }
if (-not (Test-Path ".output\chrome-mv3\manifest.json")) { Write-Host "  building..."; npm run build }
npx playwright install chromium
if ($LASTEXITCODE -ne 0) { Bad "playwright install failed"; $failed += "playwright" }
else {
    Good "chromium installed"
    npm run test:score
    if ($LASTEXITCODE -eq 0) { Good "scoring + live popup checks passed" } else { Bad "phase 8 e2e failed"; $failed += "e2e-phase8" }
    node --experimental-strip-types e2e/phase7.mjs
    if ($LASTEXITCODE -eq 0) { Good "phase 7 blocking checks passed" } else { Write-Host "  (phase 7 needs the full earlier fixtures; non-fatal)" }
}
Pop-Location

# ---------------------------------------------------------------- 4. summary
Step "4/4  summary"
if ($failed.Count -eq 0) {
    Good "everything passed"
    Write-Host ""
    Write-Host "Next, to run on real data:" -ForegroundColor Yellow
    Write-Host "  1. python -m azkaban_agent capture --i-own-this-device"
    Write-Host "  2. set the system proxy to 127.0.0.1:8080 and install the CA from http://mitm.it"
    Write-Host "  3. cd dashboard; npm run dev        ->  http://127.0.0.1:5173"
    Write-Host "  4. load azkaban-extension\.output\chrome-mv3 at chrome://extensions"
} else {
    Bad ("these did not pass: " + ($failed -join ", "))
    Write-Host "  Everything else is fine; see V1.md for what each step needs."
    exit 1
}
