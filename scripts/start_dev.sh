#!/bin/bash
# Starts both backend ports plus ARC from a single terminal -- :8000 and
# :8443 run backgrounded (their own log files, not their own windows), then
# ARC launches in the foreground so you land straight in it. One command.
# Requires Oracle 21c and Ollama already running -- this doesn't start those.
set -e
cd "$(dirname "$0")/.."

source venv/Scripts/activate

uvicorn app.main:app --reload \
  --ssl-keyfile certs/server.key --ssl-certfile certs/server.crt \
  --port 8000 > /tmp/uvicorn_8000.log 2>&1 &
echo "started :8000 (pid $!), log: /tmp/uvicorn_8000.log"

uvicorn app.main:app \
  --ssl-keyfile certs/server.key --ssl-certfile certs/server.crt \
  --ssl-ca-certs certs/ca.crt --ssl-cert-reqs 2 \
  --port 8443 > /tmp/uvicorn_8443.log 2>&1 &
echo "started :8443 (pid $!), log: /tmp/uvicorn_8443.log"

sleep 3

cd ../arc
source venv/Scripts/activate
exec python arc.py
