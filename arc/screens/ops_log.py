"""
ARC Findings Screen
---------------------
Replaces a flat run-history table with what a red-team tool is actually
supposed to produce: a list of specific, named gaps -- currently open,
or previously open and now confirmed fixed -- built from core/findings.py.
The raw run history is still here, just demoted to a collapsible section,
and rebuilt as a narrative of what changed each run (derived from
findings.json's own tagged history) rather than a flat table of counts.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from core.findings import fixed_findings, load_findings, narrative_for_run, open_findings
from core.header_bar import ArcHeader
from core.ops_log import load_history
from core.session_widget import SessionBar
from core.theme import ARC_GREEN, ARC_RED, BORDER, PANEL_ALT, TEXT, TEXT_DIM


def _date(iso_timestamp: str) -> str:
    return iso_timestamp.split("T")[0] if "T" in iso_timestamp else iso_timestamp


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class OpsLogScreen(Screen):
    CSS = f"""
    #session-bar {{
        height: 2;
        background: {PANEL_ALT};
        color: {TEXT_DIM};
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    #findings-body {{
        width: 100%;
    }}
    #findings-toolbar {{
        height: 3;
        align: left middle;
        padding: 0 2;
        margin-top: 1;
    }}
    #findings-summary {{
        width: auto;
        content-align: left middle;
    }}
    #refresh {{
        dock: right;
        width: 12;
        height: 3;
        min-width: 0;
        min-height: 0;
        background: transparent;
        color: {TEXT_DIM};
        border: solid {BORDER};
        text-style: none;
        content-align: center middle;
    }}
    #refresh:hover {{
        color: {TEXT};
        border: solid {TEXT_DIM};
    }}
    .section-header {{
        height: 1;
        content-align: left middle;
        text-style: bold;
        padding: 0 2;
        margin-top: 1;
    }}
    .section-header.-open {{
        color: {ARC_RED};
    }}
    .section-header.-fixed {{
        color: {ARC_GREEN};
    }}
    #open-list, #fixed-list {{
        height: auto;
        max-height: 16;
        padding: 0 2;
    }}
    .finding-row {{
        height: 3;
        align: left top;
        border-bottom: solid {TEXT} 8%;
    }}
    .finding-text {{
        width: 1fr;
        height: 2;
        content-align: left top;
        text-align: left;
    }}
    .pill {{
        dock: right;
        width: 8;
        height: 2;
        content-align: center middle;
        text-align: center;
        text-style: bold;
    }}
    .pill.-open {{
        background: {ARC_RED} 20%;
        color: {ARC_RED};
    }}
    .pill.-fixed {{
        background: {ARC_GREEN} 20%;
        color: {ARC_GREEN};
    }}
    #empty-open-state {{
        height: 3;
        content-align: center middle;
        text-align: center;
    }}
    #history-toggle {{
        width: auto;
        min-width: 0;
        height: 1;
        margin: 1 2;
        background: transparent;
        color: {TEXT_DIM};
        border: none;
        text-style: none;
        content-align: left middle;
    }}
    #history-toggle:hover {{
        color: {TEXT};
    }}
    #history-container {{
        height: auto;
        max-height: 16;
        padding: 0 2;
    }}
    #history-container.-collapsed {{
        display: none;
    }}
    .history-line {{
        height: 1;
        color: {TEXT_DIM};
    }}
    .history-line.-regressed {{
        color: {ARC_RED};
    }}
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, session, arc_dir: str):
        super().__init__()
        self.session = session
        self.arc_dir = arc_dir

    def compose(self) -> ComposeResult:
        yield ArcHeader(on_back=self.action_go_back)
        yield SessionBar(self.session, id="session-bar")
        with Vertical(id="findings-body"):
            with Horizontal(id="findings-toolbar"):
                yield Static("", id="findings-summary")
                yield Button("Refresh", id="refresh")
            yield Static("OPEN FINDINGS", classes="section-header -open")
            yield Vertical(id="open-list")
            yield Static("FIXED FINDINGS", classes="section-header -fixed")
            yield VerticalScroll(id="fixed-list")
            yield Button("▸ Raw run history (evidence trail)", id="history-toggle")
            yield VerticalScroll(id="history-container", classes="-collapsed")

    async def on_mount(self) -> None:
        await self._load()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            await self._load()
        elif event.button.id == "history-toggle":
            self._toggle_history()

    def _toggle_history(self) -> None:
        container = self.query_one("#history-container")
        toggle = self.query_one("#history-toggle", Button)
        collapsed = container.has_class("-collapsed")
        container.set_class(not collapsed, "-collapsed")
        arrow = "▾" if collapsed else "▸"
        toggle.label = f"{arrow} Raw run history (evidence trail)"

    async def _load(self) -> None:
        findings = load_findings(self.arc_dir)
        history = load_history(self.arc_dir)
        opens = open_findings(findings)
        fixed = fixed_findings(findings)

        summary = self.query_one("#findings-summary", Static)
        open_color = ARC_RED if opens else TEXT
        summary.update(
            f"[b]Findings[/b]   [{open_color}]{len(opens)} open[/{open_color}] "
            f"[{TEXT_DIM}]·[/{TEXT_DIM}] [{ARC_GREEN}]{len(fixed)} fixed[/{ARC_GREEN}]"
        )

        await self._render_open(opens, history)
        await self._render_fixed(fixed)
        await self._render_history_narrative(findings, history)

    async def _render_open(self, opens: list, history: list) -> None:
        container = self.query_one("#open-list", Vertical)
        await container.remove_children()

        if not opens:
            last = history[-1] if history else None
            detail = ""
            if last:
                detail = f"Last confirmed {last['timestamp']} · {last['pass']}/{last['total']} attacks held"
            await container.mount(Static(
                f"[{ARC_GREEN}]✓ No open findings — all tested attacks currently blocked[/{ARC_GREEN}]\n"
                f"[{TEXT_DIM}]{detail}[/{TEXT_DIM}]",
                id="empty-open-state",
            ))
            return

        for finding in opens:
            row = Horizontal(classes="finding-row")
            await container.mount(row)
            await row.mount(Static(
                f"[{ARC_RED}]●[/{ARC_RED}] [b]{finding['attack_id']}[/b]  {finding['name']}\n"
                f"  [{TEXT_DIM}]open since {_date(finding['first_seen'])} · "
                f"seen in {_plural(finding['seen_count'], 'run')}[/{TEXT_DIM}]",
                classes="finding-text",
            ))
            await row.mount(Static("OPEN", classes="pill -open"))

    async def _render_fixed(self, fixed: list) -> None:
        container = self.query_one("#fixed-list", VerticalScroll)
        await container.remove_children()

        for finding in fixed:
            row = Horizontal(classes="finding-row")
            await container.mount(row)
            await row.mount(Static(
                f"[{ARC_GREEN}]●[/{ARC_GREEN}] [b]{finding['attack_id']}[/b]  {finding['name']}\n"
                f"  [{TEXT_DIM}]fixed {_date(finding['status_changed_at'])} · "
                f"confirmed {_plural(finding['confirmations'], 'time')} since[/{TEXT_DIM}]",
                classes="finding-text",
            ))
            await row.mount(Static("FIXED", classes="pill -fixed"))

    async def _render_history_narrative(self, findings: dict, history: list) -> None:
        container = self.query_one("#history-container", VerticalScroll)
        await container.remove_children()

        if not history:
            await container.mount(Static(
                "No runs recorded yet. Run 'Fire all (llm-redteam)' from the "
                "Attack Library to record your first entry.",
                classes="history-line",
            ))
            return

        for record in reversed(history):
            line, had_regression = narrative_for_run(findings, record)
            classes = "history-line -regressed" if had_regression else "history-line"
            await container.mount(Static(
                f"{_date(record['timestamp'])}  {line}",
                classes=classes,
            ))
