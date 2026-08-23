"""
Renewal-failure and dedicated-account-adjustment evidence.

The category-specific searches (voice/data/sms/sos) and the cross-source
fallback all look for one thing: a row where money left the account
matching the stated amount. Two real mechanisms found during ticket
investigation don't fit that shape at all:

- A package can "expire" because its automatic renewal was attempted and
  FAILED (insufficient balance) -- no charge ever happened, so there is
  nothing for amount-matching to find. That failure is logged in
  RD_T_UC_USSD_140_DETAILS, a table none of the amount-matching tiers
  read.
- A dedicated-account bucket can be credited or debited via an
  "adjustment" record in RD_T_UC_AIR_CDR_DET that reallocates value
  across several buckets at once (DA_VALUE is a pipe-delimited list of
  every bucket touched by that one record), rather than a single
  line-item charge with one clean amount.

Both are evidence-presence checks, not amount matches: the search
window is anchored on the complaint's own stated date, not on finding a
number that adds up to the stated DT amount. That's a deliberately
different kind of evidence from everything else in this codebase, so
neither is folded into find_best_match()'s amount-matching logic --
they're reported as their own distinct tiers, with their own honest
caveats about what they do and don't prove.
"""
from datetime import timedelta

from app.database.oracle import get_connection

RENEWAL_TIER_LABEL = "Vérification des tentatives de renouvellement"
ADJUSTMENT_TIER_LABEL = "Vérification des ajustements de compte dédié"


def _run_renewal_query(cursor, msisdn, start_date, end_date):
    query = """
        SELECT service_code, orig_start_time, description, status, status_details,
               action, start_date
        FROM rd_t_uc_ussd_140_details
        WHERE a_msisdn = :msisdn
          AND start_date BETWEEN :start_date AND :end_date
          AND event_status = 'Failure'
          AND (service_code LIKE '%PKG_renew%' OR action = 'auto-renew unsubscription')
        ORDER BY orig_start_time
    """
    cursor.execute(query, {"msisdn": msisdn, "start_date": start_date, "end_date": end_date})
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def investigate_renewal_failure(msisdn, anchor_date, window_days=3):
    """
    Checks for failed package-renewal attempts in a window ending on the
    complaint's own stated event date. Renewals are commonly retried
    several times over a day or two before a package is actually
    considered expired (observed directly: 3 attempts within 2 hours in
    one real ticket), so a short lookback is needed -- not just the
    single anchor day.

    Returns None if nothing is found (caller falls through to the next
    tier), or a result dict shaped like the other tiers' results, with
    search_tier="renewal_failure" so callers/UI can tell this apart from
    an amount match.
    """
    start_date = anchor_date - timedelta(days=window_days)

    connection = get_connection()
    cursor = connection.cursor()
    rows = _run_renewal_query(cursor, msisdn, start_date, anchor_date)
    cursor.close()
    connection.close()

    if not rows:
        return None

    reasons = sorted({r["status_details"] for r in rows if r.get("status_details")})
    reason_text = ", ".join(reasons) if reasons else "raison non précisée"
    return {
        "evidence": rows,
        "search_tier": "renewal_failure",
        "da_value_used": None,
        "confidence": "MEDIUM",
        "note": (
            f"{len(rows)} tentative(s) de renouvellement automatique du forfait ont échoué "
            f"({reason_text}) entre {start_date} et {anchor_date}. Le forfait a probablement "
            f"expiré faute de renouvellement réussi, plutôt que via un débit ponctuel -- "
            f"aucun montant n'a été prélevé lors de ces tentatives."
        ),
    }


def _run_adjustment_query(cursor, msisdn, start_date, end_date):
    query = """
        SELECT charge_amount, da_amount, da_value, record_type, orig_start_time,
               dedictated_amnt, ded_amnt_before, ded_amnt_after, start_date
        FROM rd_t_uc_air_cdr_det
        WHERE a_msisdn = :msisdn
          AND start_date BETWEEN :start_date AND :end_date
          AND record_type = 'adjustmentRecordV2'
        ORDER BY orig_start_time
    """
    cursor.execute(query, {"msisdn": msisdn, "start_date": start_date, "end_date": end_date})
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def investigate_da_adjustment(msisdn, da_value, anchor_date, window_days=3):
    """
    Checks for dedicated-account adjustment records touching the named
    DA bucket (if any) in a window ending on the complaint's stated date.
    DA_VALUE on this table is a pipe-delimited list of every bucket one
    adjustment record touched (e.g. "4|10|17|18|19|23|30"), so membership
    is checked per-bucket in Python rather than a SQL substring match --
    a plain LIKE '%4%' would also match "14"/"40"/etc.

    Deliberately LOW confidence even when found: an adjustment record
    proves value moved in or out of the bucket, not which direction, and
    real examples seen so far were credits (refill bonuses), not the
    debit a customer complaint describes -- this is a lead to manually
    verify, not a confirmed cause.
    """
    start_date = anchor_date - timedelta(days=window_days)

    connection = get_connection()
    cursor = connection.cursor()
    rows = _run_adjustment_query(cursor, msisdn, start_date, anchor_date)
    cursor.close()
    connection.close()

    if da_value is not None:
        rows = [r for r in rows if r.get("da_value") and da_value in r["da_value"].split("|")]

    if not rows:
        return None

    return {
        "evidence": rows,
        "search_tier": "da_adjustment",
        "da_value_used": da_value,
        "confidence": "LOW",
        "note": (
            f"{len(rows)} ajustement(s) de compte dédié trouvé(s) entre {start_date} et "
            f"{anchor_date}"
            + (f" touchant le bucket DA{da_value}" if da_value else "")
            + " -- confirme qu'une réallocation de solde a eu lieu, mais pas si c'est un "
            "crédit ou un débit. Vérification manuelle recommandée avant de conclure."
        ),
    }
