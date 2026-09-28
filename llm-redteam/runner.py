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

# mTLS client identity for ARC's certified channel (see app/security/mtls.py
# and scripts/generate_mtls_certs.sh on the platform side). Read from env
# vars rather than added as a parameter threaded through run()/fire_playbook/
# fire_attack/fire_request -- this tool stays a decoupled HTTP client either
# way (CLI usage: set the vars before invoking; ARC's in-process bridge sets
# them at startup from its own --client-cert/--client-key/--ca-cert args
# before this module is ever imported).
_session = requests.Session()
_client_cert = os.getenv("ARC_CLIENT_CERT")
_client_key = os.getenv("ARC_CLIENT_KEY")
_ca_cert = os.getenv("ARC_CA_CERT")
if _client_cert and _client_key:
    _session.cert = (_client_cert, _client_key)
if _ca_cert:
    _session.verify = _ca_cert


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
    resp = _session.post(
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


def check_llm_health(base_url: str, timeout: int = 10) -> Optional[bool]:
    """Checks the platform's /health/llm before firing attacks that depend
    on it (benign controls, retrieval-poisoning isolation checks -- see
    scorer.py's BACKEND_UNAVAILABLE grade). /health/llm is unauthenticated,
    so this needs no token. Returns True/False for a real answer, or None
    if the platform itself couldn't be reached at all -- a more
    fundamental problem than Ollama specifically, which the run below
    will surface immediately on the first attack anyway."""
    try:
        resp = _session.get(f"{base_url}/health/llm", timeout=timeout)
        if resp.status_code != 200:
            return None
        return bool(resp.json().get("llm_online"))
    except requests.RequestException:
        return None


LOCKOUT_MARKERS = ("temporarily locked", "security violations", "account disabled")


def is_lockout_response(status_code: int, response_body: Optional[dict]) -> bool:
    """Distinguish 'account auto-locked' from a genuine gateway block. Both
    return 403, but only one means the target's Auto-Lock kicked in mid-run -
    which would otherwise silently corrupt every subsequent result, since
    they'd all read as 403/blocked for the wrong reason."""
    if status_code != 403 or not response_body:
        return False
    detail = str(response_body.get("detail", "")).lower()
    return any(marker in detail for marker in LOCKOUT_MARKERS)


def fire_request(base_url: str, token: str, endpoint: str, body: dict, timeout: int = 90) -> dict:
    """Send a single POST request and capture the raw result. Endpoint-agnostic --
    used directly for /verify-case seed submissions and, via fire_attack below,
    for the standard /classify and /investigate attack path."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    started = time.time()
    try:
        resp = _session.post(
            f"{base_url}{endpoint}",
            headers=headers,
            json=body,
            timeout=timeout,
        )
        elapsed_ms = round((time.time() - started) * 1000, 1)
        response_body = _safe_json(resp)
        return {
            "status_code": resp.status_code,
            "response_body": response_body,
            "elapsed_ms": elapsed_ms,
            "error": None,
            "locked_out": is_lockout_response(resp.status_code, response_body),
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


def _verify_case_body(prompt: str, attack: dict) -> dict:
    """/verify-case takes a different shape than /classify and /investigate
    (complaint_text, category, msisdn, da_value instead of just text) -- an
    attack targeting this endpoint carries those extra fields under
    verify_category / verify_msisdn / verify_da_value so the YAML stays
    declarative rather than needing endpoint-specific code per attack."""
    return {
        "complaint_text": prompt,
        "category": attack.get("verify_category", "VOICE_EXPIRATION"),
        "msisdn": attack.get("verify_msisdn"),
        "da_value": attack.get("verify_da_value"),
    }


def fire_attack(base_url: str, token: str, prompt: str, attack: dict,
                 endpoint: str = "/classify", timeout: int = 90) -> dict:
    """Send a single attack prompt at the target endpoint and capture the raw
    result. Builds the right body shape for /verify-case automatically."""
    body = _verify_case_body(prompt, attack) if endpoint == "/verify-case" else {"text": prompt}
    return fire_request(base_url, token, endpoint, body, timeout)


def fire_seed_probe_attack(base_url: str, token: str, attack: dict,
                            probe_endpoint: str = "/classify", timeout: int = 90) -> dict:
    """
    Two-step attack for the case-memory retrieval path: first seeds a
    (seemingly legitimate) verified case via /verify-case -- exercising
    retrieval poisoning rather than direct Gateway evasion -- then fires an
    unrelated probe complaint at probe_endpoint to check whether the seed
    leaked into, or hijacked, the probe's own classification. Grading (see
    scorer.py's "isolated" branch) is based on the probe response only: the
    seed itself is expected to succeed (that's what makes it poisoning, not
    just another blocked prompt) unless the seed's own text independently
    trips the Gateway (see RP-001 in retrieval_poisoning.yaml, which relies
    on exactly that).
    """
    seed = attack["seed"]
    seed_body = {
        "complaint_text": seed["complaint_text"],
        "category": seed.get("category", "VOICE_EXPIRATION"),
        "msisdn": seed.get("msisdn"),
        "da_value": seed.get("da_value"),
    }
    seed_result = fire_request(base_url, token, "/verify-case", seed_body, timeout)

    probe_result = fire_request(base_url, token, probe_endpoint, {"text": attack["probe"]}, timeout)

    return {
        "seed_status_code": seed_result["status_code"],
        "seed_response_body": seed_result["response_body"],
        "seed_error": seed_result["error"],
        # Probe outcome is what gets graded -- keep the standard field names
        # (status_code, response_body, ...) so scorer.py and
        # report_generator.py don't need to know this was a two-step attack.
        **probe_result,
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

    llm_online = check_llm_health(base_url)
    if llm_online is False:
        print("=" * 72)
        print("WARNING: the AI backend (Ollama) is currently OFFLINE.")
        print("Benign-control and retrieval-poisoning-isolation attacks depend on")
        print("it and will come back HTTP 503, graded BACKEND_UNAVAILABLE rather")
        print("than PASS/FAIL. Gateway-only attacks (injection/jailbreak/")
        print("exfiltration/role-confusion/sql-injection-via-prompt) are blocked")
        print("before ever reaching the LLM and are unaffected.")
        print("=" * 72 + "\n")

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
                "skipped_reason": f"Skipped: target account was locked or disabled at attack #{locked_out_at}",
                "run_at": datetime.now(timezone.utc).isoformat(),
            }
            results.append(skipped)
            if progress_callback:
                progress_callback(i, len(attacks), attack, skipped)
            continue

        print(f"[{i}/{len(attacks)}] {attack.get('id', '?')} - {attack.get('name', '?')} ...", end=" ")
        if "seed" in attack:
            outcome = fire_seed_probe_attack(base_url, token, attack, endpoint, timeout)
        else:
            attack_endpoint = attack.get("target_endpoint", endpoint)
            outcome = fire_attack(base_url, token, attack["prompt"], attack, attack_endpoint, timeout)
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
            print(f"\n  !! Target account was locked or disabled at attack #{i}.")
            print("  !! Remaining attacks will be marked SKIPPED, not scored as pass/fail.")
            print("  !! Unlock the account and rerun to get a complete result set:")
            print("     UPDATE TT_AI_USERS SET LOCKED_UNTIL = NULL WHERE USERNAME = '<user>'; COMMIT;\n")

    return results


def load_playbooks(playbooks_dir: str) -> list[dict]:
    """Loads every *.yaml file in playbooks_dir into a flat list of playbook
    dicts -- same one-file, safe_load-and-go convention as load_attack_library."""
    playbooks = []
    for filepath in sorted(glob.glob(os.path.join(playbooks_dir, "*.yaml"))):
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            playbooks.append(data)
    return playbooks


def fire_playbook(base_url: str, token: str, playbook: dict, attacks_by_id: dict,
                   endpoint: str = "/classify", timeout: int = 90,
                   progress_callback=None) -> list[dict]:
    """
    Fires a playbook's steps in order -- each step is one attack already
    in the shared library, referenced by id, reusing the exact same
    per-attack firing logic run() uses (seed/probe two-step attacks,
    target_endpoint override) so a playbook step behaves identically to
    that same attack fired standalone from the library. Nothing about
    firing or grading a single attack is duplicated here.

    Unlike run(), which always fires every attack regardless of outcome,
    a playbook honors playbook.get("stop_on_fail"): once a step's grade
    is FAIL, every remaining step is recorded as SKIPPED and never
    actually fired -- mirroring a real attack chain, where a step that
    depended on an earlier escalation succeeding never gets a chance to
    run once that escalation was blocked instead.

    progress_callback(i, total, step_attack, result) is called after each
    step (fired or skipped), same shape as run()'s callback, so a caller
    like ARC can reuse its existing live-update pattern unchanged.
    """
    from scorer import grade

    steps = playbook["steps"]
    total = len(steps)
    results = []
    stopped = False

    for i, step in enumerate(steps, 1):
        attack_id = step["attack_id"]
        attack = attacks_by_id.get(attack_id)

        if attack is None:
            result = {
                "id": attack_id,
                "name": f"Unknown attack '{attack_id}'",
                "status_code": None, "response_body": None, "elapsed_ms": 0.0,
                "error": f"'{attack_id}' not found in the loaded attack library",
                "grade": "ERROR",
                "run_at": datetime.now(timezone.utc).isoformat(),
            }
            results.append(result)
            if progress_callback:
                progress_callback(i, total, {"id": attack_id}, result)
            continue

        if stopped:
            result = {
                **attack,
                "status_code": None, "response_body": None, "elapsed_ms": 0.0,
                "error": None, "grade": "SKIPPED",
                "skipped_reason": "Chaine arretee : une etape precedente a echoue (escalade reussie)",
                "run_at": datetime.now(timezone.utc).isoformat(),
            }
            results.append(result)
            if progress_callback:
                progress_callback(i, total, attack, result)
            continue

        if "seed" in attack:
            outcome = fire_seed_probe_attack(base_url, token, attack, endpoint, timeout)
        else:
            attack_endpoint = attack.get("target_endpoint", endpoint)
            outcome = fire_attack(base_url, token, attack["prompt"], attack, attack_endpoint, timeout)

        result = {**attack, **outcome, "run_at": datetime.now(timezone.utc).isoformat()}
        result["grade"] = grade(result)
        results.append(result)

        if progress_callback:
            progress_callback(i, total, attack, result)

        if playbook.get("stop_on_fail") and result["grade"] == "FAIL":
            stopped = True

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
