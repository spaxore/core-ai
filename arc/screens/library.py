"""
ARC Attack Library Screen
--------------------------
Fire selected: ARC own lightweight path.
Fire all: routes through core/redteam_bridge.py (the real llm-redteam
engine, in-process). Every completed Fire All run appends one record
to core/ops_log.py's local history -- viewable on the Ops Log screen.
"""
from __future__ import annotations

import os
import webbrowser
from datetime import datetime

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    SelectionList,
    Static,
)
from textual.widgets.selection_list import Selection

from core.api_client import APIClient, Session
from core.attacks import Attack, AttackFile, flatten
from core.ops_log import append_run
from core.grading import grade
from core.redteam_bridge import RedTeamBridge
from core.session_widget import SessionBar

BAR_WIDTH = 40


def _ascii_bar(current: int, total: int) -> str:
    if total <= 0:
        return f"[{'-' * BAR_WIDTH}]   0/0"
    filled = int(BAR_WIDTH * current / total)
    filled = max(0, min(BAR_WIDTH, filled))
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    pct = int(100 * current / total)
    return f"[{bar}] {current}/{total} ({pct}%)"


class LibraryScreen(Screen):
    CSS = """
    #session-bar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    #body {
        height: 1fr;
    }
    #left-pane {
        width: 42%;
        border-right: solid $accent;
        padding: 1;
    }
    #right-pane {
        width: 58%;
        padding: 1;
    }
    #summary-bar {
        height: 3;
        border: round $accent;
        padding: 0 1;
        margin-bottom: 1;
    }
    #run-status {
        height: 1;
        color: $warning;
        margin-bottom: 1;
    }
    #fire-progress {
        height: 1;
        color: $success;
        margin-bottom: 1;
    }
    #button-row {
        height: 3;
        margin-top: 1;
    }
    #button-row Button {
        margin-right: 1;
    }
    #report-row {
        height: 3;
        margin-top: 1;
    }
    #report-row Button {
        margin-right: 1;
    }
    #nav-row {
        height: 3;
        margin-top: 1;
    }
    #nav-row Button {
        margin-right: 1;
    }
    SelectionList {
        height: 1fr;
        border: round $primary;
    }
    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, api_client: APIClient, session: Session, attack_files: list[AttackFile],
                 attacks_dir: str = "", arc_dir: str = ""):
        super().__init__()
        self.api_client = api_client
        self.session = session
        self.attack_files = attack_files
        self.attacks_dir = attacks_dir
        self.arc_dir = arc_dir
        self.all_attacks: list[Attack] = flatten(attack_files)
        self.attacks_by_id: dict[str, Attack] = {a.id: a for a in self.all_attacks}
        self._results: dict[str, str] = {}
        self._batch_running = False
        self._last_full_suite_scored: dict | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SessionBar(self.session, id="session-bar")
        with Horizontal(id="body"):
            with Vertical(id="left-pane"):
                yield Static("[b]Attack Library[/b]  (space = toggle, enter = fire selected)")
                yield SelectionList[str](*self._build_selections())
                with Horizontal(id="button-row"):
                    yield Button("Fire selected", id="fire-selected", variant="primary")
                    yield Button("Fire all (llm-redteam)", id="fire-all", variant="warning")
                    yield Button("Select all", id="select-all")
                    yield Button("Clear", id="select-none")
                with Horizontal(id="report-row"):
                    yield Button("Generate Report", id="generate-report", disabled=True)
                with Horizontal(id="nav-row"):
                    yield Button("Back to menu", id="go-back")
                    yield Button("Log out", id="logout", variant="error")
            with Vertical(id="right-pane"):
                yield Static("Idle.", id="run-status")
                yield Static("", id="fire-progress")
                yield Static("Total: 0   Passed: 0   Failed: 0   Errors: 0   Pass rate: --", id="summary-bar")
                yield DataTable(id="results-table")
        yield Footer()

    def action_go_back(self) -> None:
        if not self._batch_running:
            self.app.pop_screen()

    def _build_selections(self):
        selections = []
        for f in self.attack_files:
            for a in f.attacks:
                label = f"[{a.severity.upper():<8}] {a.id} - {a.name}"
                selections.append(Selection(label, a.id, False))
        return selections

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns(
            ("ID", "id"),
            ("Category", "category"),
            ("Severity", "severity"),
            ("Expected", "expected"),
            ("Status", "status"),
            ("Grade", "grade"),
        )
        for a in self.all_attacks:
            table.add_row(a.id, a.category, a.severity, a.expected, "--", "--", key=a.id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._batch_running:
            return

        selection_list = self.query_one(SelectionList)
        if event.button.id == "select-all":
            selection_list.select_all()
        elif event.button.id == "select-none":
            selection_list.deselect_all()
        elif event.button.id == "fire-selected":
            ids = list(selection_list.selected)
            if ids:
                self._fire_selected_thread(ids)
        elif event.button.id == "fire-all":
            self._fire_all_thread()
        elif event.button.id == "generate-report":
            self._generate_report()
        elif event.button.id == "go-back":
            self.app.pop_screen()
        elif event.button.id == "logout":
            self.app.action_logout()

    def _set_running(self, running: bool) -> None:
        self._batch_running = running
        for btn_id in ("fire-selected", "fire-all", "select-all", "select-none", "go-back"):
            self.query_one(f"#{btn_id}", Button).disabled = running
        if running:
            self.query_one("#generate-report", Button).disabled = True

    @work(exclusive=True, thread=True)
    def _fire_selected_thread(self, attack_ids: list[str]) -> None:
        table = self.query_one("#results-table", DataTable)
        status = self.query_one("#run-status", Static)
        progress = self.query_one("#fire-progress", Static)
        total = len(attack_ids)

        self.app.call_from_thread(self._set_running, True)
        self.app.call_from_thread(progress.update, _ascii_bar(0, total))

        session_expired = False
        results_snapshot = {}
        try:
            for i, attack_id in enumerate(attack_ids, start=1):
                attack = self.attacks_by_id[attack_id]
                self.app.call_from_thread(
                    status.update,
                    f"[b]Running (selected)...[/b]  firing {attack.id}: {attack.name}",
                )
                self.app.call_from_thread(table.update_cell, attack.id, "status", "firing...")

                fire_result = self.api_client.fire_attack(self.session, attack.prompt)
                result = grade(attack, fire_result)

                if result.grade == "SESSION_EXPIRED":
                    session_expired = True
                    self.app.call_from_thread(status.update, "[b red]Session expired.[/b red] Logging out...")
                    break

                status_text = str(result.status_code) if result.status_code is not None else "n/a"
                self.app.call_from_thread(table.update_cell, attack.id, "status", status_text)
                self.app.call_from_thread(table.update_cell, attack.id, "grade", result.grade)
                self.app.call_from_thread(progress.update, _ascii_bar(i, total))

                results_snapshot[attack.id] = result.grade
                self.app.call_from_thread(self._refresh_summary_from, dict(results_snapshot))

            if not session_expired:
                self.app.call_from_thread(status.update, f"[b]Done.[/b]  Fired {total} attack(s) (selected, ARC path).")
        finally:
            self._results.update(results_snapshot)
            self.app.call_from_thread(self._set_running, False)
            if session_expired:
                self.app.call_from_thread(self.app.action_logout, reason="Session expired (token timed out).")

    @work(exclusive=True, thread=True)
    def _fire_all_thread(self) -> None:
        table = self.query_one("#results-table", DataTable)
        status = self.query_one("#run-status", Static)
        progress = self.query_one("#fire-progress", Static)
        summary_bar = self.query_one("#summary-bar", Static)

        self.app.call_from_thread(self._set_running, True)
        self.app.call_from_thread(status.update, "[b]Loading llm-redteam engine...[/b]")

        try:
            llm_redteam_dir = os.path.normpath(os.path.join(self.attacks_dir, ".."))
            bridge = RedTeamBridge(llm_redteam_dir)

            total = len(self.all_attacks)
            self.app.call_from_thread(progress.update, _ascii_bar(0, total))
            self.app.call_from_thread(
                status.update,
                "[b]Running full suite via llm-redteam...[/b] "
                "(the 6 benign-control checks can take 5-18s each on local hardware, this is normal)",
            )

            def on_progress(i, total_count, attack_dict, result_dict):
                attack_id = attack_dict.get("id")
                if attack_id is None:
                    return
                self.app.call_from_thread(
                    status.update,
                    f"[b]Running (llm-redteam)...[/b]  firing {attack_id}",
                )
                status_code = result_dict.get("status_code")
                self.app.call_from_thread(
                    table.update_cell, attack_id, "status",
                    str(status_code) if status_code is not None else "n/a",
                )
                if result_dict.get("skipped_reason"):
                    self.app.call_from_thread(table.update_cell, attack_id, "grade", "SKIPPED (locked)")
                self.app.call_from_thread(progress.update, _ascii_bar(i, total_count))

            raw_results = bridge.run_full_suite(
                base_url=self.session.base_url,
                token=self.session.token,
                attacks_dir=self.attacks_dir,
                progress_callback=on_progress,
            )

            scored_data = bridge.score(raw_results)
            for r in scored_data["results"]:
                attack_id = r.get("id")
                if attack_id is None:
                    continue
                self.app.call_from_thread(table.update_cell, attack_id, "grade", r.get("grade", "--"))

            summary = scored_data["summary"]
            self._last_full_suite_scored = scored_data
            self.app.call_from_thread(setattr, self.query_one("#generate-report", Button), "disabled", False)

            if self.arc_dir:
                append_run(self.arc_dir, scored_data)

            pass_rate = (summary["pass"] / summary["total"] * 100) if summary["total"] else 0
            self.app.call_from_thread(
                summary_bar.update,
                f"Total: {summary['total']}   Passed: {summary['pass']}   "
                f"Failed: {summary['fail']}   Errors: {summary['error']}   "
                f"Pass rate: {pass_rate:.1f}%",
            )
            self.app.call_from_thread(
                status.update,
                f"[b]Done.[/b]  Full suite via llm-redteam: {summary['pass']}/{summary['total']} passed. "
                f"Recorded to Ops Log. Click 'Generate Report' for the full styled report.",
            )
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(status.update, f"[b red]Full-suite run failed:[/b red] {exc}")
        finally:
            self.app.call_from_thread(self._set_running, False)

    def _generate_report(self) -> None:
        if self._last_full_suite_scored is None:
            return
        self._write_and_open_report_thread()

    @work(exclusive=True, thread=True)
    def _write_and_open_report_thread(self) -> None:
        status = self.query_one("#run-status", Static)
        self.app.call_from_thread(status.update, "[b]Generating report...[/b]")

        llm_redteam_dir = os.path.normpath(os.path.join(self.attacks_dir, ".."))
        bridge = RedTeamBridge(llm_redteam_dir)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = os.path.join(llm_redteam_dir, f"report_{timestamp}.html")

        try:
            path = bridge.generate_report(self._last_full_suite_scored, output_path)
            self.app.call_from_thread(status.update, f"[b green]Report written:[/b green] {path}")
            webbrowser.open(f"file://{os.path.abspath(path)}")
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(status.update, f"[b red]Report generation failed:[/b red] {exc}")

    def _refresh_summary_from(self, results_snapshot: dict) -> None:
        results = list(results_snapshot.values())
        total = len(results)
        passed = results.count("PASS")
        failed = results.count("FAIL")
        errored = results.count("ERROR")
        scored = passed + failed + errored
        pass_rate = (passed / scored * 100) if scored else 0.0
        summary = self.query_one("#summary-bar", Static)
        summary.update(
            f"Total: {total}   Passed: {passed}   Failed: {failed}   "
            f"Errors: {errored}   Pass rate: {pass_rate:.1f}%"
        )
