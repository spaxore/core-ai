from app.database.oracle import get_connection


def investigate_sms_vas(msisdn, start_date, end_date):
    connection = get_connection()
    cursor = connection.cursor()

    query = """
        SELECT A_MSISDN, B_MSISDN, START_DATE, CALL_TYPE,
               SUBSCRIBER_TYPE, CHARGE_AMOUNT, KEYWORD
        FROM rd_t_uc_occpp_sms_vas_dt
        WHERE A_MSISDN = :msisdn
          AND START_DATE BETWEEN :start_date AND :end_date
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
