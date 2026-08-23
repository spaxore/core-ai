"""
ARC -- AI Red Team Console
============================
Usage:
    python arc.py

Defaults to the mTLS-required port (https://127.0.0.1:8443) and the
certs/ folder next to this file (see README.md's Certificates section).
Override with --base-url/--client-cert/--client-key/--ca-cert if needed --
:8000 is the browser/agent-facing port and does NOT accept ARC's client
cert, so pointing ARC there will just fail to connect.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from textual.app import App

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.api_client import APIClient, Session  # noqa: E402
from core.theme import ARC_RED_DIM, PANEL  # noqa: E402
from screens.login import LoginScreen  # noqa: E402
from screens.menu import MenuScreen  # noqa: E402


class ARCApp(App):
    TITLE = "ARC -- AI Red Team Console"
    CSS = f"""
    Screen {{
        background: {PANEL};
        border: solid {ARC_RED_DIM};
    }}
    """
    BINDINGS = [("ctrl+l", "logout", "Logout")]

    def __init__(self, base_url: str, attacks_dir: str,
                 client_cert: str | None = None, client_key: str | None = None,
                 ca_cert: str | None = None):
        super().__init__()
        self.api_client = APIClient(base_url, client_cert=client_cert, client_key=client_key, ca_cert=ca_cert)
        self.attacks_dir = attacks_dir
        self.arc_dir = os.path.dirname(os.path.abspath(__file__))
        self.session: Session | None = None
        self._session_timer = None

    def on_mount(self) -> None:
        self.push_screen(LoginScreen(self.api_client, self._on_login_success))

    def on_resize(self) -> None:
        self.refresh(layout=True)

    def _on_login_success(self, session: Session) -> None:
        self.session = session
        self.pop_screen()
        self.push_screen(MenuScreen(self.api_client, session, self.attacks_dir, self.arc_dir))
        self._schedule_session_expiry(session)

    def _schedule_session_expiry(self, session: Session) -> None:
        if self._session_timer is not None:
            self._session_timer.stop()
            self._session_timer = None

        if session.expires_at is None:
            return

        delay = max(0.0, session.expires_at - time.time())
        self._session_timer = self.set_timer(delay, self._on_session_expired)

    def _on_session_expired(self) -> None:
        if self.session is None:
            return
        self.action_logout(reason="Session expired (token timed out).")

    def action_logout(self, reason: str | None = None) -> None:
        if self._session_timer is not None:
            self._session_timer.stop()
            self._session_timer = None

        self.session = None
        login_screen = LoginScreen(self.api_client, self._on_login_success, notice=reason)
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen(login_screen)


def main() -> None:
    arc_dir = os.path.dirname(os.path.abspath(__file__))
    certs_dir = os.path.join(arc_dir, "certs")

    parser = argparse.ArgumentParser(description="ARC -- AI Red Team Console")
    # ARC's default target is its own mTLS-required port -- see
    # app/security/mtls.py and scripts/generate_mtls_certs.sh on the
    # platform side. :8000 (no client cert required) is for the browser
    # UI/normal agents, not ARC.
    parser.add_argument("--base-url", default="https://127.0.0.1:8443")
    parser.add_argument(
        "--attacks-dir",
        default=os.path.join(arc_dir, "..", "llm-redteam", "attacks"),
    )
    parser.add_argument("--client-cert", default=os.path.join(certs_dir, "arc-client.crt"))
    parser.add_argument("--client-key", default=os.path.join(certs_dir, "arc-client.key"))
    parser.add_argument("--ca-cert", default=os.path.join(certs_dir, "ca.crt"))
    args = parser.parse_args()

    # Set before RedTeamBridge is ever constructed (lazily, later in the
    # session) so llm-redteam/runner.py's module-level _session picks up
    # the same client identity ARC's own APIClient uses.
    os.environ["ARC_CLIENT_CERT"] = args.client_cert
    os.environ["ARC_CLIENT_KEY"] = args.client_key
    os.environ["ARC_CA_CERT"] = args.ca_cert

    app = ARCApp(
        base_url=args.base_url, attacks_dir=args.attacks_dir,
        client_cert=args.client_cert, client_key=args.client_key, ca_cert=args.ca_cert,
    )
    app.run()


if __name__ == "__main__":
    main()
