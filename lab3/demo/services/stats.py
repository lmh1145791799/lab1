import db
import models
from services.auth import require_role

def seller_view(user):
    require_role(user, "seller")
    return db.seller_statistics(user.user_id)

def admin_view(user):
    require_role(user, "admin")
    return db.admin_statistics()

def search(user, keyword=None, category=None, min_price=None,
           max_price=None, location=None, sort_desc=False):
    require_role(user, "buyer", "seller")
    if min_price is not None and max_price is not None \
            and min_price > max_price:
        raise models.Rejection("INVALID_RANGE",
                               "price range: min > max")
    return db.search_products(keyword, category, min_price, max_price,
                              location, sort_desc)