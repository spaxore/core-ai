# Zero-Trust AI Investigation Platform with Integrated Offensive Security Validation

**Core AI** runs every complaint through four stages: **C**lassify (`app/ai/classifier.py`), **O**rient (`app/services/router.py`), **R**etrieve (the category services and the cross-source search) and **E**xplain (`app/ai/explainer.py`). It is backed by twelve Oracle tables: five application tables (`TT_AI_*`) and seven read-only source tables (`RD_T_UC_*`).

**AI-powered complaint investigation platform for Tunisie Telecom prepaid mobile
customers, with an enterprise-grade cybersecurity layer built around it — and its own
purpose-built offensive security tooling to continuously validate that layer.**

Internship project - Tunisie Telecom - NIDS (Reseaux et Securite des
Donnees), ESPRIT. Career focus: Cloud Security Architecture.

---

## What it does

Tunisie Telecom employees manually investigate thousands of prepaid customer
complaints every month - reading the complaint, identifying the type, querying Oracle
operational databases, and explaining the finding back to the customer. This project
automates that investigation pipeline, mirroring how an agent actually works: check the
obvious fact first, narrow the search, broaden it if that doesn't explain the amount,
check every other source, and only then honestly say "not enough evidence" - never
inventing a cause.

**Employee submits a complaint in French** -> **AI classifies it (informed by retrieval
over confirmed past cases)** -> **system queries real Oracle telecom data with an
adaptive narrow-then-broaden search** -> **AI generates a grounded, factual French
explanation** - with zero hallucinated facts, since the explanation engine only ever
sees real database evidence, never invents figures. Every match carries two computed
signals - confidence (how well the evidence fits) and coverage (how much evidence,
spanning how many sources, actually went into the answer) - and every completed
investigation is reviewable afterward through a real ticket list and case-detail view,
not just logged. A reviewer can validate, correct or reject each case from the same
screen.

On top of that AI core sits a full cybersecurity layer, which is the actual focus of the
internship: authentication, role-based access control, an AI security gateway that
screens every prompt for injection/jailbreak attempts before it reaches the LLM,
automated account containment (three independent mechanisms plus an immediate lock on a
honeytoken hit), live session revocation, mutual TLS for the red-team channel, and a
cryptographically tamper-evident audit trail. The platform also contains its own
offensive validation layer - a decoupled red-team attack framework and an interactive
terminal console (ARC) - that fires real attacks at the live system and reports what
holds and what doesn't, including the attacks that get through.

## Architecture

    TT Employee                                   ARC operator (separate host / VM)
        |                                                   |
    Secure Web Interface (login-gated)          Terminal console, client certificate
        |  https :8000                                      |  https :8443 (mTLS)
        +---------------------------+-----------------------+
                                    |
    JWT Authentication  ->  Role-Based Access Control  (checked on every request,
                                    |                  incl. account still active,
                                    |                  token newer than last password change)
    AI Security Gateway (prompt injection / jailbreak / SQLi detection, risk scoring)
    -- covers every endpoint that writes AI-consumed text, including case verification
                                    |
    AI Investigation Engine
        |
        +-- Complaint Classifier (retrieval-informed via Case Memory)
        |                                          |
        |                                  Explanation Engine
        |
    Investigation Router
        |
        +---------+---------+---------+---------+
        v         v         v         v         v
      Voice    SMS/VAS    Data      SOS     Balance
     Service   Service   Service  Service   Deduction
        |         |         |         |         |
        +---------+----+----+---------+---------+
                       v
          Cross-Source Search (fallback for all 5 -
          the sole strategy for Balance Deduction,
          since it names no mechanism to start from)
        |
    Oracle Database 21c (parameterized queries only - the AI never generates SQL)
        |                      +-- honeytoken check on the target and on the evidence returned
    Tamper-Evident, Hash-Chained Audit Log
        |
    Investigation Results (persisted evidence + explanation, keyed to the audit log)
        |
    Ticket list / Ticket detail UI

