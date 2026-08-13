from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.ai.ollama_client import ask_ollama
from app.ai.classifier import classify_complaint
from app.ai.explainer import explain_investigation
from app.ai.case_memory import save_verified_case
from app.services.router import run_investigation
from app.security.dependencies import get_current_user, require_role
from app.security.audit import get_recent_events
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

@app.post("/investigate")
def investigate(complaint: dict, http_request: Request, user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    text = complaint.get("text", "")
    client_ip = http_request.client.host

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
        log_event(
            "INVESTIGATE",
            username=user["username"],
            role=user["role"],
            details=f"text={text} -> FAILED: no MSISDN extracted",
            ip_address=client_ip
        )
        return {
            "classification": classification,
            "error": "No MSISDN could be extracted from the complaint text."
        }

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
        log_event(
            "INVESTIGATE",
            username=user["username"],
            role=user["role"],
            details=f"category={category}, msisdn={msisdn} -> ERROR: {investigation_result['error']}",
            ip_address=client_ip
        )
        return {
            "classification": classification,
            "error": investigation_result["error"]
        }

    evidence = investigation_result.get("evidence", [])
    search_tier = investigation_result.get("search_tier")
    note = investigation_result.get("note")
    match_confidence = investigation_result.get("confidence")

    explanation = explain_investigation(category, evidence, confidence=match_confidence)

    log_event(
        "INVESTIGATE",
        username=user["username"],
        role=user["role"],
        details=f"category={category}, msisdn={msisdn}, da_value={da_value}, target_amount={target_amount}, target_volume_gb={target_volume_gb}, anchor={anchor_date}, search_tier={search_tier}, match_confidence={match_confidence}, rows_returned={len(evidence) if evidence else 0}",
        ip_address=client_ip
    )

    return {
        "classification": classification,
        "evidence": evidence,
        "search_tier": search_tier,
        "search_note": note,
        "match_confidence": match_confidence,
        "anchor_date": anchor_date.isoformat(),
        "explanation": explanation
    }


class VerifyCaseRequest(BaseModel):
    complaint_text: str
    category: str
    msisdn: str = None
    da_value: str = None


@app.post("/verify-case")
def verify_case(payload: VerifyCaseRequest, http_request: Request, user: dict = Depends(require_role("SUPPORT_AGENT", "SECURITY_ANALYST"))):
    client_ip = http_request.client.host

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


@app.get("/admin/audit-log")
def audit_log(limit: int = 20, user: dict = Depends(require_role("SECURITY_ANALYST"))):
    return {"events": get_recent_events(limit)}
