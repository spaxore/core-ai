# Demo readiness check -- READ-ONLY: changes nothing, starts nothing.
# Run it at your desk (and again at the venue) so a failure shows up before
# you are on stage:   .\scripts\demo_check.ps1
# Exit code 0 = everything needed is in place, 1 = at least one FAIL.
# Needs no admin rights and no openssl (certificates are read with the
# project's own Python).
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root "venv\Scripts\python.exe"
$fail = 0
function Ok($m)   { Write-Host "  [ OK ] $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  [FAIL] $m" -ForegroundColor Red; $script:fail++ }
function Warn($m) { Write-Host "  [warn] $m" -ForegroundColor Yellow }

Write-Host "== Backing services"
if (Get-NetTCPConnection -State Listen -LocalPort 1521 -ErrorAction SilentlyContinue) { Ok "Oracle listener on :1521" } else { Bad "Oracle is not listening on :1521" }
try {
    $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
    if ($tags.models.name -match '^llama3\.1') { Ok "Ollama up, llama3.1 present" } else { Bad "Ollama is up but llama3.1 is not pulled" }
} catch { Bad "Ollama not reachable on :11434" }

Write-Host "== TT servers"
$l8000 = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
$l8443 = Get-NetTCPConnection -State Listen -LocalPort 8443 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($l8000) { Ok ":8000 listening on $($l8000.LocalAddress) (browser UI)" } else { Bad ":8000 is not running -- start scripts\start_dev.ps1" }
if ($l8443) {
    if ($l8443.LocalAddress -eq "0.0.0.0" -or $l8443.LocalAddress -eq "::") { Ok ":8443 listening on all interfaces (VM / LAN ARC can connect)" }
    else { Warn ":8443 is bound to $($l8443.LocalAddress) only -- fine for ARC on this PC, a VM will time out. Restart with scripts\start_dev.ps1 (without -LocalOnly)." }
} else { Bad ":8443 is not running -- start scripts\start_dev.ps1" }

