# Kills every uvicorn process serving this app, regardless of how many
# accumulated from repeated start_dev.ps1 runs -- start_dev.ps1's servers
# are detached (Start-Process -NoNewWindow) specifically so they survive
# closing the launching terminal, which also means nothing short of this
# (or Task Manager) actually stops them.
$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match 'uvicorn app\.main:app' }

if (-not $procs) {
    Write-Host "No uvicorn app.main:app processes found."
    exit
}

foreach ($p in $procs) {
    Write-Host "Stopping PID $($p.ProcessId): $($p.CommandLine)"
    Stop-Process -Id $p.ProcessId -Force
}

Write-Host "Done."
