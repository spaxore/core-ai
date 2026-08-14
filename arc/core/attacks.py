"""
ARC Attack Library Loader
--------------------------
Reads the exact same YAML attack files llm-redteam/runner.py already
consumes. ARC does not maintain its own copy of the attack corpus --
it points at the same attacks/ directory, so authoring a new attack
(by hand, or via ARC's future attack-builder form) makes it available
to both tools with zero duplication.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field

import yaml


@dataclass
class Attack:
    id: str
    name: str
    category: str
    owasp: str
    severity: str
    expected: str  # "blocked", "allowed", or "isolated" (two-step seed/probe)
    notes: str = ""
    # Single-shot attacks (the original, still-common shape) set prompt and
    # leave seed/probe None. Two-step attacks (e.g. retrieval_poisoning.yaml,
    # expected="isolated") set seed/probe instead and leave prompt None --
    # ARC's lightweight "Fire Selected" path can't run these (it only knows
    # how to send one prompt and check one status code), only "Fire All",
    # which calls llm-redteam's own run() and already understands both
    # shapes. See library.py's is_two_step() / _fire_selected_thread guard.
    prompt: str | None = None
    seed: dict | None = None
    probe: str | None = None

    @property
    def is_two_step(self) -> bool:
        return self.prompt is None and self.seed is not None


@dataclass
class AttackFile:
    category: str
    owasp: str
    description: str
    attacks: list[Attack] = field(default_factory=list)


def load_attack_library(attacks_dir: str) -> list[AttackFile]:
    """
    Loads every *.yaml file in attacks_dir. Each file represents one
    category (matching llm-redteam's existing convention: one YAML
    file per category, e.g. direct_injection.yaml, jailbreak.yaml).
    """
    files: list[AttackFile] = []
    for path in sorted(glob.glob(os.path.join(attacks_dir, "*.yaml"))):
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        category = raw.get("category", os.path.splitext(os.path.basename(path))[0])
        owasp = raw.get("owasp", "N/A")
        description = raw.get("description", "").strip()

        attacks = []
        for a in raw.get("attacks", []):
            raw_prompt = a.get("prompt")
            attacks.append(
                Attack(
                    id=a["id"],
                    name=a["name"],
                    prompt=raw_prompt.strip() if isinstance(raw_prompt, str) else raw_prompt,
                    seed=a.get("seed"),
                    probe=a.get("probe").strip() if isinstance(a.get("probe"), str) else a.get("probe"),
                    category=category,
                    owasp=owasp,
                    severity=a.get("severity", "n/a"),
                    expected=a.get("expected", "blocked"),
                    notes=a.get("notes", "").strip() if a.get("notes") else "",
                )
            )
        files.append(AttackFile(category=category, owasp=owasp, description=description, attacks=attacks))
    return files


def flatten(files: list[AttackFile]) -> list[Attack]:
    """Convenience: every attack across every category, as one flat list."""
    out: list[Attack] = []
    for f in files:
        out.extend(f.attacks)
    return out
