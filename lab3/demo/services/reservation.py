import datetime

import db
import models
from services.auth import require_role

RESERVE_VALID_DAYS = 14
CONFIRMED_VALID_DAYS = 14

def create_reservation(user, product_id, quantity, fingerprint):
    require_role(user, "buyer")
    if quantity < 1:
        raise models.Rejection("INVALID_QTY", "reservation quantity must be >= 1")
    if not fingerprint:
        raise models.Rejection("INVALID_INPUT", "request fingerprint required")

    product = db.find_product(product_id)
    if product is None:
        raise models.Rejection("PRODUCT_NOT_FOUND", "product does not exist")
    seller_id = product[1]

    deadline = datetime.datetime.now() + datetime.timedelta(days=RESERVE_VALID_DAYS)
    result, rid = db.create_reservation(
        product_id, user.user_id, seller_id, quantity, deadline, fingerprint
    )

    if result == models.CreateResult.OK.value:
        db.insert_operation_log(
            user.user_id, "reservation_create",
            "product=%s qty=%s" % (product_id, quantity),
            "ok", rid,
        )
        db.insert_notification(
            seller_id, "new reservation on product %s, qty %s"
            % (product_id, quantity), "reservation",
        )
        return rid
    if result == models.CreateResult.DUPLICATE.value:
        return rid
    if result == models.CreateResult.DUPLICATE_ACTIVE.value:
        raise models.Rejection(
            "ACTIVE_RESERVATION_EXISTS", "you already have an active reservation on this product"
        )
    if result == models.CreateResult.REJECTED.value:
        raise models.Rejection(
            "UNAVAILABLE", "product unavailable or insufficient stock, please refresh page"
        )
    raise models.Rejection("CONFLICT_RETRY", "concurrent conflict, please retry")


def _get_party_reservation(user, reservation_id):
    row = db.find_reservation(reservation_id)
    if row is None:
        raise models.Rejection("NOT_FOUND", "reservation does not exist")
    if user.user_id not in (row[2], row[3]):
        raise models.Rejection("FORBIDDEN", "not your reservation")
    return row


def confirm(user, reservation_id):
    require_role(user, "seller")
    row = _get_party_reservation(user, reservation_id)
    if row[5] != "pending_confirm":
        raise models.Rejection("INVALID_TRANSITION",
                               "reservation is not pending confirm")
    deadline = datetime.datetime.now() + datetime.timedelta(days=CONFIRMED_VALID_DAYS)
    result, info = db.confirm_reservation(reservation_id, deadline)
    if result != "OK":
        raise models.Rejection("CONFLICT_RETRY",
                               "reservation changed concurrently, please retry")
    db.insert_operation_log(user.user_id, "reservation_confirm", "",
                            "ok", reservation_id)
    db.insert_notification(info["buyer_id"],
                           "reservation %s confirmed by seller" % reservation_id,
                           "reservation")


def reject(user, reservation_id):
    require_role(user, "seller")
    row = _get_party_reservation(user, reservation_id)
    if row[5] != "pending_confirm":
        raise models.Rejection("INVALID_TRANSITION",
                               "reservation is not pending confirm")
    result, info = db.reject_reservation(reservation_id)
    if result != "OK":
        raise models.Rejection("CONFLICT_RETRY",
                               "reservation changed concurrently, please retry")
    db.insert_operation_log(user.user_id, "reservation_reject", "",
                            "ok", reservation_id)
    db.insert_notification(info["buyer_id"],
                           "reservation %s rejected by seller" % reservation_id,
                           "reservation")


def cancel(user, reservation_id, reason=None):
    row = _get_party_reservation(user, reservation_id)
    if row[5] not in ("pending_confirm", "confirmed"):
        raise models.Rejection("INVALID_TRANSITION",
                               "reservation is not cancellable")
    if row[5] == "confirmed" and not reason:
        raise models.Rejection("REASON_REQUIRED",
                               "cancel reason required after confirmation")
    result, info = db.cancel_reservation(reservation_id, reason)
    if result != "OK":
        raise models.Rejection("CONFLICT_RETRY",
                               "reservation changed concurrently, please retry")
    db.insert_operation_log(user.user_id, "reservation_cancel",
                            "reason=%s" % reason, "ok", reservation_id)
    db.insert_notification(info["seller_id"],
                           "reservation %s cancelled, reason: %s"
                           % (reservation_id, reason), "reservation")
    db.insert_notification(info["buyer_id"],
                           "reservation %s cancelled, reason: %s"
                           % (reservation_id, reason), "reservation")


def confirm_completion(user, reservation_id):
    row = _get_party_reservation(user, reservation_id)
    if row[5] != "confirmed":
        raise models.Rejection("INVALID_TRANSITION",
                               "reservation is not confirmed")
    party = "buyer" if user.user_id == row[2] else "seller"
    result, info = db.confirm_completion(reservation_id, party)
    if result != "OK":
        raise models.Rejection("CONFLICT_RETRY",
                               "reservation changed concurrently, please retry")
    db.insert_operation_log(user.user_id, "reservation_confirm_completion",
                            "party=%s" % party, "ok", reservation_id)
    if info["completed"]:
        db.insert_notification(info["buyer_id"],
                               "trade %s completed" % reservation_id,
                               "trade")
        db.insert_notification(info["seller_id"],
                               "trade %s completed" % reservation_id,
                               "trade")