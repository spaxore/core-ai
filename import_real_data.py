"""
Import real Tunisie Telecom CDR exports (.dsv files) into the local dev
Oracle schema, for testing the AI investigation pipeline against real
complaint data instead of only synthetic test data.

Handles the real export format:
  - pipe-delimited, double-quoted fields
  - European decimal format (comma, not dot) for NUMBER columns
  - DD/MM/YYYY dates
  - "_N" placeholder tokens kept literally for VARCHAR2 columns (this is
    what the source system uses for "not applicable" -- NOT converted to
    SQL NULL, since several NOT NULL columns can legitimately contain it)

Usage:
    python import_real_data.py

Expects dataccn.dsv, sms.dsv, sos.dsv to be in the same folder as this
script (or edit FILES below to point elsewhere). Reads DB connection
info from .env, same as the rest of the project.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime

import oracledb
from dotenv import load_dotenv

load_dotenv()

# ---- Per-table column order + type map, taken directly from DESC output ----
# type: "DATE" | "NUM" | "STR"

VOICE_TABLE = "RD_T_UC_CCN_RO_GPRS_CDR_DETAIL"
VOICE_COLUMNS = [
    ("NE", "STR"), ("A_MSISDN", "STR"), ("A_MSISDN_ORIG", "STR"), ("B_MSISDN", "STR"),
    ("B_MSISDN_ORIG", "STR"), ("ORIG_START_TIME", "STR"), ("APN", "STR"),
    ("CALLED_NO_GRP", "STR"), ("CALLING_NO_GRP", "STR"), ("CALL_TYPE", "STR"),
    ("GE_AMOUNT", "NUM"), ("EVENT_TYPE", "STR"), ("EVENT_TYPE_ORIG", "STR"),
    ("FILENAME", "STR"), ("LOCATION", "STR"), ("PARTNER", "STR"), ("PARTNER_CODE", "STR"),
    ("COUNTRY", "STR"), ("PORTABILITY_FLAG", "STR"), ("SERVICE_TYPE", "STR"),
    ("START_DATE", "DATE"), ("START_HOUR", "NUM"), ("SUBSCRIBER_TYPE", "STR"),
    ("TRAFFIC_TYPE", "STR"), ("DATA_VOLUME", "NUM"), ("TELE_SERVICE_CODE", "STR"),
    ("PGW_ADDRESS", "STR"), ("RECORD_TYPE", "STR"), ("FLEX1", "STR"), ("FLEX2", "STR"),
    ("FLEX3", "STR"), ("EVENT_DURATION", "NUM"), ("DA_VALUE", "STR"),
    ("MAIN_VALUE_AFTER", "NUM"), ("MAIN_VALUE_BEFORE", "NUM"), ("DA_VALUE_AFTER", "NUM"),
    ("DA_VALUE_BEFORE", "NUM"), ("KEYWORD", "STR"), ("DA_BEFORE_AMOUNT_LST", "STR"),
    ("DA_AFTER_AMOUNT_LST", "STR"), ("CHARGE_AMOUNT", "NUM"),
]

SMS_TABLE = "RD_T_UC_OCCPP_SMS_VAS_DT"
SMS_COLUMNS = [
    ("DATASOURCE", "STR"), ("A_MSISDN", "STR"), ("B_MSISDN", "STR"), ("START_DATE", "DATE"),
    ("START_HOUR", "NUM"), ("APN", "STR"), ("CALL_TYPE", "STR"), ("EVENT_TYPE", "STR"),
    ("CHARGING_ID", "STR"), ("SERVICE_ID", "STR"), ("SUBSCRIBER_TYPE", "STR"),
    ("ROAMING_TYPE", "STR"), ("PARTNER", "STR"), ("EVENT_COUNT", "NUM"), ("DATA_VOLUME", "NUM"),
    ("EVENT_DURATION", "NUM"), ("CHARGE_AMOUNT", "NUM"), ("FILTER_CODE", "STR"),
    ("KEYWORD", "STR"), ("ORIG_START_TIME", "STR"), ("DA_AMOUNT_CALC", "NUM"),
    ("MA_AMNT_CALC", "NUM"), ("FLEX_FLD1", "STR"), ("FLEX_FLD2", "STR"), ("FLEX_FLD3", "STR"),
]

SOS_TABLE = "RD_T_UC_USSD_SOS_CDR_DET"
SOS_COLUMNS = [
    ("CHARGE_AMOUNT", "NUM"), ("DA_AMOUNT", "NUM"), ("NE", "STR"), ("TYPE_SOS", "STR"),
    ("MAIN_DEB_AMOUNT", "NUM"), ("FILENAME", "STR"), ("START_DATE", "DATE"),
    ("START_HOUR", "NUM"), ("EVENT_TYPE", "STR"), ("EVENT_STATUS", "STR"),
    ("SUBSCRIBER_TYPE", "STR"), ("TRAFFIC_TYPE", "STR"), ("SERVICE_ID", "STR"),
    ("A_MSISDN", "STR"), ("ORIG_START_TIME", "STR"), ("TRANSACTION_ID", "STR"),
    ("SERVICE", "STR"), ("LOANADJUSTMENT", "NUM"), ("LOANLEFT", "NUM"),
    ("FEEADJUSTMENT", "NUM"), ("FEELEFT", "NUM"), ("FEE", "NUM"), ("LOAN_ID", "STR"),
    ("EVENT_ID", "STR"), ("CREDIT_DATE", "DATE"), ("CR_ORIG_START_TIME", "STR"),
]

DATA_TABLE = "RD_T_UC_OCCPP_DATA_DT"
DATA_COLUMNS = SMS_COLUMNS  # identical column shape, same OCCPP family (confirmed via DESC)

FILES = [
    ("dataccn.dsv", VOICE_TABLE, VOICE_COLUMNS),
    ("sms.dsv", SMS_TABLE, SMS_COLUMNS),
    ("sos.dsv", SOS_TABLE, SOS_COLUMNS),
    ("occpp_data.dsv", DATA_TABLE, DATA_COLUMNS),
]


def convert_value(raw: str, col_type: str):
    raw = raw.strip()
    if col_type == "DATE":
        if not raw:
            return None
        return datetime.strptime(raw, "%d/%m/%Y").date()
    if col_type == "NUM":
        if raw == "" or raw == "_N":
            return None
        return float(raw.replace(",", "."))
    # STR -- keep literally, including "_N" (a real source-system token,
    # not a NULL marker -- several NOT NULL columns can legitimately hold it)
    return raw if raw != "" else None


def parse_file(path: str, columns: list[tuple[str, str]]) -> list[tuple]:
    rows = []
    errors = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter="|", quotechar='"')
        header = next(reader)
        if len(header) != len(columns):
            raise ValueError(
                f"{path}: expected {len(columns)} columns, file header has {len(header)}. "
                f"Column order/count mismatch -- stopping rather than risk mis-mapped inserts."
            )
        for i, raw_row in enumerate(reader, start=2):
            if len(raw_row) != len(columns):
                errors.append(f"line {i}: expected {len(columns)} fields, got {len(raw_row)} -- skipped")
                continue
            try:
                converted = tuple(
                    convert_value(val, col_type)
                    for val, (_, col_type) in zip(raw_row, columns)
                )
                rows.append(converted)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"line {i}: {exc} -- skipped")
    return rows, errors


def import_table(conn, table: str, columns: list[tuple[str, str]], rows: list[tuple]):
    col_names = ", ".join(name for name, _ in columns)
    placeholders = ", ".join(f":{i+1}" for i in range(len(columns)))
    sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"

    cursor = conn.cursor()
    cursor.executemany(sql, rows)
    conn.commit()
    cursor.close()


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    conn = oracledb.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dsn=os.getenv("DB_DSN"),
    )

    for filename, table, columns in FILES:
        path = os.path.join(base_dir, filename)
        if not os.path.exists(path):
            print(f"SKIPPED: {filename} not found at {path}")
            continue

        print(f"\n=== {filename} -> {table} ===")
        rows, errors = parse_file(path, columns)
        print(f"Parsed {len(rows)} row(s), {len(errors)} error(s).")
        for e in errors[:10]:
            print("  ", e)
        if len(errors) > 10:
            print(f"   ...and {len(errors) - 10} more")

        if rows:
            import_table(conn, table, columns, rows)
            print(f"Inserted {len(rows)} row(s) into {table}.")
        else:
            print("Nothing to insert.")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
