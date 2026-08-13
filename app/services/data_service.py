from datetime import timedelta

from app.database.oracle import get_connection
from app.services.investigation_helpers import find_best_match

# DATA_VOLUME is stored in KB (inferred from real imported CDR data --
# single-session records for a heavy data user cluster around ~29,569,
# consistent with a ~29 MB partial-record volume trigger, and daily
# totals land in the single-digit-GB range once divided by 1024*1024).
# target_volume_gb comes from the complaint text in GB, so it is
# converted to KB before being compared against DATA_VOLUME.
KB_PER_GB = 1024 * 1024

# FLEX_FLD1 (balance before) and FLEX_FLD3 (balance after) form a
# running DT ledger for the named DA bucket -- confirmed, not guessed:
# FLEX_FLD1 - FLEX_FLD3 == CHARGE_AMOUNT on 100% of 3,902 real rows
# checked for DA bucket 7 on MSISDN 21692641320 (the same before/after
# balance-swing shape voice_service.py already relies on via
# DA_VALUE_BEFORE/DA_VALUE_AFTER, just relabeled in this table). That
# ledger drains toward zero and then jumps back up when the bucket is
# recharged -- a real, ledger-evidenced billing-cycle boundary, not a
# calendar assumption. _find_cycle_start() detects the most recent such
# jump at or before the anchor date and uses it as the window for the
# broadened search, which is what actually explains stated GB figures
# that don't fit in a single day (a bucket's full-cycle consumption is
# what the customer is describing, not one day's traffic).
# Real recharges observed in the imported data jump the balance by
# thousands of DT (0 -> 13107.2 on the 01/08 reset). Ordinary
# concurrent-session noise at day boundaries -- multiple simultaneous
# PDP sessions each snapshotting the balance and landing in slightly
# non-chronological order -- only ever produces jumps in the tens of DT
# (observed: 29.7, 44.4, 74.0). 500 sits well above that noise ceiling
# and well below the smallest real recharge seen, so it separates the
# two without being tuned to any particular GB figure.
CYCLE_LOOKBACK_DAYS = 60
CYCLE_RESET_THRESHOLD_DT = 500.0


