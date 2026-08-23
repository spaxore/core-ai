"""
ARC Canary Alerts Screen
-------------------------
Everything else in ARC either fires an attack and reads the target's
response (Attack Library) or reads locally-tracked findings (Findings).
Nothing shows what the honeytoken layer on the platform side catches --
a fabricated MSISDN that surfaces means an attack actually reached the
data, not just that it matched a text pattern. This screen polls
GET /admin/canary-events live and shows each trigger as it's recorded.

Two things are shown per trigger, deliberately kept separate since they
answer different questions:
  - certified/unverified -- did this specific request come through ARC's
    own mTLS-verified channel, or somewhere else (a real end-user app, an
    unknown source)? Computed server-side from which port the request
    actually arrived on (app/security/mtls.py), not something this
    screen can fake.
  - locked/exempt -- did the triggering account actually get locked as a
    consequence? Always "locked" unless the account is redteam_runner,
    which stays exempt so an authorized attack run doesn't interrupt
    itself (app/security/lockout.py's REDTEAM_EXEMPT_USERS).
Events are grouped into an Unverified section (shown first -- this is
the one worth a human's attention) and a Certified section (ARC's own
test traffic, expected noise), mirroring how Findings groups Open before
Fixed for the same reason: the thing that needs a reaction goes first.
"""
from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from core.header_bar import ArcHeader
from core.session_widget import SessionBar
from core.theme import ARC_AMBER, ARC_GREEN, ARC_RED, BORDER, PANEL_ALT, TEXT, TEXT_DIM

POLL_INTERVAL_SECONDS = 15


