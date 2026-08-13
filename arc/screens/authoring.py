"""
ARC Attack Authoring Screen
-----------------------------
A form for adding new attacks to the shared YAML library.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Select, Static, TextArea

from core.attack_writer import AttackWriteError, write_attack
from core.session_widget import SessionBar

SEVERITY_OPTIONS = [("critical", "critical"), ("high", "high"), ("medium", "medium"),
                    ("low", "low"), ("n/a", "n/a")]
EXPECTED_OPTIONS = [("blocked", "blocked"), ("allowed", "allowed")]


class AuthoringScreen(Screen):
    CSS = """
    #session-bar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    #form-scroll {
        height: 1fr;
        padding: 1 2;
    }
    .field-label {
        margin-top: 1;
        color: $text-muted;
    }
    Input {
        margin-bottom: 0;
    }
    TextArea {
        height: 6;
        margin-bottom: 0;
    }
    Select {
        margin-bottom: 0;
    }
    #form-status {
        height: 2;
        margin-top: 1;
        color: $warning;
    }
    #nav-row {
        height: 3;
        padding: 0 1;
    }
    #nav-row Button {
        margin-right: 1;
    }
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, session, attacks_dir: str):
        super().__init__()
        self.session = session
        self.attacks_dir = attacks_dir

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SessionBar(self.session, id="session-bar")
        with VerticalScroll(id="form-scroll"):
            yield Static("Attack ID (e.g. DI-006) *", classes="field-label")
            yield Input(placeholder="DI-006", id="f-id")

            yield Static("Name *", classes="field-label")
            yield Input(placeholder="Short human-readable name", id="f-name")

            yield Static("Category (existing or new, e.g. direct_injection) *", classes="field-label")
            yield Input(placeholder="direct_injection", id="f-category")

            yield Static("Severity *", classes="field-label")
            yield Select(SEVERITY_OPTIONS, id="f-severity", value="high")

            yield Static("Expected outcome *", classes="field-label")
            yield Select(EXPECTED_OPTIONS, id="f-expected", value="blocked")

            yield Static("Prompt *", classes="field-label")
            yield TextArea(id="f-prompt")

            yield Static("OWASP mapping (optional)", classes="field-label")
            yield Input(placeholder="LLM01 - Prompt Injection", id="f-owasp")

            yield Static("Notes (optional)", classes="field-label")
            yield TextArea(id="f-notes")

            yield Static("", id="form-status")

        with Horizontal(id="nav-row"):
            yield Button("Save attack", id="save", variant="primary")
            yield Button("Back to menu", id="go-back")
            yield Button("Log out", id="logout", variant="error")
        yield Footer()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        elif event.button.id == "go-back":
            self.app.pop_screen()
        elif event.button.id == "logout":
            self.app.action_logout()

    def _save(self) -> None:
        status = self.query_one("#form-status", Static)

        attack_id = self.query_one("#f-id", Input).value
        name = self.query_one("#f-name", Input).value
        category = self.query_one("#f-category", Input).value
        severity = self.query_one("#f-severity", Select).value
        expected = self.query_one("#f-expected", Select).value
        prompt = self.query_one("#f-prompt", TextArea).text
        owasp = self.query_one("#f-owasp", Input).value
        notes = self.query_one("#f-notes", TextArea).text

        try:
            path = write_attack(
                attacks_dir=self.attacks_dir,
                attack_id=attack_id,
                name=name,
                prompt=prompt,
                category=category,
                severity=severity,
                expected=expected,
                owasp=owasp,
                notes=notes,
            )
        except AttackWriteError as exc:
            status.update(f"[b red]Not saved:[/b red] {exc}")
            return

        status.update(
            f"[b green]Saved.[/b green] Attack '{attack_id}' written to {path}."
        )
        for field_id in ("f-id", "f-name", "f-category", "f-owasp"):
            self.query_one(f"#{field_id}", Input).value = ""
        self.query_one("#f-prompt", TextArea).text = ""
        self.query_one("#f-notes", TextArea).text = ""
