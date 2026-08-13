from app.database.oracle import get_connection
from app.services.investigation_helpers import find_best_match


def _run_sms_query(cursor, msisdn, start_date, end_date):
    query = """
        SELECT A_MSISDN, B_MSISDN, START_DATE, CALL_TYPE,
               SUBSCRIBER_TYPE, CHARGE_AMOUNT, KEYWORD
        FROM rd_t_uc_occpp_sms_vas_dt
        WHERE A_MSISDN = :msisdn
          AND START_DATE BETWEEN :start_date AND :end_date
    """
    cursor.execute(query, {
        "msisdn": msisdn,
        "start_date": start_date,
        "end_date": end_date
    })
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def investigate_sms_vas(msisdn, start_date, end_date, target_amount=None, anchor_date=None):
    """
    Same narrow-then-broaden strategy as the other categories. SMS+/VAS
    subscription charges are small, recurring per-event debits (real
    imported data: 0.3-0.6 DT per event) with no DA-bucket dimension --
    unlike voice/data, FLEX_FLD1/2/3 on this table are always 0 in the
    real imported data, so there is no bucket to narrow by. The
    complaint's stated DT total is usually several days of accumulated
    charges (matches the classifier's own known example: "abonnement
    100 SECONDES, 0.7 dinar/jour"), so this tries the single day first,
    then the wider window the caller supplied if that alone doesn't
    explain the stated amount.

    If nothing in either window explains the stated amount, this
    honestly reports search_tier="not_found" rather than presenting an
    unrelated total as if it were the answer.
    """
    single_day = anchor_date if anchor_date is not None else end_date

    connection = get_connection()
    cursor = connection.cursor()

    tier1_evidence = _run_sms_query(cursor, msisdn, single_day, single_day)

    if target_amount is None:
        cursor.close()
        connection.close()
        return {
            "evidence": tier1_evidence,
            "search_tier": "narrow_single_day",
            "da_value_used": None,
            "note": None,
        }

    match = find_best_match(tier1_evidence, target_amount)
    if match is not None:
        cursor.close()
        connection.close()
        return {
            "evidence": match["matched_rows"],
            "search_tier": "narrow_single_day",
            "da_value_used": None,
            "confidence": match["confidence"],
            "note": f"Matched via {match['match_type']} on {single_day}",
        }

    tier2_evidence = _run_sms_query(cursor, msisdn, start_date, end_date)
    cursor.close()
    connection.close()

    match2 = find_best_match(tier2_evidence, target_amount)
    if match2 is not None:
        return {
            "evidence": match2["matched_rows"],
            "search_tier": "broadened_date_range",
            "da_value_used": None,
            "confidence": match2["confidence"],
            "note": f"Single-day search did not explain the stated amount. Broadened to {start_date}..{end_date} matched via {match2['match_type']}.",
        }

    from app.services.cross_source_search import try_cross_source_fallback
    return try_cross_source_fallback(
        msisdn, start_date, end_date, target_amount, anchor_date,
        f"Neither the single-day search, the broadened window {start_date}..{end_date}, nor any other source found evidence explaining the stated amount of {target_amount} DT. Manual verification recommended.",
    )
