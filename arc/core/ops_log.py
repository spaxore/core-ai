"""
ARC Ops Log
-------------
Tracks ARC own attack-run history over time -- entirely local, entirely
about ARC own results. Never reads the target audit log or database;
this is the attacker own record of engagements, not a view into the
target internal logging. Every completed Fire All (full-suite, via
core/redteam_bridge.py) run appends one record here.

Storage: a single JSON file, ops_log.json, living next to arc.py. Each
record captures the run summary counts plus a full attack_id -> grade
map, so later runs can be diffed against earlier ones to show what
changed -- gaps closed, or regressions introduced.
"""
from __future__ import annotations

import json
import os
from datetime import datetime


def _log_path(arc_dir: str) -> str:
    return os.path.join(arc_dir, "ops_log.json")


def load_history(arc_dir: str) -> list:
    path = _log_path(arc_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def append_run(arc_dir: str, scored_data: dict) -> dict:
    """Appends one run record built from a completed Fire All run's
    scored output (the same shape RedTeamBridge.score() returns).
    Returns the record that was appended."""
    summary = scored_data["summary"]
    results_map = {
        r["id"]: r["grade"]
        for r in scored_data["results"]
        if r.get("id") is not None
    }

    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total": summary["total"],
        "pass": summary["pass"],
        "fail": summary["fail"],
        "error": summary["error"],
        "skipped": summary.get("skipped", 0),
        "pass_rate": (summary["pass"] / summary["total"] * 100) if summary["total"] else 0.0,
        "results": results_map,
    }

    history = load_history(arc_dir)
    history.append(record)

    path = _log_path(arc_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    return record


def diff_runs(prev, curr: dict) -> dict:
    """
    Compares curr against prev (the immediately preceding run, or None
    if curr is the first run ever).
    "improved" = anything that moved TO PASS from something else.
    "regressed" = anything that moved AWAY from PASS.
    "new_attacks" = IDs present in curr but not in prev.
    """
    if prev is None:
        return {"improved": [], "regressed": [], "new_attacks": list(curr["results"].keys())}

    improved = []
    regressed = []
    new_attacks = []

    prev_results = prev["results"]
    curr_results = curr["results"]

    for attack_id, new_grade in curr_results.items():
        if attack_id not in prev_results:
            new_attacks.append(attack_id)
            continue
        old_grade = prev_results[attack_id]
        if old_grade == new_grade:
            continue
        if new_grade == "PASS" and old_grade != "PASS":
            improved.append((attack_id, old_grade, new_grade))
        elif old_grade == "PASS" and new_grade != "PASS":
            regressed.append((attack_id, old_grade, new_grade))

    return {"improved": improved, "regressed": regressed, "new_attacks": new_attacks}
