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
# The arrow (U+2190) is common enough to render everywhere and is kept as
# a glyph. The power symbol (U+23FB) is not -- confirmed via screenshot to
# render as a tofu/fallback box in this user's terminal font (a rare
# "Miscellaneous Technical" block character, unlike the much more common
# arrow), so logout stays plain text rather than risk another silent
# fallback glyph.
BACK_GLYPH = "←"  # <-
LOGOUT_LABEL = "Logout"


class ArcHeader(Horizontal):
    DEFAULT_CSS = f"""
    ArcHeader {{
        height: 2;
        background: {PANEL_ALT};
        border-bottom: solid {BORDER};
        padding-right: 2;
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
        width: 4;
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
            yield Button(BACK_GLYPH, id="header-back")
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
