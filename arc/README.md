# ARC — AI Red Team Console

A standalone terminal application for interactively driving the platform's
offensive security validation layer. ARC is a client of the existing
FastAPI backend — it never touches the database, the AI modules, or the
security modules directly. Access is restricted to the `SECURITY_ANALYST`
role, enforced both server-side (existing RBAC) and again in ARC itself.

## What this is (and isn't)

- **Is:** a new, additive client — like `static_ui.html` or `llm-redteam/runner.py`,
  just interactive and terminal-based.
- **Isn't:** a modification to any existing module. `app/ai/*`, `app/services/*`,
  `app/security/*`, `static_ui.html`, and `llm-redteam/` are all untouched.
- **Attacks are data, not code.** ARC reads and writes the same YAML attack
  files `llm-redteam/runner.py` already uses — no duplicated attack corpus.
  An attack authored in ARC is immediately usable by `llm-redteam` too, and
  vice versa.

## Setup

```bash
pip install -r requirements.txt
```

## Certificates (mTLS)

ARC authenticates to the platform over a dedicated port that requires a
client certificate (`:8443`, `ssl_cert_reqs=CERT_REQUIRED` — see
`app/security/mtls.py` on the platform side). The browser UI / normal
agents still use plain `:8000` HTTPS with just a JWT, unaffected.

Generate a CA + server cert + ARC client cert once (from the platform
repo, `scripts/generate_mtls_certs.sh`), then copy `ca.crt`,
`arc-client.crt`, and `arc-client.key` into a `certs/` folder next to
this README — `arc.py` looks for them there by default.

## Run (development — same machine as the API)

```bash
python arc.py --base-url https://127.0.0.1:8443 --attacks-dir ../llm-redteam/attacks
```

(These are also the defaults — the above is equivalent to just `python arc.py`.)

## Run (network-separated — from the operator VM)

```bash
python arc.py --base-url https://<host-lan-ip>:8443 --attacks-dir ./attacks
```

Requires the API server's `:8443` process to bind to `0.0.0.0` instead of
`127.0.0.1`, and the VM to be able to reach the host over the LAN. This is
a networking-only change — no application code is affected, and it's
fully reversible by restarting that uvicorn process without `--host
0.0.0.0`. The client cert itself (not just network reachability) is what
actually gates access from the VM — same guarantee either way.

## Navigating ARC

After login, you land on a **Menu** screen with four destinations:

- **Attack Library** — select/fire attacks, live results table
- **Author New Attack** — a form that writes a new attack into the shared
  YAML library (appends to an existing category file, or creates a new one)
- **Audit Log** — reads `GET /admin/audit-log` and displays recent events
- **Security Overview** — a description of every control the platform
  enforces (auth, RBAC, Gateway, Auto-Lock, audit trail), each paired with
  a *live* evidence count pulled from the real audit log — not just a
  static claim

Every screen has a **Back to menu** button (or `Esc`) and a **Log out**
button. `Ctrl+L` logs out from anywhere in the app, at any time.

## Project layout

```
arc.py                    Entry point -- wires login -> menu -> everything else
core/
  api_client.py            HTTP client (login, fire_attack, get_audit_log)
  attacks.py                Loads the shared YAML attack library
  attack_writer.py           Validates and writes new attacks into that same library
  grading.py                  PASS/FAIL/ERROR logic, mirrors llm-redteam/scorer.py
screens/
  login.py                   Login screen, enforces SECURITY_ANALYST-only access
  menu.py                     Post-login hub, routes to every other screen
  library.py                  Attack library + live fire/results screen
  audit.py                     Audit log viewer
  overview.py                   Security control overview + live evidence
  authoring.py                   New-attack authoring form
```

## Current status

- [x] Login screen, authenticated against `/login`, `SECURITY_ANALYST`-only
- [x] Menu/hub screen tying everything together
- [x] Attack library screen -- loads all YAML attacks, select/fire, live results table
- [x] Global run-status indicator during a fire batch, all controls disabled while running
- [x] Grading logic -- mirrors `llm-redteam/scorer.py`'s pass/fail rule
- [x] Audit log panel (reads `/admin/audit-log`)
- [x] Security overview panel with live evidence counts from the audit log
- [x] In-console attack authoring (writes a new YAML entry, shared with `llm-redteam`)
- [x] Logout, from any screen, via button or `Ctrl+L`
- [ ] Full styled HTML report generation from a fired session

## Testing notes

Validated end-to-end against a minimal fake backend (login, `/classify`,
`/admin/audit-log`) using Textual's `run_test()` headless pilot harness.
18 checks covering the full navigation graph: login success/failure, RBAC
rejection of non-`SECURITY_ANALYST` roles, Menu routing to all four
sub-screens and back, attack loading/firing/grading, the audit log
actually rendering fetched rows, the overview screen's live evidence
counts matching the fake backend's known event counts, an authored attack
being written to disk and then reloaded by the real loader (proving
round-trip correctness, not just "no exception was thrown"), and logout
correctly clearing the session and returning to a fresh login screen.

Two real bugs were found and fixed during this testing pass, not just
during initial development:

1. A custom `self._running` attribute on `LibraryScreen` silently collided
   with a reserved internal attribute Textual's own App/Screen lifecycle
   machinery uses for the same name -- it kept getting overwritten to `True`
   after mount, which made every button on the screen appear permanently
   disabled from the very first render. Renamed to `self._batch_running`.
2. The original logout implementation used `switch_screen()` on the
   automatically-created base screen after popping the stack down to it,
   which crashed with `IndexError: pop from empty list` inside Textual's
   own screen-transition internals (that base screen never had a result
   callback pushed onto it, and `switch_screen`'s cleanup unconditionally
   tries to pop one). Fixed by using `push_screen()` instead, mirroring
   exactly how the app already mounts the login screen on startup.

Point `--base-url` at the real platform to run it for real.
