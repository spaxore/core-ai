import re
from app.security.gateway import INJECTION_PATTERNS, BLOCK_THRESHOLD, inspect_prompt

# Minimal strings, each designed to trip exactly ONE pattern in isolation
MINIMAL_TRIGGERS = {
    r"ignore (all|any|previous|prior|the|every)( previous| prior| all| any| every)* (instructions|rules?)": "ignore all instructions",
    r"disregard (the|all|any) (above|previous|prior)": "disregard the above",
    r"you are now": "you are now",
    r"act as (a|an)": "act as a",
    r"pretend (you are|to be)": "pretend to be",
    r"system prompt": "system prompt",
    r"reveal your (instructions|prompt|rules)": "reveal your rules",
    r"print (your|the) (instructions|prompt|rules|system)": "print your rules",
    r"forget (everything|all|your instructions)": "forget everything",
    r"new instructions?:": "new instructions:",
    r"</?(system|assistant|user)>": "<system>",
    r"jailbreak": "jailbreak",
    r"dan mode": "dan mode",
    r"developer mode": "developer mode",
    r"bypass (all|any) (restrictions|rules|filters)": "bypass all restrictions",
    r"ignore your (safety )?(guidelines|instructions|rules)": "ignore your safety guidelines",
    r"(drop|delete|truncate|update)\s+table": "drop table",
    r"--\s*$|;\s*--": "test--",
    r"select\s+.+\s+from": "select x from y",
    r"translate your (system prompt|instructions|rules)": "translate your rules",
    r"'1'\s*=\s*'1'": "'1'='1'",
}

print(f"{'Pattern':<70} {'Trigger':<30} {'Score':<6} {'Solo-blocks?'}")
print("-" * 120)

gaps = []
for pattern, category, weight in INJECTION_PATTERNS:
    trigger = MINIMAL_TRIGGERS.get(pattern)
    if trigger is None:
        print(f"{pattern:<70} NO TEST STRING DEFINED - SKIPPED")
        continue

    result = inspect_prompt(trigger)
    matched_categories = [m["pattern"] for m in result["matches"]]
    is_isolated = len(result["matches"]) == 1 and result["matches"][0]["pattern"] == pattern

    solo_blocks = result["is_blocked"]
    flag = "OK" if solo_blocks else "GAP - does not block alone"
    if not is_isolated:
        flag += "  [WARNING: trigger matched >1 pattern, not a clean isolation test]"

    if not solo_blocks:
        gaps.append((pattern, weight, trigger))

    print(f"{pattern[:68]:<70} {trigger[:28]:<30} {result['risk_score']:<6} {flag}")

print("\n" + "=" * 60)
if gaps:
    print(f"{len(gaps)} PATTERN(S) DO NOT BLOCK IN ISOLATION:")
    for pattern, weight, trigger in gaps:
        print(f"  weight={weight:<4} pattern={pattern}")
else:
    print("All patterns block on their own. No solo-gap found.")
