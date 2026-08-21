"""
ARC Playbook Picker
---------------------
A playbook is a named, ordered sequence of existing attacks (referenced
by id, not redefined) that tells a coherent attacker story -- recon,
escalate, exfiltrate -- rather than a flat batch. This screen lists what
llm-redteam/playbooks/*.yaml defines; the actual live run view is
PlaybookRunScreen (screens/playbook_run.py).
"""
from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from core.header_bar import ArcHeader
from core.redteam_bridge import RedTeamBridge
from core.session_widget import SessionBar
from core.theme import ARC_BLUE, BORDER, PANEL_ALT, TEXT, TEXT_DIM


class PlaybookListScreen(Screen):
    CSS = f"""
    #session-bar {{
        height: 2;
        background: {PANEL_ALT};
        color: {TEXT_DIM};
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    #pb-caption {{
        height: 2;
        background: {PANEL_ALT};
        color: {TEXT_DIM};
        padding: 0 1;
        border-bottom: solid {BORDER};
    }}
    Button.pb-row {{
        width: 100%;
        height: 4;
        background: transparent;
        color: {TEXT};
        content-align: left top;
        text-align: left;
        text-style: none;
        border: none;
        border-bottom: solid {TEXT} 8%;
        padding: 1 0 0 3;
    }}
    Button.pb-row:focus {{
        background: {ARC_BLUE} 8%;
        border-left: solid {ARC_BLUE};
        padding: 1 0 0 2;
        text-style: none;
    }}
    Button.pb-row:hover {{
        background: {TEXT} 2%;
    }}
    #pb-empty {{
        padding: 2 3;
        color: {TEXT_DIM};
    }}
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, session, attacks_dir: str, arc_dir: str):
        super().__init__()
        self.session = session
        self.attacks_dir = attacks_dir
        self.arc_dir = arc_dir
        self.playbooks: list[dict] = []

    def compose(self) -> ComposeResult:
        yield ArcHeader(on_back=self.action_go_back)
        yield SessionBar(self.session, id="session-bar")
        yield Static("Playbooks -- ordered attack scenarios (select to run)", id="pb-caption")
        yield Vertical(id="pb-list")

    def on_mount(self) -> None:
        self._load_playbooks()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def _load_playbooks(self) -> None:
        llm_redteam_dir = os.path.normpath(os.path.join(self.attacks_dir, ".."))
        playbooks_dir = os.path.join(llm_redteam_dir, "playbooks")
        bridge = RedTeamBridge(llm_redteam_dir)
        self.playbooks = bridge.load_playbooks(playbooks_dir) if os.path.isdir(playbooks_dir) else []

        container = self.query_one("#pb-list", Vertical)
        if not self.playbooks:
            container.mount(Static(
                "No playbooks found. Add one as a *.yaml file under llm-redteam/playbooks/.",
                id="pb-empty",
            ))
            return

        for i, pb in enumerate(self.playbooks):
            step_count = len(pb.get("steps", []))
            container.mount(Button(
                f"[b]{pb.get('name', pb.get('id', '?'))}[/b]\n"
                f"    [dim]{pb.get('description', '').strip()}[/dim]\n"
                f"    [dim]{step_count} step(s)[/dim]",
                id=f"go-pb-{i}",
                classes="pb-row",
            ))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("go-pb-"):
            index = int(event.button.id.removeprefix("go-pb-"))
            playbook = self.playbooks[index]
            from screens.playbook_run import PlaybookRunScreen
            self.app.push_screen(PlaybookRunScreen(self.session, self.attacks_dir, self.arc_dir, playbook))
