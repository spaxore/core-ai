# Zero-Trust AI Investigation Platform with Integrated Offensive Security Validation

*(repository: `secure-tt-ai-agent`)*

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
investigation is reviewable afterward through a real history and case-detail view, not
just logged.

On top of that AI core sits a full cybersecurity layer, which is the actual focus of the
internship: authentication, role-based access control, an AI security gateway that
screens every prompt for injection/jailbreak attempts before it reaches the LLM,
automated account containment on repeated attacks (two independent mechanisms - AI
subversion and login brute-force), and a cryptographically tamper-evident audit trail.
The platform also contains its own offensive validation layer - a decoupled red-team
attack framework and an interactive terminal console (ARC) - that fires real attacks at
the live system and reports what holds and what doesn't.

## Architecture

    TT Employee
        |
    Secure Web Interface (login-gated)
        |
    JWT Authentication  ->  Role-Based Access Control
        |
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
        |
    Tamper-Evident, Hash-Chained Audit Log
        |
    Investigation Results (persisted evidence + explanation, keyed to the audit log)
        |
    History / Ticket Detail UI

Offensive validation sits alongside this pipeline, not inside it: `llm-redteam/` fires
YAML-defined attacks at the live API over HTTP exactly like any other client, and `arc/`
is an interactive terminal console for the same engine, restricted to the
`SECURITY_ANALYST` role.

## Key design principle: the AI never touches SQL

    LLM -> Router -> Approved Python Function -> Parameterized SQL -> Oracle

The LLM only ever classifies complaint text and extracts a customer number via regex.
Every actual database query is a pre-written, parameterized Python function - the model
has no ability to generate or influence SQL directly.

## Security features

| Feature | Status |
|---|---|
| JWT authentication (bcrypt password hashing) | Done |
| Role-Based Access Control (Support Agent / Security Analyst) | Done, enforced on every route |
| AI Security Gateway - prompt injection, jailbreak, role-confusion, exfiltration, SQLi-via-prompt detection | Done - covers `/classify`, `/investigate`, and `/verify-case` |
| Auto-Lock - account-level containment after repeated Gateway alerts (AI-subversion) | Done |
| Login lockout - separate containment after repeated failed logins (brute-force) | Done, independently triggered and logged from Auto-Lock |
| Tamper-evident audit trail - SHA256 hash-chained, verifiable | Done |
| Offensive validation - a decoupled attack framework + terminal console, 42/42 attacks passing, zero open findings | Done, covers the case-memory retrieval path |

The audit trail was tested by directly tampering with a stored log row in the database
and confirming a standalone verification script correctly flagged it - then restoring
it and reconfirming a clean chain. The Gateway itself has been exercised repeatedly by
the red-team framework, catching and closing eight real gaps to date (see
`llm-redteam/README.md` and the project blueprint for the full history). This isn't
just implemented, it's demonstrated.

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
- **Validation status** - a reviewer can mark a past case `rejected` (e.g. a precedent
  that turned out to be a coincidental match), which immediately excludes it from future
  retrieval - the self-learning loop is correctable, not just additive.
- **Evidence coverage** - a second, computed statistic next to confidence, showing how
  many distinct sources/dates the supporting evidence actually spans - so a support
  agent can tell "one tight bucket" apart from "four unrelated sources loosely
  correlated" at a glance.
- **Investigation history and detail view** - every completed investigation with real
  evidence is persisted (explanation, technical note, and evidence rows), so a case can
  be genuinely reopened and reviewed later, not just summarized in a log line.

## Offensive validation

`llm-redteam/` is a standalone, decoupled attack framework: YAML-defined attacks across
7 categories (direct/indirect injection, jailbreak, role confusion, data exfiltration,
SQLi-via-prompt, and retrieval poisoning against the case-memory path) plus a benign
control set for false-positive measurement, fired against the live platform over HTTP.

`arc/` (AI Red Team Console) is an interactive terminal operator interface to the same
engine - not a web dashboard, in the tradition of tools like `nmap`'s interactive mode.
Restricted to the `SECURITY_ANALYST` role, with attack authoring, live results, and a
local run-history log that diffs each run against the last.

