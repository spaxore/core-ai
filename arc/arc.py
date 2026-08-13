"""
ARC -- AI Red Team Console
============================
Usage:
    python arc.py --base-url http://127.0.0.1:8000 --attacks-dir ../llm-redteam/attacks
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from textual.app import App

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.api_client import APIClient, Session  # noqa: E402
from screens.login import LoginScreen  # noqa: E402
from screens.menu import MenuScreen  # noqa: E402


class ARCApp(App):
    TITLE = "ARC -- AI Red Team Console"
    CSS = """
    Screen {
        background: $surface;
    }
    """
    BINDINGS = [("ctrl+l", "logout", "Logout")]

    def __init__(self, base_url: str, attacks_dir: str):
        super().__init__()
        self.api_client = APIClient(base_url)
        self.attacks_dir = attacks_dir
        self.arc_dir = os.path.dirname(os.path.abspath(__file__))
        self.session: Session | None = None
        self._session_timer = None

    def on_mount(self) -> None:
        self.push_screen(LoginScreen(self.api_client, self._on_login_success))

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
    parser = argparse.ArgumentParser(description="ARC -- AI Red Team Console")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--attacks-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "llm-redteam", "attacks"),
    )
    args = parser.parse_args()

    app = ARCApp(base_url=args.base_url, attacks_dir=args.attacks_dir)
    app.run()


if __name__ == "__main__":
    main()
