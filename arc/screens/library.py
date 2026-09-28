"""
ARC Attack Library Screen
--------------------------
The hub for everything attack-related: browse/search/fire the catalog
here, then reach Author New Attack and Playbooks from the catalog-tools-row
below -- they're different modes of working with this same catalog, not
unrelated top-level destinations, so they're reachable from here instead
of the main menu (see screens/menu.py).

Fire selected: ARC's own lightweight path.
Fire all: routes through core/redteam_bridge.py (the real llm-redteam
engine, in-process). Every completed Fire All run appends one record
to core/ops_log.py's local history -- viewable on the Findings screen.
"""
from __future__ import annotations

import os
import webbrowser
from datetime import datetime

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, ProgressBar, Static

from core.api_client import APIClient, Session
from core.attacks import Attack, AttackFile, flatten
from core.findings import update_findings
from core.grading import grade
from core.header_bar import ArcHeader
from core.ops_log import append_run
from core.redteam_bridge import RedTeamBridge
from core.session_widget import SessionBar
from core.theme import (
    ARC_AMBER,
    ARC_BLUE,
    ARC_GREEN,
    ARC_RED,
    ARC_ROSE,
    BORDER,
    PANEL_ALT,
    SPINNER_FRAMES,
    TEXT,
    TEXT_DIM,
)

# Known categories get a deliberate short tag + color, matching the
# confirmed mockup's CTRL/EX/DI/JB/SQLI language; categories added later
# (new attack files) fall back to an auto-generated tag/color so the
# screen never breaks, it just looks a little less curated until someone
# adds a real mapping here.
_CATEGORY_STYLES: dict[str, tuple[str, str]] = {
    "control_benign": ("CTRL", TEXT_DIM),
    "data_exfiltration": ("EX", ARC_AMBER),
    "direct_injection": ("DI", ARC_RED),
    "indirect_injection": ("II", ARC_ROSE),
    "jailbreak": ("JB", ARC_ROSE),
    "retrieval_poisoning": ("RP", ARC_BLUE),
    "role_confusion": ("RC", ARC_GREEN),
    "sql_injection_via_prompt": ("SQLI", ARC_BLUE),
}
_FALLBACK_PALETTE = [ARC_RED, ARC_BLUE, ARC_AMBER, ARC_GREEN, ARC_ROSE, TEXT_DIM]


def _category_style(category: str) -> tuple[str, str]:
    if category in _CATEGORY_STYLES:
        return _CATEGORY_STYLES[category]
    tag = "".join(w[0] for w in category.split("_") if w)[:4].upper() or "GEN"
    color = _FALLBACK_PALETTE[hash(category) % len(_FALLBACK_PALETTE)]
    return tag, color


LIVE_GLYPH = {"pass": "✓", "fail": "✗", "running": "…", "pending": "○", "skip": "·"}
LIVE_LABEL = {"pass": "PASS", "fail": "FAIL", "running": "firing...", "pending": "pending", "skip": "skipped"}
LIVE_COLOR = {"pass": ARC_GREEN, "fail": ARC_RED, "running": ARC_AMBER, "pending": TEXT_DIM, "skip": TEXT_DIM}


