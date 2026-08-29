import re

INJECTION_PATTERNS = [
    (r"ignore (all|any|previous|prior|the|every)( previous| prior| all| any| every)* (instructions|rules?)", "DIRECT_INJECTION", 50),
    (r"disregard (the|all|any) (above|previous|prior)", "DIRECT_INJECTION", 50),
    (r"you are now", "ROLE_CONFUSION", 50),
    (r"act as (a|an)", "ROLE_CONFUSION", 50),
    (r"pretend (you are|to be)", "ROLE_CONFUSION", 50),
    (r"system prompt", "EXFILTRATION", 55),
    (r"reveal your (instructions|prompt|rules)", "EXFILTRATION", 55),
    (r"print (your|the) (instructions|prompt|rules|system)", "EXFILTRATION", 55),
    (r"forget (everything|all|your instructions)", "DIRECT_INJECTION", 50),
    (r"new instructions?:", "DIRECT_INJECTION", 50),
    (r"</?(system|assistant|user)>", "ROLE_CONFUSION", 50),
    (r"jailbreak", "JAILBREAK", 50),
    (r"dan mode", "JAILBREAK", 50),
    (r"developer mode", "JAILBREAK", 50),
    (r"bypass (all|any) (restrictions|rules|filters)", "JAILBREAK", 50),
    (r"ignore your (safety )?(guidelines|instructions|rules)", "DIRECT_INJECTION", 50),
    (r"(drop|delete|truncate|update)\s+table", "SQLI_ATTEMPT", 50),
    (r"--\s*$|;\s*--", "SQLI_ATTEMPT", 50),
    (r"select\s+.+\s+from", "SQLI_ATTEMPT", 50),
    (r"translate your (system prompt|instructions|rules)", "EXFILTRATION", 55),
    (r"'1'\s*=\s*'1'", "SQLI_ATTEMPT", 50),
    # French equivalents -- complaint text is French by convention in this
    # app (DI-010: same ignore-restrictions + reveal-internal-rules ask as
    # DI-001, just phrased in French, which the English-only patterns above
    # never covered).
    (r"ignore (le|la|les|tout|toute|toutes) (contexte|restrictions?|règles?)", "DIRECT_INJECTION", 50),
    (r"règles internes", "EXFILTRATION", 55),
    (r"base de connaissances", "EXFILTRATION", 55),
    (r"administrateur (système|systeme)", "ROLE_CONFUSION", 50),
]

BLOCK_THRESHOLD = 50

def inspect_prompt(text: str) -> dict:
    text_lower = text.lower()
    matches = []
    total_score = 0

    for pattern, category, weight in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            matches.append({"pattern": pattern, "category": category, "weight": weight})
            total_score += weight

    is_blocked = total_score >= BLOCK_THRESHOLD

    return {
        "risk_score": total_score,
        "matches": matches,
        "is_blocked": is_blocked
    }
