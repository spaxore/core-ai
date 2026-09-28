#!/usr/bin/env bash
# `arc` launcher for the operator VM (copy to the VM, e.g. ~/arc/arc, chmod +x).
#
# It connects by NAME (tt-demo), not by IP, so the host's address can change
# per network without touching the certificate. The server certificate covers
# the name tt-demo; you only need to map that name to the host's CURRENT IP:
#
#   On the VM, once per network (get the IP with `ipconfig` on the host):
#     sudo sed -i '/ tt-demo$/d' /etc/hosts && echo "<host-ip> tt-demo" | sudo tee -a /etc/hosts
#
# Extra arguments still work and win over the default, e.g.:
#   arc --base-url https://tt-demo:8443
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOME/venv/bin/activate"

if ! getent hosts tt-demo >/dev/null 2>&1; then
    echo "tt-demo is not mapped to an IP yet. Run:  echo \"<host-ip> tt-demo\" | sudo tee -a /etc/hosts" >&2
    exit 1
fi
if ! timeout 5 bash -c "</dev/tcp/tt-demo/8443" 2>/dev/null; then
    echo "WARNING: cannot open a TCP connection to tt-demo:8443 ($(getent hosts tt-demo | awk '{print $1}'))." >&2
    echo "         Check: server running with --host 0.0.0.0, host firewall rule, same network/hotspot as the host." >&2
fi

python3 "$DIR/arc.py" --base-url https://tt-demo:8443 "$@"
