"""
ARC Login Screen
-----------------
Authenticates against the platform's existing /login endpoint. ARC
enforces its own additional restriction on top of whatever the backend
already returns: only SECURITY_ANALYST may proceed past this screen.
"""
from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Static

from core.api_client import APIClient, ARCAuthError

REQUIRED_ROLE = "SECURITY_ANALYST"


class LoginScreen(Screen):
    CSS = """
    LoginScreen {
        align: center middle;
    }
    #login-box {
        width: 56;
        height: auto;
        border: heavy $accent;
        padding: 2 4;
    }
    #login-title {
        text-style: bold;
        color: $accent;
        content-align: center middle;
        width: 100%;
        margin-bottom: 1;
    }
    #login-subtitle {
        color: $text-muted;
        content-align: center middle;
        width: 100%;
        margin-bottom: 2;
    }
    #login-notice {
        color: $warning;
        content-align: center middle;
        width: 100%;
        margin-bottom: 1;
        display: none;
    }
    #login-notice.visible {
        display: block;
    }
    #login-error {
        color: $error;
        content-align: center middle;
        width: 100%;
        margin-top: 1;
        display: none;
    }
    #login-error.visible {
        display: block;
    }
    Input {
        margin-bottom: 1;
    }
    #login-button {
        width: 100%;
        margin-top: 1;
    }
    """

    def __init__(self, api_client: APIClient, on_success, notice: str | None = None):
        super().__init__()
        self.api_client = api_client
        self.on_success = on_success
        self.notice = notice

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="login-box"):
                    yield Static("ARC", id="login-title")
                    yield Static("AI Red Team Console -- security analyst access only", id="login-subtitle")
                    yield Static(self.notice or "", id="login-notice")
                    yield Input(placeholder="Username", id="username")
                    yield Input(placeholder="Password", password=True, id="password")
                    yield Button("Log in", id="login-button", variant="primary")
                    yield Static("", id="login-error")
        yield Footer()

    def on_mount(self) -> None:
        if self.notice:
            self.query_one("#login-notice", Static).add_class("visible")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "login-button":
            self._attempt_login()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._attempt_login()

    def _attempt_login(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not username or not password:
            self._show_error("Enter both username and password.")
            return
        self._do_login(username, password)

    @work(exclusive=True)
    async def _do_login(self, username: str, password: str) -> None:
        button = self.query_one("#login-button", Button)
        button.disabled = True
        try:
            session = self.api_client.login(username, password)
            if session.role != REQUIRED_ROLE:
                self._show_error(
                    f"Access denied: ARC requires {REQUIRED_ROLE}, this account is {session.role}."
                )
                return
            self.on_success(session)
        except ARCAuthError as exc:
            self._show_error(str(exc))
        finally:
            button.disabled = False

    def _show_error(self, message: str) -> None:
        error_widget = self.query_one("#login-error", Static)
        error_widget.update(message)
        error_widget.add_class("visible")
