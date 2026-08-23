"""
Canary/honeytoken detection.

Everything else in the security layer inspects the request text (the
Gateway's pattern matching) or the account's history (the lockout
mechanisms). Nothing watches whether an attack actually reaches the data.

This is that check: CANARY_MSISDN is a fabricated number, seeded once
into the CDR tables (see scripts/seed_honeytoken.py), that no real
complaint can ever legitimately reference -- it isn't a real customer, so
under normal operation it should never be the investigation's target nor
appear in a result set. If it ever does, either the MSISDN extraction was
manipulated (a prompt-injection redirect) or a query was broadened beyond
its normal single-MSISDN parameterized shape (a real SQLi-via-prompt
success) -- both are outcomes the Gateway's text-only inspection
structurally cannot see for itself.
"""
from app.security.audit import log_event
from app.security.lockout import REDTEAM_EXEMPT_USERS, apply_immediate_lockout

# Outside real Tunisian MSISDN allocation ranges, so it can never collide
# with an actual customer number now or after a future numbering-plan
# change.
CANARY_MSISDN = "21600000000"


def check_for_canary(msisdn, evidence, username, role, client_ip, category=None, channel="standard"):
    """
    Call once right after MSISDN extraction (evidence=None is fine -- a
    manipulated target is worth catching even before any DB call runs)
    and again once evidence rows come back, so a canary surfacing only
    inside a broadened query -- not as the extracted target itself -- is
    caught too. Returns True if the canary was found.

    `category`/`channel` are logged as key=value pairs, the same
    convention every other audit DETAILS string in this codebase already
    uses (see _extract_field/_parse_investigation_details in audit.py) --
    ARC's Canary Alerts screen parses both back out to show what category
    of investigation was targeted and which channel the trigger came
    through.
    """
    triggered = msisdn == CANARY_MSISDN or any(
        CANARY_MSISDN in str(value)
        for row in (evidence or [])
        for value in row.values()
    )
    if not triggered:
        return False

    log_event(
        "CANARY_TRIGGERED",
        username=username,
        role=role,
        details=f"category={category}, msisdn={msisdn}, channel={channel}",
        ip_address=client_ip,
    )

    # redteam_runner is expected to trip this during authorized attack
    # runs -- log and alert, but don't lock, or every successful test
    # attack would interrupt the suite it's part of. Any other account
    # gets locked immediately; apply_immediate_lockout() also checks
    # REDTEAM_EXEMPT_USERS itself, this check just avoids the log noise
    # of calling it for an account we already know is exempt.
    if username not in REDTEAM_EXEMPT_USERS:
        apply_immediate_lockout(username, role, client_ip, reason="honeytoken MSISDN surfaced")

    return True
