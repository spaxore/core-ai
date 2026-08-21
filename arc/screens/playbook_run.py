"""
ARC Playbook Run
------------------
Fires a playbook's steps live, one attack at a time, rendering each step
as it completes -- reusing the exact same tiered/step visual language
already validated on the AI app's own investigation trace/stepper
(pending -> running -> settled), just applied to an attack chain instead
of an investigation's internal search tiers.

Firing itself is not reimplemented here: RedTeamBridge.run_playbook()
calls straight into llm-redteam's own fire_playbook(), the same engine
"Fire all" already uses.
"""
from __future__ import annotations

import os

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, ProgressBar, Static

from core.header_bar import ArcHeader
from core.redteam_bridge import RedTeamBridge
from core.session_widget import SessionBar
from core.theme import ARC_AMBER, ARC_BLUE, ARC_GREEN, ARC_RED, BORDER, PANEL_ALT, SPINNER_FRAMES, TEXT, TEXT_DIM


GLYPH = {"pending": "○", "pass": "✓", "fail": "✗", "skip": "·", "error": "✗"}
GLYPH_COLOR = {
    "pending": TEXT_DIM, "running": ARC_AMBER, "pass": ARC_GREEN,
    "fail": ARC_RED, "skip": TEXT_DIM, "error": ARC_RED,
}
LABEL = {
    "pending": "PENDING", "running": "RUNNING", "pass": "PASS",
    "fail": "FAIL", "skip": "SKIPPED", "error": "ERROR",
}


def _summarize_step_result(result: dict) -> str:
    """
    One-line, honest summary of what actually happened for a step --
    reads the Gateway's own matched-category detail (now exposed on a
    403 response body, see app/main.py) for blocked steps, and the
    classification/investigation result for allowed ones, rather than
    just reporting a bare status code.
    """
    grade = result.get("grade")
    status = result.get("status_code")
    body = result.get("response_body") or {}

    if grade == "SKIPPED":
        return result.get("skipped_reason", "Skipped")
    if grade == "ERROR":
        return result.get("error") or "Error firing this step"

    if status == 403:
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            # Parentheses, not square brackets: a single-word bracketed value
            # like "[EXFILTRATION]" parses as a Rich markup style tag (and
            # gets silently swallowed since no such style exists) once this
            # string is embedded inside another markup-formatted line --
            # already hit this exact bug once this session with a literal
            # "[Logout]" label.
            categories = ", ".join(detail.get("matched_categories", [])) or "n/a"
            return f"Blocked -- risk_score: {detail.get('risk_score')} -- matched: ({categories})"
        return "Blocked by security gateway"

    if status == 200:
        if isinstance(body, dict) and "pipeline" in body:
            classification = body.get("classification") or {}
            return (
                f"Allowed -- classified as {classification.get('category', '?')} "
                f"({classification.get('confidence', '?')}) -- investigation ran"
            )
        if isinstance(body, dict) and "category" in body:
            return f"Allowed -- classified as {body.get('category', '?')} ({body.get('confidence', '?')})"
        return "Allowed (200)"

    return f"Unexpected status {status}"


