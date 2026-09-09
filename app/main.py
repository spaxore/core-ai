import smtplib
import subprocess

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
from app.ai.ollama_client import ask_ollama, is_ollama_online, OllamaUnavailableError
from app.ai.classifier import classify_complaint
from app.ai.explainer import explain_investigation
from app.ai.case_memory import save_verified_case, update_case_status, get_verified_case_by_log_id, VALID_STATUSES
from app.services.router import run_investigation
from app.services.investigation_results import save_investigation_result, get_investigation_result, mark_superseded
from app.services.email_account import send_email
from app.services.user_admin import (
    list_users, create_user, set_user_role, set_user_active,
    unlock_user, reset_password, get_user_activity_admin,
)
from app.security.dependencies import get_current_user, require_role
from app.security.audit import get_recent_events, get_investigation_history, get_investigation_stats, get_investigation_summary, get_canary_events
from app.security.audit import log_event
from app.security.gateway import inspect_prompt
from app.security.lockout import check_and_apply_lockout
from app.security.honeytoken import check_for_canary
from app.security.mtls import channel_label
from datetime import date, timedelta
from app.routes.auth_routes import router as auth_router
from app.routes.profile_routes import router as profile_router

app = FastAPI(
    title="Secure TT AI Agent",
    description="AI assistant for Tunisia Telecom complaint analysis",
    version="1.0"
)
app.include_router(auth_router)
app.include_router(profile_router)


