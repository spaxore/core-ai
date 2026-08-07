from app.services.voice_service import investigate_voice_expiration
from app.services.sms_service import investigate_sms_vas
from app.services.data_service import investigate_data_usage
from app.services.sos_service import investigate_sos_credit


def run_investigation(category, msisdn, start_date, end_date):

    if category == "VOICE_EXPIRATION":
        return investigate_voice_expiration(msisdn, start_date, end_date)

    elif category == "SMS_VAS":
        return investigate_sms_vas(msisdn, start_date, end_date)

    elif category == "DATA_USAGE":
        return investigate_data_usage(msisdn, start_date, end_date)

    elif category == "SOS_CREDIT":
        return investigate_sos_credit(msisdn, start_date, end_date)

    elif category == "BALANCE_DEDUCTION":
        return {"error": "BALANCE_DEDUCTION investigation not implemented yet"}

    else:
        return {"error": f"Unknown category: {category}"}
