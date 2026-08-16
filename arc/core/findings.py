"""
ARC Findings Tracker
----------------------
Turns ARC's run history from a flat log into what a red-team tool is
actually supposed to produce: a list of specific, named things currently
wrong (or previously wrong, now confirmed fixed) -- not a table of pass
counts. Built on top of the exact same per-run results map ops_log.py
already records; this module only interprets it differently.

One finding per attack_id that has ever failed at least once:
  - status "open": currently getting through. Created the first time an
    attack fails; seen_count increments on every subsequent failing run
    without resetting first_seen, so "open since X, seen in N runs" is
    honest about how long a gap has existed, not just that it exists now.
  - status "fixed": was open, then passed. confirmations increments on
    every subsequent passing run, so "confirmed N times since" reflects
    real repeated verification, not a single lucky pass.
  - A fixed finding that fails again flips back to "open" -- this *is*
    what a regression means here, replacing the old two-run diff_runs()
    comparison with something that persists across runs instead of only
    ever comparing the two most recent.

Storage: a single JSON file, findings.json, living next to ops_log.json
-- same simple local-JSON pattern, same directory, entirely additive.
"""
from __future__ import annotations

import json
import os


def _findings_path(arc_dir: str) -> str:
    return os.path.join(arc_dir, "findings.json")


def load_findings(arc_dir: str) -> dict:
    path = _findings_path(arc_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_findings(arc_dir: str, findings: dict) -> None:
    path = _findings_path(arc_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, ensure_ascii=False)


def update_findings(arc_dir: str, run_record: dict, attacks_by_id: dict | None = None) -> dict:
    """
    Interprets one completed run (the same record ops_log.append_run()
    already builds and returns -- timestamp + results map) against the
    persisted findings store, updating it in place. attacks_by_id (an
    id -> Attack map from core.attacks) is used only to capture a
    human-readable name/category at the moment a finding is first
    created -- later renames to the source YAML don't retroactively
    change an already-recorded finding, same as any other evidence record.
    Returns the updated findings dict.
    """
    findings = load_findings(arc_dir)
    timestamp = run_record["timestamp"]
    attacks_by_id = attacks_by_id or {}

    for attack_id, grade in run_record["results"].items():
        passed = grade == "PASS"
        existing = findings.get(attack_id)

        if existing is None:
            if passed:
                continue  # never failed -- nothing to track
            attack = attacks_by_id.get(attack_id)
            findings[attack_id] = {
                "attack_id": attack_id,
                "name": attack.name if attack else attack_id,
                "category": attack.category if attack else "",
                "status": "open",
                "first_seen": timestamp,
                "status_changed_at": timestamp,
                "seen_count": 1,
                "confirmations": 0,
                "history": [{"timestamp": timestamp, "grade": grade, "event": "opened"}],
            }
            continue

        entry = {"timestamp": timestamp, "grade": grade}

        if existing["status"] == "open":
            if passed:
                existing["status"] = "fixed"
                existing["status_changed_at"] = timestamp
                existing["confirmations"] = 0
                entry["event"] = "fixed"
            else:
                existing["seen_count"] += 1
                entry["event"] = "seen_again"
        else:  # status == "fixed"
            if passed:
                existing["confirmations"] += 1
                entry["event"] = "confirmed"
                entry["confirmation_number"] = existing["confirmations"]
            else:
                entry["event"] = "regressed"
                entry["previously_fixed_at"] = existing["status_changed_at"]
                existing["status"] = "open"
                existing["status_changed_at"] = timestamp
                existing["seen_count"] = existing.get("seen_count", 1) + 1

        existing["history"].append(entry)

    _save_findings(arc_dir, findings)
    return findings


def narrative_for_run(findings: dict, run_record: dict) -> tuple[str, bool]:
    """
    A one-line, human-readable summary of what happened to findings
    during this specific run -- e.g. "38 fired - JB-006 failed (new) -
    all others held" or "38 fired - DI-006 regressed: was fixed
    2026-08-14, failed again this run". Built by cross-referencing each
    finding's own tagged history entries against this run's timestamp,
    not by re-deriving transitions from raw grades after the fact.
    Returns (line, had_regression) so the caller can style regressions
    distinctly without the text needing its own embedded marker.
    """
    timestamp = run_record["timestamp"]
    total = run_record["total"]
    notable = []
    regressed = False

    for finding in findings.values():
        for entry in finding["history"]:
            if entry["timestamp"] != timestamp:
                continue
            event = entry.get("event")
            if event is None:
                continue  # recorded before history entries were tagged with an event type
            attack_id = finding["attack_id"]
            if event == "opened":
                notable.append(f"{attack_id} failed (new)")
            elif event == "regressed":
                regressed = True
                prev_at = entry.get("previously_fixed_at")
                prev_date = prev_at.split("T")[0] if prev_at else "an earlier run"
                notable.append(f"{attack_id} regressed: was fixed {prev_date}, failed again this run")
            elif event == "fixed":
                notable.append(f"{attack_id} fixed (first pass since opening)")
            elif event == "confirmed":
                n = entry.get("confirmation_number", 1)
                ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")
                notable.append(f"{attack_id} confirmed fixed ({ordinal} consecutive pass)")
            # "seen_again" isn't notable on its own -- it's an already-known
            # open finding still failing, folded into "all others held" below.

    if not notable:
        line = f"{total} fired - all attacks held"
    else:
        line = f"{total} fired - " + " - ".join(notable) + " - all others held"

    return line, regressed


def open_findings(findings: dict) -> list:
    items = [f for f in findings.values() if f["status"] == "open"]
    return sorted(items, key=lambda f: f["first_seen"])


def fixed_findings(findings: dict) -> list:
    items = [f for f in findings.values() if f["status"] == "fixed"]
    return sorted(items, key=lambda f: f["status_changed_at"], reverse=True)
