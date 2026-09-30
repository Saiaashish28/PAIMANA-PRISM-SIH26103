# PAIMANA PRISM - one-command start for Windows (PowerShell)
#   Right-click > "Run with PowerShell", or from a terminal in this folder:  .\start.ps1
# If scripts are blocked:  powershell -ExecutionPolicy Bypass -File .\start.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPy = Join-Path $backend ".venv\Scripts\python.exe"

Write-Host "== PAIMANA PRISM ==" -ForegroundColor Cyan

# 1. Python virtual environment (always use ITS python, never whichever one is first on PATH)
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating Python environment in backend\.venv ..."
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { & py -3 -m venv (Join-Path $backend ".venv") } else { & python -m venv (Join-Path $backend ".venv") }
}
$stamp = Join-Path $backend ".venv\.installed"
$req = Join-Path $backend "requirements.txt"
if (-not (Test-Path $stamp) -or (Get-Item $req).LastWriteTime -gt (Get-Item $stamp).LastWriteTime) {
    Write-Host "Installing backend packages (first run takes a few minutes) ..."
    & $venvPy -m pip install --upgrade pip | Out-Null
    & $venvPy -m pip install -r $req
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    New-Item -ItemType File -Force $stamp | Out-Null
}

# 2. Frontend packages
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "Installing frontend packages ..."
    Push-Location $frontend; npm install; Pop-Location
}

# Is a dashboard already running (and probably open in a browser tab)?
$webUp = [bool](Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue)

# 3. Free port 8000 if an old server is still running
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host "Stopping old process on port 8000 (PID $($_.OwningProcess))"; Stop-Process -Id $_.OwningProcess -Force }

# 4. Optional local LLM (Ollama + Qwen 2.5 3B) for fluent assistant answers
$model = if ($env:PRISM_OLLAMA_MODEL) { $env:PRISM_OLLAMA_MODEL } else { "qwen2.5:3b" }
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    if (-not (Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)) {
        Write-Host "Starting Ollama ..."
        Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 3
    }
    if (-not ((ollama list) -match [regex]::Escape($model))) {
        Write-Host "Downloading LLM model $model (~2 GB, one time) ..."
        ollama pull $model
    }
    Write-Host "Local LLM: $model (Ollama)" -ForegroundColor Green
} else {
    Write-Host "Optional: install Ollama from https://ollama.com/download for LLM-written assistant answers." -ForegroundColor Yellow
}

# 5. Start API and dashboard in their own windows
Start-Process powershell -WorkingDirectory $backend -ArgumentList "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle='PRISM API'; & '$venvPy' -m uvicorn prism.api.main:app --port 8000"
if (-not $webUp) {
    Start-Process powershell -WorkingDirectory $frontend -ArgumentList "-NoExit", "-Command",
        "`$host.UI.RawUI.WindowTitle='PRISM dashboard'; npm run dev"
}

Write-Host "API:        http://localhost:8000/docs"
Write-Host "Dashboard:  http://localhost:5173  (opening in a few seconds; first start trains the models ~2 min)"
Write-Host "Tip: keep ONE PRISM tab open; if a page stays on the dark start screen, close the other PRISM tabs." -ForegroundColor Yellow
if (-not $webUp) {
    Start-Sleep -Seconds 6
    Start-Process "http://localhost:5173"
} else {
    Write-Host "Dashboard already running - reusing your open tab (refresh it)."
}
