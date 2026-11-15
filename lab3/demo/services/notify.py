import db
from services.auth import require_role

def my_notifications(user):
    require_role(user, "buyer", "seller", "admin")
    return db.list_user_notifications(user.user_id)

def logs_for_seller(user):
    require_role(user, "seller")
    return db.list_logs_for_seller(user.user_id)

def all_logs(user):
    require_role(user, "admin")
    return db.list_all_logs()

def my_reservations(user):
    require_role(user, "buyer")
    return db.list_user_reservations(user.user_id)

def reservations_to_handle(user):
    require_role(user, "seller")
    return db.list_seller_reservations(user.user_id)

def my_products(user):
    require_role(user, "seller", "admin")
    if any(r.value == "admin" for r in user.roles):
        return db.list_all_products()
    return db.list_seller_products(user.user_id)