class PlaybookRunScreen(Screen):
    CSS = f"""
    #session-bar {{
        height: 2;
        background: {PANEL_ALT};
        color: {TEXT_DIM};
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    #pb-header {{
        padding: 1 2;
        border-bottom: solid {BORDER};
    }}
    #pb-name {{
        text-style: bold;
        color: {TEXT};
    }}
    #pb-desc {{
        color: {TEXT_DIM};
    }}
    #pb-progress {{
        height: 3;
        padding: 0 2;
        color: {TEXT_DIM};
        border-bottom: solid {BORDER};
    }}
    #pb-progress-label {{
        height: 1;
    }}
    #pb-progress-bar {{
        width: 100%;
        height: 1;
    }}
    #pb-progress-bar Bar {{
        width: 1fr;
    }}
    #pb-progress-bar Bar > .bar--bar {{
        color: {ARC_BLUE};
    }}
    #pb-progress-bar Bar > .bar--complete {{
        color: {ARC_GREEN};
    }}
    #pb-run-btn {{
        margin: 1 2;
        width: auto;
        background: {ARC_BLUE};
        color: white;
    }}
    #pb-chain {{
        padding: 1 3;
    }}
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, session, attacks_dir: str, arc_dir: str, playbook: dict):
        super().__init__()
        self.session = session
        self.attacks_dir = attacks_dir
        self.arc_dir = arc_dir
        self.playbook = playbook
        self.step_states: list[dict] = [
            {"state": "pending", "attack_id": s["attack_id"], "name": "", "target": "", "detail": None}
            for s in playbook.get("steps", [])
        ]
        self._spin_frame = 0
        self._spin_timer = None

    def compose(self) -> ComposeResult:
        yield ArcHeader(on_back=self.action_go_back)
        yield SessionBar(self.session, id="session-bar")
        with Vertical(id="pb-header"):
            yield Static(self.playbook.get("name", "Playbook"), id="pb-name")
            yield Static(self.playbook.get("description", "").strip(), id="pb-desc")
        with Vertical(id="pb-progress"):
            yield Static("", id="pb-progress-label")
            yield ProgressBar(total=len(self.step_states) or None, show_eta=False, id="pb-progress-bar")
        yield Button("Run playbook", id="pb-run-btn")
        with VerticalScroll(id="pb-scroll"):
            yield Static("", id="pb-chain")

    def on_mount(self) -> None:
        self._render_chain()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pb-run-btn":
            event.button.disabled = True
            self._run_thread()

    def _render_chain(self) -> None:
        total = len(self.step_states)
        done = sum(1 for s in self.step_states if s["state"] not in ("pending", "running"))
        if done >= total:
            progress_label = f"Done -- {total}/{total}"
        else:
            current = next((i for i, s in enumerate(self.step_states, 1) if s["state"] == "running"), done + 1)
            progress_label = f"Step {current} of {total}"
        self.query_one("#pb-progress-label", Static).update(progress_label)
        self.query_one("#pb-progress-bar", ProgressBar).progress = done

        lines = []
        last_index = len(self.step_states) - 1
        for i, s in enumerate(self.step_states):
            state = s["state"]
            color = GLYPH_COLOR[state]
            glyph = SPINNER_FRAMES[self._spin_frame] if state == "running" else GLYPH[state]
            label = LABEL[state]
            title_color = TEXT_DIM if state in ("pending", "skip") else TEXT

            lines.append(
                f"[{color}]{glyph}[/{color}] [{title_color} b]Step {i + 1} -- {s['attack_id']}[/{title_color} b]"
                f"  [{color}]{label}[/{color}]"
            )
            sub_parts = [p for p in (s.get("name"), f"target {s['target']}" if s.get("target") else None) if p]
            if sub_parts:
                lines.append(f"  [dim]{' -- '.join(sub_parts)}[/dim]")
            if s.get("detail"):
                detail_color = ARC_RED if state == "skip" else TEXT_DIM
                lines.append(f"  [{detail_color}]{s['detail']}[/{detail_color}]")
            if i != last_index:
                lines.append("")

        self.query_one("#pb-chain", Static).update("\n".join(lines))

    @work(exclusive=True, thread=True)
    def _run_thread(self) -> None:
        llm_redteam_dir = os.path.normpath(os.path.join(self.attacks_dir, ".."))
        bridge = RedTeamBridge(llm_redteam_dir)

        self.app.call_from_thread(self._start_spinner)

        def on_progress(i, total, attack, result):
            grade = result.get("grade")
            state = {"PASS": "pass", "FAIL": "fail", "SKIPPED": "skip"}.get(grade, "error")
            self.step_states[i - 1] = {
                "state": state,
                "attack_id": result.get("id", attack.get("id", "?")),
                "name": result.get("name", ""),
                "target": result.get("target_endpoint") or "/classify",
                "detail": _summarize_step_result(result),
            }
            if i < len(self.step_states):
                self.step_states[i]["state"] = "running"
            self.app.call_from_thread(self._render_chain)

        try:
            bridge.run_playbook(
                base_url=self.session.base_url,
                token=self.session.token,
                playbook=self.playbook,
                attacks_dir=self.attacks_dir,
                progress_callback=on_progress,
            )
        finally:
            self.app.call_from_thread(self._stop_spinner)

    def _start_spinner(self) -> None:
        if self.step_states:
            self.step_states[0]["state"] = "running"
        self._render_chain()
        self._spin_timer = self.set_interval(0.09, self._spin)

    def _spin(self) -> None:
        self._spin_frame = (self._spin_frame + 1) % len(SPINNER_FRAMES)
        self._render_chain()

    def _stop_spinner(self) -> None:
        if self._spin_timer:
            self._spin_timer.stop()
