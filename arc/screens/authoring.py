"""
ARC Attack Authoring Screen
-----------------------------
A form for adding new attacks to the shared YAML library.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Select, Static, TextArea

from core.attack_writer import AttackWriteError, write_attack
from core.header_bar import ArcHeader
from core.session_widget import SessionBar
from core.theme import ARC_BLUE, BORDER, PANEL_ALT, TEXT, TEXT_DIM

SEVERITY_OPTIONS = [("critical", "critical"), ("high", "high"), ("medium", "medium"),
                    ("low", "low"), ("n/a", "n/a")]
EXPECTED_OPTIONS = [("blocked", "blocked"), ("allowed", "allowed")]


class AuthoringScreen(Screen):
    CSS = f"""
    #session-bar {{
        height: 2;
        background: {PANEL_ALT};
        color: {TEXT_DIM};
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    #form-scroll {{
        height: 1fr;
        width: 100%;
        max-width: 110;
        padding: 1 2;
    }}
    .field-label {{
        margin-top: 1;
        color: {TEXT_DIM};
    }}
    .field-label:first-of-type {{
        margin-top: 0;
    }}
    Input, Select, TextArea {{
        background: {PANEL_ALT};
        color: {TEXT};
        border: solid {BORDER};
        margin-bottom: 0;
    }}
    Input:focus, TextArea:focus {{
        border: solid {ARC_BLUE};
    }}
    TextArea {{
        height: 4;
    }}
    #form-status {{
        height: 2;
        margin-top: 1;
        color: $warning;
    }}
    #form-footer {{
        height: 3;
        align: left middle;
        background: {PANEL_ALT};
        border-top: solid {BORDER};
        padding: 0 2;
    }}
    #form-cancel {{
        width: auto;
        min-width: 0;
        height: 1;
        min-height: 0;
        content-align: left middle;
        text-align: left;
        color: {TEXT_DIM};
        background: transparent;
        border: none;
        text-style: none;
        padding: 0 1;
    }}
    #form-cancel:hover {{
        color: {TEXT};
        background: {TEXT_DIM} 15%;
    }}
    #save {{
        dock: right;
        width: 20;
        height: 1;
        min-width: 0;
        min-height: 0;
        background: {ARC_BLUE};
        color: $text;
        text-style: bold;
        border: none;
        content-align: center middle;
        padding: 0 3;
    }}
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, session, attacks_dir: str):
        super().__init__()
        self.session = session
        self.attacks_dir = attacks_dir

    def compose(self) -> ComposeResult:
        yield ArcHeader(on_back=self.action_go_back)
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

        with Horizontal(id="form-footer"):
            yield Button("Cancel", id="form-cancel")
            yield Button("Save attack", id="save")

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        elif event.button.id == "form-cancel":
            self.action_go_back()

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