Offensive validation sits alongside this pipeline, not inside it: `llm-redteam/` fires
YAML-defined attacks at the live API over HTTP exactly like any other client, and `arc/`
is an interactive terminal console for the same engine, restricted to the
`SECURITY_ANALYST` role and reaching the platform only through the certificate-required
port.

## Key design principle: the AI never touches SQL

    LLM -> Router -> Approved Python Function -> Parameterized SQL -> Oracle

The LLM only ever classifies complaint text and extracts a customer number via regex.
Every actual database query is a pre-written, parameterized Python function - the model
has no ability to generate or influence SQL directly.

## Security features

| Feature | Status |
|---|---|
| JWT authentication (bcrypt password hashing, server-side password-strength check) | Done |
| Role-Based Access Control (Support Agent / Security Analyst) | Done, enforced on every route except `/`, `/health/llm`, `/ui` and `/login` |
| Live session revocation - a deactivated account or a changed/reset password invalidates already-issued tokens | Done |
| AI Security Gateway - prompt injection, jailbreak, role-confusion, exfiltration, SQLi-via-prompt detection (literal patterns, confusable-character normalization, Base64 decode-and-rescan) | Done - covers `/classify`, `/investigate` and `/verify-case` |
| Auto-Lock - account containment after repeated Gateway alerts (AI-subversion) | Done |
| Login lockout - containment after repeated failed logins (brute-force) | Done, independently triggered and logged |
| Near-miss escalation - repeated below-threshold requests lock the account | Done |
| Honeytoken - a canary customer number seeded in every source table; any result touching it is confirmed bypass evidence and locks the account immediately | Done |
| Mutual TLS on a dedicated port for ARC; every audit entry records whether it arrived through the certified channel | Done |
| Tamper-evident audit trail - SHA-256 hash-chained, verifiable | Done |
| Output encoding in the web UI, CSP and other HTTP security headers, API schema off by default | Done |
| Offensive validation - a decoupled attack framework + terminal console, 46 attacks: 44 blocked/allowed as expected, 2 documented external bypasses | Done, covers the case-memory retrieval path |

The audit trail was tested by directly tampering with a stored log row in the database
and confirming a standalone verification script correctly flagged it - then restoring
it and reconfirming a clean chain. The Gateway has been exercised repeatedly by the
red-team framework; eighteen findings (defects and documented limitations) are recorded
in the project blueprint, Section 8. This isn't just implemented, it's demonstrated.

**Known, documented limits** (not hidden): the Gateway is a literal-pattern filter, not a
semantic one - two of four attacks taken verbatim from public prompt-injection incidents
(`EXT-001`, `EXT-004`) get through by rephrasing and are deliberately left unpatched as
evidence of that boundary. The application connects as the schema owner, so database-level
read-only / append-only protection is not enforced; there is no IP-based login throttling;
and the development certificate is self-signed.

## Functional scope

| Complaint category | Status |
|---|---|
| Voice package expiration | Working |
| SMS+/VAS charges | Working |
| Mobile data usage | Working |
| SOS credit | Working |
| Balance deduction | Working - via cross-source search, since this category names no mechanism to start from |

Every category follows the same adaptive narrow-then-broaden search, and falls back to
checking every other data source before honestly reporting "not enough evidence" if a
complaint names the wrong bucket or mechanism.

## AI self-learning and reviewability

- **Case memory** - the classifier retrieves the most similar past *verified* complaints
  and uses them both as few-shot examples and to compute a real, calculated confidence
  score from precedent strength, rather than relying only on the LLM's own self-report.
- **Validation status** - a reviewer can mark a case validated, corrected or `rejected`
  (e.g. a precedent that turned out to be a coincidental match), which immediately
  excludes a rejected one from future retrieval - the self-learning loop is
  correctable, not just additive. Correcting a ticket re-investigates for real and links
  the two; the original audit entry is never rewritten.
