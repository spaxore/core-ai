"""
Seeds one fabricated ("honeytoken") row per CDR table into the live
Oracle schema, using app.security.honeytoken.CANARY_MSISDN -- a number
outside real Tunisian allocation ranges that no genuine complaint can
ever legitimately reference. See app/security/honeytoken.py for how
detection uses this.

DELIBERATELY NOT RUN AUTOMATICALLY. This writes to the live Oracle
schema -- review the INSERTs below (columns match each service's own
SELECT: voice_service.py, data_service.py, sms_service.py,
sos_service.py, renewal_service.py) before running:

    python scripts/seed_honeytoken.py

Safe to re-run: each block checks for an existing canary row in that
table first and skips the insert if one is already there.
"""
from datetime import date

from app.database.oracle import get_connection
from app.security.honeytoken import CANARY_MSISDN

CANARY_DATE = date.today()


def _already_seeded(cursor, table, msisdn_column="A_MSISDN"):
    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {msisdn_column} = :msisdn", msisdn=CANARY_MSISDN)
    return cursor.fetchone()[0] > 0


def seed_voice(cursor):
    # rd_t_uc_ccn_ro_gprs_cdr_detail -- columns per voice_service.py:58-67
    if _already_seeded(cursor, "rd_t_uc_ccn_ro_gprs_cdr_detail"):
        return
    cursor.execute("""
        INSERT INTO rd_t_uc_ccn_ro_gprs_cdr_detail
            (start_date, a_msisdn, call_type, da_value, da_value_before, da_value_after,
             main_value_before, main_value_after, charge_amount)
        VALUES
            (:start_date, :msisdn, 'VOICE', '4', 20.0, 15.0, 0.0, 0.0, 5.0)
    """, start_date=CANARY_DATE, msisdn=CANARY_MSISDN)


def seed_data(cursor):
    # rd_t_uc_occpp_data_dt -- columns per data_service.py:49-54, plus every
    # other NOT NULL-without-default column on this table (confirmed via
    # USER_TAB_COLUMNS: DATASOURCE, APN, EVENT_TYPE, CHARGING_ID,
    # SERVICE_ID, PARTNER, FILTER_CODE, FLEX_FLD1, FLEX_FLD3).
    if _already_seeded(cursor, "rd_t_uc_occpp_data_dt"):
        return
    cursor.execute("""
        INSERT INTO rd_t_uc_occpp_data_dt
            (datasource, a_msisdn, start_date, apn, call_type, event_type, charging_id,
             service_id, subscriber_type, roaming_type, partner, filter_code,
             flex_fld1, flex_fld2, flex_fld3, data_volume, charge_amount)
        VALUES
            ('CANARY', :msisdn, :start_date, 'CANARY', 'DATA', 'CANARY', 'CANARY',
             'CANARY', 'PREPAID', 'N', 'CANARY', 'CANARY',
             '0', '7', '0', 29569, 2.0)
    """, msisdn=CANARY_MSISDN, start_date=CANARY_DATE)


def seed_sms(cursor):
    # rd_t_uc_occpp_sms_vas_dt -- columns per sms_service.py:13-14, plus
    # every other NOT NULL-without-default column (same set as data_dt --
    # both tables share the same base schema shape).
    if _already_seeded(cursor, "rd_t_uc_occpp_sms_vas_dt"):
        return
    cursor.execute("""
        INSERT INTO rd_t_uc_occpp_sms_vas_dt
            (datasource, a_msisdn, b_msisdn, start_date, apn, call_type, event_type,
             charging_id, service_id, subscriber_type, roaming_type, partner, filter_code,
             flex_fld1, flex_fld2, flex_fld3, charge_amount, keyword)
        VALUES
            ('CANARY', :msisdn, '00000000', :start_date, 'CANARY', 'SMS', 'CANARY',
             'CANARY', 'CANARY', 'PREPAID', 'N', 'CANARY', 'CANARY',
             '0', '0', '0', 0.5, 'CANARY')
    """, msisdn=CANARY_MSISDN, start_date=CANARY_DATE)


def seed_sos(cursor):
    # rd_t_uc_ussd_sos_cdr_det -- columns per sos_service.py:13-14
    if _already_seeded(cursor, "rd_t_uc_ussd_sos_cdr_det"):
        return
    cursor.execute("""
        INSERT INTO rd_t_uc_ussd_sos_cdr_det
            (a_msisdn, start_date, event_type, event_status, subscriber_type, charge_amount, da_amount, loan_id)
        VALUES
            (:msisdn, :start_date, 'REV', 'SUCCESS', 'PREPAID', 2.0, 2.0, 999999)
    """, msisdn=CANARY_MSISDN, start_date=CANARY_DATE)


def seed_renewal(cursor):
    # rd_t_uc_ussd_140_details -- columns per renewal_service.py:37-46
    if _already_seeded(cursor, "rd_t_uc_ussd_140_details"):
        return
    cursor.execute("""
        INSERT INTO rd_t_uc_ussd_140_details
            (a_msisdn, service_code, orig_start_time, description, status, status_details,
             action, start_date, event_status)
        VALUES
            (:msisdn, 'PKG_renew_CANARY', :start_date, 'Canary renewal attempt', 'Failure',
             'Insufficient balance', 'auto-renew unsubscription', :start_date, 'Failure')
    """, msisdn=CANARY_MSISDN, start_date=CANARY_DATE)


def seed_adjustment(cursor):
    # rd_t_uc_air_cdr_det -- columns per renewal_service.py:95-96
    if _already_seeded(cursor, "rd_t_uc_air_cdr_det"):
        return
    cursor.execute("""
        INSERT INTO rd_t_uc_air_cdr_det
            (a_msisdn, charge_amount, da_amount, da_value, record_type, orig_start_time,
             dedictated_amnt, ded_amnt_before, ded_amnt_after, start_date)
        VALUES
            (:msisdn, 0.0, 5.0, '4', 'adjustmentRecordV2', :start_date, 5.0, 0.0, 5.0, :start_date)
    """, msisdn=CANARY_MSISDN, start_date=CANARY_DATE)


SEEDERS = [seed_voice, seed_data, seed_sms, seed_sos, seed_renewal, seed_adjustment]


def main():
    connection = get_connection()
    cursor = connection.cursor()
    for seeder in SEEDERS:
        seeder(cursor)
    connection.commit()
    cursor.close()
    connection.close()
    print(f"Honeytoken MSISDN {CANARY_MSISDN} seeded (or already present) across {len(SEEDERS)} CDR tables.")


if __name__ == "__main__":
    main()