Write-Host "== Certificates"
$crt = Join-Path $root "certs\server.crt"
$info = & $py -c "import ssl, json, time; d = ssl._ssl._test_decode_cert(r'$crt'); print(json.dumps({'san': [list(x) for x in d['subjectAltName']], 'end': d['notAfter'], 'left': ssl.cert_time_to_seconds(d['notAfter']) - time.time()}))" | ConvertFrom-Json
$sanText = ($info.san | ForEach-Object { "$($_[0]):$($_[1])" }) -join " "
foreach ($n in @("DNS:localhost", "DNS:tt-demo", "IP Address:127.0.0.1")) {
    if ($sanText -match [regex]::Escape($n)) { Ok "server cert covers $n" } else { Bad "server cert does NOT cover $n -- re-issue it (see scripts\generate_mtls_certs.sh)" }
}
if ($info.left -gt 30 * 86400) { Ok "server cert valid for $([int]($info.left / 86400)) more days (expires $($info.end))" } else { Bad "server cert expires within 30 days ($($info.end))" }
$hostIps = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '169.254*' -and $_.IPAddress -ne '127.0.0.1' -and $_.InterfaceAlias -notmatch 'VMware|VirtualBox|vEthernet|Loopback' }
foreach ($ip in $hostIps) {
    if ($sanText -match [regex]::Escape("IP Address:$($ip.IPAddress)")) { Ok "this PC's IP $($ip.IPAddress) ($($ip.InterfaceAlias)) is in the cert" }
    else { Warn "this PC's IP $($ip.IPAddress) ($($ip.InterfaceAlias)) is not in the cert -- fine if the VM connects by the name tt-demo: on the VM run  echo `"$($ip.IPAddress) tt-demo`" | sudo tee -a /etc/hosts" }
}
foreach ($f in @("ca.crt", "arc-client.crt", "arc-client.key")) {
    $a = Join-Path $root "certs\$f"; $b = Join-Path (Join-Path $root "..\arc\certs") $f
    if ((Test-Path $b) -and ((Get-FileHash $a).Hash -eq (Get-FileHash $b).Hash)) { Ok "ARC's copy of $f matches the server's" }
    elseif (Test-Path $b) { Bad "ARC's copy of $f DIFFERS from certs\$f -- ARC on this PC would fail TLS" }
    else { Warn "no ARC copy of $f at $b" }
}

Write-Host "== mTLS behaviour (this PC, loopback)"
if ($l8443) {
    $certDir = (Join-Path $root "certs") -replace '\\', '/'
    $code = @"
import socket, ssl
CRLF = bytes([13, 10])
D = r'$certDir'
def go(name, cert):
    c = ssl.create_default_context(cafile=D + '/ca.crt')
    if cert: c.load_cert_chain(D + '/arc-client.crt', D + '/arc-client.key')
    try:
        with socket.create_connection(('127.0.0.1', 8443), timeout=8) as s:
            with c.wrap_socket(s, server_hostname=name) as t:
                t.sendall(b'GET / HTTP/1.1' + CRLF + b'Host: x' + CRLF + b'Connection: close' + CRLF + CRLF)
                return 'accepted' if t.recv(20).startswith(b'HTTP/') else 'refused'
    except Exception:
        return 'refused'
print('with-cert-localhost=' + go('localhost', True))
print('with-cert-tt-demo=' + go('tt-demo', True))
print('no-cert=' + go('localhost', False))
"@
    $out = (& $py -c $code 2>&1) -join " "
    if ($out -match 'with-cert-localhost=accepted') { Ok "ARC client cert accepted via localhost" } else { Bad "client cert NOT accepted via localhost: $out" }
    if ($out -match 'with-cert-tt-demo=accepted') { Ok "client cert accepted via the name tt-demo" } else { Bad "client cert NOT accepted via tt-demo -- the running server still has the old certificate; restart it (scripts\start_dev.ps1)" }
    if ($out -match 'no-cert=refused') { Ok "connection without a client cert is refused (mTLS enforced)" } else { Bad "connection without a client cert was NOT refused" }
} else { Warn "skipped (:8443 not running)" }

Write-Host "== Windows Firewall (only matters for a VM / another machine)"
# netsh, not Get-NetFirewallRule: it lists every rule without admin rights.
$rules = (netsh advfirewall firewall show rule name=all dir=in verbose | Out-String) -split "(?m)^Rule Name:" | Where-Object { $_ -match "Enabled:" }
function Field($blk, $name) { if ($blk -match "(?m)^\s*$name\s*:\s*(.+)$") { $Matches[1].Trim() } else { "" } }
$allow8443 = $rules | Where-Object { (Field $_ "LocalPort") -match '(^|,)\s*8443\s*(,|$)' -and (Field $_ "Action") -eq "Allow" -and (Field $_ "Enabled") -eq "Yes" }
if ($allow8443) {
    $n = ($allow8443 | ForEach-Object { ($_ -split "`n")[0].Trim() }) -join "; "
    Ok "inbound allow rule for TCP 8443 present ($n)"
} else { Warn "no inbound allow rule for TCP 8443 -- a VM will time out. Once, in an Administrator prompt: netsh advfirewall firewall add rule name=`"TT-AI ARC mTLS (8443)`" dir=in action=allow protocol=TCP localport=8443" }
$profiles = Get-NetConnectionProfile
$profiles | ForEach-Object { Write-Host "         network '$($_.Name)' [$($_.InterfaceAlias)] is $($_.NetworkCategory)" }
# A Block rule beats an Allow rule. Windows creates python.exe Block rules when the
# 'Allow access?' popup is dismissed for a network type -- on that network type the
# VM's connection is silently dropped even though the port itself is allowed.
$blocks = $rules | Where-Object { (Field $_ "Program") -match 'python' -and (Field $_ "Action") -eq "Block" -and (Field $_ "Enabled") -eq "Yes" }
$reported = @{}
foreach ($b in $blocks) {
    $prof = Field $b "Profiles"
    foreach ($p in $profiles) {
        if (($prof -match [regex]::Escape([string]$p.NetworkCategory)) -and -not $reported[$p.Name]) {
            $reported[$p.Name] = $true
            Bad "a python.exe BLOCK rule covers '$($p.NetworkCategory)' networks and '$($p.Name)' is one -- the VM will be silently dropped there. Mark that network Private (Windows network settings) or delete that Block rule (admin)."
        }
    }
}
if (-not $blocks) { Ok "no python.exe Block rules" }

Write-Host ""
if ($fail -eq 0) { Write-Host "READY: no failures." -ForegroundColor Green; exit 0 } else { Write-Host "$fail FAILURE(S) above -- fix these before the demo." -ForegroundColor Red; exit 1 }
