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

from core.theme import TEXT


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
        # Default is the bright TEXT tone (distinguished from the rest of
        # this bar's dim gray) -- only the countdown phrase itself escalates
        # to yellow/red near expiry, matching the mockup's dedicated
        # `.countdown` span rather than dimming the whole bar equally.
        countdown_style = TEXT

        if self.session.expires_at is not None:
            secs_left = int(self.session.expires_at - time.time())
            if secs_left <= 0:
                remaining = "expired"
                countdown_style = "bold red"
            else:
                mins, secs = divmod(secs_left, 60)
                remaining = f"{mins:02d}:{secs:02d}"
                if secs_left <= 60:
                    countdown_style = "bold red"
                elif secs_left <= 300:
                    countdown_style = "bold yellow"

        text = (
            f" ARC connected as {self.session.username} ({self.session.role})  |  "
            f"[{countdown_style}]session expires in: {remaining}[/{countdown_style}]  |  "
            f"target: {self.session.base_url}"
        )
        self.update(text)