class CanaryAlertsScreen(Screen):
    CSS = f"""
    #session-bar {{
        height: 2;
        background: {PANEL_ALT};
        color: {TEXT_DIM};
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    #canary-body {{
        width: 100%;
    }}
    #canary-toolbar {{
        height: 3;
        align: left middle;
        padding: 0 2;
        margin-top: 1;
    }}
    #canary-summary {{
        width: auto;
        content-align: left middle;
    }}
    #canary-toolbar-right {{
        dock: right;
        width: auto;
        height: 3;
        align: right middle;
    }}
    #canary-live {{
        width: auto;
        height: 3;
        content-align: right middle;
        color: {TEXT_DIM};
        padding: 0 2;
    }}
    #refresh {{
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
    #canary-note {{
        height: auto;
        color: {TEXT_DIM};
        text-style: italic;
        padding: 1 2;
        border-bottom: solid {BORDER};
        border-left: solid {BORDER} 60%;
    }}
    #unverified-list, #certified-list {{
        height: 1fr;
    }}
    .section-header {{
        height: 3;
        content-align: left middle;
        text-style: bold;
        padding: 1 2;
        margin-top: 1;
    }}
    .section-header.-unverified {{
        color: {ARC_RED};
        background: {ARC_RED} 6%;
    }}
    .section-header.-certified {{
        color: {ARC_GREEN};
        background: {PANEL_ALT};
    }}
    .canary-row {{
        height: 9;
        align: left top;
        padding: 1 2 0 2;
        border-bottom: solid {TEXT} 8%;
    }}
    .canary-row.-unverified {{
        border-left: solid {ARC_RED};
        background: {ARC_RED} 3%;
    }}
    .canary-dot {{
        width: 3;
        height: 4;
        padding-top: 2;
        content-align: left top;
    }}
    .canary-dot.-unverified {{
        color: {ARC_RED};
    }}
    .canary-dot.-certified {{
        color: {TEXT_DIM};
    }}
    .canary-text {{
        width: 1fr;
        height: 4;
        padding-top: 2;
        content-align: left top;
        text-align: left;
    }}
    .canary-right {{
        width: 26;
        height: 7;
    }}
    .pill-wrap {{
        width: 100%;
        height: 3;
        align: right middle;
    }}
    .pill-wrap.-bottom {{
        margin-top: 1;
    }}
    .status-pill {{
        width: auto;
        min-width: 0;
        height: 3;
        min-height: 0;
        padding: 0 1;
        border: solid {TEXT_DIM};
        content-align: center middle;
        text-align: center;
        text-style: bold;
    }}
    .status-pill.-certified {{
        background: {ARC_GREEN} 20%;
        color: {ARC_GREEN};
        border: solid {ARC_GREEN};
    }}
    .status-pill.-uncertified {{
        background: {ARC_AMBER} 20%;
        color: {ARC_AMBER};
        border: solid {ARC_AMBER};
    }}
    /* No shared fixed width here -- the mockup never forces LOCKED and
       EXEMPT to match sizes. Each badge auto-sizes to its own word, same
       as the pill above it: LOCKED is naturally wider ("ACCOUNT LOCKED"
       is a long, alarming phrase), EXEMPT is naturally smaller ("EXEMPT"
       is short and meant to read as quiet/secondary). */
    .status-pill.-locked {{
        background: {ARC_RED} 20%;
        color: {ARC_RED};
        border: solid {ARC_RED};
    }}
    .status-pill.-exempt {{
        background: {TEXT_DIM} 15%;
        color: {TEXT_DIM};
        border: solid {TEXT_DIM};
    }}
    #empty-unverified {{
        height: 3;
        content-align: center middle;
        text-align: center;
    }}
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, api_client, session):
        super().__init__()
        self.api_client = api_client
        self.session = session
        self._live_tick = False

    def compose(self) -> ComposeResult:
        yield ArcHeader(on_back=self.action_go_back)
        yield SessionBar(self.session, id="session-bar")
        with Vertical(id="canary-body"):
            with Horizontal(id="canary-toolbar"):
                yield Static("[b]Canary Alerts[/b]  loading...", id="canary-summary")
                with Horizontal(id="canary-toolbar-right"):
                    yield Static("", id="canary-live")
                    yield Button("Refresh", id="refresh")
            yield Static(
                f"A honeytoken (MSISDN 21600000000) appearing in an investigation means a "
                f"request actually reached the CDR data -- a near-certain signal, independent "
                f"of what the Gateway let through.",
                id="canary-note",
            )
            yield Static("UNVERIFIED — UNKNOWN SOURCE", classes="section-header -unverified")
            yield VerticalScroll(id="unverified-list")
            yield Static("CERTIFIED — ARC TEST TRAFFIC", classes="section-header -certified")
            yield VerticalScroll(id="certified-list")

    def on_mount(self) -> None:
        self._poll_thread()
        self.set_interval(POLL_INTERVAL_SECONDS, self._poll_thread)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            self._poll_thread()

    @work(exclusive=True, thread=True)
    def _poll_thread(self) -> None:
        try:
            events = self.api_client.get_canary_events(self.session, limit=50)
            error = None
        except Exception as exc:
            events = []
            error = str(exc)
        self.app.call_from_thread(self._render_alerts, events, error)

    async def _render_alerts(self, events: list, error: str | None) -> None:
        # Real, timer-driven pulse (toggled once per actual poll, not a
        # decorative CSS animation) -- honest about the 5s cadence rather
        # than implying a continuous live stream.
        self._live_tick = not self._live_tick
        live = self.query_one("#canary-live", Static)
        dot_color = ARC_RED if self._live_tick else TEXT_DIM
        live.update(f"[{dot_color}]●[/{dot_color}] updates {POLL_INTERVAL_SECONDS}s")

        summary = self.query_one("#canary-summary", Static)
        if error is not None:
            summary.update(f"[b]Canary Alerts[/b]  [{ARC_RED}]poll failed: {error}[/{ARC_RED}]")
            return

        unverified = sorted((e for e in events if not e.get("certified")),
                             key=lambda e: e.get("created_at") or "", reverse=True)
        certified = sorted((e for e in events if e.get("certified")),
                            key=lambda e: e.get("created_at") or "", reverse=True)

        summary.update(
            f"[b]Canary Alerts[/b]   [{ARC_RED}]{len(unverified)} unverified[/{ARC_RED}] "
            f"[{TEXT_DIM}]·[/{TEXT_DIM}] [{ARC_GREEN}]{len(certified)} certified[/{ARC_GREEN}]"
        )

        # Two independent scroll containers now (one per section) so
        # scrolling through a long Unverified list doesn't push the
        # Certified section out of view, and vice versa -- each keeps its
        # own scroll position across refreshes, same save/restore approach
        # as before, just applied per-container instead of once.
        unverified_container = self.query_one("#unverified-list", VerticalScroll)
        certified_container = self.query_one("#certified-list", VerticalScroll)
        unverified_scroll_y = unverified_container.scroll_y
        certified_scroll_y = certified_container.scroll_y

        await unverified_container.remove_children()
        if not unverified:
            await unverified_container.mount(Static(
                f"[{ARC_GREEN}]✓ No unverified events[/{ARC_GREEN}]\n"
                f"[{TEXT_DIM}]All recent activity came through the certified ARC channel.[/{TEXT_DIM}]",
                id="empty-unverified",
            ))
        else:
            for event in unverified:
                await self._mount_row(unverified_container, event, certified=False)

        await certified_container.remove_children()
        for event in certified:
            await self._mount_row(certified_container, event, certified=True)

        # Setting scroll_y immediately isn't reliable on its own -- Textual
        # recomputes virtual_size on the next layout pass (after all these
        # mounts), which can silently reset/clamp scroll_y again after this
        # line runs. call_after_refresh schedules the restore for AFTER
        # that layout pass completes, which is what actually sticks.
        unverified_container.scroll_y = unverified_scroll_y
        certified_container.scroll_y = certified_scroll_y

        def _restore_scroll() -> None:
            unverified_container.scroll_y = unverified_scroll_y
            certified_container.scroll_y = certified_scroll_y

        self.call_after_refresh(_restore_scroll)

    async def _mount_row(self, container: VerticalScroll, event: dict, certified: bool) -> None:
        state = "-certified" if certified else "-unverified"
        row = Horizontal(classes=f"canary-row {state}")
        await container.mount(row)
        await row.mount(Static("●" if certified else "▲", classes=f"canary-dot {state}"))

        category = event.get("category") or "?"
        msisdn = event.get("msisdn") or "?"
        headline = f"[b]{event.get('username')}[/b] [{TEXT_DIM}]({event.get('role')})[/{TEXT_DIM}] — category [b]{category}[/b]"
        meta = f"[{TEXT_DIM}]{event.get('created_at')} · MSISDN {msisdn} · IP {event.get('ip_address')}[/{TEXT_DIM}]"
        await row.mount(Static(f"{headline}\n{meta}", classes="canary-text"))

        # Each pill gets its own single-child wrapper, individually
        # right-aligned -- Textual's `align: right` on a shared parent with
        # TWO differently-sized children doesn't recompute per-child (a
        # real framework quirk, confirmed by direct measurement: both
        # children landed at the same x, so only the widest one actually
        # reached the right edge). One wrapper per pill sidesteps it.
        right = Vertical(classes="canary-right")
        await row.mount(right)

        top_wrap = Horizontal(classes="pill-wrap")
        await right.mount(top_wrap)
        if certified:
            await top_wrap.mount(Static("CERTIFIED", classes="status-pill -certified"))
        else:
            await top_wrap.mount(Static("UNVERIFIED", classes="status-pill -uncertified"))

        bottom_wrap = Horizontal(classes="pill-wrap -bottom")
        await right.mount(bottom_wrap)
        if event.get("status") == "exempt":
            await bottom_wrap.mount(Static("EXEMPT", classes="status-pill -exempt"))
        else:
            await bottom_wrap.mount(Static("ACCOUNT LOCKED", classes="status-pill -locked"))
