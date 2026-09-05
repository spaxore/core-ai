import base64
import re
import unicodedata

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

# Confusable-homoglyph normalization (Finding 6, KT-001): a Cyrillic/Greek
# letter that renders visually identical to a Latin one still reads as
# plain English to a human or an LLM, but is a different codepoint to a
# literal-substring regex. Covers the practical subset attackers actually
# reach for -- letters with a 1:1 Latin lookalike requiring no font
# trickery to read -- not full Unicode confusables coverage.
_CONFUSABLES = {
    "а": "a", "А": "A",  # CYRILLIC A
    "е": "e", "Е": "E",  # CYRILLIC IE
    "к": "k", "К": "K",  # CYRILLIC KA
    "м": "m", "М": "M",  # CYRILLIC EM
    "н": "h", "Н": "H",  # CYRILLIC EN
    "о": "o", "О": "O",  # CYRILLIC O
    "р": "p", "Р": "P",  # CYRILLIC ER
    "с": "c", "С": "C",  # CYRILLIC ES
    "т": "t", "Т": "T",  # CYRILLIC TE
    "у": "y", "У": "Y",  # CYRILLIC U
    "х": "x", "Х": "X",  # CYRILLIC HA
    "і": "i", "І": "I",  # CYRILLIC/UKRAINIAN I
    "ѕ": "s", "Ѕ": "S",  # CYRILLIC DZE
    "ј": "j", "Ј": "J",  # CYRILLIC JE
    "ԁ": "d",             # CYRILLIC KOMI DE
    "ɡ": "g",             # LATIN SMALL LETTER SCRIPT G
    "α": "a", "Α": "A",  # GREEK ALPHA
    "ο": "o", "Ο": "O",  # GREEK OMICRON
    "ρ": "p", "Ρ": "P",  # GREEK RHO
    "υ": "u", "Υ": "Y",  # GREEK UPSILON
    "ν": "v", "Ν": "N",  # GREEK NU
    "χ": "x", "Χ": "X",  # GREEK CHI
}
_CONFUSABLES_TABLE = str.maketrans(_CONFUSABLES)


def _normalize_confusables(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_CONFUSABLES_TABLE)


# Base64 instruction smuggling (Finding 7, KT-002): the malicious
# instruction never appears in plaintext, only inside an encoded blob --
# decode any plausible base64 run in the text and scan the decoded result
# through the same pattern check.
_B64_CANDIDATE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def _decode_base64_candidates(text: str) -> list:
    decoded = []
    for m in _B64_CANDIDATE.finditer(text):
        candidate = m.group(0)
        if len(candidate) % 4 != 0:
            continue
        try:
            raw = base64.b64decode(candidate, validate=True)
            decoded.append(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
    return decoded


def _scan(text_lower: str) -> tuple:
    matches = []
    total_score = 0
    for pattern, category, weight in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            matches.append({"pattern": pattern, "category": category, "weight": weight})
            total_score += weight
    return matches, total_score


def inspect_prompt(text: str) -> dict:
    matches, total_score = _scan(_normalize_confusables(text).lower())

    for decoded_text in _decode_base64_candidates(text):
        decoded_matches, decoded_score = _scan(_normalize_confusables(decoded_text).lower())
        for match in decoded_matches:
            matches.append({**match, "category": match["category"] + "_B64_ENCODED"})
        total_score += decoded_score

    is_blocked = total_score >= BLOCK_THRESHOLD

    return {
        "risk_score": total_score,
        "matches": matches,
        "is_blocked": is_blocked
    }
