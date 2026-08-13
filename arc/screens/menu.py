"""
ARC Menu Screen
----------------
The hub screen shown right after login.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from core.api_client import APIClient, Session
from core.session_widget import SessionBar


class MenuScreen(Screen):
    CSS = """
    MenuScreen {
        align: center middle;
    }
    #menu-box {
        width: 60;
        height: auto;
        border: heavy $accent;
        padding: 2 4;
    }
    #menu-title {
        text-style: bold;
        color: $accent;
        content-align: center middle;
        width: 100%;
        margin-bottom: 1;
    }
    #menu-subtitle {
        color: $text-muted;
        content-align: center middle;
        width: 100%;
        margin-bottom: 2;
    }
    #menu-box Button {
        width: 100%;
        margin-bottom: 1;
    }
    """

    def __init__(self, api_client: APIClient, session: Session, attacks_dir: str, arc_dir: str):
        super().__init__()
        self.api_client = api_client
        self.session = session
        self.attacks_dir = attacks_dir
        self.arc_dir = arc_dir

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Center():
            with Middle():
                with Vertical(id="menu-box"):
                    yield Static("ARC -- AI Red Team Console", id="menu-title")
                    yield SessionBar(self.session, id="menu-subtitle")
                    yield Button("Attack Library", id="go-library", variant="primary")
                    yield Button("Author New Attack", id="go-author")
                    yield Button("Ops Log", id="go-ops-log")
                    yield Button("Log out", id="logout", variant="error")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "logout":
            self.app.action_logout()
            return

        if event.button.id == "go-library":
            from core.attacks import load_attack_library
            from screens.library import LibraryScreen

            attack_files = load_attack_library(self.attacks_dir)
            self.app.push_screen(LibraryScreen(self.api_client, self.session, attack_files, self.attacks_dir, self.arc_dir))

        elif event.button.id == "go-author":
            from screens.authoring import AuthoringScreen

            self.app.push_screen(AuthoringScreen(self.session, self.attacks_dir))

        elif event.button.id == "go-ops-log":
            from screens.ops_log import OpsLogScreen

            self.app.push_screen(OpsLogScreen(self.session, self.arc_dir))
