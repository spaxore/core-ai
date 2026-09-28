#!/usr/bin/env bash
# Generates a self-signed CA, one server cert (used by both uvicorn ports),
# and one client cert for ARC's host. Internship-scoped: a real PKI/CA
# vendor isn't needed here, just something uvicorn's ssl_cert_reqs=CERT_REQUIRED
# can verify against on ARC's port.
#
# Run once from the repo root:
#   bash scripts/generate_mtls_certs.sh
#
# Output goes to certs/ (gitignored) -- never commit private keys.
set -euo pipefail

# Git Bash (MSYS) rewrites any argument that looks like a leading-slash
# POSIX path -- including openssl's -subj "/O=.../CN=..." -- into a
# Windows path before openssl ever sees it. This disables that rewriting
# for this script only.
export MSYS_NO_PATHCONV=1

OUT_DIR="$(dirname "$0")/../certs"
mkdir -p "$OUT_DIR"
cd "$OUT_DIR"

DAYS=825  # matches most CA/browser trust-store limits, generous for a dev/demo cert

echo "== CA =="
openssl genrsa -out ca.key 4096
# basicConstraints=CA:TRUE and keyUsage=keyCertSign are required by modern
# OpenSSL (3.x, as shipped on current Kali) for a CA cert to validate at
# all -- the original version of this script omitted them, which happened
# to still work against Windows' more lenient default validation but fails
# hard ("CA cert does not include key usage extension") on a stricter
# client. Real bug, not a client-specific quirk, so it's fixed here rather
# than worked around on the client side.
openssl req -x509 -new -nodes -key ca.key -sha256 -days "$DAYS" \
  -subj "/O=Secure-TT-AI-Agent/CN=Secure-TT-AI-Agent Dev CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -out ca.crt

echo "== Server cert (both :8000 and :8443) =="
openssl genrsa -out server.key 2048
openssl req -new -key server.key \
  -subj "/O=Secure-TT-AI-Agent/CN=localhost" \
  -out server.csr
# tt-demo is the name a remote ARC (a VM / another machine) connects to, so the
# host's IP can change per venue without re-issuing the cert -- map the name to
# the current IP on the client instead (see scripts/vm_arc_wrapper.sh). Any
# fixed LAN IPs to also cover: EXTRA_SAN_IPS="192.168.1.72 192.168.1.128" bash scripts/generate_mtls_certs.sh
SAN="DNS:localhost,DNS:tt-demo,IP:127.0.0.1"
for ip in ${EXTRA_SAN_IPS:-}; do SAN="$SAN,IP:$ip"; done
printf "subjectAltName=%s" "$SAN" > server_ext.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days "$DAYS" -sha256 \
  -extfile server_ext.cnf \
  -out server.crt
rm -f server_ext.cnf

echo "== ARC client cert =="
openssl genrsa -out arc-client.key 2048
openssl req -new -key arc-client.key \
  -subj "/O=Secure-TT-AI-Agent/CN=arc-redteam-console" \
  -out arc-client.csr
openssl x509 -req -in arc-client.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days "$DAYS" -sha256 \
  -out arc-client.crt

rm -f server.csr arc-client.csr

echo
echo "Done. Files in $OUT_DIR:"
echo "  ca.crt, ca.key           -- CA (ca.crt goes on both the server's --ssl-ca-certs and ARC's verify=)"
echo "  server.key, server.crt   -- used by both uvicorn :8000 and :8443"
echo "  arc-client.key, arc-client.crt -- copy to ARC's host, used as cert= in core/api_client.py"
