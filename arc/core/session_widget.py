"""
ARC Session Bar Widget
------------------------
A self-updating status bar shown at the top of every authenticated
screen: who's logged in, which target it's talking to, and a live
countdown to the current token's expiry -- so the analyst can see a
logout coming and plan around it, instead of being surprised by it.

Color escalates as expiry approaches: normal -> yellow under 5 minutes
-> red under 1 minute -> "expired" once the countdown hits zero (the
actual logout itself is still driven by arc.py's proactive timer, not
by this widget -- this is purely the visible countdown).
"""
from __future__ import annotations

import time

from textual.widgets import Static


class SessionBar(Static):
    def __init__(self, session, **kwargs):
        super().__init__("", **kwargs)
        self.session = session
        self._timer = None

    def on_mount(self) -> None:
        self._refresh()
        self._timer = self.set_interval(1.0, self._refresh)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    def _refresh(self) -> None:
        remaining = "unknown"
        style = ""

        if self.session.expires_at is not None:
            secs_left = int(self.session.expires_at - time.time())
            if secs_left <= 0:
                remaining = "expired"
                style = "bold red"
            else:
                mins, secs = divmod(secs_left, 60)
                remaining = f"{mins:02d}:{secs:02d}"
                if secs_left <= 60:
                    style = "bold red"
                elif secs_left <= 300:
                    style = "bold yellow"

        text = (
            f" ARC connected as {self.session.username} ({self.session.role})  |  "
            f"session expires in: {remaining}  |  target: {self.session.base_url}"
        )
        if style:
            text = f"[{style}]{text}[/{style}]"
        self.update(text)