- **Evidence coverage** - a second, computed statistic next to confidence, showing how
  many distinct sources/dates the supporting evidence actually spans.
- **Investigation trace** - every investigation records which search tiers were tried,
  what each found and which were skipped, and the UI replays it step by step.
- **Ticket history and detail view** - every completed investigation with real evidence
  is persisted (explanation, technical note, evidence rows, original complaint text), so
  a case can be genuinely reopened and reviewed later.

## Offensive validation

`llm-redteam/` is a standalone, decoupled attack framework: YAML-defined attacks across
7 categories (direct/indirect injection, jailbreak, role confusion, data exfiltration,
SQLi-via-prompt, and retrieval poisoning against the case-memory path), a benign control
set for false-positive measurement, and an external validation set of 4 prompts taken
verbatim from public incidents (46 attacks in 9 files), fired against the live platform
over HTTP. Five ordered attack-chain playbooks (`llm-redteam/playbooks/`) model an
attacker who escalates and stops once they succeed.

`arc/` (AI Red Team Console) is an interactive terminal operator interface to the same
engine - not a web dashboard, in the tradition of tools like `nmap`'s interactive mode.
Restricted to the `SECURITY_ANALYST` role. Its menu has three destinations: the
**Attack Library** (browse, fire one or all, author a new attack, run playbooks),
**Findings** (a persistent tracker of every attack that ever failed, plus run history)
and **Canary Alerts** (live honeytoken monitor, split into certified and unverified
sources).

Current state: **44/46 as expected, 2 open findings** - both from the external set, both
explained by the Gateway matching wording rather than intent. Eighteen curated
findings (see blueprint Section 8) have been found and closed or documented, including a
case where `/verify-case` accepted AI-consumed text with zero Gateway inspection, caught
while building red-team coverage for the case-memory path. Two of them, Unicode
homoglyph evasion and Base64 instruction smuggling, bypassed the Gateway's literal
matching entirely and are fixed by normalizing confusable characters and
decoding-and-rescanning Base64 spans; the honeytoken layer caught the homoglyph attack
even before that fix, as an independent second control.

## Tech stack

- **Backend:** Python 3.9+, FastAPI
- **Database:** Oracle Database 21c (`oracledb` driver)
- **AI:** Ollama running Llama 3.1, fully local - no customer data leaves the machine
- **Auth:** `python-jose` (JWT), `passlib` + `bcrypt` (password hashing)
- **Transport:** TLS on `:8000`; mutual TLS (client certificate required) on `:8443`
- **Secrets at rest:** Fernet (`cryptography`) for linked-email app passwords
- **Frontend:** vanilla HTML/JS employee-facing web UI on the real TT brand palette
  (Space Grotesk / IBM Plex Sans / IBM Plex Mono type system, no framework)
- **Offensive validation:** custom YAML/Python framework (`llm-redteam/`) + a Textual
  terminal console (`arc/`)
- **CI:** GitHub Actions (compile check, attack-file validation, non-blocking dependency scan)

## Project structure

    app/
      ai/           classification, case memory, explanation generation
      database/     Oracle connection handling
      services/     one investigation service per complaint category, plus
                     cross-source search, persisted results, user administration
      routes/       login and profile routes
      security/     auth, RBAC, AI gateway, lockout, honeytoken, mTLS provenance,
                     email encryption, audit logging
      static_ui.html
      main.py
    arc/            terminal operator console for offensive validation (Textual)
    llm-redteam/    standalone red-team attack framework (YAML + Python) + playbooks
    scripts/        certificate generation, account/honeytoken seeding, start/stop,
                     demo readiness check, VM launcher
    tools/          standalone audit-chain integrity verifier, Gateway pattern self-audit
    tests/          regression test suite
    certs/          generated mTLS material (gitignored - never commit private keys)

## Running it locally

    python -m venv venv
    venv\Scripts\activate          # Windows
    pip install -r requirements.txt

