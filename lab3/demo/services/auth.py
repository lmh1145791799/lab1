import hashlib

import db
import models

def _hash(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def register(account, password, nickname, contact, roles):
    if not account or not password or not nickname:
        raise models.Rejection("INVALID_INPUT", "account/password/nickname required")
    if not roles or any(r not in ("buyer", "seller") for r in roles):
        raise models.Rejection("INVALID_ROLE", "roles must be buyer and/or seller")
    user_id = db.insert_user(account, _hash(password), nickname, contact, tuple(roles))
    if user_id is None:
        raise models.Rejection("ACCOUNT_EXISTS", "account already registered")
    return models.User(user_id, account, nickname, contact, tuple(roles))


def seed_admin(account, password):
    user_id = db.insert_user(account, _hash(password), "admin", None, ("admin",))
    if user_id is None:
        raise models.Rejection("ACCOUNT_EXISTS", "admin account already seeded")
    return user_id


def login(account, password):
    row = db.find_user_by_account(account)
    if row is None or row[2] != _hash(password):
        raise models.Rejection("AUTH_FAILED", "wrong account or password")
    roles = tuple(row[5].split(",")) if row[5] else ()
    return models.User(row[0], row[1], row[3], row[4], roles)


def require_role(user, *roles):
    have = {r.value for r in user.roles}
    if not set(roles) & have:
        raise models.Rejection("FORBIDDEN", "permission denied")
    return user
