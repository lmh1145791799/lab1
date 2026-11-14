from enum import Enum
from typing import Optional

class ProductStatus(Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    PUBLISHED = "published"
    TAKEN_DOWN = "taken_down"
    VIOLATION_TAKEN_DOWN = "violation_taken_down"
    SOLD = "sold"

class ReservationStatus(Enum):
    PENDING_CONFIRM = "pending_confirm"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    COMPLETED = "completed"

class Role(Enum):
    BUYER = "buyer"
    SELLER = "seller"
    ADMIN = "admin"

class CreateResult(Enum):
    OK = "ok"
    DUPLICATE = "duplicate"
    DUPLICATE_ACTIVE = "duplicate_active"
    REJECTED = "rejected"
    RETRY = "retry"

class User:
    def __init__(self, user_id, account, nickname, contact, roles):
        self.user_id = user_id
        self.account = account
        self.nickname = nickname
        self.contact = contact
        self.roles = frozenset(Role(r) for r in roles)

    def __repr__(self):
        return "User(%s, %s)" % (self.account, "/".join(sorted(r.value for r in self.roles)))

class Product:
    def __init__(self, product_id, seller_id, title, category, price,
                 stock_qty, reserved_qty, status):
        self.product_id = product_id
        self.seller_id = seller_id
        self.title = title
        self.category = category
        self.price = price
        self.stock_qty = stock_qty
        self.reserved_qty = reserved_qty
        self.status = ProductStatus(status)

    @property
    def available_qty(self):
        return self.stock_qty - self.reserved_qty

class Reservation:
    def __init__(self, reservation_id, product_id, buyer_id, seller_id,
                 quantity, reserve_time, valid_deadline, status,
                 confirm_time=None, finish_time=None, cancel_reason=None):
        self.reservation_id = reservation_id
        self.product_id = product_id
        self.buyer_id = buyer_id
        self.seller_id = seller_id
        self.quantity = quantity
        self.reserve_time = reserve_time
        self.valid_deadline = valid_deadline
        self.status = ReservationStatus(status)
        self.confirm_time = confirm_time
        self.finish_time = finish_time
        self.cancel_reason = cancel_reason

class OperationLog:
    def __init__(self, log_id, operator_id, action, detail, result,
                 related_id, operate_time):
        self.log_id = log_id
        self.operator_id = operator_id
        self.action = action
        self.detail = detail
        self.result = result
        self.related_id = related_id
        self.operate_time = operate_time

class Notification:
    def __init__(self, notice_id, user_id, content, type, send_time):
        self.notice_id = notice_id
        self.user_id = user_id
        self.content = content
        self.type = type
        self.send_time = send_time

class Rejection(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message