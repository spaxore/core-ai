# Secure TT AI Agent

**AI-powered complaint investigation platform for Tunisie Telecom prepaid mobile
customers, with an enterprise-grade cybersecurity layer built around it.**

Internship project - Tunisie Telecom (DCSI Kasbah) - NIDS (Reseaux et Securite des
Donnees), ESPRIT. Career focus: Cloud Security Architecture.

---

## What it does

Tunisie Telecom employees manually investigate thousands of prepaid customer
complaints every month - reading the complaint, identifying the type, querying Oracle
operational databases, and explaining the finding back to the customer. This project
automates that investigation pipeline:

**Employee submits a complaint in French** -> **AI classifies it** -> **system queries
real Oracle telecom data** -> **AI generates a grounded, factual French explanation** -
with zero hallucinated facts, since the explanation engine only ever sees real database
evidence, never invents figures.

On top of that AI core sits a full cybersecurity layer, which is the actual focus of the
internship: authentication, role-based access control, an AI security gateway that
screens every prompt for injection/jailbreak attempts before it reaches the LLM,
automated account lockout on repeated attacks, and a cryptographically tamper-evident
audit trail.

## Architecture

    TT Employee
        |
    Secure Web Interface (login-gated)
        |
    JWT Authentication  ->  Role-Based Access Control
        |
    AI Security Gateway (prompt injection / jailbreak / SQLi detection, risk scoring)
        |
    AI Investigation Engine
        |
        +-- Complaint Classifier          +-- Explanation Engine
        |                                          |
    Investigation Router
        |
        +---------+---------+---------+---------+
        v         v         v         v         v
      Voice    SMS/VAS    Data      SOS     Balance
     Service   Service   Service  Service  (pending)
        |
    Oracle Database 21c (parameterized queries only - the AI never generates SQL)
        |
    Tamper-Evident, Hash-Chained Audit Log

## Key design principle: the AI never touches SQL

    LLM -> Router -> Approved Python Function -> Parameterized SQL -> Oracle

The LLM only ever classifies complaint text and extracts a customer number via regex.
Every actual database query is a pre-written, parameterized Python function - the model
has no ability to generate or influence SQL directly.

## Security features

| Feature | Status |
|---|---|
| JWT authentication (bcrypt password hashing, 60-min token expiry) | Done |
| Role-Based Access Control (Support Agent / Security Analyst) | Done, enforced on live routes |
| AI Security Gateway - prompt injection, jailbreak, role-confusion, exfiltration, SQLi-via-prompt detection | Done, tested against all 5 categories |
| Auto-Lock - account-level containment after repeated attacks | Done |
| Tamper-evident audit trail - SHA256 hash-chained, verifiable | Done |
| Data masking (MSISDN redaction) | Descoped - see notes below |

The audit trail was tested by directly tampering with a stored log row in the database
and confirming a standalone verification script correctly flagged it - then restoring
it and reconfirming a clean chain. This isn't just implemented, it's demonstrated.

## Functional scope

| Complaint category | Status |
|---|---|
| Voice package expiration | Working |
| SMS+/VAS charges | Working |
| Mobile data usage | Working |
| SOS credit | Working |
| Balance deduction | In progress - pending business-logic confirmation |

## Tech stack

- **Backend:** Python 3.9+, FastAPI
- **Database:** Oracle Database 21c (`oracledb` driver)
- **AI:** Ollama running Llama 3.1, fully local - no customer data leaves the machine
- **Auth:** `python-jose` (JWT), `passlib` + `bcrypt` (password hashing)
- **Frontend:** a lightweight vanilla HTML/JS employee-facing web UI (no framework)

## Project structure

    app/
      ai/           classification, MSISDN extraction, explanation generation
      database/     Oracle connection handling
      services/     one investigation service per complaint category
      routes/       API routes (login)
      security/     auth, RBAC, AI gateway, auto-lock, audit logging
      static_ui.html
      main.py
    scripts/        account provisioning utilities
    tools/          standalone audit-chain integrity verifier
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

## Notes on scope

Authentication, RBAC, the AI Security Gateway, Auto-Lock, and the hash-chained audit
trail were all self-imposed extensions beyond the original internship brief (which
scoped only the AI assistant itself). Data masking was considered and deliberately
descoped in favor of finishing the balance-deduction investigation flow and formal
security testing, which carry more long-term value for the internship's outcomes.

A standalone LLM red-teaming framework - a YAML-driven adversarial test harness against
the AI Security Gateway, mapped to OWASP LLM Top 10 categories - is planned as the next
phase, designed to be decoupled and reusable independently of this codebase.

## Status

Cybersecurity core (Phase 4) is functionally complete and verified end-to-end. Remaining
work: finishing the balance-deduction investigation logic, formal security testing
(Phase 5), and the red-teaming framework.
