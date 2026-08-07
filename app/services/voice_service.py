from app.database.oracle import get_connection


def investigate_voice_expiration(msisdn, start_date, end_date):
    connection = get_connection()
    cursor = connection.cursor()

    query = """
        SELECT start_date, a_msisdn, call_type,
               SUM(event_duration)/60 duree_minutes,
               SUM(ge_amount) amount
        FROM rd_t_uc_ccn_ro_gprs_cdr_detail
        WHERE a_msisdn = :msisdn
          AND start_date BETWEEN :start_date AND :end_date
          AND call_type = 'VOICE'
        GROUP BY start_date, a_msisdn, call_type
    """

    cursor.execute(query, {
        "msisdn": msisdn,
        "start_date": start_date,
        "end_date": end_date
    })

    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()

    results = [dict(zip(columns, row)) for row in rows]

    cursor.close()
    connection.close()

    return results
