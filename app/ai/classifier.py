import json
import re
from datetime import datetime

from app.ai.ollama_client import ask_ollama
from app.ai.case_memory import find_similar_cases, compute_confidence


CATEGORIES = [
    "VOICE_EXPIRATION",
    "DATA_USAGE",
    "SMS_VAS",
    "SOS_CREDIT",
    "BALANCE_DEDUCTION"
]

CONFIDENCE_LEVELS = ["HIGH", "MEDIUM", "LOW"]


def extract_msisdn(text):
    match = re.search(r'216\d{8}', text)
    if match:
        return match.group(0)
    return None


def extract_da_value(text):
    match = re.search(r'\bDA\s*(\d{1,3})\b', text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def extract_target_amount(text):
    match = re.search(r'(\d+[.,]?\d*)\s*DT', text, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", "."))
    return None


def extract_target_volume_gb(text):
    match = re.search(r'(\d+[.,]?\d*)\s*GB', text, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", "."))
    return None


def extract_event_date(text):
    """
    Extracts the date the complaint itself states the event happened
    (e.g. "Date expiree: le 02/08/2026"), format DD/MM/YYYY. This is
    used to anchor the investigation window on the actual event date
    rather than the system clock -- correct for both live complaints
    (where this date is recent) and historical/test complaints (where
    it may be well in the past). Returns a datetime.date or None.
    """
    match = re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
    if match:
        day, month, year = match.groups()
        try:
            return datetime(int(year), int(month), int(day)).date()
        except ValueError:
            return None
    return None


def _format_precedent_examples(similar_cases):
    if not similar_cases:
        return ""
    lines = []
    for case in similar_cases:
        lines.append(
            f'Complaint: "{case["complaint_text"]}"\n'
            f'Answer: {{"category": "{case["category"]}", "confidence": "HIGH"}}'
        )
    return "\n\n".join(lines)


def build_prompt(complaint_text, similar_cases=None):
    precedent_block = _format_precedent_examples(similar_cases or [])
    precedent_section = f"\nVerified past examples from this system's own history:\n{precedent_block}\n" if precedent_block else ""

    return f'''You are a classifier for Tunisie Telecom customer complaints.

Categories and what they mean:
- VOICE_EXPIRATION: forfait/package voice minutes/credit expired unexpectedly (mentions "forfait", "FF VOIX", voice balance like "DA4")
- DATA_USAGE: complaint about data/internet consumption or data volume charges
- SMS_VAS: balance consumed by a VAS/SMS+ subscription service (mentions "SMS+", "VAS", "abonnement", a named service like "100 SECONDES"), even if the customer describes it only as a balance/solde problem
- SOS_CREDIT: complaint related to SOS credit/emergency balance or data advance (loan-based credit)
- BALANCE_DEDUCTION: balance disappeared/reduced with no VAS subscription, forfait, or named service mentioned as the cause

Examples:
Complaint: "expiration brusque de 2.100 DT de son solde principale" (investigation confirmed: service SMS+ VAS, abonnement 100 SECONDES, 0.7 dinar/jour)
Answer: {{"category": "SMS_VAS", "confidence": "HIGH"}}

Complaint: "reclame l'expiration du forfait Voix, Balance concerne DA4, Montant expire 18 DT"
Answer: {{"category": "VOICE_EXPIRATION", "confidence": "HIGH"}}
{precedent_section}
Now classify the complaint below into exactly ONE of these categories:
VOICE_EXPIRATION, DATA_USAGE, SMS_VAS, SOS_CREDIT, BALANCE_DEDUCTION

Also assign a confidence level based on how clearly the complaint text signals the category:
- HIGH: the complaint explicitly names the service/mechanism (e.g. "forfait Voix", "SMS+", "consommation data", "avance SOS")
- MEDIUM: the complaint describes symptoms consistent with one category but doesn't name the mechanism explicitly
- LOW: the complaint is vague, could plausibly fit multiple categories, or lacks enough detail to be confident

Respond ONLY with valid JSON in this exact format, nothing else:
{{"category": "CATEGORY_NAME", "confidence": "HIGH_OR_MEDIUM_OR_LOW"}}

Complaint:
{complaint_text}
'''


def classify_complaint(complaint_text):
    similar_cases = find_similar_cases(complaint_text, top_k=3)

    prompt = build_prompt(complaint_text, similar_cases)
    raw_response = ask_ollama(prompt)

    category = "UNKNOWN"
    llm_confidence = "LOW"

    try:
        parsed = json.loads(raw_response)
        category = parsed.get("category", "UNKNOWN")
        llm_confidence = parsed.get("confidence", "LOW")
    except json.JSONDecodeError:
        for cat in CATEGORIES:
            if cat in raw_response:
                category = cat
                break

    if category not in CATEGORIES:
        category = "UNKNOWN"
        llm_confidence = "LOW"

    if llm_confidence not in CONFIDENCE_LEVELS:
        llm_confidence = "LOW"

    confidence, confidence_reason = compute_confidence(category, similar_cases, llm_confidence)

    msisdn = extract_msisdn(complaint_text)
    da_value = extract_da_value(complaint_text)
    target_amount = extract_target_amount(complaint_text)
    target_volume_gb = extract_target_volume_gb(complaint_text)
    event_date = extract_event_date(complaint_text)

    return {
        "category": category,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "msisdn": msisdn,
        "da_value": da_value,
        "target_amount": target_amount,
        "target_volume_gb": target_volume_gb,
        "event_date": event_date.isoformat() if event_date else None,
        "raw_ai_response": raw_response
    }