@app.exception_handler(OllamaUnavailableError)
def handle_ollama_unavailable(request: Request, exc: OllamaUnavailableError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/")
def home():
    return {
        "status": "running",
        "project": "Secure TT AI Agent"
    }


@app.get("/health/llm")
def llm_health():
    return {"llm_online": is_ollama_online()}

def _build_version() -> str:
    """The actual deployed commit's short hash -- real, verifiable data,
    not a hand-maintained version number that'll drift out of sync with
    what's really running. Falls back to a plain dash if git isn't
    available (e.g. a source-only deployment with no .git directory)."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "-"


@app.get("/ui", response_class=HTMLResponse)
def ui():
    with open("app/static_ui.html", "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("{{BUILD_VERSION}}", _build_version())
    # No-cache: this file is read fresh from disk on every request during
    # active development, but browsers cache an HTML response by default
    # absent an explicit header telling them not to -- without this, an
    # edit here can silently keep serving a stale copy until a hard
    # refresh, which looks exactly like the edit never took effect.
    return HTMLResponse(content=content, headers={"Cache-Control": "no-store"})

@app.get("/test-ai")
def test_ai():
    answer = ask_ollama("Classify this complaint: Client says his balance disappeared")
    return {
        "AI_Response": answer
    }

@app.post("/classify")
def classify(complaint: dict, http_request: Request, user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    text = complaint.get("text", "")
    client_ip = http_request.client.host

    scan = inspect_prompt(text)
    if scan["is_blocked"]:
        log_event(
            "SECURITY_ALERT",
            username=user["username"],
            role=user["role"],
            details=f"BLOCKED classify: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={text}, channel={channel_label(http_request)}",
            ip_address=client_ip
        )
        check_and_apply_lockout(user["username"], user["role"], client_ip)
        raise HTTPException(status_code=403, detail={
            "message": "Request blocked by security gateway",
            "risk_score": scan["risk_score"],
            "matched_categories": [m["category"] for m in scan["matches"]],
        })
    elif scan["risk_score"] > 0:
        log_event(
            "SECURITY_FLAG",
            username=user["username"],
            role=user["role"],
            details=f"FLAGGED classify: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={text}, channel={channel_label(http_request)}",
            ip_address=client_ip
        )

    result = classify_complaint(text)

    log_event(
        "CLASSIFY",
        username=user["username"],
        role=user["role"],
        details=f"text={text} -> category={result.get('category')}, msisdn={result.get('msisdn')}, da_value={result.get('da_value')}, channel={channel_label(http_request)}",
        ip_address=client_ip
    )

    return result

def _pipeline_step(label, status, detail=None):
    return {"label": label, "status": status, "detail": detail}


# Mirrors app/services/cross_source_search.py's own French confidence labels
# rather than importing it directly (that module already imports plenty from
# investigation_helpers.py; this keeps main.py's display strings independent
# of a service-layer constant).
_CONFIDENCE_LABEL_FR = {"HIGH": "confiance élevée", "MEDIUM": "confiance moyenne", "LOW": "confiance faible"}

_DIAGNOSTIC_SYNTHESIS = {
    "HIGH": "Confiance élevée — cause confirmée avec un haut degré de certitude.",
    "MEDIUM": "Confiance moyenne — à confirmer si nécessaire.",
    "LOW": "Confiance faible — signalé comme piste possible, pas comme cause confirmée.",
}


@app.post("/investigate")
def investigate(complaint: dict, http_request: Request, user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    text = complaint.get("text", "")
    client_ip = http_request.client.host
    pipeline = []

    # The Gateway scan and its outcome aren't shown in the pipeline UI --
    # a real block raises HTTPException below and never reaches the
    # frontend's pipeline rendering at all, and a pass is infrastructure
    # plumbing the agent doesn't need to see; the pipeline is reserved for
    # the AI's own classification/search/diagnosis work.
    scan = inspect_prompt(text)
    if scan["is_blocked"]:
        log_event(
            "SECURITY_ALERT",
            username=user["username"],
            role=user["role"],
            details=f"BLOCKED investigate: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={text}, channel={channel_label(http_request)}",
            ip_address=client_ip
        )
        check_and_apply_lockout(user["username"], user["role"], client_ip)
        raise HTTPException(status_code=403, detail={
            "message": "Request blocked by security gateway",
            "risk_score": scan["risk_score"],
            "matched_categories": [m["category"] for m in scan["matches"]],
        })
    elif scan["risk_score"] > 0:
        log_event(
            "SECURITY_FLAG",
            username=user["username"],
            role=user["role"],
            details=f"FLAGGED investigate: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={text}, channel={channel_label(http_request)}",
            ip_address=client_ip
        )

    classification = classify_complaint(text)
    category = classification.get("category")
    msisdn = classification.get("msisdn")
    da_value = classification.get("da_value")
    target_amount = classification.get("target_amount")
    target_volume_gb = classification.get("target_volume_gb")
    event_date_str = classification.get("event_date")

    # Checked as soon as a target exists, before the DB is ever touched --
    # a canary target is worth catching even if the request goes on to
    # find no evidence, since the manipulation already happened at
    # classification time.
    channel = channel_label(http_request)
    target_was_canary = check_for_canary(msisdn, None, user["username"], user["role"], client_ip, category=category, channel=channel)

    if not msisdn:
        pipeline.append(_pipeline_step("Classification", "error", "Aucun numéro client détecté"))
        log_event(
            "INVESTIGATE",
            username=user["username"],
            role=user["role"],
            details=f"text={text} -> FAILED: no MSISDN extracted, channel={channel}",
            ip_address=client_ip
        )
        return {
            "classification": classification,
            "pipeline": pipeline,
            "error": "No MSISDN could be extracted from the complaint text."
        }
    classification_confidence = classification.get("confidence")
    pipeline.append(_pipeline_step(
        "Classification", "ok",
        f"{category} — {_CONFIDENCE_LABEL_FR.get(classification_confidence, classification_confidence)}"
    ))

    # Anchor the investigation window on the date the complaint itself
    # states the event happened -- correct for both live complaints
    # (where this is recent) and historical/test complaints (where it
    # may be well in the past). The stated date is the EVENT date
    # (e.g. "Date d'expiration: le 02/08/2026"), not necessarily the
    # submission date, so it is used INCLUSIVELY as the end of the
    # window -- the expiration event itself is very plausibly logged
    # on that exact day, and excluding it would guarantee it can never
    # be found. Only falls back to "yesterday" when no date is
    # mentioned in the text at all (a live complaint with nothing
    # better to anchor on). The actual window size (5 days for voice,
    # matching the encadrant's real query) is applied inside
    # voice_service.py itself using this anchor.
    if event_date_str:
        anchor_date = date.fromisoformat(event_date_str)
    else:
        anchor_date = date.today() - timedelta(days=1)
    default_start_date = anchor_date - timedelta(days=20)

    investigation_result = run_investigation(
        category=category,
        msisdn=msisdn,
        start_date=default_start_date,
        end_date=anchor_date,
        da_value=da_value,
        target_amount=target_amount,
        target_volume_gb=target_volume_gb,
        anchor_date=anchor_date
    )

    if investigation_result.get("error"):
        pipeline.append(_pipeline_step("Recherche", "error", investigation_result["error"]))
        log_event(
            "INVESTIGATE",
            username=user["username"],
            role=user["role"],
            details=f"category={category}, msisdn={msisdn} -> ERROR: {investigation_result['error']}, channel={channel}",
            ip_address=client_ip
        )
        return {
            "classification": classification,
            "pipeline": pipeline,
            "error": investigation_result["error"]
        }

    # The real tiers actually tried (narrow bucket, broadened, cross-source,
    # ...) are recorded step by step inside the investigation service itself
    # (see e.g. voice_service.py) -- this is what makes the pipeline view
    # useful to a support agent instead of a single opaque "search ran" dot.
    pipeline.extend(investigation_result.get("trace", []))

    evidence = investigation_result.get("evidence", [])

    # Second check, on the actual rows returned: catches a case where the
    # extracted MSISDN looked legitimate but a manipulated/broadened query
    # pulled the canary row in anyway -- a real SQLi-via-prompt success,
    # not just an attempted one, which the first check (on the target
    # alone) can't see. Skipped when the target itself was already the
    # canary -- that's already logged above, checking evidence too would
    # just be a second, redundant entry for the same known trigger.
    if not target_was_canary:
        check_for_canary(msisdn, evidence, user["username"], user["role"], client_ip, category=category, channel=channel)

    search_tier = investigation_result.get("search_tier")
    note = investigation_result.get("note")
    match_confidence = investigation_result.get("confidence")
    evidence_coverage = investigation_result.get("evidence_coverage")

    try:
        explanation = explain_investigation(category, evidence, confidence=match_confidence)
    except Exception as exc:
        pipeline.append(_pipeline_step("Génération de l'explication", "error", str(exc)))
        log_event(
            "INVESTIGATE",
            username=user["username"],
            role=user["role"],
            details=f"category={category}, msisdn={msisdn} -> ERROR generating explanation: {exc}, channel={channel}",
            ip_address=client_ip
        )
        return {
            "classification": classification,
            "pipeline": pipeline,
            "error": "The AI could not generate an explanation from the evidence found."
        }

    # "Not enough evidence" is an honest, correct outcome, not a pipeline
    # failure -- it's gray (like an empty search tier), not red, and not
    # green either since there's nothing positive to report.
    if match_confidence:
        pipeline.append(_pipeline_step("Diagnostic", "ok", _DIAGNOSTIC_SYNTHESIS[match_confidence]))
    else:
        pipeline.append(_pipeline_step("Diagnostic", "empty", "Aucune preuve trouvée — résultat honnête, vérification manuelle recommandée."))

    log_id = log_event(
        "INVESTIGATE",
        username=user["username"],
        role=user["role"],
        details=f"category={category}, msisdn={msisdn}, da_value={da_value}, target_amount={target_amount}, target_volume_gb={target_volume_gb}, anchor={anchor_date}, search_tier={search_tier}, match_confidence={match_confidence}, evidence_coverage={evidence_coverage}, rows_returned={len(evidence) if evidence else 0}, channel={channel}",
        ip_address=client_ip
    )

    # Only persist a real "case file" when there's actual evidence to
    # reopen later -- a not_found result has nothing beyond what the
    # history row already shows, and persisting one would let the detail
    # view fake a page for an empty result.
    if evidence:
        save_investigation_result(log_id, explanation, note, evidence, complaint_text=text)

    return {
        "log_id": log_id,
        "classification": classification,
        "pipeline": pipeline,
        "evidence": evidence,
        "search_tier": search_tier,
        "search_note": note,
        "match_confidence": match_confidence,
        "evidence_coverage": evidence_coverage,
        "anchor_date": anchor_date.isoformat(),
        "explanation": explanation
    }


class VerifyCaseRequest(BaseModel):
    complaint_text: str
    category: str
    msisdn: Optional[str] = None
    da_value: Optional[str] = None


@app.post("/verify-case")
def verify_case(payload: VerifyCaseRequest, http_request: Request, user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    client_ip = http_request.client.host

    scan = inspect_prompt(payload.complaint_text)
    if scan["is_blocked"]:
        log_event(
            "SECURITY_ALERT",
            username=user["username"],
            role=user["role"],
            details=f"BLOCKED verify-case: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={payload.complaint_text}, channel={channel_label(http_request)}",
            ip_address=client_ip
        )
        check_and_apply_lockout(user["username"], user["role"], client_ip)
        raise HTTPException(status_code=403, detail={
            "message": "Request blocked by security gateway",
            "risk_score": scan["risk_score"],
            "matched_categories": [m["category"] for m in scan["matches"]],
        })
    elif scan["risk_score"] > 0:
        log_event(
            "SECURITY_FLAG",
            username=user["username"],
            role=user["role"],
            details=f"FLAGGED verify-case: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={payload.complaint_text}, channel={channel_label(http_request)}",
            ip_address=client_ip
        )

    save_verified_case(
        complaint_text=payload.complaint_text,
        category=payload.category,
        msisdn=payload.msisdn,
        da_value=payload.da_value,
        verified_by=user["username"]
    )

    log_event(
        "VERIFY_CASE",
        username=user["username"],
        role=user["role"],
        details=f"Verified case saved: category={payload.category}, msisdn={payload.msisdn}, da_value={payload.da_value}, channel={channel_label(http_request)}",
        ip_address=client_ip
    )

    return {"status": "saved"}


class UpdateCaseStatusRequest(BaseModel):
    status: str


@app.patch("/verify-case/{case_id}/status")
def verify_case_status(case_id: int, payload: UpdateCaseStatusRequest, http_request: Request,
                        user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    """
    Lets a reviewer move a previously-saved verified case to a different
    status after the fact -- e.g. "rejected" once a precedent turns out to
    be a coincidental match that should stop being used by case_memory.py's
    retrieval (see fetch_verified_cases), or "corrected" once a human fixes
    its category. This is the whole point of the STATUS field: without it,
    every row in TT_AI_VERIFIED_CASES looks equally trustworthy forever,
    even after someone learns otherwise.
    """
    client_ip = http_request.client.host

    if payload.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{payload.status}'. Must be one of: {sorted(VALID_STATUSES)}"
        )

    updated = update_case_status(case_id, payload.status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"No verified case found with id {case_id}")

    log_event(
        "VERIFY_CASE_STATUS_UPDATE",
        username=user["username"],
        role=user["role"],
        details=f"case_id={case_id} -> status={payload.status}, channel={channel_label(http_request)}",
        ip_address=client_ip
    )

    return {"case_id": case_id, "status": payload.status}


@app.get("/admin/audit-log")
def audit_log(limit: int = 20, user: dict = Depends(require_role("SECURITY_ANALYST"))):
    return {"events": get_recent_events(limit)}


@app.get("/admin/canary-events")
def canary_events(limit: int = 20, user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    """
    Deliberately narrower than /admin/audit-log (SECURITY_ANALYST-only):
    this only ever returns CANARY_TRIGGERED rows, so an account that just
    needs to see honeytoken hits -- ARC's redteam_runner, a SUPPORT_AGENT
    role -- doesn't need the broader analyst-only audit-log grant to see
    them.
    """
    return {"events": get_canary_events(limit)}


class CreateUserRequest(BaseModel):
    username: str
    role: str
    password: str


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    active: Optional[bool] = None


@app.get("/admin/users")
def admin_list_users(user: dict = Depends(require_role("SECURITY_ANALYST"))):
    return {"users": list_users()}


@app.post("/admin/users")
def admin_create_user(payload: CreateUserRequest, http_request: Request,
                       user: dict = Depends(require_role("SECURITY_ANALYST"))):
    try:
        create_user(payload.username, payload.role, payload.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_event(
        "USER_CREATED",
        username=user["username"], role=user["role"],
        details=f"created={payload.username}, role={payload.role}, channel={channel_label(http_request)}",
        ip_address=http_request.client.host,
    )
    return {"status": "created", "username": payload.username}


@app.patch("/admin/users/{username}")
def admin_update_user(username: str, payload: UpdateUserRequest, http_request: Request,
                       user: dict = Depends(require_role("SECURITY_ANALYST"))):
    if payload.active is False and username == user["username"]:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas désactiver votre propre compte.")

    if payload.role is not None:
        try:
            if not set_user_role(username, payload.role):
                raise HTTPException(status_code=404, detail=f"Utilisateur '{username}' introuvable.")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        log_event(
            "USER_ROLE_CHANGED",
            username=user["username"], role=user["role"],
            details=f"target={username}, new_role={payload.role}, channel={channel_label(http_request)}",
            ip_address=http_request.client.host,
        )

    if payload.active is not None:
        if not set_user_active(username, payload.active):
            raise HTTPException(status_code=404, detail=f"Utilisateur '{username}' introuvable.")
        log_event(
            "USER_ACTIVATED" if payload.active else "USER_DEACTIVATED",
            username=user["username"], role=user["role"],
            details=f"target={username}, channel={channel_label(http_request)}",
            ip_address=http_request.client.host,
        )

    return {"status": "updated", "username": username}


@app.post("/admin/users/{username}/unlock")
def admin_unlock_user(username: str, http_request: Request,
                       user: dict = Depends(require_role("SECURITY_ANALYST"))):
    if not unlock_user(username):
        raise HTTPException(status_code=404, detail=f"Utilisateur '{username}' introuvable.")

    log_event(
        "USER_UNLOCKED",
        username=user["username"], role=user["role"],
        details=f"target={username}, channel={channel_label(http_request)}",
        ip_address=http_request.client.host,
    )
    return {"status": "unlocked", "username": username}


@app.post("/admin/users/{username}/reset-password")
def admin_reset_password(username: str, http_request: Request,
                          user: dict = Depends(require_role("SECURITY_ANALYST"))):
    try:
        new_password = reset_password(username)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    log_event(
        "USER_PASSWORD_RESET",
        username=user["username"], role=user["role"],
        details=f"target={username}, channel={channel_label(http_request)}",
        ip_address=http_request.client.host,
    )
    return {"status": "reset", "username": username, "password": new_password}


@app.get("/admin/users/{username}/activity")
def admin_user_activity(username: str, user: dict = Depends(require_role("SECURITY_ANALYST"))):
    return {"activity": get_user_activity_admin(username, limit=20)}


@app.get("/investigations/history")
def investigation_history(limit: int = 50, category: Optional[str] = None, msisdn: Optional[str] = None,
                           user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    """
    Read-only list of past investigations, same role access as
    /investigate itself -- an agent reviewing what's already been
    checked doesn't need SECURITY_ANALYST clearance the way the raw
    /admin/audit-log (which includes security events, not just
    investigation outcomes) does.
    """
    return {"history": get_investigation_history(limit=limit, category=category, msisdn=msisdn)}


@app.get("/investigations/stats")
def investigation_stats(user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    """Today's count + a rough average-confidence indicator, for the New
    Investigation view's empty-state stats strip."""
    return get_investigation_stats()


@app.get("/investigations/{log_id}")
def investigation_detail(log_id: int, user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    """
    The full, original result behind one history row -- the explanation
    and evidence table as they actually were at investigate-time, not
    regenerated or re-run. 404 for anything never persisted: either it
    predates this feature, or it was a not_found result with no case
    file to open in the first place (see the "if evidence:" guard in
    /investigate).
    """
    result = get_investigation_result(log_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No investigation result found for id {log_id}")

    summary = get_investigation_summary(log_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"No investigation result found for id {log_id}")

    # None when this ticket has never been validated/corrected/rejected --
    # the detail view shows that as "not yet reviewed" rather than assuming
    # every investigation has a linked verified case (most don't, see
    # POST /investigations/{log_id}/verify).
    verification = get_verified_case_by_log_id(log_id)

    return {**summary, **result, "verification": verification}


class VerifyInvestigationRequest(BaseModel):
    status: str
    correction_note: Optional[str] = None


@app.post("/investigations/{log_id}/verify")
def verify_investigation(log_id: int, payload: VerifyInvestigationRequest, http_request: Request,
                          user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    """
    The ticket-detail counterpart to /verify-case: instead of an agent
    re-typing the complaint, category, and MSISDN by hand, this looks all
    of it up from the investigation itself (already scanned by the Gateway
    and persisted at /investigate time, see save_investigation_result) and
    either creates a new verified case linked to this LOG_ID or, if one
    already exists for this ticket, updates it in place -- so re-clicking
    Valider/Rejeter on the same ticket never creates duplicate precedent.

    Only "human_validated" and "rejected" are accepted here -- a ticket
    whose complaint text was actually wrong doesn't belong in case_memory
    at all under its original (bad) text, so that path is a separate
    action: see POST /investigations/{log_id}/correct, which re-runs the
    investigation for real instead of trying to "fix" a case in place.
    """
    client_ip = http_request.client.host
    allowed_statuses = {"human_validated", "rejected"}
    if payload.status not in allowed_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{payload.status}' for this action. Must be one of: {sorted(allowed_statuses)}"
        )

    result = get_investigation_result(log_id)
    summary = get_investigation_summary(log_id)
    if result is None or summary is None:
        raise HTTPException(status_code=404, detail=f"No investigation result found for id {log_id}")
    if not result.get("complaint_text"):
        raise HTTPException(
            status_code=409,
            detail="This investigation predates complaint-text persistence and cannot be linked to a verified case."
        )

    existing = get_verified_case_by_log_id(log_id)
    if existing is not None:
        update_case_status(existing["case_id"], payload.status, correction_note=payload.correction_note)
        case_id = existing["case_id"]
    else:
        save_verified_case(
            complaint_text=result["complaint_text"],
            category=summary.get("category"),
            msisdn=summary.get("msisdn"),
            da_value=summary.get("da_value"),
            verified_by=user["username"],
            status=payload.status,
            log_id=log_id,
            correction_note=payload.correction_note,
        )
        case_id = get_verified_case_by_log_id(log_id)["case_id"]

    log_event(
        "TICKET_VALIDATION_UPDATE",
        username=user["username"],
        role=user["role"],
        details=f"log_id={log_id}, case_id={case_id} -> status={payload.status}",
        ip_address=client_ip
    )

    return {"case_id": case_id, "status": payload.status, "correction_note": payload.correction_note}


class SendInvestigationEmailRequest(BaseModel):
    recipient: str
    subject: str
    body: str


@app.post("/investigations/{log_id}/send-email")
def send_investigation_email(log_id: int, payload: SendInvestigationEmailRequest, http_request: Request,
                              user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    """
    Sends a validated ticket's data by email from the agent's own linked
    account (see app/services/email_account.py). Deliberately re-checks
    "human_validated" server-side rather than trusting that the frontend
    only shows this button on a validated ticket -- the button hiding is
    a UX convenience, not the actual access control.
    """
    verification = get_verified_case_by_log_id(log_id)
    if verification is None or verification["status"] != "human_validated":
        raise HTTPException(status_code=403, detail="Seuls les dossiers validés peuvent être envoyés par email.")

    try:
        sender_email = send_email(user["username"], payload.recipient, payload.subject, payload.body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (smtplib.SMTPException, OSError) as e:
        raise HTTPException(status_code=400, detail=f"Échec de l'envoi : {e}")

    log_event(
        "EMAIL_SENT",
        username=user["username"],
        role=user["role"],
        details=f"log_id={log_id}, recipient={payload.recipient}, sender={sender_email}, channel={channel_label(http_request)}",
        ip_address=http_request.client.host,
    )

    return {"status": "sent", "recipient": payload.recipient, "sender": sender_email}


class CorrectInvestigationRequest(BaseModel):
    new_log_id: int


@app.post("/investigations/{log_id}/correct")
def correct_investigation(log_id: int, payload: CorrectInvestigationRequest, http_request: Request,
                           user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    """
    Marks this ticket as superseded by a real re-investigation -- the
    frontend edits the complaint text and fires an ordinary /investigate
    call first (full Gateway scan, classification, search, the whole real
    pipeline), then calls this endpoint with the resulting new_log_id to
    link the two. This never rewrites this ticket's own EXPLANATION/
    EVIDENCE_JSON/audit entry -- both are append-only/tamper-evident by
    design (see mark_superseded's docstring) -- it only records "the real
    answer is over here now".
    """
    client_ip = http_request.client.host

    if get_investigation_result(log_id) is None:
        raise HTTPException(status_code=404, detail=f"No investigation result found for id {log_id}")
    if get_investigation_result(payload.new_log_id) is None:
        raise HTTPException(status_code=404, detail=f"No investigation result found for new_log_id {payload.new_log_id}")

    mark_superseded(log_id, payload.new_log_id)

    log_event(
        "TICKET_CORRECTED",
        username=user["username"],
        role=user["role"],
        details=f"log_id={log_id} -> superseded_by_log_id={payload.new_log_id}",
        ip_address=client_ip
    )

    return {"log_id": log_id, "superseded_by_log_id": payload.new_log_id}
