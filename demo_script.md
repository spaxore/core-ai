# Demo Script — AI Assistant (Secure TT AI Agent)

Scope: the AI assistant / investigation interface only (`app/static_ui.html` +
backend). Does not cover ARC / offensive validation — that's a separate demo
if it comes up.

Based on blueprint v3.4 (`OneDrive\Bureau\Project\Project_Blueprint_v3.4.docx`).

---

## 0. Before you start (do this before anyone's watching)

1. Oracle 21c instance running.
2. Ollama running with `llama3.1` pulled (`ollama list` to check).
3. Start the backend (two ports since the mTLS work landed -- see
   `scripts/generate_mtls_certs.sh` if `certs/` doesn't exist yet):
   ```bash
   venv\Scripts\activate
   uvicorn app.main:app --reload --ssl-keyfile certs/server.key --ssl-certfile certs/server.crt --port 8000
   ```
   `:8000` is plain HTTPS (browser UI, normal agents) -- no client cert
   needed. ARC's own `:8443` (client-cert-required) is a second process,
   ARC/llm-redteam's own run instructions cover starting it.
4. Open `http://127.0.0.1:8000/ui` in a browser, confirm it loads before you're live.
5. Log in once yourself first to confirm the DB connection and Ollama are actually
   responding — a cold Ollama call can be slow on the very first request of the
   session, don't let that first delay happen live.
6. Have a login ready: `agent1` (SUPPORT_AGENT role) is the right account for
   this demo — it's the role that actually files/investigates complaints.
   `ikbal` (SECURITY_ANALYST) is a fallback if you want to show a different
   role's view. Don't use `redteam_runner` for this — that account is reserved
   for ARC attack traffic.

---

## 1. Login

- Show the login screen — mention the ambient glow polish (ss. Pass 5) if
  anyone comments on the visual.
- Log in as `agent1`.

**Talking point:** JWT auth, bcrypt-hashed passwords, role-based access —
every request from here on is authenticated and role-checked server-side, not
just hidden in the UI.

---

## 2. File a complaint → watch it investigate

Pick ONE category to walk through in full, then mention the other four exist
and work the same way (don't run all five live unless you have time).

Suggested: **Balance Deduction** or **Voice Expiration** — usually the
clearest "before/after" story.

Steps:
1. Paste a real complaint (use a number/case you've already verified works —
   don't improvise a new MSISDN live).
2. Submit.
3. **Investigation trace/stepper ("Parcours de l'investigation")** appears —
   this is new this version. Let it play out; don't skip past it.

**Talking points while it plays:**
- Each row is a real tier the AI actually tried, in the real order, not a
  fixed animation — a search that matches immediately shows fewer rows than
  one that had to broaden.
- Gray = tried, found nothing (not a failure — an honest "checked, no match
  here"). Green = matched. Dashed = skipped because an earlier, more specific
  tier already matched. Red = a real error.
- It's not a live stream — the investigation itself is one fast synchronous
  call; this replays the real recorded steps at a readable pace so a human
  can actually follow it.

4. Point out the **Résultat card**: confidence (how well the evidence fits)
   and evidence coverage (how much of the evidence was actually used — buckets,
   dates, row count) are two separate, computed numbers — neither is
   self-reported by the model.

---

## 3. Validation loop — Valider / Corriger / Rejeter

This is the other headline feature this version — previously only reachable
via a raw API call, now live in the UI.

1. On the fresh Résultat card, point out the three buttons.
2. Click **Valider** — show it updates in place and the ticket detail view
   opens as confirmation (not a quiet badge change).
3. Note: once validated, Valider/Rejeter disappear, only Corriger remains.

**Talking point on Corriger** (if you demo it): editing the complaint text
and resubmitting does **not** overwrite the original investigation — it fires
a genuine new `/investigate` call and links the original ticket to the new
one. The audit trail stays append-only; nothing is mutated in place. This
was a deliberate design constraint, not an accident.

---

## 4. History

1. Open History.
2. Point out: sortable columns (Date, Catégorie, Numéro, Confiance — sorted
   client-side on the already-loaded batch).
3. Point out the **Statut** column — shows validated/corrected/rejected per
   ticket without a separate query per row.
4. Click a corrected ticket → shows it links straight through to its
   replacement.
5. Click "N investigations aujourd'hui" stat → jumps to History pre-filtered
   to today.

---

## 5. Small polish worth mentioning if there's time

- Fixed sidebar, consistent category icons everywhere a category renders.
- Confidence badges have a hover explanation of what HIGH/MEDIUM/LOW mean.
- Copy-ticket-ID button in ticket detail.
- Global back button — driven by a real navigation stack (fixed a bug where
  detail→related ticket→back used to skip the first ticket).

---

## 6. Security architecture — mention, don't demo deeply

Keep this brief unless asked directly (scope is the assistant, not ARC):

- Every request: Auth (JWT) → RBAC → AI Security Gateway (prompt injection /
  jailbreak / exfiltration / SQLi-via-prompt detection) → investigation →
  parameterized-only DB access → hash-chained audit log.
- Two independent account-containment mechanisms: AI-subversion Auto-Lock and
  a separate login brute-force lockout.
- If asked "has this been tested": the full 38-attack offensive suite
  (separate tool, ARC) has been re-run after every major change this version,
  38/38 pass, zero regressions — happy to show that tool separately if there's
  time/interest.

---

## If something breaks live

- Ollama cold-start slow on first call → mention it's warming up, don't panic.
- If a specific ticket/MSISDN doesn't reproduce cleanly, fall back to a
  category you've already verified today rather than improvising a new one.
- `tests/test_regression_full.py` is known non-functional (missing auth
  header) — don't run it live as a "proof" of anything, it will show false
  failures unrelated to the app itself.

---

## One-line summary if asked "what's new this version"

"Two things: you can now watch the AI's search happen step by step instead of
just getting an answer, and a support agent can validate, correct, or reject
a past investigation directly from the page they're already on — both used to
only exist as raw API calls."
