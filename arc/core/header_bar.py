"""
ARC Header Bar
---------------
Replaces Textual's stock Header widget with one that carries a real,
visible logout control (a small muted icon-style button, top-right) --
the stock Header has no slot for that, and ARCApp's own Ctrl+L binding
alone left logout only reachable via the footer's keybind hint, not a
clickable control, which is what the mockup's header actually shows.
"""
from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static

from core.theme import ARC_ROSE, BORDER, PANEL_ALT, TEXT_DIM

TITLE = "ARC -- AI Red Team Console"
# The power-symbol glyph (U+23FB) didn't render in the user's terminal font
# -- falling back to plain text, per the earlier consult's agreed fallback.
LOGOUT_LABEL = "Logout"


class ArcHeader(Horizontal):
    DEFAULT_CSS = f"""
    ArcHeader {{
        height: 2;
        background: {PANEL_ALT};
        border-bottom: solid {BORDER};
    }}
    ArcHeader #header-brand {{
        width: 1fr;
        content-align: left middle;
        color: $text;
        text-style: bold;
        padding-left: 1;
    }}
    ArcHeader #header-clock {{
        width: auto;
        content-align: right middle;
        color: {TEXT_DIM};
        padding-right: 1;
    }}
    ArcHeader Button#header-logout {{
        width: 10;
        min-width: 0;
        height: 1;
        min-height: 0;
        background: transparent;
        color: {ARC_ROSE};
        border: none;
        text-style: none;
        content-align: center middle;
        text-align: center;
        padding: 0 1;
    }}
    ArcHeader Button#header-logout:hover {{
        color: {ARC_ROSE};
        background: {ARC_ROSE} 15%;
    }}
    ArcHeader Button#header-back {{
        width: 8;
        min-width: 0;
        height: 1;
        min-height: 0;
        background: transparent;
        color: {TEXT_DIM};
        border: none;
        text-style: none;
        content-align: center middle;
        text-align: center;
        padding: 0 1;
    }}
    ArcHeader Button#header-back:hover {{
        color: $text;
        background: {TEXT_DIM} 15%;
    }}
    """

    def __init__(self, on_back=None, **kwargs):
        super().__init__(**kwargs)
        self._on_back = on_back

    def compose(self) -> ComposeResult:
        yield Static(TITLE, id="header-brand")
        yield Static("", id="header-clock")
        if self._on_back is not None:
            yield Button("Back", id="header-back")
        yield Button(LOGOUT_LABEL, id="header-logout")

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self.query_one("#header-clock", Static).update(time.strftime("%H:%M:%S"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "header-logout":
            event.stop()
            self.app.action_logout()
        elif event.button.id == "header-back" and self._on_back is not None:
            event.stop()
            self._on_back()
