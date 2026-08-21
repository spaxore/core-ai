"""
ARC Menu Screen
----------------
The hub screen shown right after login.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from core.api_client import APIClient, Session
from core.header_bar import ArcHeader
from core.session_widget import SessionBar
from core.theme import ARC_BLUE, BORDER, PANEL_ALT, TEXT, TEXT_DIM

# (num, dest_id, title, badge_fg) -- dest_id doubles as the row's Button id
# ("go-<dest_id>") and the routing key _go_to() dispatches on. Subtitles
# aren't listed here -- they're built from real data (core.attacks/
# core.ops_log/core.findings) in compose().
#
# Author New Attack, Playbooks, and Known Techniques used to be their own
# top-level entries here -- they were pulled into Attack Library's own
# catalog-tools-row instead (screens/library.py), since they're different
# modes of working with the same catalog, not unrelated destinations. The
# main menu now only lists the two genuinely separate concerns: the
# catalog itself, and what it found.
MENU_DESTINATIONS = [
    ("01", "library", "Attack Library", ARC_BLUE),
    ("02", "ops-log", "Findings", TEXT_DIM),
]


def _library_subtitle(attacks_dir: str, arc_dir: str) -> str:
    from core.attacks import flatten, load_attack_library
    from core.ops_log import load_history

    try:
        count = len(flatten(load_attack_library(attacks_dir)))
    except OSError:
        count = 0

    history = load_history(arc_dir)
    if history:
        pass_rate = history[-1]["pass_rate"]
        return f"{count} attacks - last run {pass_rate:.0f}% pass"
    return f"{count} attacks - never run"


def _findings_subtitle(arc_dir: str) -> str:
    from core.findings import fixed_findings, load_findings, open_findings

    findings = load_findings(arc_dir)
    opens = open_findings(findings)
    fixed = fixed_findings(findings)
    if not opens and not fixed:
        return "No findings recorded yet"
    return f"{len(opens)} open - {len(fixed)} fixed"


class MenuScreen(Screen):
    CSS = f"""
    #session-bar {{
        height: 2;
        background: {PANEL_ALT};
        color: {TEXT_DIM};
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    #menu-caption {{
        height: 2;
        background: {PANEL_ALT};
        color: {TEXT_DIM};
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    #menu-rows {{
        padding: 0;
    }}
    Button.menu-row {{
        width: 100%;
        height: 3;
        background: transparent;
        color: $text;
        content-align: left top;
        text-align: left;
        text-style: none;
        border: none;
        border-bottom: solid {TEXT} 8%;
        padding: 0 0 0 3;
    }}
    Button.menu-row:focus {{
        background: {ARC_BLUE} 8%;
        border-left: solid {ARC_BLUE};
        padding: 0 0 0 2;
        text-style: none;
    }}
    Button.menu-row:hover {{
        background: {TEXT} 2%;
    }}
    #menu-footer {{
        height: 1;
        color: {TEXT_DIM};
        padding: 0 2;
    }}
    """

    BINDINGS = [
        Binding("1", "open_destination('library')", "Attack Library", show=False),
        Binding("2", "open_destination('ops-log')", "Findings", show=False),
    ]

    def __init__(self, api_client: APIClient, session: Session, attacks_dir: str, arc_dir: str):
        super().__init__()
        self.api_client = api_client
        self.session = session
        self.attacks_dir = attacks_dir
        self.arc_dir = arc_dir

    def compose(self) -> ComposeResult:
        yield ArcHeader()
        yield SessionBar(self.session, id="session-bar")
        yield Static("Main menu -- select a destination (1/2, or click)", id="menu-caption")
        with Vertical(id="menu-rows"):
            for num, dest_id, title, badge_fg in MENU_DESTINATIONS:
                if dest_id == "library":
                    subtitle = _library_subtitle(self.attacks_dir, self.arc_dir)
                else:
                    subtitle = _findings_subtitle(self.arc_dir)
                yield Button(
                    f"[{TEXT_DIM}]›[/{TEXT_DIM}] [{badge_fg} on {badge_fg} 15%] {num} [/]  [b]{title}[/b]\n"
                    f"        [dim]{subtitle}[/dim]",
                    id=f"go-{dest_id}",
                    classes="menu-row",
                )
        yield Static(f"{self.session.username} - {self.session.role}   (Ctrl+L to log out)", id="menu-footer")

    def on_mount(self) -> None:
        # Textual's default auto-focus lands on the first focusable widget in
        # composition order -- that's ArcHeader's Logout button, not any menu
        # row, since ArcHeader is composed first. Without this, the "primary"
        # row's :focus styling (highlight tint, left accent) never actually
        # triggers on a fresh menu load.
        self.query_one("#go-library").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("go-"):
            self._go_to(event.button.id.removeprefix("go-"))

    def action_open_destination(self, dest_id: str) -> None:
        self._go_to(dest_id)

    def _go_to(self, dest_id: str) -> None:
        if dest_id == "library":
            from core.attacks import load_attack_library
            from screens.library import LibraryScreen

            attack_files = load_attack_library(self.attacks_dir)
            self.app.push_screen(LibraryScreen(self.api_client, self.session, attack_files, self.attacks_dir, self.arc_dir))

        elif dest_id == "ops-log":
            from screens.ops_log import OpsLogScreen

            self.app.push_screen(OpsLogScreen(self.session, self.arc_dir))
