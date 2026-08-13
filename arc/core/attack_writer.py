"""
ARC Attack Writer
------------------
Writes a newly authored attack into the shared attacks/ YAML library --
the exact same files llm-redteam/runner.py and ARC's own library loader
already read. No new storage format, no duplication: authoring an
attack here makes it available to both tools immediately, with zero
code changes to either.

Kept separate from screens/authoring.py (the UI) so this logic is
independently testable without spinning up a Textual app.
"""
from __future__ import annotations

import os
import re

import yaml

VALID_SEVERITIES = {"critical", "high", "medium", "low", "n/a"}
VALID_EXPECTED = {"blocked", "allowed"}


class AttackWriteError(Exception):
    """Raised for any validation failure before anything is written to disk."""


def validate_attack(attack_id: str, name: str, prompt: str, category: str,
                     severity: str, expected: str) -> None:
    if not attack_id or not attack_id.strip():
        raise AttackWriteError("Attack ID is required.")
    if not re.match(r"^[A-Za-z0-9_\-]+$", attack_id.strip()):
        raise AttackWriteError("Attack ID may only contain letters, numbers, hyphens, underscores.")
    if not name or not name.strip():
        raise AttackWriteError("Name is required.")
    if not prompt or not prompt.strip():
        raise AttackWriteError("Prompt is required.")
    if not category or not category.strip():
        raise AttackWriteError("Category is required.")
    if severity.lower() not in VALID_SEVERITIES:
        raise AttackWriteError(f"Severity must be one of: {', '.join(sorted(VALID_SEVERITIES))}")
    if expected.lower() not in VALID_EXPECTED:
        raise AttackWriteError(f"Expected must be one of: {', '.join(sorted(VALID_EXPECTED))}")


def write_attack(
    attacks_dir: str,
    attack_id: str,
    name: str,
    prompt: str,
    category: str,
    severity: str,
    expected: str,
    owasp: str = "",
    notes: str = "",
) -> str:
    """
    Appends a new attack to the YAML file for `category` (creating the
    file if it doesn't exist yet). Returns the path written to.

    Raises AttackWriteError on validation failure or if the attack_id
    already exists anywhere in the library (IDs must stay unique across
    files, since llm-redteam's scorer and ARC's own table both key
    results by ID).
    """
    validate_attack(attack_id, name, prompt, category, severity, expected)
    attack_id = attack_id.strip()
    category_slug = _slugify(category)
    target_path = os.path.join(attacks_dir, f"{category_slug}.yaml")

    _ensure_id_is_unique(attacks_dir, attack_id)

    if os.path.exists(target_path):
        with open(target_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        if "attacks" not in raw or raw["attacks"] is None:
            raw["attacks"] = []
    else:
        raw = {
            "category": category_slug,
            "owasp": owasp.strip() if owasp.strip() else "N/A - custom attack",
            "description": f"Custom attacks authored via ARC for the '{category_slug}' category.",
            "attacks": [],
        }

    new_attack = {
        "id": attack_id,
        "name": name.strip(),
        "prompt": prompt.strip(),
        "severity": severity.lower(),
        "expected": expected.lower(),
    }
    if notes.strip():
        new_attack["notes"] = notes.strip()

    raw["attacks"].append(new_attack)

    with open(target_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True, default_flow_style=False)

    return target_path


def _ensure_id_is_unique(attacks_dir: str, attack_id: str) -> None:
    import glob

    for path in glob.glob(os.path.join(attacks_dir, "*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        for a in raw.get("attacks", []) or []:
            if a.get("id") == attack_id:
                raise AttackWriteError(
                    f"Attack ID '{attack_id}' already exists in {os.path.basename(path)}. IDs must be unique."
                )


def _slugify(category: str) -> str:
    slug = category.strip().lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    return slug or "custom"