class LibraryScreen(Screen):
    CSS = f"""
    #session-bar {{
        height: 2;
        background: {PANEL_ALT};
        color: {TEXT_DIM};
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    #lib-title {{
        height: 2;
        background: {PANEL_ALT};
        color: {TEXT_DIM};
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    #search-row {{
        height: 4;
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    #search-box {{
        background: {PANEL_ALT};
        color: {TEXT};
        border: solid {BORDER};
    }}
    #search-box:focus {{
        border: solid {ARC_BLUE};
    }}
    #split {{
        height: 1fr;
    }}
    #left-pane {{
        width: 56%;
        height: 1fr;
        border-right: solid {BORDER};
    }}
    #right-pane {{
        width: 44%;
        height: 1fr;
        padding: 1 2;
    }}
    .cat-header-row {{
        height: 2;
        background: {PANEL_ALT};
        border-bottom: solid {BORDER};
    }}
    .cat-spacer {{
        height: 1;
    }}
    Button.cat-header-btn {{
        width: 1fr;
        height: 1;
        min-height: 0;
        background: transparent;
        color: {TEXT_DIM};
        border: none;
        text-style: none;
        content-align: left middle;
        text-align: left;
        padding: 0 1;
    }}
    Button.cat-header-btn:hover {{
        color: {TEXT};
    }}
    Button.cat-selall-btn {{
        width: 14;
        height: 1;
        min-height: 0;
        background: transparent;
        color: {ARC_BLUE};
        border: none;
        text-style: none;
        content-align: right middle;
        text-align: right;
        padding: 0 1;
    }}
    .lib-rows {{
        height: auto;
    }}
    .lib-rows.-collapsed {{
        display: none;
    }}
    Button.row-body {{
        width: 100%;
        height: 4;
        min-height: 0;
        background: transparent;
        color: {TEXT};
        border: none;
        border-bottom: solid {TEXT} 6%;
        text-style: none;
        content-align: left middle;
        text-align: left;
        padding: 1 1;
    }}
    Button.row-body:hover {{
        background: {TEXT} 3%;
    }}
    Button.row-body.-focused {{
        background: {ARC_BLUE} 8%;
        border-left: solid {ARC_BLUE};
        padding: 1 1 1 0;
    }}
    #preview-scroll {{
        height: 1fr;
    }}
    #right-pane .detail-label {{
        color: {TEXT_DIM};
        text-style: bold;
        margin-top: 1;
    }}
    #right-pane .detail-label:first-child {{
        margin-top: 0;
    }}
    #right-pane .detail-prompt {{
        background: {PANEL_ALT};
        border: solid {BORDER};
        padding: 1;
        margin-top: 1;
    }}
    #live-progress-bar {{
        width: 100%;
        margin-top: 1;
    }}
    #live-progress-bar Bar {{
        width: 1fr;
    }}
    #live-progress-bar Bar > .bar--bar {{
        color: {ARC_BLUE};
    }}
    #live-progress-bar Bar > .bar--complete {{
        color: {ARC_GREEN};
    }}
    #live-list-scroll {{
        height: 1fr;
        margin-top: 1;
    }}
    #live-list {{
        height: auto;
    }}
    .live-row {{
        height: 1;
    }}
    #report-cta {{
        height: 4;
        align: left middle;
        margin-top: 1;
        border-top: solid {BORDER};
    }}
    #report-summary {{
        width: auto;
        height: 3;
        content-align: left middle;
    }}
    #report-spacer {{
        width: 1fr;
    }}
    Button#generate-report {{
        width: 20;
        height: 3;
        background: transparent;
        color: {ARC_BLUE};
        border: solid {ARC_BLUE};
        text-style: none;
        content-align: center middle;
    }}
    #footer-bar {{
        height: 4;
        align: left middle;
        background: {PANEL_ALT};
        border-top: solid {BORDER};
        padding: 0 2;
    }}
    #selection-count {{
        width: auto;
        color: {TEXT_DIM};
    }}
    Button.footer-link {{
        width: auto;
        min-width: 0;
        height: 1;
        min-height: 0;
        background: transparent;
        color: {ARC_BLUE};
        border: none;
        text-style: none;
        margin-left: 2;
    }}
    #footer-spacer {{
        width: 1fr;
    }}
    Button#fire-selected {{
        width: 18;
        height: 3;
        background: {ARC_BLUE};
        color: $text;
        border: none;
        text-style: bold;
        margin-right: 1;
    }}
    Button#fire-all {{
        width: 22;
        height: 3;
        background: {ARC_AMBER};
        color: #1A1400;
        border: none;
        text-style: bold;
    }}
    #catalog-tools-row {{
        height: 4;
        align: left middle;
        border-top: solid {BORDER};
        padding: 0 2;
    }}
    #catalog-tools-label {{
        width: auto;
        height: 3;
        content-align: left middle;
        color: {TEXT_DIM};
        margin-right: 1;
    }}
    Button.catalog-tool-btn {{
        width: auto;
        height: 3;
        background: transparent;
        color: {TEXT_DIM};
        border: solid {BORDER};
        text-style: none;
        margin-right: 1;
        padding: 0 2;
    }}
    Button.catalog-tool-btn:hover {{
        color: {TEXT};
        border: solid {TEXT_DIM};
    }}
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

        self.selected_ids: set[str] = set()
        self.collapsed: set[str] = set()
        self.focused_id: str | None = self.all_attacks[0].id if self.all_attacks else None
        self.last_results: dict[str, str] = {}  # attack_id -> grade, this session only

        self.right_mode = "preview"  # "preview" | "live" | "done"
        self.live_states: dict[str, str] = {}
        self.live_order: list[str] = []
        self.live_label = ""
        self._batch_running = False
        self._last_full_suite_scored: dict | None = None
        self._spinner_frame = 0
        self._spinner_timer = None

    # ---- compose -----------------------------------------------------

    def compose(self) -> ComposeResult:
        yield ArcHeader(on_back=self.action_go_back)
        yield SessionBar(self.session, id="session-bar")
        yield Static("Attack Library (space = toggle, enter = fire selected, / = search)", id="lib-title")
        with Horizontal(id="search-row"):
            yield Input(placeholder="Filter by ID, keyword, category...", id="search-box")
        with Horizontal(id="split"):
            yield VerticalScroll(id="left-pane")
            yield Vertical(id="right-pane")
        with Horizontal(id="footer-bar"):
            yield Static("", id="selection-count")
            yield Button("Select all", id="select-all", classes="footer-link")
            yield Button("Clear", id="select-none", classes="footer-link")
            yield Static("", id="footer-spacer")
            yield Button("Fire selected", id="fire-selected")
            yield Button(f"Fire all ({len(self.all_attacks)})", id="fire-all")
        with Horizontal(id="catalog-tools-row"):
            yield Static("Catalog tools:", id="catalog-tools-label")
            yield Button("Author New Attack", id="go-author", classes="catalog-tool-btn")
            yield Button("Playbooks", id="go-playbooks", classes="catalog-tool-btn")

    async def on_mount(self) -> None:
        await self._render_left()
        await self._render_right()
        self._update_selection_count()

    def action_go_back(self) -> None:
        if not self._batch_running:
            self.app.pop_screen()

    # ---- left pane: categorized, collapsible, searchable --------------

    async def _render_left(self, query: str = "") -> None:
        left = self.query_one("#left-pane", VerticalScroll)
        await left.remove_children()
        q = query.strip().lower()

        for f in self.attack_files:
            visible = [
                a for a in f.attacks
                if not q or q in a.id.lower() or q in a.name.lower() or q in f.category.lower()
            ]
            if not visible:
                continue

            tag, color = _category_style(f.category)
            collapsed = f.category in self.collapsed
            chevron = "▸" if collapsed else "▾"

            header_row = Horizontal(classes="cat-header-row")
            await left.mount(header_row)
            await header_row.mount(Button(
                f"{chevron} [{color} on {color} 15%] {tag} [/] {f.category} ({len(visible)})",
                id=f"cat-{f.category}",
                classes="cat-header-btn",
            ))
            await header_row.mount(Button("select all", id=f"selcat-{f.category}", classes="cat-selall-btn"))

            rows = Vertical(id=f"rows-{f.category}", classes="lib-rows")
            if collapsed:
                rows.add_class("-collapsed")
            await left.mount(rows)

            for a in visible:
                await self._mount_row(rows, a)

            # A real, height-1 spacer widget -- not CSS margin. VerticalScroll's
            # virtual_size (the scroll-bounds calculation) was measured to
            # under-count content height by exactly the sum of margins when
            # spacing was done with margin-top/margin-bottom instead: rows
            # painted correctly but scrolling couldn't reach the last ones at
            # normal terminal sizes. A mounted widget's own height is always
            # counted correctly, margin isn't reliably.
            await left.mount(Static("", classes="cat-spacer"))

        # Forces the compositor's hit-test arrangement to recompute
        # immediately rather than on the next natural render tick --
        # without this, rapid successive rebuilds (search-while-typing,
        # repeated category toggles) can leave stale region data that
        # misroutes the next click to whatever widget used to occupy
        # that screen cell.
        self.refresh(layout=True)

    async def _mount_row(self, container: Vertical, a: Attack) -> None:
        # A row used to be two side-by-side Buttons (a narrow checkbox +
        # a wide body) so click-to-select and click-to-preview were
        # independent gestures, matching the mockup. Textual's hit-testing
        # doesn't reliably route clicks to a ~3-cell-wide Button squeezed
        # next to another Button in a Horizontal -- clicks landed on the
        # parent container instead (confirmed via get_widget_at during
        # testing). One full-width row Button, same proven pattern as
        # every other screen in this app (menu-row, pb-row), avoids that
        # entirely: a click both toggles selection and sets the preview.
        last = self.last_results.get(a.id)
        if last == "PASS":
            dot = f"[{ARC_GREEN}]●[/{ARC_GREEN}]"
        elif last in ("FAIL", "ERROR"):
            dot = f"[{ARC_RED}]●[/{ARC_RED}]"
        else:
            dot = f"[{TEXT_DIM}]○[/{TEXT_DIM}]"

        checked = f"[{ARC_BLUE}]×[/{ARC_BLUE}]" if a.id in self.selected_ids else f"[{TEXT_DIM}]☐[/{TEXT_DIM}]"
        suffix = " (Fire All only)" if a.is_two_step else ""

        btn = Button(
            f"{checked} {dot} {a.id}  {a.name}{suffix}",
            id=f"row-{a.id}",
            classes="row-body",
        )
        if a.id == self.focused_id:
            btn.add_class("-focused")
        await container.mount(btn)

    async def _toggle_category(self, category: str) -> None:
        if category in self.collapsed:
            self.collapsed.discard(category)
        else:
            self.collapsed.add(category)
        query = self.query_one("#search-box", Input).value
        await self._render_left(query)

    async def _select_category(self, category: str) -> None:
        for f in self.attack_files:
            if f.category == category:
                for a in f.attacks:
                    self.selected_ids.add(a.id)
        query = self.query_one("#search-box", Input).value
        await self._render_left(query)
        self._update_selection_count()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-box":
            await self._render_left(event.value)

    # ---- row interactions ----------------------------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id.startswith("cat-"):
            await self._toggle_category(btn_id.removeprefix("cat-"))
            return
        if btn_id.startswith("selcat-"):
            await self._select_category(btn_id.removeprefix("selcat-"))
            return
        if btn_id.startswith("row-"):
            await self._row_clicked(btn_id.removeprefix("row-"))
            return

        if self._batch_running:
            return

        if btn_id == "select-all":
            self.selected_ids = {a.id for a in self.all_attacks}
            await self._render_left(self.query_one("#search-box", Input).value)
            self._update_selection_count()
        elif btn_id == "select-none":
            self.selected_ids.clear()
            await self._render_left(self.query_one("#search-box", Input).value)
            self._update_selection_count()
        elif btn_id == "fire-selected":
            if self.selected_ids:
                self._fire_selected_thread(list(self.selected_ids))
        elif btn_id == "fire-all":
            self._fire_all_thread()
        elif btn_id == "generate-report":
            self._generate_report()
        elif btn_id == "go-author":
            from screens.authoring import AuthoringScreen
            self.app.push_screen(AuthoringScreen(self.session, self.attacks_dir))
        elif btn_id == "go-playbooks":
            from screens.playbook import PlaybookListScreen
            self.app.push_screen(PlaybookListScreen(self.session, self.attacks_dir, self.arc_dir))

    async def _row_clicked(self, attack_id: str) -> None:
        # A single click both toggles selection (the checkbox glyph baked
        # into the row's own label) and sets the preview -- see the note
        # in _mount_row for why this is one row Button, not two.
        if attack_id in self.selected_ids:
            self.selected_ids.discard(attack_id)
        else:
            self.selected_ids.add(attack_id)
        self._update_selection_count()

        attack = self.attacks_by_id[attack_id]
        checked = f"[{ARC_BLUE}]×[/{ARC_BLUE}]" if attack_id in self.selected_ids else f"[{TEXT_DIM}]☐[/{TEXT_DIM}]"
        last = self.last_results.get(attack_id)
        if last == "PASS":
            dot = f"[{ARC_GREEN}]●[/{ARC_GREEN}]"
        elif last in ("FAIL", "ERROR"):
            dot = f"[{ARC_RED}]●[/{ARC_RED}]"
        else:
            dot = f"[{TEXT_DIM}]○[/{TEXT_DIM}]"
        suffix = " (Fire All only)" if attack.is_two_step else ""
        self.query_one(f"#row-{attack_id}", Button).label = f"{checked} {dot} {attack_id}  {attack.name}{suffix}"

        if self.focused_id is not None:
            try:
                self.query_one(f"#row-{self.focused_id}").remove_class("-focused")
            except Exception:
                pass
        self.focused_id = attack_id
        try:
            self.query_one(f"#row-{attack_id}").add_class("-focused")
        except Exception:
            pass
        if self.right_mode == "preview":
            await self._render_right()

    def _update_selection_count(self) -> None:
        self.query_one("#selection-count", Static).update(
            f"[b]{len(self.selected_ids)}[/b] / {len(self.all_attacks)} selected"
        )

    # ---- right pane: preview / live / done -----------------------------

    async def _render_right(self) -> None:
        right = self.query_one("#right-pane", Vertical)
        await right.remove_children()

        if self.right_mode != "live":
            self._stop_spinner()

        if self.right_mode == "preview":
            await self._render_preview(right)
        elif self.right_mode == "live":
            await self._render_live(right)
        elif self.right_mode == "done":
            await self._render_live(right, done=True)

    async def _render_preview(self, right: Vertical) -> None:
        scroll = VerticalScroll(id="preview-scroll")
        await right.mount(scroll)

        attack = self.attacks_by_id.get(self.focused_id) if self.focused_id else None
        if attack is None:
            await scroll.mount(Static("Select an attack to preview it.", classes="detail-label"))
            return

        await scroll.mount(Static("ID / CATEGORY", classes="detail-label"))
        await scroll.mount(Static(f"{attack.id}  ({attack.category})"))
        await scroll.mount(Static("SEVERITY / EXPECTED", classes="detail-label"))
        await scroll.mount(Static(f"{attack.severity} -> {attack.expected}"))
        await scroll.mount(Static("PROMPT", classes="detail-label"))
        if attack.is_two_step:
            body = f"SEED:\n{attack.seed}\n\nPROBE:\n{attack.probe}"
        else:
            body = attack.prompt or ""
        await scroll.mount(Static(body, classes="detail-prompt"))
        await scroll.mount(Static("LAST RESULT (this session)", classes="detail-label"))
        last = self.last_results.get(attack.id)
        if last == "PASS":
            outcome = {"allowed": "allowed as expected", "isolated": "isolated as expected"}.get(attack.expected, "blocked as expected")
            await scroll.mount(Static(f"[{ARC_GREEN}]✓ PASS — {outcome}[/{ARC_GREEN}]"))
        elif last in ("FAIL",):
            outcome = {"allowed": "blocked unexpectedly (false positive), recheck", "isolated": "not isolated, recheck"}.get(attack.expected, "not blocked, recheck")
            await scroll.mount(Static(f"[{ARC_RED}]✗ FAIL — {outcome}[/{ARC_RED}]"))
        elif last == "ERROR":
            await scroll.mount(Static(f"[{ARC_AMBER}]⚠ ERROR firing this attack[/{ARC_AMBER}]"))
        else:
            await scroll.mount(Static(f"[{TEXT_DIM}]— no result yet this session[/{TEXT_DIM}]"))

    async def _render_live(self, right: Vertical, done: bool = False) -> None:
        total = len(self.live_order)
        current = sum(1 for s in self.live_states.values() if s != "pending")
        await right.mount(Static(self.live_label, id="live-progress-label"))
        bar = ProgressBar(total=total or None, show_eta=False, id="live-progress-bar")
        await right.mount(bar)
        bar.progress = current

        # The row list is the only part that scrolls -- the summary/report
        # button below is mounted as a direct sibling of `right`, outside
        # this scroll area, so it stays pinned in place and reachable
        # without having to scroll past 42 rows to find it.
        list_scroll = VerticalScroll(id="live-list-scroll")
        await right.mount(list_scroll)
        rows = Vertical(id="live-list")
        await list_scroll.mount(rows)
        for attack_id in self.live_order:
            state = self.live_states.get(attack_id, "pending")
            color = LIVE_COLOR[state]
            glyph = SPINNER_FRAMES[self._spinner_frame] if state == "running" else LIVE_GLYPH[state]
            await rows.mount(Static(
                f"[{color}]{glyph}[/{color}]  {attack_id}  [{color}]{LIVE_LABEL[state]}[/{color}]",
                id=f"live-row-{attack_id}",
                classes="live-row",
            ))
        if done and self._last_full_suite_scored is not None:
            summary = self._last_full_suite_scored["summary"]
            with_cta = Horizontal(id="report-cta")
            await right.mount(with_cta)
            await with_cta.mount(Static(
                f"{summary['pass']}/{summary['total']} passed · "
                f"{summary['fail']} failed · {summary['error']} errors",
                id="report-summary",
            ))
            await with_cta.mount(Static("", id="report-spacer"))
            await with_cta.mount(Button("Generate Report", id="generate-report"))

    async def _set_live(self, order: list[str], label: str) -> None:
        self.live_order = order
        self.live_states = {aid: "pending" for aid in order}
        self.live_label = label
        self.right_mode = "live"
        self._start_spinner()
        await self._render_right()

    async def _update_live_row(self, attack_id: str, state: str, label: str | None = None) -> None:
        # Per-attack progress events fire up to 42 times during Fire All --
        # a full right-pane remove_children()+rebuild on every single one of
        # them is what caused the visible rapid-refresh/flicker. Update the
        # already-mounted widgets in place instead; only a real mode switch
        # (_set_live, or the one-time transition into "done") does a full
        # _render_right().
        self.live_states[attack_id] = state
        if label is not None:
            self.live_label = label

        if self.right_mode != "live":
            await self._render_right()
            return

        try:
            self.query_one("#live-progress-label", Static).update(self.live_label)
            total = len(self.live_order)
            current = sum(1 for s in self.live_states.values() if s != "pending")
            self.query_one("#live-progress-bar", ProgressBar).progress = current
            color = LIVE_COLOR[state]
            glyph = SPINNER_FRAMES[self._spinner_frame] if state == "running" else LIVE_GLYPH[state]
            self.query_one(f"#live-row-{attack_id}", Static).update(
                f"[{color}]{glyph}[/{color}]  {attack_id}  [{color}]{LIVE_LABEL[state]}[/{color}]"
            )
        except Exception:
            # Widgets not mounted yet (race with the initial _set_live render) --
            # fall back to a full render rather than silently dropping the update.
            await self._render_right()

    def _start_spinner(self) -> None:
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.09, self._spin)

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _spin(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(SPINNER_FRAMES)
        glyph = SPINNER_FRAMES[self._spinner_frame]
        for attack_id, state in self.live_states.items():
            if state != "running":
                continue
            try:
                row = self.query_one(f"#live-row-{attack_id}", Static)
            except Exception:
                continue
            row.update(
                f"[{ARC_AMBER}]{glyph}[/{ARC_AMBER}]  {attack_id}  "
                f"[{ARC_AMBER}]{LIVE_LABEL['running']}[/{ARC_AMBER}]"
            )

    # ---- firing ----------------------------------------------------------

    def _set_running(self, running: bool) -> None:
        self._batch_running = running
        for btn_id in ("fire-selected", "fire-all", "select-all", "select-none"):
            try:
                self.query_one(f"#{btn_id}", Button).disabled = running
            except Exception:
                pass

    @work(exclusive=True, thread=True)
    def _fire_selected_thread(self, attack_ids: list[str]) -> None:
        total = len(attack_ids)
        self.app.call_from_thread(self._set_running, True)
        self.app.call_from_thread(self._set_live, list(attack_ids), f"Fire selected — 0/{total}")

        session_expired = False
        try:
            for i, attack_id in enumerate(attack_ids, start=1):
                attack = self.attacks_by_id[attack_id]

                if attack.is_two_step:
                    # Fire Selected only ever sends one prompt and checks one
                    # status code -- it has no concept of seeding a case via
                    # /verify-case first, so a two-step attack can't run
                    # correctly here. Skip it visibly rather than silently
                    # mis-firing just the probe.
                    self.app.call_from_thread(
                        self._update_live_row, attack_id, "skip", f"Fire selected — {i}/{total}"
                    )
                    continue

                self.app.call_from_thread(self._update_live_row, attack_id, "running", f"Fire selected — {i}/{total}")

                fire_result = self.api_client.fire_attack(self.session, attack.prompt)
                result = grade(attack, fire_result)

                if result.grade == "SESSION_EXPIRED":
                    session_expired = True
                    break

                state = "pass" if result.grade == "PASS" else ("fail" if result.grade == "FAIL" else "skip")
                self.app.call_from_thread(self._update_live_row, attack_id, state, f"Fire selected — {i}/{total}")
                self.last_results[attack_id] = result.grade
        finally:
            self.app.call_from_thread(self._set_running, False)
            if session_expired:
                self.app.call_from_thread(self.app.action_logout, reason="Session expired (token timed out).")
            else:
                self.right_mode = "preview"
                self.app.call_from_thread(self._render_right)
                self.app.call_from_thread(self._render_left, self.query_one("#search-box", Input).value)

    @work(exclusive=True, thread=True)
    def _fire_all_thread(self) -> None:
        all_ids = [a.id for a in self.all_attacks]
        total = len(all_ids)
        self.app.call_from_thread(self._set_running, True)
        self.app.call_from_thread(self._set_live, all_ids, "Loading llm-redteam engine...")

        try:
            llm_redteam_dir = os.path.normpath(os.path.join(self.attacks_dir, ".."))
            bridge = RedTeamBridge(llm_redteam_dir)

            # Warn up front rather than let benign-control/isolation results
            # come back as a confusing wall of FAILs -- see scorer.py's
            # BACKEND_UNAVAILABLE grade for how those individual results are
            # still reported honestly either way.
            llm_online = bridge.runner.check_llm_health(self.session.base_url)
            if llm_online is False:
                self.app.call_from_thread(
                    self.app.notify,
                    "Benign-control and isolation checks will show BACKEND_UNAVAILABLE, "
                    "not PASS/FAIL. Gateway-only attacks are unaffected.",
                    title="AI backend (Ollama) is offline",
                    severity="warning",
                    timeout=10,
                )

            self.app.call_from_thread(
                self._update_live_row_label,
                f"Running full suite via llm-redteam — 0/{total} "
                "(benign-control checks can take 5-18s each, this is normal)",
            )

            def on_progress(i, total_count, attack_dict, result_dict):
                attack_id = attack_dict.get("id")
                if attack_id is None:
                    return
                state = "skip" if result_dict.get("skipped_reason") else "running"
                self.app.call_from_thread(
                    self._update_live_row, attack_id, state,
                    f"Running full suite via llm-redteam — {i}/{total_count}",
                )

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
                grade_value = r.get("grade", "--")
                state = "pass" if grade_value == "PASS" else ("fail" if grade_value == "FAIL" else "skip")
                self.app.call_from_thread(self._update_live_row, attack_id, state)
                self.last_results[attack_id] = grade_value

            self._last_full_suite_scored = scored_data
            summary = scored_data["summary"]
            self.right_mode = "done"
            self.app.call_from_thread(
                self._update_live_row_label,
                f"Done — {summary['pass']}/{summary['total']} passed.",
            )
            self.app.call_from_thread(self._render_right)

            if self.arc_dir:
                run_record = append_run(self.arc_dir, scored_data)
                update_findings(self.arc_dir, run_record, self.attacks_by_id)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._update_live_row_label, f"Full-suite run failed: {exc}")
        finally:
            self.app.call_from_thread(self._set_running, False)
            self.app.call_from_thread(self._render_left, self.query_one("#search-box", Input).value)

    async def _update_live_row_label(self, label: str) -> None:
        self.live_label = label
        if self.right_mode == "preview":
            await self._render_right()
            return
        try:
            self.query_one("#live-progress-label", Static).update(label)
        except Exception:
            await self._render_right()

    def _generate_report(self) -> None:
        if self._last_full_suite_scored is None:
            return
        self._write_and_open_report_thread()

    @work(exclusive=True, thread=True)
    def _write_and_open_report_thread(self) -> None:
        self.app.call_from_thread(self._update_live_row_label, "Generating report...")

        llm_redteam_dir = os.path.normpath(os.path.join(self.attacks_dir, ".."))
        bridge = RedTeamBridge(llm_redteam_dir)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = os.path.join(llm_redteam_dir, f"report_{timestamp}.html")

        try:
            path = bridge.generate_report(self._last_full_suite_scored, output_path)
            self.app.call_from_thread(self._update_live_row_label, f"Report written: {path}")
            webbrowser.open(f"file://{os.path.abspath(path)}")
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._update_live_row_label, f"Report generation failed: {exc}")
