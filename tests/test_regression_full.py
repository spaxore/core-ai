import os
import sys

import requests

BASE_URL = "http://127.0.0.1:8000"

# agent1/SUPPORT_AGENT is the account this suite is meant to run as (see
# demo_script.md) -- it's the role that actually files/investigates
# complaints. Override via env vars rather than hardcoding a password here.
LOGIN_USERNAME = os.getenv("REGRESSION_TEST_USERNAME", "agent1")
LOGIN_PASSWORD = os.getenv("REGRESSION_TEST_PASSWORD")

TEST_CASES = [
    {
        "name": "VOICE_EXPIRATION (21693861112)",
        "text": "Le client teneur de la ligne numero 21693861112 reclame l'expiration du forfait Voix. Balance concerne DA4. Montant expire 18 DT. Date d'expiration le 21/07/2026.",
        "expected_category": "VOICE_EXPIRATION",
        "expect_evidence": True
    },
    {
        "name": "SMS_VAS (21693926356)",
        "text": "Le client teneur de la ligne 21693926356 reclame l'expiration brusque de 2.100 DT de son solde principale entre le 12 et 14/07/2026.",
        "expected_category": "SMS_VAS",
        "expect_evidence": True
    },
    {
        "name": "VOICE_EXPIRATION (21655569158)",
        "text": "Le client teneur de la ligne 21655569158 reclame l'expiration brusque de 13 DT de son forfait entre le 22/07/2026 et 29/07/2026.",
        "expected_category": "VOICE_EXPIRATION",
        "expect_evidence": True
    },
    {
        "name": "DATA_USAGE (21692918830)",
        "text": "Client 21692918830 se plaint d'une consommation data excessive et anormale sur sa ligne.",
        "expected_category": "DATA_USAGE",
        "expect_evidence": True
    },
    {
        "name": "SOS_CREDIT (21697865660)",
        "text": "Client 21697865660 signale un probleme avec son avance SOS, le montant n'est pas correct.",
        "expected_category": "SOS_CREDIT",
        "expect_evidence": True
    },
]

print("=" * 70)
print("REGRESSION TEST - Secure TT AI Agent")
print("=" * 70)

if not LOGIN_PASSWORD:
    print(f"\nSet REGRESSION_TEST_PASSWORD (account: {LOGIN_USERNAME}) and re-run.")
    sys.exit(1)

login_response = requests.post(
    f"{BASE_URL}/login",
    json={"username": LOGIN_USERNAME, "password": LOGIN_PASSWORD},
)
if login_response.status_code != 200:
    print(f"\nLogin failed ({login_response.status_code}): {login_response.text}")
    sys.exit(1)

auth_header = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
print(f"Logged in as {LOGIN_USERNAME}.")

results = []

for case in TEST_CASES:
    response = requests.post(f"{BASE_URL}/investigate", json={"text": case["text"]}, headers=auth_header)
    data = response.json()

    classification = data.get("classification", {})
    actual_category = classification.get("category")
    confidence = classification.get("confidence")
    msisdn = classification.get("msisdn")
    evidence = data.get("evidence")
    error = data.get("error")

    category_ok = actual_category == case["expected_category"]
    evidence_ok = (isinstance(evidence, list) and len(evidence) > 0) if case["expect_evidence"] else True

    status = "PASS" if (category_ok and evidence_ok) else "FAIL"
    results.append(status)

    print(f"\n[{status}] {case['name']}")
    print(f"  Expected category: {case['expected_category']}")
    print(f"  Actual category:   {actual_category} (confidence: {confidence})")
    print(f"  MSISDN detected:   {msisdn}")
    print(f"  Evidence rows:     {len(evidence) if isinstance(evidence, list) else 'N/A'}")
    if error:
        print(f"  Error: {error}")
    if not category_ok:
        print(f"  >>> CATEGORY MISMATCH <<<")
    if case["expect_evidence"] and not evidence_ok:
        print(f"  >>> NO EVIDENCE FOUND (expected some) <<<")

print("\n" + "=" * 70)
passed = results.count("PASS")
total = len(results)
print(f"RESULT: {passed}/{total} passed")
if passed < total:
    print("WARNING: one or more tests failed. Review output above.")
print("=" * 70)
