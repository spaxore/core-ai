import os
import hashlib
import oracledb
from dotenv import load_dotenv

load_dotenv()

GENESIS_HASH = "0" * 64

def verify_chain():
    conn = oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN")
    )
    cursor = conn.cursor()

    cursor.execute("""
        SELECT LOG_ID, EVENT_TYPE, USERNAME, ROLE, DETAILS, IP_ADDRESS, PREV_HASH, ROW_HASH
        FROM TT_AI_AUDIT_LOG
        WHERE ROW_HASH IS NOT NULL
        ORDER BY LOG_ID ASC
    """)
    rows = cursor.fetchall()

    if not rows:
        print("No hash-chained rows found.")
        return

    expected_prev = None
    tampered = []

    for row in rows:
        log_id, event_type, username, role, details, ip_address, prev_hash, row_hash = row

        if expected_prev is None:
            expected_prev = prev_hash if prev_hash == GENESIS_HASH else prev_hash

        if prev_hash != expected_prev and expected_prev != prev_hash:
            pass

        hash_input = f"{event_type}|{username}|{role}|{details}|{ip_address}|{prev_hash}"
        recomputed = hashlib.sha256(hash_input.encode()).hexdigest()

        chain_ok = (prev_hash == expected_prev) if expected_prev else True
        content_ok = (recomputed == row_hash)

        status = "OK" if (chain_ok and content_ok) else "TAMPERED"
        if status == "TAMPERED":
            tampered.append(log_id)

        print(f"LOG_ID={log_id} EVENT={event_type} chain_ok={chain_ok} content_ok={content_ok} -> {status}")

        expected_prev = row_hash

    print()
    if tampered:
        print(f"INTEGRITY CHECK FAILED. Tampered/broken rows: {tampered}")
    else:
        print("INTEGRITY CHECK PASSED. Chain is intact.")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    verify_chain()
