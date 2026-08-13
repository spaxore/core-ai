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
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COMPLAINT_TEXT, CATEGORY, MSISDN, DA_VALUE
        FROM TT_AI_VERIFIED_CASES
        ORDER BY VERIFIED_AT DESC
        FETCH FIRST :lim ROWS ONLY
    """, lim=limit)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [
        {"complaint_text": r[0], "category": r[1], "msisdn": r[2], "da_value": r[3]}
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


def save_verified_case(complaint_text, category, msisdn, da_value, verified_by):
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO TT_AI_VERIFIED_CASES (COMPLAINT_TEXT, CATEGORY, MSISDN, DA_VALUE, VERIFIED_BY)
        VALUES (:complaint_text, :category, :msisdn, :da_value, :verified_by)
    """, complaint_text=complaint_text, category=category, msisdn=msisdn,
         da_value=da_value, verified_by=verified_by)
    conn.commit()
    cursor.close()
    conn.close()
