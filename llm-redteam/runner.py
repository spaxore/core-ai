"""
LLM Red-Teaming Framework - Runner

Loads every YAML file in attacks/, authenticates against the target
Secure TT AI Agent instance, and fires each attack prompt at /classify
over HTTP. Records the raw result for scorer.py to grade.

This tool is intentionally decoupled from the TT codebase: it only ever
talks to the Gateway over HTTP, exactly the way a real attacker would.
It imports nothing from the app/ package.

CLI usage (unchanged):
    python runner.py --base-url http://127.0.0.1:8000 --username ikbal --password ChangeMe123!

Programmatic usage (new -- lets ARC reuse its own live session instead
of logging in a second time):
    from runner import run
    results = run(base_url, attacks_dir=attacks_dir, endpoint="/classify", token=existing_token)
"""

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests
import yaml


def load_attack_library(attacks_dir: str) -> list[dict]:
    """Load every YAML file in attacks_dir into a flat list of attack dicts,
    each tagged with its source category/owasp metadata."""
    all_attacks = []
    yaml_files = sorted(glob.glob(os.path.join(attacks_dir, "*.yaml")))

    if not yaml_files:
        print(f"WARNING: no YAML files found in {attacks_dir}")
        return all_attacks

    for filepath in yaml_files:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "attacks" not in data:
            print(f"WARNING: {filepath} has no 'attacks' key, skipping")
            continue

        category = data.get("category", "uncategorized")
        owasp = data.get("owasp", "unspecified")

        for attack in data["attacks"]:
            attack["category"] = category
            attack["owasp"] = owasp
            attack["source_file"] = os.path.basename(filepath)
            all_attacks.append(attack)

    return all_attacks


def login(base_url: str, username: str, password: str) -> str:
    """Authenticate against /login and return the bearer token."""
    resp = requests.post(
        f"{base_url}/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"FATAL: login failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    token = resp.json().get("access_token")
    if not token:
        print("FATAL: login succeeded but no access_token in response")
        sys.exit(1)

    return token


LOCKOUT_MARKERS = ("temporarily locked", "security violations")


def is_lockout_response(status_code: int, response_body: Optional[dict]) -> bool:
    """Distinguish 'account auto-locked' from a genuine gateway block. Both
    return 403, but only one means the target's Auto-Lock kicked in mid-run -
    which would otherwise silently corrupt every subsequent result, since
    they'd all read as 403/blocked for the wrong reason."""
    if status_code != 403 or not response_body:
        return False
    detail = str(response_body.get("detail", "")).lower()
    return any(marker in detail for marker in LOCKOUT_MARKERS)


def fire_attack(base_url: str, token: str, prompt: str, endpoint: str = "/classify", timeout: int = 90) -> dict:
    """Send a single attack prompt to the Gateway and capture the raw result."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    started = time.time()
    try:
        resp = requests.post(
            f"{base_url}{endpoint}",
            headers=headers,
            json={"text": prompt},
            timeout=timeout,
        )
        elapsed_ms = round((time.time() - started) * 1000, 1)
        body = _safe_json(resp)
        return {
            "status_code": resp.status_code,
            "response_body": body,
            "elapsed_ms": elapsed_ms,
            "error": None,
            "locked_out": is_lockout_response(resp.status_code, body),
        }
    except requests.RequestException as e:
        elapsed_ms = round((time.time() - started) * 1000, 1)
        return {
            "status_code": None,
            "response_body": None,
            "elapsed_ms": elapsed_ms,
            "error": str(e),
            "locked_out": False,
        }


def _safe_json(resp) -> Optional[dict]:
    try:
        return resp.json()
    except ValueError:
        return {"raw_text": resp.text[:500]}


def run(base_url: str, username: str = None, password: str = None, attacks_dir: str = None,
        endpoint: str = "/classify", timeout: int = 90, token: str = None,
        progress_callback=None) -> list[dict]:
    """
    Runs the full attack library against base_url.

    Auth: either pass token directly (reuses an existing session -- this
    is how ARC calls in, avoiding a second login), or pass
    username/password and this function will log in itself (CLI usage).
    Exactly one of the two must be supplied.

    progress_callback, if given, is called as
    progress_callback(i, total, attack, outcome) after each attack fires --
    lets a caller (like ARC) update a live UI without this function
    needing to know anything about Textual or any other UI framework.
    """
    if token is None and (username is None or password is None):
        raise ValueError("run() requires either a token, or both username and password")

    print(f"Loading attack library from {attacks_dir} ...")
    attacks = load_attack_library(attacks_dir)
    print(f"Loaded {len(attacks)} attacks across "
          f"{len(set(a['category'] for a in attacks))} categories.")

    # Run benign controls first, so we get a clean false-positive baseline
    # before any real attack has a chance to trip Auto-Lock.
    attacks.sort(key=lambda a: 0 if a["category"] == "control_benign" else 1)

    if token is None:
        print(f"Authenticating as '{username}' against {base_url} ...")
        token = login(base_url, username, password)
        print("Authenticated. Beginning run.\n")
    else:
        print("Reusing existing session token. Beginning run.\n")

    results = []
    locked_out_at = None

    for i, attack in enumerate(attacks, 1):
        if locked_out_at is not None:
            skipped = {
                **attack,
                "status_code": None,
                "response_body": None,
                "elapsed_ms": 0.0,
                "error": None,
                "locked_out": False,
                "skipped_reason": f"Skipped: target account was auto-locked at attack #{locked_out_at}",
                "run_at": datetime.now(timezone.utc).isoformat(),
            }
            results.append(skipped)
            if progress_callback:
                progress_callback(i, len(attacks), attack, skipped)
            continue

        print(f"[{i}/{len(attacks)}] {attack.get('id', '?')} - {attack.get('name', '?')} ...", end=" ")
        outcome = fire_attack(base_url, token, attack["prompt"], endpoint, timeout)
        result = {
            **attack,
            **outcome,
            "run_at": datetime.now(timezone.utc).isoformat(),
        }
        results.append(result)
        print(f"status={outcome['status_code']} ({outcome['elapsed_ms']}ms)")

        if progress_callback:
            progress_callback(i, len(attacks), attack, result)

        if outcome.get("locked_out"):
            locked_out_at = i
            print(f"\n  !! Target account got auto-locked at attack #{i}.")
            print("  !! Remaining attacks will be marked SKIPPED, not scored as pass/fail.")
            print("  !! Unlock the account and rerun to get a complete result set:")
            print("     UPDATE TT_AI_USERS SET LOCKED_UNTIL = NULL WHERE USERNAME = '<user>'; COMMIT;\n")

    return results


def main():
    parser = argparse.ArgumentParser(description="LLM Red-Teaming Framework runner")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--attacks-dir", default=os.path.join(os.path.dirname(__file__), "attacks"))
    parser.add_argument("--endpoint", default="/classify", choices=["/classify", "/investigate"])
    parser.add_argument("--output", default="results.json")
    parser.add_argument("--timeout", type=int, default=90,
                         help="Per-request HTTP timeout in seconds (local LLM inference can be slow)")
    args = parser.parse_args()

    results = run(args.base_url, username=args.username, password=args.password,
                  attacks_dir=args.attacks_dir, endpoint=args.endpoint, timeout=args.timeout)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nRun complete. Raw results written to {args.output}")
    print("Next: python scorer.py --input results.json --output scored.json")


if __name__ == "__main__":
    main()
