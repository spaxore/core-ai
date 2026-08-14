from app.services.cross_source_search import search_all_sources


def investigate_balance_deduction(msisdn, start_date, end_date, target_amount=None, anchor_date=None):
    """
    BALANCE_DEDUCTION complaints, by the classifier's own definition,
    name no VAS subscription, forfait, or service as the cause -- the
    customer only knows their balance dropped by some amount. Unlike
    the other four categories, there's no "obvious fact" to start from,
    so this goes straight to checking every real charge-generating
    source for this MSISDN (voice, data, SMS/VAS, SOS credit) for
    whatever actually explains the stated amount.

    If nothing in any source explains it even after broadening the
    window, this honestly reports search_tier="not_found" -- "not
    enough evidence to support this ticket" -- rather than presenting
    an unrelated total as the answer.
    """
    result, trace = search_all_sources(msisdn, start_date, end_date, target_amount, anchor_date)
    if result is not None:
        result["trace"] = trace
        return result

    if target_amount is None:
        return {
            "evidence": [],
            "search_tier": "no_target_amount",
            "da_value_used": None,
            "note": "No DT amount could be extracted from the complaint to search for.",
            "trace": trace,
        }

    return {
        "evidence": [],
        "search_tier": "not_found",
        "da_value_used": None,
        "note": f"Checked voice, data, SMS/VAS and SOS credit, single day and broadened window {start_date}..{end_date} -- nothing explains the stated amount of {target_amount} DT. Not enough evidence to support this ticket; manual verification recommended.",
        "trace": trace,
    }