Create a `.env` file (never committed) with:

    DB_USER=...
    DB_PASSWORD=...
    DB_DSN=localhost:1521/ORCLPDB
    SECRET_KEY=...       # python -c "import secrets; print(secrets.token_hex(32))"
    EMAIL_CRED_KEY=...   # Fernet key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Requires a running Oracle 21c instance (the `TT_AI_*` tables and the `RD_T_UC_*` source
tables - the DDL for the former is not scripted in this repository) and Ollama with
`llama3.1` pulled locally. After the source tables exist, seed the honeytoken once:

    python scripts/seed_honeytoken.py

Generate the certificates once (output goes to `certs/`; add `EXTRA_SAN_IPS="<ip> <ip>"`
to also cover fixed LAN addresses):

    bash scripts/generate_mtls_certs.sh

Copy `arc-client.crt`, `arc-client.key` and `ca.crt` into `arc/certs/`.

**Start everything (Windows, PowerShell):**

    .\scripts\start_dev.ps1            # :8000 (loopback) + :8443 (all interfaces), then ARC
    .\scripts\start_dev.ps1 -LocalOnly # keep :8443 on loopback (ARC on this PC only)
    .\scripts\stop_dev.ps1             # stop every uvicorn process
    .\scripts\demo_check.ps1           # read-only readiness check before a demo

Visit `https://127.0.0.1:8000/ui` for the employee interface. The auto-generated `/docs`
API reference is disabled by default (it is unauthenticated); set `ENABLE_API_DOCS=1` to
turn it on for local development.

**Accounts:** `scripts/seed_user*.py` create the initial accounts. `redteam_runner` (the
account ARC and `llm-redteam` fire attacks as) must have the `SECURITY_ANALYST` role;
`seed_user3.py` creates it as `SUPPORT_AGENT`, so change its role after seeding.

## Running ARC from a separate machine (recommended)

ARC is meant to run on a host that is not the platform's (it has been run from a Kali
Linux VM, bridged network). `:8443` listens on all interfaces; the client certificate,
not the network position, is what admits a connection.

1. **Host:** allow inbound TCP 8443 once (Administrator prompt):

       netsh advfirewall firewall add rule name="TT-AI ARC mTLS (8443)" dir=in action=allow protocol=TCP localport=8443

2. **VM:** copy `arc/` and `llm-redteam/` (not `venv/`, not `certs/`), install their
   requirements in a venv, put the three certificate files in `arc/certs/`, and install
   `scripts/vm_arc_wrapper.sh` as `arc/arc` (`chmod +x`).
3. **Name the host.** The server certificate covers the name `tt-demo`, not a fixed IP,
   so the same certificate works on any network. On the VM, once per network:

       sudo sed -i '/ tt-demo$/d' /etc/hosts && echo "<host-ip> tt-demo" | sudo tee -a /etc/hosts

4. Run `arc/arc` on the VM. If it cannot connect, `scripts/demo_check.ps1` on the host
   reports which layer is wrong (server bind, certificate, firewall, network profile).

On a Wi-Fi network Windows classifies as *Public*, a `python.exe` Block rule can drop the
VM's connection silently; mark the network Private or remove that rule.

## Notes on scope

The AI investigation assistant was proposed by Tunisie Telecom; the security architecture
around it and the validation layer that tests it are the author's solution. They are
delivered as three integrated layers, planned together: the AI investigation engine, the zero-trust security architecture around it (authentication,
RBAC, the AI Security Gateway, account containment, the hash-chained audit trail), and
the offensive validation layer (`llm-redteam/` + `arc/`) that tests it.

## Status

All five functional categories are complete. The security layer, self-learning
correction mechanism, investigation trace, and offensive validation layer are
functionally complete and independently verified; ARC has been run from a
network-separated host. The two open red-team findings are the documented external
bypasses. The documentation set (architecture, threat model, API reference, security
test report, user/deployment/ARC guides, evidence pack) accompanies the project
blueprint (Phase 6).
