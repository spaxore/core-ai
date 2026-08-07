import json
import re
from app.ai.ollama_client import ask_ollama


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


def build_prompt(complaint_text):
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
    prompt = build_prompt(complaint_text)
    raw_response = ask_ollama(prompt)

    category = "UNKNOWN"
    confidence = "LOW"

    try:
        parsed = json.loads(raw_response)
        category = parsed.get("category", "UNKNOWN")
        confidence = parsed.get("confidence", "LOW")
    except json.JSONDecodeError:
        for cat in CATEGORIES:
            if cat in raw_response:
                category = cat
                break

    if category not in CATEGORIES:
        category = "UNKNOWN"
        confidence = "LOW"

    if confidence not in CONFIDENCE_LEVELS:
        confidence = "LOW"

    msisdn = extract_msisdn(complaint_text)

    return {
        "category": category,
        "confidence": confidence,
        "msisdn": msisdn,
        "raw_ai_response": raw_response
    }
