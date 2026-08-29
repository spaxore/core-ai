# Starts both backend ports plus ARC from a single terminal -- :8000 and
# :8443 run backgrounded, hidden (no extra windows, logs go to %TEMP%),
# then ARC launches in the foreground of THIS window. One command.
# Requires Oracle 21c and Ollama already running -- this doesn't start those.
$root = Split-Path -Parent $PSScriptRoot
$log8000 = Join-Path $env:TEMP "uvicorn_8000.log"
$log8443 = Join-Path $env:TEMP "uvicorn_8443.log"

Start-Process -NoNewWindow -WorkingDirectory $root `
    -FilePath "$root\venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", `
        "--ssl-keyfile", "certs/server.key", "--ssl-certfile", "certs/server.crt", "--port", "8000" `
    -RedirectStandardOutput $log8000 -RedirectStandardError "$log8000.err"
Write-Host "started :8000, log: $log8000"

Start-Process -NoNewWindow -WorkingDirectory $root `
    -FilePath "$root\venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", `
        "--ssl-keyfile", "certs/server.key", "--ssl-certfile", "certs/server.crt", `
        "--ssl-ca-certs", "certs/ca.crt", "--ssl-cert-reqs", "2", "--port", "8443" `
    -RedirectStandardOutput $log8443 -RedirectStandardError "$log8443.err"
Write-Host "started :8443, log: $log8443"

Start-Sleep -Seconds 3

Set-Location "$root\..\arc"
& ".\venv\Scripts\python.exe" arc.py
