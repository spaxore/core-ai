"""
mTLS-certified channel tagging.

Two uvicorn processes run the same FastAPI app: one plain HTTPS port for
the browser UI / normal agents, one HTTPS port that additionally requires
a client certificate (ssl_cert_reqs=CERT_REQUIRED), reserved for ARC. The
TLS handshake itself refuses to complete on that second port without a
valid cert -- so "this request arrived on that port at all" IS the proof
of identity, no need to inspect certificate details from inside the app.

request.scope["server"] is the (host, port) of the actual listening
socket the connection was accepted on -- part of the ASGI spec, not a
client-supplied header, so it can't be spoofed by a request claiming to
be on the wrong port.
"""
import os

MTLS_PORT = int(os.getenv("MTLS_PORT", "8443"))


def is_certified(request) -> bool:
    server = request.scope.get("server")
    return bool(server and server[1] == MTLS_PORT)


def channel_label(request) -> str:
    return "mTLS" if is_certified(request) else "standard"
