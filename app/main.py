from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from app.ai.ollama_client import ask_ollama
from app.ai.classifier import classify_complaint
from app.ai.explainer import explain_investigation
from app.ai.case_memory import save_verified_case, update_case_status, get_verified_case_by_log_id, VALID_STATUSES
from app.services.router import run_investigation
from app.services.investigation_results import save_investigation_result, get_investigation_result, mark_superseded
from app.security.dependencies import get_current_user, require_role
from app.security.audit import get_recent_events, get_investigation_history, get_investigation_stats, get_investigation_summary
from app.security.audit import log_event
from app.security.gateway import inspect_prompt
from app.security.lockout import check_and_apply_lockout
from datetime import date, timedelta
from app.routes.auth_routes import router as auth_router

app = FastAPI(
    title="Secure TT AI Agent",
    description="AI assistant for Tunisia Telecom complaint analysis",
    version="1.0"
)
app.include_router(auth_router)

@app.get("/")
def home():
    return {
        "status": "running",
        "project": "Secure TT AI Agent"
    }

@app.get("/ui", response_class=HTMLResponse)
def ui():
    with open("app/static_ui.html", "r", encoding="utf-8") as f:
        return f.read()

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
            details=f"BLOCKED classify: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={text}",
            ip_address=client_ip
        )
        check_and_apply_lockout(user["username"], user["role"], client_ip)
        raise HTTPException(status_code=403, detail="Request blocked by security gateway")
    elif scan["risk_score"] > 0:
        log_event(
            "SECURITY_FLAG",
            username=user["username"],
            role=user["role"],
            details=f"FLAGGED classify: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={text}",
            ip_address=client_ip
        )

    result = classify_complaint(text)

    log_event(
        "CLASSIFY",
        username=user["username"],
        role=user["role"],
        details=f"text={text} -> category={result.get('category')}, msisdn={result.get('msisdn')}, da_value={result.get('da_value')}",
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
            details=f"BLOCKED investigate: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={text}",
            ip_address=client_ip
        )
        check_and_apply_lockout(user["username"], user["role"], client_ip)
        raise HTTPException(status_code=403, detail="Request blocked by security gateway")
    elif scan["risk_score"] > 0:
        log_event(
            "SECURITY_FLAG",
            username=user["username"],
            role=user["role"],
            details=f"FLAGGED investigate: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={text}",
            ip_address=client_ip
        )

    classification = classify_complaint(text)
    category = classification.get("category")
    msisdn = classification.get("msisdn")
    da_value = classification.get("da_value")
    target_amount = classification.get("target_amount")
    target_volume_gb = classification.get("target_volume_gb")
    event_date_str = classification.get("event_date")

    if not msisdn:
        pipeline.append(_pipeline_step("Classification", "error", "Aucun numéro client détecté"))
        log_event(
            "INVESTIGATE",
            username=user["username"],
            role=user["role"],
            details=f"text={text} -> FAILED: no MSISDN extracted",
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
            details=f"category={category}, msisdn={msisdn} -> ERROR: {investigation_result['error']}",
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
            details=f"category={category}, msisdn={msisdn} -> ERROR generating explanation: {exc}",
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
        details=f"category={category}, msisdn={msisdn}, da_value={da_value}, target_amount={target_amount}, target_volume_gb={target_volume_gb}, anchor={anchor_date}, search_tier={search_tier}, match_confidence={match_confidence}, evidence_coverage={evidence_coverage}, rows_returned={len(evidence) if evidence else 0}",
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
            details=f"BLOCKED verify-case: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={payload.complaint_text}",
            ip_address=client_ip
        )
        check_and_apply_lockout(user["username"], user["role"], client_ip)
        raise HTTPException(status_code=403, detail="Request blocked by security gateway")
    elif scan["risk_score"] > 0:
        log_event(
            "SECURITY_FLAG",
            username=user["username"],
            role=user["role"],
            details=f"FLAGGED verify-case: score={scan['risk_score']} matches={[m['category'] for m in scan['matches']]} text={payload.complaint_text}",
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
        details=f"Verified case saved: category={payload.category}, msisdn={payload.msisdn}, da_value={payload.da_value}",
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
        details=f"case_id={case_id} -> status={payload.status}",
        ip_address=client_ip
    )

    return {"case_id": case_id, "status": payload.status}


@app.get("/admin/audit-log")
def audit_log(limit: int = 20, user: dict = Depends(require_role("SECURITY_ANALYST"))):
    return {"events": get_recent_events(limit)}


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
