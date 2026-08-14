"""
Case Memory -- retrieval-based learning from past verified complaints.

Not a fine-tuned model: Ollama/Llama 3.1 is run locally and is not
retrained. Instead, this retrieves the most textually similar past
complaints that an employee has confirmed were correctly investigated
(TT_AI_VERIFIED_CASES), and uses them two ways:

1. As dynamic few-shot examples fed into the classifier prompt, so the
   system is guided by real, confirmed precedent instead of only the
   two static hardcoded examples that existed before.
2. To compute a REAL, calculated confidence score based on similarity
   to a matching verified precedent -- as opposed to before, where
   "confidence" was entirely the LLM's own self-reported guess with no
   actual computation behind it. When no strong precedent exists yet,
   this honestly falls back to the LLM's self-report rather than
   pretending to have precedent it doesn't.

Similarity is plain Jaccard token-overlap -- no external ML dependency,
appropriate for a local-only, offline system.
"""
import os
import re

import oracledb
from dotenv import load_dotenv

load_dotenv()

# Mirrors the DB check constraint chk_verified_cases_status on
# TT_AI_VERIFIED_CASES.STATUS -- kept in sync by hand since this is a
# small, fixed vocabulary. ai_generated/human_reviewed/human_validated
# describe how a case entered the table in the first place;
# corrected/rejected are states a reviewer can move a case into later
# (via update_case_status) once they've had a chance to check it against
# what actually happened -- e.g. a precedent that turned out to be a
# coincidental match, not a real one.
VALID_STATUSES = {"ai_generated", "human_reviewed", "human_validated", "corrected", "rejected"}


def _get_connection():
    return oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN")
    )


def _tokenize(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return set(t for t in text.split() if len(t) > 2)


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def fetch_verified_cases(limit=200):
    """
    Excludes rejected cases -- a reviewer marking a precedent "rejected"
    (e.g. a coincidental match that shouldn't have been trusted) means it
    must stop being used as a few-shot example or a confidence-boosting
    precedent, not just get a label nobody reads. Everything else
    (ai_generated/human_reviewed/human_validated/corrected) is still
    usable precedent -- "corrected" in particular is often the *most*
    trustworthy kind, since a human explicitly fixed it.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COMPLAINT_TEXT, CATEGORY, MSISDN, DA_VALUE, STATUS
        FROM TT_AI_VERIFIED_CASES
        WHERE STATUS != 'rejected'
        ORDER BY VERIFIED_AT DESC
        FETCH FIRST :lim ROWS ONLY
    """, lim=limit)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [
        {"complaint_text": r[0], "category": r[1], "msisdn": r[2], "da_value": r[3], "status": r[4]}
        for r in rows
    ]


def find_similar_cases(new_complaint_text, top_k=3):
    """Returns up to top_k past verified cases most textually similar to
    new_complaint_text, each tagged with its similarity score (0-1),
    sorted highest first."""
    cases = fetch_verified_cases()
    new_tokens = _tokenize(new_complaint_text)

    scored = []
    for case in cases:
        sim = _jaccard(new_tokens, _tokenize(case["complaint_text"]))
        if sim > 0:
            scored.append({**case, "similarity": sim})

    scored.sort(key=lambda c: c["similarity"], reverse=True)
    return scored[:top_k]


def compute_confidence(chosen_category, similar_cases, llm_confidence):
    """
    Returns (confidence, reason).

    Real, calculated confidence based on the strongest verified
    precedent in the SAME category the LLM chose. Falls back to the
    LLM's own self-reported confidence only when there's no matching
    precedent yet -- this is honest about which part is computed and
    which part is still a guess, rather than presenting a fake number.
    """
    if not similar_cases:
        return llm_confidence, "no_precedent_yet"

    best = similar_cases[0]
    if best["category"] != chosen_category:
        return llm_confidence, "no_matching_category_precedent"

    if best["similarity"] >= 0.5:
        return "HIGH", f"matches verified precedent, similarity={best['similarity']:.2f}"
    elif best["similarity"] >= 0.25:
        return "MEDIUM", f"partial match to verified precedent, similarity={best['similarity']:.2f}"
    else:
        return llm_confidence, "weak_precedent"


def save_verified_case(complaint_text, category, msisdn, da_value, verified_by, status="human_validated"):
    """
    Default status is "human_validated", not "ai_generated" -- /verify-case
    is only ever called by a SUPPORT_AGENT or SECURITY_ANALYST confirming a
    case by hand (see app/main.py), so every row created through the normal
    path already represents a human validation, not a raw AI guess.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}', must be one of {sorted(VALID_STATUSES)}")

    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO TT_AI_VERIFIED_CASES (COMPLAINT_TEXT, CATEGORY, MSISDN, DA_VALUE, VERIFIED_BY, STATUS)
        VALUES (:complaint_text, :category, :msisdn, :da_value, :verified_by, :status)
    """, complaint_text=complaint_text, category=category, msisdn=msisdn,
         da_value=da_value, verified_by=verified_by, status=status)
    conn.commit()
    cursor.close()
    conn.close()


def update_case_status(case_id, status):
    """
    Lets a reviewer move a case to a different status after the fact --
    e.g. marking a precedent "corrected" once a human fixes its category,
    or "rejected" once it's found to be a coincidental/bad match that
    should stop being used as precedent (see fetch_verified_cases, which
    excludes rejected cases). Returns True if a row was actually updated,
    False if case_id doesn't exist -- lets the caller 404 instead of
    silently no-op'ing.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}', must be one of {sorted(VALID_STATUSES)}")

    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE TT_AI_VERIFIED_CASES SET STATUS = :status WHERE CASE_ID = :case_id
    """, status=status, case_id=case_id)
    updated = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    return updated
