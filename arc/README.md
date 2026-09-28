# ARC — AI Red Team Console

A standalone terminal application for interactively driving the platform's
offensive security validation layer. ARC is a client of the existing
FastAPI backend — it never touches the database, the AI modules, or the
security modules directly. Access is restricted to the `SECURITY_ANALYST`
role, enforced both server-side (existing RBAC) and again in ARC itself.

## What this is (and isn't)

- **Is:** a new, additive client — like `static_ui.html` or `llm-redteam/runner.py`,
  just interactive and terminal-based.
- **Isn't:** a modification to any existing platform module.
- **Attacks are data, not code.** ARC reads and writes the same YAML attack
  files `llm-redteam/runner.py` uses — no duplicated attack corpus. An attack
  authored in ARC is immediately usable by `llm-redteam`, and vice versa.
- **Two firing paths, by design.** *Fire all* delegates to `llm-redteam`'s engine
  in-process (so it does the pre-flight AI-backend health check, grades a 503 as
  BACKEND_UNAVAILABLE rather than FAIL, writes the run to `ops_log.json` and
  updates `findings.json`). *Fire selected* sends one prompt at a time through
  ARC's own client and grader and records nothing.

## Setup

```bash
pip install -r requirements.txt
```

ARC expects `../llm-redteam/` next to it (attack YAML files, playbooks, engine).

## Certificates (mTLS)

ARC authenticates to the platform over a dedicated port that requires a
client certificate (`:8443`, `ssl_cert_reqs=CERT_REQUIRED` — see
`app/security/mtls.py` on the platform side). The browser UI / normal
agents use `:8000` HTTPS with just a JWT, unaffected.

Generate a CA + server cert + ARC client cert once (from the platform
repo, `scripts/generate_mtls_certs.sh`), then copy `ca.crt`,
`arc-client.crt`, and `arc-client.key` into a `certs/` folder next to
this README — `arc.py` looks for them there by default. The server
certificate covers `localhost`, `127.0.0.1` and the name `tt-demo`.

## Run on the same machine as the platform

```bash
python arc.py            # defaults: --base-url https://127.0.0.1:8443, ../llm-redteam/attacks
```

On the platform's PC, the `arc` PowerShell function (or `scripts\start_dev.ps1`)
starts the servers if needed and then opens ARC.

## Run from a separate machine (operator VM) — the standard way

The platform's `:8443` listens on all interfaces; the client certificate, not
network position, is what admits a connection. The VM reaches it **by name**
(`tt-demo`), so the host's IP can change per network without re-issuing the
certificate.

1. Copy `arc/` and `llm-redteam/` to the VM (not `venv/`, not `certs/`), create a
   venv, `pip install -r requirements.txt` in each, place the three certificate
   files in `arc/certs/`.
2. Install `scripts/vm_arc_wrapper.sh` (platform repo) as `arc/arc` and
   `chmod +x` it. It activates the venv, warns if `tt-demo` is not mapped or the
   port is unreachable, then runs `arc.py --base-url https://tt-demo:8443`.
3. Once per network, map the name to the platform host's current IP:
   ```bash
   sudo sed -i '/ tt-demo$/d' /etc/hosts && echo "<host-ip> tt-demo" | sudo tee -a /etc/hosts
   ```
4. Run `~/arc/arc`. If login does not respond, ARC gives up after about 90 s with
   "Cannot reach ... ConnectTimeout"; on the host run `scripts\demo_check.ps1`
   to see which layer is wrong.

Command-line overrides win over the wrapper's default:
`arc --base-url https://tt-demo:8443 --client-cert ... --client-key ... --ca-cert ...`

## Navigating ARC

After login (a live session countdown is shown; ARC logs out at token expiry) the
**Menu** has three destinations (keys `1`–`3`):

- **Attack Library** — a categorized, collapsible, searchable catalog (filter by
  id, keyword or category). Space toggles an attack, Enter fires the selection,
  the right pane previews the full prompt, severity/expected outcome and last
  result. Buttons: *Fire selected*, *Fire all*, *Author New Attack* (writes a
  validated new entry into the shared YAML library) and *Playbooks* (five ordered
  attack chains that stop at the first step that gets through). After a run,
  *Generate Report* writes a timestamped HTML report next to `llm-redteam/`.
- **Findings** — the persistent findings tracker: one entry per attack that has
  ever failed, "open since X, seen in N runs" or "fixed X, confirmed N times
  since", plus the raw run history. Fed only by *Fire all*.
- **Canary Alerts** — polls the honeytoken-event endpoint every 15 s. Two sections:
  *Unverified* (source unknown, shown first) and *Certified* (arrived through the
  client-certificate port, i.e. ARC's own traffic), each with an
  account-locked / exempt badge.

Every screen has `Esc` to go back. `Ctrl+L` logs out from anywhere; `Ctrl+Q` quits.

### Reading results

- **PASS** — the platform behaved as the attack expected: `blocked` attacks were
  blocked, `allowed` (benign control) requests went through, two-step attacks were
  isolated.
- **FAIL** — the attack got through (or a benign request was wrongly blocked).
- **ERROR** — the run could not be scored, including a 403 caused by a locked or
  disabled account ("not a Gateway decision").
- **BACKEND_UNAVAILABLE** — HTTP 503, the AI backend (Ollama) is offline. Reported
  separately so it is never mistaken for a security regression.

## Project layout

```
arc.py                     Entry point -- login -> menu -> everything else
core/
  api_client.py             HTTP client (persistent mTLS session)
  attacks.py                 Loads the shared YAML attack library
  attack_writer.py            Validates and writes new attacks
  grading.py                   PASS/FAIL/ERROR/BACKEND_UNAVAILABLE for Fire selected
  findings.py                   Findings tracker (findings.json)
  ops_log.py                     Run history (ops_log.json)
  redteam_bridge.py               In-process bridge to llm-redteam (Fire all, playbooks)
  header_bar.py, session_widget.py, theme.py
screens/
  login.py    menu.py    library.py    authoring.py
  playbook.py    playbook_run.py    ops_log.py (Findings)    canary_alerts.py
```

## Testing notes

Validated in three ways: headless Textual pilot tests against a fake backend
(navigation, RBAC rejection of non-`SECURITY_ANALYST` roles, grading, authoring
round-trip, logout); direct measurement of widget geometry for layout bugs; and
live runs against the real platform, locally and from a separate Kali VM.
The full suite currently reports **44/46**: the two FAILs (`EXT-001`, `EXT-004`)
are attacks taken verbatim from public prompt-injection incidents that the
platform's literal-pattern Gateway does not catch. They are documented and left
open on purpose (see the project blueprint, Section 8).
