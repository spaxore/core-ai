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
from textual.widgets import Button, Footer, Input, Static

from core.api_client import APIClient, ARCAuthError
from core.theme import ARC_BLUE, ARC_RED, BORDER, PANEL_ALT, TEXT_DIM

REQUIRED_ROLE = "SECURITY_ANALYST"

# Block-letter "ARC" banner, same convention nmap/msfconsole use for their
# splash -- plain text in a Static, not an image, so it renders identically
# on any terminal with no asset to package or check for support.
ASCII_BANNER = """\
 ███   ████    ████
█   █  █   █  █
█████  ████   █
█   █  █  █   █
█   █  █   █   ████"""


class LoginScreen(Screen):
    CSS = f"""
    LoginScreen {{
        align: center middle;
    }}
    #login-banner {{
        color: {ARC_RED};
        text-style: bold;
        content-align: center middle;
        width: 100%;
        margin-bottom: 1;
    }}
    #login-banner-sub {{
        color: {TEXT_DIM};
        content-align: center middle;
        width: 100%;
        margin-bottom: 3;
    }}
    #login-column {{
        width: 44;
        height: auto;
    }}
    #login-form {{
        width: 100%;
        height: auto;
    }}
    #login-notice {{
        color: $warning;
        content-align: center middle;
        width: 100%;
        margin-bottom: 1;
        display: none;
    }}
    #login-notice.visible {{
        display: block;
    }}
    #login-error {{
        color: $error;
        content-align: center middle;
        width: 100%;
        margin-top: 1;
        display: none;
    }}
    #login-error.visible {{
        display: block;
    }}
    Input {{
        margin-bottom: 1;
        background: {PANEL_ALT};
        border: solid {BORDER};
    }}
    Input:focus {{
        border: solid {ARC_BLUE};
    }}
    #login-button {{
        width: 100%;
        margin-top: 1;
        background: {ARC_RED};
        color: $text;
    }}
    #login-button:hover {{
        background: {ARC_RED};
    }}
    #login-target {{
        content-align: center middle;
        width: 100%;
        color: {TEXT_DIM};
        margin-top: 1;
    }}
    """

    def __init__(self, api_client: APIClient, on_success, notice: str | None = None):
        super().__init__()
        self.api_client = api_client
        self.on_success = on_success
        self.notice = notice

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="login-column"):
                    yield Static(ASCII_BANNER, id="login-banner")
                    yield Static("A I   R E D   T E A M   C O N S O L E", id="login-banner-sub")
                    with Vertical(id="login-form"):
                        yield Static(self.notice or "", id="login-notice")
                        yield Input(placeholder="Username", id="username")
                        yield Input(placeholder="Password", password=True, id="password")
                        yield Button("Log in", id="login-button")
                        yield Static("", id="login-error")
                        yield Static(f"target: {self.api_client.base_url}", id="login-target")
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
