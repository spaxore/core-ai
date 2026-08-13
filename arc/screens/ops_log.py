"""
ARC Ops Log Screen
--------------------
ARC own local record of its attack runs over time -- built entirely
from ARC own Fire All results (core/ops_log.py), never from the target
audit log. This is the attacker engagement history: what was tested,
what got through, what got fixed, confirmed by re-testing.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from core.ops_log import load_history, diff_runs
from core.session_widget import SessionBar


class OpsLogScreen(Screen):
    CSS = """
    #session-bar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    #nav-row {
        height: 3;
        padding: 0 1;
    }
    #nav-row Button {
        margin-right: 1;
    }
    #runs-table {
        height: 12;
        margin: 1;
    }
    #diff-title {
        text-style: bold;
        color: $accent;
        padding: 0 1;
        margin-top: 1;
    }
    #diff-box {
        border: round $primary;
        padding: 1 2;
        margin: 1;
        height: 1fr;
    }
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, session, arc_dir: str):
        super().__init__()
        self.session = session
        self.arc_dir = arc_dir

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SessionBar(self.session, id="session-bar")
        with Horizontal(id="nav-row"):
            yield Button("Refresh", id="refresh", variant="primary")
            yield Button("Back to menu", id="go-back")
            yield Button("Log out", id="logout", variant="error")
        yield Static("[b]Ops Log[/b]  (most recent first)")
        yield DataTable(id="runs-table")
        yield Static("Change since previous run", id="diff-title")
        with VerticalScroll(id="diff-box"):
            yield Static("", id="diff-content")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#runs-table", DataTable)
        table.add_columns(
            ("Timestamp", "timestamp"),
            ("Total", "total"),
            ("Pass", "pass"),
            ("Fail", "fail"),
            ("Error", "error"),
            ("Pass rate", "pass_rate"),
        )
        self._load()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            self._load()
        elif event.button.id == "go-back":
            self.app.pop_screen()
        elif event.button.id == "logout":
            self.app.action_logout()

    def _load(self) -> None:
        table = self.query_one("#runs-table", DataTable)
        table.clear()

        history = load_history(self.arc_dir)

        if not history:
            self.query_one("#diff-content", Static).update(
                "No runs recorded yet. Run 'Fire all (llm-redteam)' from the "
                "Attack Library to record your first entry in the Ops Log."
            )
            return

        for record in reversed(history):
            table.add_row(
                record["timestamp"],
                str(record["total"]),
                str(record["pass"]),
                str(record["fail"]),
                str(record["error"]),
                f"{record['pass_rate']:.1f}%",
            )

        curr = history[-1]
        prev = history[-2] if len(history) >= 2 else None
        diff = diff_runs(prev, curr)

        self._render_diff(diff, prev is None)

    def _render_diff(self, diff: dict, is_first_run: bool) -> None:
        content = self.query_one("#diff-content", Static)

        if is_first_run:
            content.update("This is the first recorded run -- nothing to compare against yet.")
            return

        lines = []

        if diff["improved"]:
            lines.append("[b green]Gaps closed:[/b green]")
            for attack_id, old_grade, new_grade in diff["improved"]:
                lines.append(f"  [green]{attack_id}[/green]: {old_grade} -> {new_grade}")

        if diff["regressed"]:
            lines.append("")
            lines.append("[b red]REGRESSIONS -- previously passing, now failing:[/b red]")
            for attack_id, old_grade, new_grade in diff["regressed"]:
                lines.append(f"  [red]{attack_id}[/red]: {old_grade} -> {new_grade}")

        if diff["new_attacks"]:
            lines.append("")
            lines.append("[b yellow]New attacks since last run:[/b yellow]")
            for attack_id in diff["new_attacks"]:
                lines.append(f"  [yellow]{attack_id}[/yellow]")

        if not lines:
            lines.append("No changes since the previous run. Same pass/fail state across all attacks.")

        content.update("\n".join(lines))