Current state: **42/42 attacks passing, zero open findings.** Eight real gaps have
been found and closed over the project's life, including a case where `/verify-case`
was found to accept AI-consumed text with zero Gateway inspection - caught while
building red-team coverage for the case-memory retrieval path, not discovered later in
production. The two most recent, Unicode homoglyph evasion and Base64 instruction
smuggling (see blueprint Section 8), both bypassed `inspect_prompt()`'s
literal-substring matching entirely; fixed by normalizing confusable Cyrillic/Greek
characters to their Latin equivalents and by decoding-and-rescanning any Base64 spans
in the request text, both confirmed against the live server. A honeytoken-based
detection layer remains in place as a second, independent control alongside the
Gateway fix, not a replacement for it.

## Tech stack

- **Backend:** Python 3.9+, FastAPI
- **Database:** Oracle Database 21c (`oracledb` driver)
- **AI:** Ollama running Llama 3.1, fully local - no customer data leaves the machine
- **Auth:** `python-jose` (JWT), `passlib` + `bcrypt` (password hashing)
- **Frontend:** vanilla HTML/JS employee-facing web UI on the real TT brand palette
  (Space Grotesk / IBM Plex Sans / IBM Plex Mono type system, no framework)
- **Offensive validation:** custom YAML/Python framework (`llm-redteam/`) + a Textual
  terminal console (`arc/`)

## Project structure

    app/
      ai/           classification, case memory, explanation generation
      database/     Oracle connection handling
      services/     one investigation service per complaint category, plus
                     cross-source search and persisted investigation results
      routes/       API routes (login)
      security/     auth, RBAC, AI gateway, lockout, audit logging
      static_ui.html
      main.py
    arc/            terminal operator console for offensive validation (Textual)
    llm-redteam/    standalone red-team attack framework (YAML + Python)
    scripts/        account provisioning utilities
    tools/          standalone audit-chain integrity verifier, Gateway pattern self-audit
    tests/          regression test suite

## Running it locally

    python -m venv venv
    venv\Scripts\activate          # Windows
    pip install -r requirements.txt --break-system-packages

Create a `.env` file (never committed) with:

    DB_USER=...
    DB_PASSWORD=...
    DB_DSN=localhost:1521/ORCLPDB
    SECRET_KEY=...   # generate with: python -c "import secrets; print(secrets.token_hex(32))"

Requires a running Oracle 21c instance and Ollama with `llama3.1` pulled locally.

    uvicorn app.main:app --reload

Visit `http://127.0.0.1:8000/ui` for the employee interface, or `http://127.0.0.1:8000/docs`
for the API reference.

ARC connects over a separate, mTLS-required port (`:8443`) rather than the plain
`:8000` above. Generate the certs once (output goes to `certs/`, gitignored):

    bash scripts/generate_mtls_certs.sh

Copy `arc-client.crt`, `arc-client.key`, and `ca.crt` into `arc/certs/`, then run the
second server and the console:

    uvicorn app.main:app --ssl-keyfile certs/server.key --ssl-certfile certs/server.crt \
        --ssl-ca-certs certs/ca.crt --ssl-cert-reqs 2 --port 8443

    cd arc
    python arc.py

ARC also runs the same way from any other machine on the network (it's been run from a
separate Kali Linux VM against this platform, to demonstrate a genuine trust boundary
between the security tooling and the system it validates) - just pass
`--base-url https://<host-ip>:8443` and point `--client-cert`/`--client-key`/`--ca-cert`
at copies of the same three files.

## Notes on scope

Authentication, RBAC, the AI Security Gateway, account containment, the hash-chained
audit trail, and the entire offensive validation layer (`llm-redteam/` + `arc/`) were
all self-imposed extensions beyond the original internship brief, which scoped only the
AI assistant itself.

## Status

All five functional categories are complete. The security layer, self-learning
correction mechanism, investigation trace/stepper, and offensive validation layer are
all functionally complete and independently verified, with zero open red-team findings
as of the latest pass. ARC has also been deployed and run from a genuinely
network-separated host (a Kali Linux VM), closing out that item. Remaining work: Phase
6 documentation (architecture diagrams, threat model, final report).
