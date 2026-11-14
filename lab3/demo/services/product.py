import db
import models
from services.auth import require_role

def _validate_product_fields(title, price, stock_qty):
    if not title:
        raise models.Rejection("INVALID_INPUT", "title required")
    if price is None or price <= 0:
        raise models.Rejection("INVALID_INPUT", "price must be positive")
    if stock_qty is None or stock_qty < 1:
        raise models.Rejection("INVALID_INPUT", "stock quantity must be >= 1")

def _get_product(product_id):
    product = db.find_product(product_id)
    if product is None:
        raise models.Rejection("PRODUCT_NOT_FOUND", "product does not exist")
    return product


def _get_owned_product(user, product_id):
    product = _get_product(product_id)
    if product[1] != user.user_id:
        raise models.Rejection("FORBIDDEN", "not your product")
    return product

def create_draft(user, title, description, category, price, condition_grade,
                 location, trade_method, stock_qty):
    require_role(user, "seller")
    _validate_product_fields(title, price, stock_qty)
    pid = db.insert_product(user.user_id, title, description, category, price,
                            condition_grade, location, trade_method, stock_qty)
    db.insert_operation_log(user.user_id, "product_create", "title=%s" % title,
                            "ok", pid)
    return pid

def submit_for_review(user, product_id):
    require_role(user, "seller")
    _get_owned_product(user, product_id)
    if not db.transition_product(product_id, "draft", "pending_review"):
        raise models.Rejection("INVALID_TRANSITION",
                               "product is not in draft status")
    db.insert_operation_log(user.user_id, "product_submit_review", "",
                            "ok", product_id)

def audit(user, product_id, approved, reason=None):
    require_role(user, "admin")
    if not approved and not reason:
        raise models.Rejection("REASON_REQUIRED",
                               "rejection reason required")
    if approved:
        changed = db.transition_product(product_id, "pending_review",
                                        "published", publish=True)
        result = "approved"
    else:
        changed = db.transition_product(product_id, "pending_review", "rejected")
        result = "rejected"
    if not changed:
        raise models.Rejection("INVALID_TRANSITION",
                               "product is not pending review")
    db.insert_review_record(product_id, user.user_id, result, reason)
    product = db.find_product(product_id)
    db.insert_notification(product[1],
                           "product %s audit result: %s" % (product_id, result),
                           "audit")
    db.insert_operation_log(user.user_id, "product_audit",
                            "result=%s reason=%s" % (result, reason),
                            result, product_id)

def modify_product(user, product_id, title, description, category, price,
                   condition_grade, location, trade_method, stock_qty):
    require_role(user, "seller")
    _validate_product_fields(title, price, stock_qty)
    product = _get_owned_product(user, product_id)
    status = product[7]
    if status == "draft":
        to_status = "draft"
    elif status in ("rejected", "published"):
        if status == "published" and product[6] > 0:
            raise models.Rejection(
                "RESERVATIONS_EXIST",
                "active reservations exist, only stock adjustment allowed")
        to_status = "pending_review"
    else:
        raise models.Rejection("INVALID_TRANSITION",
                               "product cannot be modified in current status")
    changed = db.update_product(product_id, status, to_status, title,
                                description, category, price, condition_grade,
                                location, trade_method, stock_qty)
    if not changed:
        raise models.Rejection("CONFLICT_RETRY",
                               "product changed concurrently, please retry")
    db.insert_operation_log(user.user_id, "product_modify",
                            "from=%s to=%s" % (status, to_status),
                            "ok", product_id)

def adjust_stock(user, product_id, new_qty):
    require_role(user, "seller")
    if new_qty is None or new_qty < 1:
        raise models.Rejection("INVALID_INPUT", "stock quantity must be >= 1")
    _get_owned_product(user, product_id)
    if not db.adjust_stock(product_id, new_qty):
        raise models.Rejection("STOCK_CONFLICT",
                               "new stock must cover active reservations")
    db.insert_operation_log(user.user_id, "product_adjust_stock",
                            "new_qty=%s" % new_qty, "ok", product_id)


def take_down(user, product_id):
    require_role(user, "seller")
    product = _get_owned_product(user, product_id)
    result, cancelled = db.take_down_and_cancel(product_id, "taken_down",
                                                "卖家强制取消")
    if result != "OK":
        raise models.Rejection("INVALID_TRANSITION",
                               "product is not published")
    db.insert_operation_log(user.user_id, "product_take_down",
                            "cancelled=%d" % cancelled, "ok", product_id)
    db.insert_notification(product[1],
                           "product %s taken down, %d active reservations "
                           "cancelled" % (product_id, cancelled), "take_down")

def handle_violation(user, product_id, reason):
    require_role(user, "admin")
    if not reason:
        raise models.Rejection("REASON_REQUIRED",
                               "violation reason required")
    product = _get_product(product_id)
    result, cancelled = db.take_down_and_cancel(product_id,
                                                "violation_taken_down", reason)
    if result != "OK":
        raise models.Rejection("INVALID_TRANSITION",
                               "product is not published")
    db.insert_operation_log(user.user_id, "product_violation",
                            "reason=%s cancelled=%d" % (reason, cancelled),
                            "ok", product_id)
    db.insert_notification(product[1],
                           "product %s violation taken down, reason: %s"
                           % (product_id, reason), "violation")

def republish(user, product_id):
    require_role(user, "seller")
    _get_owned_product(user, product_id)
    if not db.transition_product(product_id, "taken_down", "published"):
        raise models.Rejection("INVALID_TRANSITION",
                               "product is not taken down")
    db.insert_operation_log(user.user_id, "product_republish", "",
                            "ok", product_id)

def restore_from_violation(user, product_id):
    require_role(user, "admin")
    _get_product(product_id)
    if not db.transition_product(product_id, "violation_taken_down",
                                 "published"):
        raise models.Rejection("INVALID_TRANSITION",
                               "product is not violation taken down")
    db.insert_operation_log(user.user_id, "product_restore", "",
                            "ok", product_id)