def _run_data_query(cursor, msisdn, start_date, end_date, flex_fld2):
    if flex_fld2 is not None:
        query = """
            SELECT
                a_msisdn,
                start_date,
                roaming_type,
                data_volume,
                charge_amount,
                flex_fld2
            FROM rd_t_uc_occpp_data_dt
            WHERE a_msisdn = :msisdn
              AND start_date BETWEEN :start_date AND :end_date
              AND call_type = 'DATA'
              AND flex_fld2 = :flex_fld2
            ORDER BY start_date DESC
        """
        cursor.execute(query, {
            "msisdn": msisdn,
            "start_date": start_date,
            "end_date": end_date,
            "flex_fld2": flex_fld2
        })
    else:
        query = """
            SELECT
                a_msisdn,
                start_date,
                roaming_type,
                data_volume,
                charge_amount,
                flex_fld2
            FROM rd_t_uc_occpp_data_dt
            WHERE a_msisdn = :msisdn
              AND start_date BETWEEN :start_date AND :end_date
              AND call_type = 'DATA'
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


def _find_cycle_start(cursor, msisdn, flex_fld2, anchor_date):
    """
    Finds the start of the DA bucket's current ledger cycle: the most
    recent date on or before anchor_date where the bucket's DT balance
    (see module comment) jumps back up after having drained toward
    zero -- a recharge/reset rather than ordinary session-by-session
    depletion. Detected directly from the ledger, not assumed from a
    calendar rule.

    Returns the reset date, or None if no reset is found within
    CYCLE_LOOKBACK_DAYS (e.g. not enough history imported).
    """
    # FLEX_FLD1/FLEX_FLD3 are VARCHAR2 in the real schema (confirmed via
    # DESC, see import_real_data.py), so MAX()/MIN() without a cast would
    # do lexicographic string comparison instead of numeric -- TO_NUMBER
    # is required for this to mean anything.
    lookback_start = anchor_date - timedelta(days=CYCLE_LOOKBACK_DAYS)
    query = """
        SELECT start_date, MAX(TO_NUMBER(flex_fld1)) AS max_before, MIN(TO_NUMBER(flex_fld3)) AS min_after
        FROM rd_t_uc_occpp_data_dt
        WHERE a_msisdn = :msisdn
          AND call_type = 'DATA'
          AND flex_fld2 = :flex_fld2
          AND start_date BETWEEN :lookback_start AND :anchor_date
        GROUP BY start_date
        ORDER BY start_date
    """
    cursor.execute(query, {
        "msisdn": msisdn,
        "flex_fld2": flex_fld2,
        "lookback_start": lookback_start,
        "anchor_date": anchor_date,
    })

    cycle_start = None
    prev_min_after = None
    for day, max_before, min_after in cursor.fetchall():
        is_reset = prev_min_after is None or (
            max_before is not None and max_before > prev_min_after + CYCLE_RESET_THRESHOLD_DT
        )
        if is_reset:
            cycle_start = day.date() if hasattr(day, "date") else day
        prev_min_after = min_after

    return cycle_start


def investigate_data_usage(msisdn, start_date, end_date, da_value=None, target_volume_gb=None, anchor_date=None, target_amount=None):
    """
    Same narrow-then-broaden strategy as investigate_voice_expiration,
    adapted to what's actually real for data:

    - Window: the real query the encadrant uses looks at a single day
      (anchor_date), not a multi-day span like voice's 5-day window.
      If nothing on that single day explains the stated GB figure, this
      broadens to the named bucket's own ledger cycle (see
      _find_cycle_start) -- a stated GB total is usually the bucket's
      full-cycle consumption, not one day's traffic. Only as a last
      resort does it fall back to the wider generic date range the
      caller supplied (start_date..end_date).

    - FLEX_FLD2 filter: the real query also applies a FLEX_FLD2 filter
      whose exact meaning the encadrant hasn't confirmed to us yet. In
      the real imported data for MSISDN 21692641320, the complaint's
      stated "DA7" lines up with FLEX_FLD2='7' on every DATA row for
      that number, which is why FLEX_FLD2 is tried here as the narrow
      first-pass filter when a DA/bucket value is named. This is a
      working hypothesis, not confirmed semantics -- re-check with the
      encadrant before relying on it. If it doesn't explain the stated
      volume, the filter is dropped before broadening, same as voice
      drops its DA filter.

    target_volume_gb is converted to KB (see KB_PER_GB) before matching
    against DATA_VOLUME, which is stored in KB.

    If nothing in either window explains the stated volume even after
    dropping the filter, this honestly reports search_tier="not_found"
    rather than presenting an unrelated total as if it were the answer.
    """
    single_day = anchor_date if anchor_date is not None else end_date
    target_volume_kb = target_volume_gb * KB_PER_GB if target_volume_gb is not None else None

    connection = get_connection()
    cursor = connection.cursor()

    if da_value is not None:
        tier1_evidence = _run_data_query(cursor, msisdn, single_day, single_day, da_value)

        if target_volume_kb is None:
            cursor.close()
            connection.close()
            return {
                "evidence": tier1_evidence,
                "search_tier": "narrow_single_day_flex_filtered",
                "da_value_used": da_value,
                "note": None,
            }

        match = find_best_match(tier1_evidence, target_volume_kb, amount_field="DATA_VOLUME")
        if match is not None:
            cursor.close()
            connection.close()
            return {
                "evidence": match["matched_rows"],
                "search_tier": "narrow_single_day_flex_filtered",
                "da_value_used": da_value,
                "confidence": match["confidence"],
                "note": f"Matched via {match['match_type']} on {single_day} within FLEX_FLD2={da_value}",
            }

        tier2_evidence = _run_data_query(cursor, msisdn, single_day, single_day, None)
        match2 = find_best_match(tier2_evidence, target_volume_kb, amount_field="DATA_VOLUME")
        if match2 is not None:
            cursor.close()
            connection.close()
            return {
                "evidence": match2["matched_rows"],
                "search_tier": "broadened_no_flex_filter",
                "da_value_used": None,
                "confidence": match2["confidence"],
                "note": f"FLEX_FLD2={da_value}-filtered search did not explain the stated volume. Broadened to full day matched via {match2['match_type']}.",
            }

        cycle_start = _find_cycle_start(cursor, msisdn, da_value, single_day)
        if cycle_start is not None and cycle_start < single_day:
            tier3_evidence = _run_data_query(cursor, msisdn, cycle_start, single_day, da_value)
            match3 = find_best_match(tier3_evidence, target_volume_kb, amount_field="DATA_VOLUME")
            if match3 is not None:
                cursor.close()
                connection.close()
                return {
                    "evidence": match3["matched_rows"],
                    "search_tier": "broadened_cycle_window",
                    "da_value_used": da_value,
                    "confidence": match3["confidence"],
                    "note": f"Single-day search did not explain the stated volume. Broadened to the DA{da_value} bucket's own billing cycle ({cycle_start}..{single_day}, detected from a ledger reset in FLEX_FLD1/FLEX_FLD3) matched via {match3['match_type']}.",
                }

        tier4_evidence = _run_data_query(cursor, msisdn, start_date, end_date, None)
        cursor.close()
        connection.close()

        match4 = find_best_match(tier4_evidence, target_volume_kb, amount_field="DATA_VOLUME")
        if match4 is not None:
            return {
                "evidence": match4["matched_rows"],
                "search_tier": "broadened_date_range",
                "da_value_used": None,
                "confidence": match4["confidence"],
                "note": f"Single-day search and the DA{da_value} bucket's own cycle window did not explain the stated volume. Broadened to {start_date}..{end_date} matched via {match4['match_type']}.",
            }

        from app.services.cross_source_search import try_cross_source_fallback
        return try_cross_source_fallback(
            msisdn, start_date, end_date, target_amount, anchor_date,
            f"Neither the single-day FLEX_FLD2={da_value}-filtered search, the DA{da_value} bucket's own cycle window, the full window {start_date}..{end_date}, nor any other source found evidence explaining the stated volume of {target_volume_gb} GB. Manual verification recommended.",
        )

    evidence = _run_data_query(cursor, msisdn, single_day, single_day, None)

    if target_volume_kb is None:
        cursor.close()
        connection.close()
        return {
            "evidence": evidence,
            "search_tier": "single_day_no_flex_named",
            "da_value_used": None,
            "note": None,
        }

    match = find_best_match(evidence, target_volume_kb, amount_field="DATA_VOLUME")
    if match is not None:
        cursor.close()
        connection.close()
        return {
            "evidence": match["matched_rows"],
            "search_tier": "single_day_no_flex_named",
            "da_value_used": None,
            "confidence": match["confidence"],
            "note": f"Matched via {match['match_type']}",
        }

    tier2_evidence = _run_data_query(cursor, msisdn, start_date, end_date, None)
    cursor.close()
    connection.close()

    match2 = find_best_match(tier2_evidence, target_volume_kb, amount_field="DATA_VOLUME")
    if match2 is not None:
        return {
            "evidence": match2["matched_rows"],
            "search_tier": "broadened_date_range",
            "da_value_used": None,
            "confidence": match2["confidence"],
            "note": f"Single day did not explain the stated volume. Broadened to {start_date}..{end_date} matched via {match2['match_type']}.",
        }

    from app.services.cross_source_search import try_cross_source_fallback
    return try_cross_source_fallback(
        msisdn, start_date, end_date, target_amount, anchor_date,
        f"No evidence found explaining the stated volume of {target_volume_gb} GB in single day {single_day}, broadened window {start_date}..{end_date}, or any other source. Manual verification recommended.",
    )
