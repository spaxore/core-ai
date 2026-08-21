"""
ARC Red-Team Bridge
---------------------
"Fire All" in ARC is not a separate reimplementation of the attack
runner -- it IS the llm-redteam engine, called in-process with ARC's
existing session token instead of logging in again. This is the
deliberate architectural choice behind ARC and llm-redteam: one tested
engine, two front doors. The interactive path (this bridge, used by
ARC's Library screen) and the CLI path (llm-redteam/runner.py run
directly) both call the exact same run()/score_all()/generate_html()
functions -- nothing is duplicated, nothing can drift out of sync.

"Fire selected" deliberately does NOT go through this bridge -- it
stays on ARC's own lightweight core/api_client.py + core/grading.py
path, since firing a handful of hand-picked attacks during iteration
is a different job than running the canonical full-suite validation.

llm-redteam is expected to sit as a sibling folder next to arc/, e.g.
C:/Users/ikbal/arc/ and C:/Users/ikbal/llm-redteam/ side by side.
"""
from __future__ import annotations

import importlib.util
import os
import sys


def _load_llm_redteam_modules(llm_redteam_dir: str):
    """
    Imports runner.py, scorer.py, and report_generator.py directly from
    the llm-redteam folder as real Python modules -- not a subprocess
    call. This keeps everything in-process (so ARC's live UI can update
    as results come in via a progress callback) while still reusing the
    exact same, already-tested code as the standalone CLI tool.
    """
    if llm_redteam_dir not in sys.path:
        sys.path.insert(0, llm_redteam_dir)

    def _import(name, filename):
        path = os.path.join(llm_redteam_dir, filename)
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    runner = _import("llm_redteam_runner", "runner.py")
    scorer = _import("llm_redteam_scorer", "scorer.py")
    report_generator = _import("llm_redteam_report_generator", "report_generator.py")
    return runner, scorer, report_generator


class RedTeamBridge:
    def __init__(self, llm_redteam_dir: str):
        self.llm_redteam_dir = llm_redteam_dir
        self.runner, self.scorer, self.report_generator = _load_llm_redteam_modules(llm_redteam_dir)

    def run_full_suite(self, base_url: str, token: str, attacks_dir: str,
                        progress_callback=None) -> list[dict]:
        """Fires the entire shared attack library using llm-redteam's own
        run() -- same benign-first ordering, same lockout-awareness, same
        scoring logic the canonical report already uses."""
        return self.runner.run(
            base_url=base_url,
            attacks_dir=attacks_dir,
            token=token,
            progress_callback=progress_callback,
        )

    def load_playbooks(self, playbooks_dir: str) -> list[dict]:
        return self.runner.load_playbooks(playbooks_dir)

    def run_playbook(self, base_url: str, token: str, playbook: dict, attacks_dir: str,
                      progress_callback=None) -> list[dict]:
        """
        Same in-process, one-engine reuse as run_full_suite -- fires the
        playbook's steps via llm-redteam's own fire_playbook(). Deliberately
        loads its own raw-dict attack library from attacks_dir here rather
        than accepting ARC's attacks_by_id: fire_playbook() dict-unpacks
        each attack (**attack), which works on the plain dicts llm-redteam's
        own load_attack_library() produces but not on ARC's Attack
        dataclass instances (core/attacks.py) -- same reason run_full_suite
        never takes ARC's attack objects either, it loads its own copy.
        """
        attacks_by_id = {a["id"]: a for a in self.runner.load_attack_library(attacks_dir)}
        return self.runner.fire_playbook(
            base_url=base_url,
            token=token,
            playbook=playbook,
            attacks_by_id=attacks_by_id,
            progress_callback=progress_callback,
        )

    def score(self, results: list[dict]) -> dict:
        scored = self.scorer.score_all(results)
        summary = self.scorer.summarize(scored)
        return {"summary": summary, "results": scored}

    def generate_report(self, scored_data: dict, output_path: str) -> str:
        html = self.report_generator.generate_html(scored_data)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return output_path
