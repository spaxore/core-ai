"""
Cross-table search: what a support agent actually does when a customer
reports a DT amount without being sure of the cause. The customer's
stated category/bucket is a starting hypothesis, not ground truth --
they don't have visibility into which system actually charged them, so
this checks every real charge-generating source for this MSISDN (voice,
data, SMS/VAS, SOS credit) for whatever explains the stated amount,
narrow (single day) before broad (the caller's window), across all
four sources before giving up.

Matches carry a confidence level (see find_best_match) rather than
being silently discarded when weak. A support agent seeing a LOW
confidence lead -- e.g. a total that only loosely fits, spread across
several unrelated buckets -- can judge for themselves whether to chase
it; hiding it behind a flat "not found" throws away information the
agent might actually want. Both passes (single day, then broadened) are
always run and the single best candidate across all of it is returned,
so a strong match found while broadening isn't shadowed by a weak one
found on the single day.

Used two ways:
- As the primary (only) strategy for BALANCE_DEDUCTION, which by
  definition has no named mechanism to start from.
- As a final fallback tier for the other four categories: if a
  complaint names DA4 but DA4 genuinely doesn't explain the amount,
  this checks whether it was actually a data session, an SMS+ charge,
  or an SOS credit recovery instead, before honestly giving up.
"""
from app.database.oracle import get_connection
from app.services.investigation_helpers import find_best_match, compute_evidence_coverage

SOURCES = ["VOICE", "DATA", "SMS_VAS", "SOS_CREDIT"]
CONFIDENCE_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def _query_source(cursor, source, msisdn, start_date, end_date):
    from app.services.voice_service import _run_voice_query
    from app.services.data_service import _run_data_query
    from app.services.sms_service import _run_sms_query
    from app.services.sos_service import _run_sos_query

    if source == "VOICE":
        return _run_voice_query(cursor, msisdn, start_date, end_date, None)
    if source == "DATA":
        return _run_data_query(cursor, msisdn, start_date, end_date, None)
    if source == "SMS_VAS":
        return _run_sms_query(cursor, msisdn, start_date, end_date)
    if source == "SOS_CREDIT":
        return _run_sos_query(cursor, msisdn, start_date, end_date)
    return []


def search_all_sources(msisdn, start_date, end_date, target_amount, anchor_date=None):
    """
    Returns a result dict ({"evidence", "search_tier", "da_value_used",
    "confidence", "note"}) if some source explains target_amount even
    weakly, or None if nothing in any of the four sources does at all
    -- callers decide how to report that (BALANCE_DEDUCTION reports it
    as its own not_found; the other categories fold it into their
    existing not_found note).

    Each matched row is tagged with "_SOURCE" so the evidence table is
    self-explanatory about which system actually caused the deduction,
    since that's very often not what the customer assumed.
    """
    if target_amount is None:
        return None

    single_day = anchor_date if anchor_date is not None else end_date

    connection = get_connection()
    cursor = connection.cursor()

    candidates = []
    for tier, s_date, e_date in (
        ("cross_source_single_day", single_day, single_day),
        ("cross_source_broadened", start_date, end_date),
    ):
        for source in SOURCES:
            rows = _query_source(cursor, source, msisdn, s_date, e_date)
            match = find_best_match(rows, target_amount)
            if match is not None:
                candidates.append((tier, source, s_date, e_date, match))

    cursor.close()
    connection.close()

    if not candidates:
        return None

    tier, source, s_date, e_date, match = max(
        candidates,
        key=lambda c: (CONFIDENCE_RANK[c[4]["confidence"]], c[0] == "cross_source_single_day"),
    )

    for row in match["matched_rows"]:
        row["_SOURCE"] = source

    # Recomputed after _SOURCE tagging above (find_best_match ran before the
    # rows were tagged), so a full_period_total match spanning several
    # cross-source rows correctly counts them as distinct sources here, not
    # just distinct DA/LOAN buckets.
    evidence_coverage = compute_evidence_coverage(match["matched_rows"])

    confidence = match["confidence"]
    caveat = " -- treat as a possible lead, not a confirmed cause" if confidence == "LOW" else ""
    window_desc = str(single_day) if tier == "cross_source_single_day" else f"{s_date}..{e_date}"

    return {
        "evidence": match["matched_rows"],
        "search_tier": tier,
        "da_value_used": None,
        "confidence": confidence,
        "evidence_coverage": evidence_coverage,
        "note": f"Matched via {match['match_type']} in {source} ({window_desc}), confidence={confidence} -- not necessarily the mechanism the customer described{caveat}.",
    }


def try_cross_source_fallback(msisdn, start_date, end_date, target_amount, anchor_date, own_not_found_note):
    """
    Used by the other four categories as a final tier: if their own
    category-specific search didn't explain the amount, check whether
    another source does before giving up -- mirrors how a support
    agent actually works (check the obvious fact, narrow down, check
    everywhere else, and only report "not enough evidence" once every
    source has been checked). Returns a result dict either way: the
    cross-source match if one exists (at whatever confidence), or the
    category's own not_found dict (unchanged) if nothing anywhere
    explains the amount even weakly.
    """
    fallback = search_all_sources(msisdn, start_date, end_date, target_amount, anchor_date)
    if fallback is not None:
        return fallback
    return {
        "evidence": [],
        "search_tier": "not_found",
        "da_value_used": None,
        "note": own_not_found_note,
    }
