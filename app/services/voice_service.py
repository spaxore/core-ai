from datetime import timedelta

from app.database.oracle import get_connection
from app.services.investigation_helpers import find_best_match, skip_trace_step
from app.services.cross_source_search import CROSS_SOURCE_TIER_LABELS


def _skip_cross_source(trace):
    trace.append(skip_trace_step(CROSS_SOURCE_TIER_LABELS["cross_source_single_day"]))
    trace.append(skip_trace_step(CROSS_SOURCE_TIER_LABELS["cross_source_broadened"]))

# 5-day window, matching the real query the encadrant uses for voice
# investigations (start_date BETWEEN '01/07/2026' AND '05/07/2026' --
# a 5-day span ending at the investigation point). Not invented: this
# is the actual window size observed in a real, working query.
VOICE_WINDOW_DAYS = 5


def _run_voice_query(cursor, msisdn, start_date, end_date, da_value):
    if da_value is not None:
        query = """
            SELECT
                start_date,
                a_msisdn,
                call_type,
                da_value,
                da_value_before,
                da_value_after,
                main_value_before,
                main_value_after,
                charge_amount
            FROM rd_t_uc_ccn_ro_gprs_cdr_detail
            WHERE a_msisdn = :msisdn
              AND start_date BETWEEN :start_date AND :end_date
              AND call_type = 'VOICE'
              AND da_value = :da_value
            ORDER BY start_date DESC
        """
        cursor.execute(query, {
            "msisdn": msisdn,
            "start_date": start_date,
            "end_date": end_date,
            "da_value": da_value
        })
    else:
        query = """
            SELECT
                start_date,
                a_msisdn,
                call_type,
                da_value,
                da_value_before,
                da_value_after,
                main_value_before,
                main_value_after,
                charge_amount
            FROM rd_t_uc_ccn_ro_gprs_cdr_detail
            WHERE a_msisdn = :msisdn
              AND start_date BETWEEN :start_date AND :end_date
              AND call_type = 'VOICE'
            ORDER BY start_date DESC
        """
        cursor.execute(query, {
            "msisdn": msisdn,
            "start_date": start_date,
            "end_date": end_date
        })

    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def investigate_voice_expiration(msisdn, start_date, end_date, da_value=None, target_amount=None, anchor_date=None):
    """
    Investigation, matching the encadrant's real manual process:

    - Window: a single 5-day span ending the day before the complaint's
      own stated event date (anchor_date), or the day before "today" if
      no date was mentioned. This mirrors the real query's window size
      and boundary -- not an invented range.

    - DA-bucket filter: if the complaint named a DA bucket, search only
      that bucket first, then check whether the evidence actually
      explains the stated amount. If not, drop the filter and search
      all voice records for this customer in the same window -- this
      mirrors the encadrant literally commenting the DA filter in and
      out of the same query.

    If nothing in the window explains the stated amount even after
    dropping the DA filter, this checks every other source (data,
    SMS/VAS, SOS credit -- see cross_source_search.py) before giving
    up, since the customer naming "DA4" doesn't mean DA4 is actually
    where the money went. Only if nothing anywhere explains it does
    this report search_tier="not_found", rather than presenting an
    unrelated total as if it were the answer.
    """
    if anchor_date is not None:
        end_date = anchor_date
        start_date = end_date - timedelta(days=VOICE_WINDOW_DAYS - 1)

    connection = get_connection()
    cursor = connection.cursor()
    trace = []

    if da_value is not None:
        tier1_evidence = _run_voice_query(cursor, msisdn, start_date, end_date, da_value)

        if target_amount is None:
            cursor.close()
            connection.close()
            return {
                "evidence": tier1_evidence,
                "search_tier": "narrow_da_filtered",
                "da_value_used": da_value,
                "note": None,
                "trace": trace,
            }

        match = find_best_match(tier1_evidence, target_amount)
        if match is not None:
            trace.append({"label": f"Recherche ciblée — bucket DA{da_value}", "status": "ok",
                           "detail": f"Correspondance trouvée via {match['match_type']}"})
            trace.append(skip_trace_step("Recherche élargie — tous buckets"))
            _skip_cross_source(trace)
            cursor.close()
            connection.close()
            return {
                "evidence": match["matched_rows"],
                "search_tier": "narrow_da_filtered",
                "da_value_used": da_value,
                "confidence": match["confidence"],
                "evidence_coverage": match["evidence_coverage"],
                "note": f"Matched via {match['match_type']} within DA{da_value}",
                "trace": trace,
            }
        trace.append({"label": f"Recherche ciblée — bucket DA{da_value}", "status": "empty",
                       "detail": "N'explique pas le montant déclaré"})

        tier2_evidence = _run_voice_query(cursor, msisdn, start_date, end_date, None)
        cursor.close()
        connection.close()

        match2 = find_best_match(tier2_evidence, target_amount)
        if match2 is not None:
            trace.append({"label": "Recherche élargie — tous buckets", "status": "ok",
                           "detail": f"Correspondance trouvée via {match2['match_type']}"})
            _skip_cross_source(trace)
            return {
                "evidence": match2["matched_rows"],
                "search_tier": "broadened_no_da_filter",
                "da_value_used": None,
                "confidence": match2["confidence"],
                "evidence_coverage": match2["evidence_coverage"],
                "note": f"DA{da_value}-filtered search did not explain the stated amount. Broadened search matched via {match2['match_type']}.",
                "trace": trace,
            }
        trace.append({"label": "Recherche élargie — tous buckets", "status": "empty",
                       "detail": "N'explique toujours pas le montant déclaré"})

        from app.services.cross_source_search import try_cross_source_fallback
        return try_cross_source_fallback(
            msisdn, start_date, end_date, target_amount, anchor_date,
            f"Neither the DA{da_value}-filtered search, the broadened search, nor any other source (window {start_date}..{end_date}) found evidence explaining the stated amount of {target_amount} DT. Manual verification recommended.",
            trace=trace,
        )

    evidence = _run_voice_query(cursor, msisdn, start_date, end_date, None)
    cursor.close()
    connection.close()

    if target_amount is None:
        return {
            "evidence": evidence,
            "search_tier": "broad_no_da_named",
            "da_value_used": None,
            "note": None,
            "trace": trace,
        }

    match = find_best_match(evidence, target_amount)
    if match is not None:
        trace.append({"label": "Recherche — toutes les données voix", "status": "ok",
                       "detail": f"Correspondance trouvée via {match['match_type']}"})
        _skip_cross_source(trace)
        return {
            "evidence": match["matched_rows"],
            "search_tier": "broad_no_da_named",
            "da_value_used": None,
            "confidence": match["confidence"],
            "evidence_coverage": match["evidence_coverage"],
            "note": f"Matched via {match['match_type']}",
            "trace": trace,
        }
    trace.append({"label": "Recherche — toutes les données voix", "status": "empty",
                   "detail": "N'explique pas le montant déclaré"})

    from app.services.cross_source_search import try_cross_source_fallback
    return try_cross_source_fallback(
        msisdn, start_date, end_date, target_amount, anchor_date,
        f"No evidence found explaining the stated amount of {target_amount} DT in window {start_date}..{end_date}, in voice or any other source. Manual verification recommended.",
        trace=trace,
    )
