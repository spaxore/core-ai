"""
Shared logic for the adaptive narrow-then-broaden investigation
strategy used across every service. Mirrors the encadrant's real
manual process: try the specific Dedicated Account bucket the customer
named first, and if that evidence does not actually explain the
stated amount, drop the DA filter and search the whole table.

find_best_match() is the more important function -- broadening the
search alone is not enough. Dumping the entire broadened result set as
"the answer" without checking whether it actually explains the target
amount is not honest investigation, it is just a bigger unfiltered
report. This searches the broadened set for the specific evidence that
actually accounts for the stated amount, preferring the most specific
explanation (one matching transaction, or one row's before/after
balance swing) over the least specific one (the grand total of
everything).
"""


def is_close_to_target(evidence, target_amount, amount_field="CHARGE_AMOUNT", tolerance_ratio=0.15, tolerance_floor=1.0):
    if target_amount is None or not evidence:
        return False

    tolerance = max(tolerance_floor, tolerance_ratio * target_amount)

    total = 0
    for row in evidence:
        value = row.get(amount_field)
        if value is None:
            continue
        total += value
        if abs(value - target_amount) <= tolerance:
            return True

    if abs(total - target_amount) <= tolerance:
        return True

    return False


CONFIDENCE_LEVELS = ["LOW", "MEDIUM", "HIGH"]


def _downgrade(confidence):
    return CONFIDENCE_LEVELS[max(0, CONFIDENCE_LEVELS.index(confidence) - 1)]


def _bucket_identity(row):
    """
    A row's real-world "bucket" regardless of which table it came from
    -- voice/data use DA_VALUE/FLEX_FLD2, SOS uses LOAN_ID, and
    cross_source_search.py tags every row with _SOURCE. Used to tell
    "one coherent thing's total" apart from "an unfiltered grab-bag."
    """
    return (row.get("_SOURCE"), row.get("DA_VALUE") or row.get("FLEX_FLD2") or row.get("LOAN_ID"))


def _full_period_total_confidence(matched_rows, total, target_amount, tolerance_ratio):
    """
    A summed total is only as trustworthy as what it's a total OF.
    Base confidence comes from how scoped the evidence is:
    - one bucket, one day               -> HIGH  (e.g. a single day's SMS charges)
    - one bucket, multiple days          -> MEDIUM (e.g. a data bucket's full billing cycle)
    - multiple unrelated buckets/sources -> LOW    (an unfiltered grab-bag across a wide
                                                      window -- a large enough sum will land
                                                      near almost any target by chance)
    Then downgraded one level only if the fit is in the outer edge of
    the tolerance band (e.g. 24.94 GB vs a stated 23 GB -- 8.4% off out
    of 15% allowed -- is still a solid single-bucket, real-cycle match
    and should stay MEDIUM; only a fit that barely squeaks in, close to
    the tolerance boundary itself, gets downgraded).
    """
    distinct_buckets = set(_bucket_identity(r) for r in matched_rows)
    distinct_dates = set(r.get("START_DATE") for r in matched_rows if r.get("START_DATE"))

    if len(distinct_buckets) <= 1:
        confidence = "HIGH" if len(distinct_dates) <= 1 else "MEDIUM"
    else:
        confidence = "LOW"

    relative_error = abs(total - target_amount) / target_amount if target_amount else 0
    if relative_error > tolerance_ratio * 0.8:
        confidence = _downgrade(confidence)

    return confidence


def compute_evidence_coverage(matched_rows):
    """
    A second stat alongside confidence, answering a different question:
    not "how well did this fit", but "how much of the evidence actually
    went into this answer". Two matches can both be MEDIUM confidence for
    very different reasons -- one bucket broadened once, versus four
    unrelated sources pieced together -- and confidence alone can't tell
    a support agent which is which. Reuses _bucket_identity, the same
    breadth calculation _full_period_total_confidence already does
    internally; this just keeps that result instead of throwing it away
    after computing confidence. No new matching logic.
    """
    distinct_buckets = set(_bucket_identity(r) for r in matched_rows)
    distinct_dates = set(r.get("START_DATE") for r in matched_rows if r.get("START_DATE"))
    return {
        "row_count": len(matched_rows),
        "distinct_buckets": len(distinct_buckets),
        "distinct_dates": len(distinct_dates),
    }


def find_best_match(evidence, target_amount, amount_field="CHARGE_AMOUNT",
                     before_field="DA_VALUE_BEFORE", after_field="DA_VALUE_AFTER",
                     tolerance_ratio=0.15, tolerance_floor=1.0):
    """
    Searches evidence for what actually explains target_amount, checked
    in order from most specific to least specific:

    1. A single transaction whose amount_field is close to target_amount
       -- the strongest, most specific kind of match (one real event
       that explains the complaint). Always HIGH confidence.
    2. A single row's before/after balance swing (e.g. DA_VALUE_BEFORE
       minus DA_VALUE_AFTER) close to target_amount -- a distinct debit
       event visible in the balance state itself, not a per-call charge.
       Always HIGH confidence.
    3. The SUM of every row's amount_field close to target_amount -- the
       weakest match, only used if nothing more specific exists. Its
       confidence (HIGH/MEDIUM/LOW) depends on how scoped the summed
       evidence is and how tight the fit is -- see
       _full_period_total_confidence. A support agent seeing a LOW
       confidence lead can judge for themselves whether to chase it,
       rather than the system silently hiding it as "not found."

    Returns a dict: {"matched_rows": [...], "match_type": str,
    "confidence": "HIGH"|"MEDIUM"|"LOW"} on success, or None if nothing
    in the evidence explains target_amount even approximately.
    Returning None on purpose is the honest outcome when the data
    genuinely does not contain any explanation, even a weak one --
    better than reporting an unrelated total as if it were the answer.
    """
    if target_amount is None or not evidence:
        return None

    tolerance = max(tolerance_floor, tolerance_ratio * target_amount)

    for row in evidence:
        value = row.get(amount_field)
        if value is not None and abs(value - target_amount) <= tolerance:
            return {
                "matched_rows": [row], "match_type": "single_transaction", "confidence": "HIGH",
                "evidence_coverage": compute_evidence_coverage([row]),
            }

    for row in evidence:
        before = row.get(before_field)
        after = row.get(after_field)
        if before is not None and after is not None:
            swing = abs(before - after)
            if abs(swing - target_amount) <= tolerance:
                return {
                    "matched_rows": [row], "match_type": "balance_swing", "confidence": "HIGH",
                    "evidence_coverage": compute_evidence_coverage([row]),
                }

    total = sum((row.get(amount_field) or 0) for row in evidence)
    if abs(total - target_amount) <= tolerance:
        confidence = _full_period_total_confidence(evidence, total, target_amount, tolerance_ratio)
        return {
            "matched_rows": evidence, "match_type": "full_period_total", "confidence": confidence,
            "evidence_coverage": compute_evidence_coverage(evidence),
        }

    return None
