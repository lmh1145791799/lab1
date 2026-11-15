from pymysql.err import OperationalError

import db

def process_expired():
    rows = db.find_expired_reservations()
    processed = []
    for reservation_id, status, _b, _s in rows:
        try:
            if status == "pending_confirm":
                result, info = db.expire_reservation(reservation_id)
                action = "reservation_expire"
                message = "reservation %s expired, product re-available" % reservation_id
            else:
                result, info = db.complete_trade(reservation_id)
                action = "reservation_auto_complete"
                message = "reservation %s auto completed by timeout" % reservation_id
        except OperationalError:
            continue
        if result != "OK":
            continue
        db.insert_operation_log(None, action, "system", "ok",
                                "reservation", reservation_id)
        db.insert_notification(info["buyer_id"], message, "scheduler")
        db.insert_notification(info["seller_id"], message, "scheduler")
        processed.append(reservation_id)
    return processed
