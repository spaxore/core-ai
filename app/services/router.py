from app.services.voice_service import investigate_voice_expiration
from app.services.sms_service import investigate_sms_vas
from app.services.data_service import investigate_data_usage
from app.services.sos_service import investigate_sos_credit
from app.services.balance_deduction_service import investigate_balance_deduction


def run_investigation(category, msisdn, start_date, end_date, da_value=None, target_amount=None, target_volume_gb=None, anchor_date=None):
    """
    Returns a consistent shape for every category:
    {"evidence": [...], "search_tier": str, "da_value_used": str|None, "note": str|None}

    anchor_date, when given, is the complaint's own stated event date
    (or "yesterday" if no date was mentioned) -- the anchor the adaptive
    date-window search is built around. VOICE_EXPIRATION/DATA_USAGE/
    SMS_VAS/SOS_CREDIT each try their own category-specific narrow(single
    day)-then-broaden(window) search first, and fall back to checking
    every other source (app/services/cross_source_search.py) before
    reporting not_found -- a complaint naming the wrong bucket still
    gets solved if the real cause is elsewhere. BALANCE_DEDUCTION names
    no mechanism at all, so it goes straight to that cross-source search.
    """
    if category == "VOICE_EXPIRATION":
        return investigate_voice_expiration(msisdn, start_date, end_date, da_value, target_amount, anchor_date)

    elif category == "SMS_VAS":
        return investigate_sms_vas(msisdn, start_date, end_date, target_amount, anchor_date)

    elif category == "DATA_USAGE":
        return investigate_data_usage(msisdn, start_date, end_date, da_value, target_volume_gb, anchor_date, target_amount)

    elif category == "SOS_CREDIT":
        return investigate_sos_credit(msisdn, start_date, end_date, target_amount, anchor_date)

    elif category == "BALANCE_DEDUCTION":
        return investigate_balance_deduction(msisdn, start_date, end_date, target_amount, anchor_date)

    else:
        return {"evidence": [], "search_tier": "unknown_category", "da_value_used": None, "note": None,
                "error": f"Unknown category: {category}"}
