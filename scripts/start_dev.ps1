# Starts both backend ports plus ARC from a single terminal -- :8000 and
# :8443 run backgrounded, hidden (no extra windows, logs go to %TEMP%),
# then ARC launches in the foreground of THIS window. One command.
# Requires Oracle 21c and Ollama already running -- this doesn't start those.
#
# :8000 (browser UI, JWT only) always stays on loopback.
# :8443 (ARC, client certificate REQUIRED at the TLS layer) is bound to all
# interfaces by default so ARC can run from a separate VM/host -- the client
# certificate, not the network position, is what gates access. Pass
# -LocalOnly to keep it on loopback instead (ARC on this machine only).
# A VM/LAN client additionally needs a one-time Windows Firewall rule:
# add a rule once, in an Administrator prompt:
#   netsh advfirewall firewall add rule name="TT-AI ARC mTLS (8443)" dir=in action=allow protocol=TCP localport=8443
param([switch]$LocalOnly)

$root = Split-Path -Parent $PSScriptRoot
$log8000 = Join-Path $env:TEMP "uvicorn_8000.log"
$log8443 = Join-Path $env:TEMP "uvicorn_8443.log"

Start-Process -NoNewWindow -WorkingDirectory $root `
    -FilePath "$root\venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", `
        "--ssl-keyfile", "certs/server.key", "--ssl-certfile", "certs/server.crt", "--port", "8000" `
    -RedirectStandardOutput $log8000 -RedirectStandardError "$log8000.err"
Write-Host "started :8000 (loopback only), log: $log8000"

$args8443 = @("-m", "uvicorn", "app.main:app",
    "--ssl-keyfile", "certs/server.key", "--ssl-certfile", "certs/server.crt",
    "--ssl-ca-certs", "certs/ca.crt", "--ssl-cert-reqs", "2", "--port", "8443")
if (-not $LocalOnly) { $args8443 += @("--host", "0.0.0.0") }

Start-Process -NoNewWindow -WorkingDirectory $root `
    -FilePath "$root\venv\Scripts\python.exe" `
    -ArgumentList $args8443 `
    -RedirectStandardOutput $log8443 -RedirectStandardError "$log8443.err"

if ($LocalOnly) {
    Write-Host "started :8443 (loopback only -- ARC on this machine), log: $log8443"
} else {
    Write-Host "started :8443 (all interfaces, mTLS required -- ARC on this machine or a VM), log: $log8443"
    # netsh (not Get-NetFirewallRule) so this works without admin and finds a rule under any name
    $fwText = netsh advfirewall firewall show rule name=all dir=in verbose | Out-String
    $hasAllow = $false
    foreach ($blk in ($fwText -split "(?m)^Rule Name:")) {
        if ($blk -match "(?m)^\s*LocalPort:\s+.*\b8443\b" -and $blk -match "(?m)^\s*Action:\s+Allow" -and $blk -match "(?m)^\s*Enabled:\s+Yes") { $hasAllow = $true; break }
    }
    if (-not $hasAllow) {
        Write-Host "WARNING: no inbound firewall rule for :8443 -- a VM/LAN ARC will time out (ConnectTimeout)." -ForegroundColor Yellow
        Write-Host "         Add one (Administrator prompt): netsh advfirewall firewall add rule name=`"TT-AI ARC mTLS (8443)`" dir=in action=allow protocol=TCP localport=8443" -ForegroundColor Yellow
        Write-Host "         (scripts\demo_check.ps1 runs the full readiness check.)" -ForegroundColor Yellow
    }
}

Start-Sleep -Seconds 3

Set-Location "$root\..\arc"
& ".\venv\Scripts\python.exe" arc.py
