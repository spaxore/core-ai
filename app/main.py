from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from app.ai.ollama_client import ask_ollama
from app.ai.classifier import classify_complaint
from app.ai.explainer import explain_investigation
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
        details=f"text={text} -> category={result.get('category')}, msisdn={result.get('msisdn')}",
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

    end_date = date.today()
    start_date = end_date - timedelta(days=60)
    evidence = run_investigation(
        category=category,
        msisdn=msisdn,
        start_date=start_date,
        end_date=end_date
    )
    explanation = explain_investigation(category, evidence)

    log_event(
        "INVESTIGATE",
        username=user["username"],
        role=user["role"],
        details=f"category={category}, msisdn={msisdn}, rows_returned={len(evidence) if evidence else 0}",
        ip_address=client_ip
    )

    return {
        "classification": classification,
        "evidence": evidence,
        "explanation": explanation
    }



@app.get("/admin/audit-log")
def audit_log(limit: int = 20, user: dict = Depends(require_role("SECURITY_ANALYST"))):
    return {"events": get_recent_events(limit)}
