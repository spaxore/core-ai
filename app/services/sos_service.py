from app.database.oracle import get_connection


def investigate_sos_credit(msisdn, start_date, end_date):
    connection = get_connection()
    cursor = connection.cursor()

    query = """
        SELECT DA_AMOUNT, START_DATE, EVENT_TYPE, EVENT_STATUS, SUBSCRIBER_TYPE, A_MSISDN
        FROM rd_t_uc_ussd_sos_cdr_det
        WHERE A_MSISDN = :msisdn
          AND START_DATE BETWEEN :start_date AND :end_date
          AND EVENT_TYPE = 'REV'
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
