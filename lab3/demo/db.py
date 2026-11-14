import os
import pymysql
from pymysql.err import IntegrityError, OperationalError
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "trading"),
    "charset": "utf8mb4",
    "autocommit": False,
    "init_command": "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",
}
# region DDL_STATEMENTS
DDL_STATEMENTS = [
"""
CREATE TABLE IF NOT EXISTS user (
    user_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
    account     VARCHAR(64)  NOT NULL UNIQUE,
    password    VARCHAR(128) NOT NULL,
    nickname    VARCHAR(64)  NOT NULL,
    contact     VARCHAR(64)
) ENGINE=InnoDB
""",
"""
CREATE TABLE IF NOT EXISTS user_role (
    user_id BIGINT NOT NULL,
    role    ENUM('buyer','seller','admin') NOT NULL,
    PRIMARY KEY (user_id, role),
    FOREIGN KEY (user_id) REFERENCES user(user_id)
) ENGINE=InnoDB
""",
"""
CREATE TABLE IF NOT EXISTS product (
    product_id   BIGINT AUTO_INCREMENT PRIMARY KEY,
    seller_id    BIGINT NOT NULL,
    title        VARCHAR(128) NOT NULL,
    description  TEXT,
    category     VARCHAR(64),
    price        DECIMAL(10,2) NOT NULL,
    condition_grade VARCHAR(32),
    location     VARCHAR(128),
    trade_method VARCHAR(32),
    stock_qty    INT NOT NULL,
    reserved_qty INT NOT NULL DEFAULT 0,
    status       ENUM('draft','pending_review','rejected','published',
                      'taken_down','violation_taken_down','sold') NOT NULL,
    publish_time DATETIME,
    FOREIGN KEY (seller_id) REFERENCES user(user_id),
    CHECK (reserved_qty >= 0 AND reserved_qty <= stock_qty)
) ENGINE=InnoDB
""",
"""
CREATE TABLE IF NOT EXISTS reservation (
    reservation_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id     BIGINT NOT NULL,
    buyer_id       BIGINT NOT NULL,
    seller_id      BIGINT NOT NULL,
    quantity       INT NOT NULL CHECK (quantity >= 1),
    reserve_time   DATETIME NOT NULL,
    valid_deadline DATETIME NOT NULL,
    status         ENUM('pending_confirm','confirmed','rejected',
                         'cancelled','expired','completed') NOT NULL,
    confirm_time   DATETIME,
    finish_time    DATETIME,
    cancel_reason  VARCHAR(255),
    fingerprint    CHAR(64) NOT NULL,
    active_buyer   BIGINT NULL,
    buyer_confirmed_at  DATETIME NULL,
    seller_confirmed_at DATETIME NULL,
    FOREIGN KEY (product_id) REFERENCES product(product_id),
    UNIQUE KEY ux_fingerprint (fingerprint),
    UNIQUE KEY ux_active_reservation (product_id, active_buyer)
) ENGINE=InnoDB
""",
"""
CREATE TABLE IF NOT EXISTS review_record (
    record_id  BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id BIGINT NOT NULL,
    admin_id   BIGINT NOT NULL,
    result     ENUM('approved','rejected') NOT NULL,
    reason     VARCHAR(255),
    audit_time DATETIME NOT NULL,
    FOREIGN KEY (product_id) REFERENCES product(product_id),
    FOREIGN KEY (admin_id) REFERENCES user(user_id)
) ENGINE=InnoDB
""",
"""
CREATE TABLE IF NOT EXISTS operation_log (
    log_id       BIGINT AUTO_INCREMENT PRIMARY KEY,
    operator_id  BIGINT NULL,
    action       VARCHAR(64) NOT NULL,
    detail       VARCHAR(255),
    result       VARCHAR(64),
    related_id   BIGINT,
    operate_time DATETIME NOT NULL,
    FOREIGN KEY (operator_id) REFERENCES user(user_id)
) ENGINE=InnoDB
""",
"""
CREATE TABLE IF NOT EXISTS notification (
    notice_id  BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    content    VARCHAR(255) NOT NULL,
    type       VARCHAR(32) NOT NULL,
    send_time  DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES user(user_id)
) ENGINE=InnoDB
""",
]
# endregion DDL_STATEMENTS
def get_connection():
    return pymysql.connect(**DB_CONFIG)

#product 相关操作
def insert_product(seller_id, title, description, category, price,
                   condition_grade, location, trade_method, stock_qty):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO product (seller_id, title, description, category, price, "
                "condition_grade, location, trade_method, stock_qty, reserved_qty, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 'draft')",
                (seller_id, title, description, category, price,
                 condition_grade, location, trade_method, stock_qty),
            )
            product_id = cur.lastrowid
        conn.commit()
        return product_id
    finally:
        conn.close()


def transition_product(product_id, from_status, to_status, publish=False):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            sql = "UPDATE product SET status = %s"
            params = [to_status]
            if publish:
                sql += ", publish_time = NOW()"
            sql += " WHERE product_id = %s AND status = %s"
            params.extend([product_id, from_status])
            cur.execute(sql, params)
            changed = cur.rowcount > 0
        conn.commit()
        return changed
    finally:
        conn.close()


def update_product(product_id, from_status, to_status, title, description,
                   category, price, condition_grade, location, trade_method,
                   stock_qty):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE product SET title=%s, description=%s, category=%s, price=%s, "
                "condition_grade=%s, location=%s, trade_method=%s, stock_qty=%s, "
                "status=%s WHERE product_id=%s AND status=%s AND reserved_qty = 0",
                (title, description, category, price, condition_grade, location,
                 trade_method, stock_qty, to_status, product_id, from_status),
            )
            changed = cur.rowcount > 0
        conn.commit()
        return changed
    finally:
        conn.close()


def adjust_stock(product_id, new_stock_qty):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE product SET stock_qty = %s "
                "WHERE product_id = %s AND status IN ('draft','published') "
                "AND %s >= reserved_qty",
                (new_stock_qty, product_id, new_stock_qty),
            )
            changed = cur.rowcount > 0
        conn.commit()
        return changed
    finally:
        conn.close()


def insert_review_record(product_id, admin_id, result, reason):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO review_record (product_id, admin_id, result, reason, "
                "audit_time) VALUES (%s, %s, %s, %s, NOW())",
                (product_id, admin_id, result, reason),
            )
        conn.commit()
    finally:
        conn.close()


def take_down_and_cancel(product_id, new_status, cancel_reason):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM product WHERE product_id = %s FOR UPDATE",
                (product_id,),
            )
            row = cur.fetchone()
            if row is None or row[0] != "published":
                conn.rollback()
                return ("REJECTED", 0)
            cur.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM reservation "
                "WHERE product_id = %s AND status IN ('pending_confirm','confirmed')",
                (product_id,),
            )
            active_qty = cur.fetchone()[0]
            cur.execute(
                "UPDATE product SET status = %s, "
                "reserved_qty = reserved_qty - %s "
                "WHERE product_id = %s",
                (new_status, active_qty, product_id),
            )
            cur.execute(
                "UPDATE reservation SET status = 'cancelled', cancel_reason = %s, "
                "active_buyer = NULL "
                "WHERE product_id = %s AND status IN ('pending_confirm','confirmed')",
                (cancel_reason, product_id),
            )
            cancelled = cur.rowcount
        conn.commit()
        return ("OK", cancelled)
    finally:
        conn.close()


def init_db(admin_config=None):
    cfg = dict(DB_CONFIG)
    db_name = cfg.pop("database")
    if admin_config:
        cfg.update(admin_config)
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS {db_name} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute(f"USE {db_name}")
            for stmt in DDL_STATEMENTS:
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()

def insert_user(account, password_hash, nickname, contact, roles):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user (account, password, nickname, contact) "
                "VALUES (%s, %s, %s, %s)",
                (account, password_hash, nickname, contact),
            )
            user_id = cur.lastrowid
            for role in roles:
                cur.execute(
                    "INSERT INTO user_role (user_id, role) VALUES (%s, %s)",
                    (user_id, role),
                )
        conn.commit()
        return user_id
    except IntegrityError:
        conn.rollback()
        return None
    finally:
        conn.close()


def find_user_by_account(account):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT u.user_id, u.account, u.password, u.nickname, u.contact, "
                "GROUP_CONCAT(r.role) "
                "FROM user u LEFT JOIN user_role r ON r.user_id = u.user_id "
                "WHERE u.account = %s GROUP BY u.user_id",
                (account,),
            )
            return cur.fetchone()
    finally:
        conn.close()

""" 清空所有数据(仅测试用) """
def clear_all_data():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table in ("reservation", "operation_log", "notification",
                          "user_role", "product", "user"):
                cur.execute("TRUNCATE TABLE " + table)
            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()
    finally:
        conn.close()


def find_product(product_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT product_id, seller_id, title, category, price, "
                "stock_qty, reserved_qty, status "
                "FROM product WHERE product_id = %s",
                (product_id,),
            )
            return cur.fetchone()
    finally:
        conn.close()

#通知日志相关操作
def insert_operation_log(operator_id, action, detail, result, related_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO operation_log (operator_id, action, detail, result, "
                "related_id, operate_time) VALUES (%s, %s, %s, %s, %s, NOW())",
                (operator_id, action, detail, result, related_id),
            )
        conn.commit()
    finally:
        conn.close()


def insert_notification(user_id, content, type):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notification (user_id, content, type, send_time) "
                "VALUES (%s, %s, %s, NOW())",
                (user_id, content, type),
            )
        conn.commit()
    finally:
        conn.close()

#reservation 相关操作
def create_reservation(product_id, buyer_id, seller_id, quantity, deadline, fingerprint):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT reservation_id FROM reservation WHERE fingerprint = %s",
                (fingerprint,),
            )
            row = cur.fetchone()
            if row:
                return ("DUPLICATE", row[0])
            cur.execute(
                "UPDATE product SET reserved_qty = reserved_qty + %s "
                "WHERE product_id = %s AND status = 'published' "
                "AND reserved_qty + %s <= stock_qty",
                (quantity, product_id, quantity),
            )
            if cur.rowcount == 0:
                return ("REJECTED", None)
            cur.execute(
                "INSERT INTO reservation (product_id, buyer_id, seller_id, quantity, "
                "reserve_time, valid_deadline, status, fingerprint, active_buyer) "
                "VALUES (%s, %s, %s, %s, NOW(), %s, 'pending_confirm', %s, %s)",
                (product_id, buyer_id, seller_id, quantity, deadline, fingerprint, buyer_id),
            )
            reservation_id = cur.lastrowid
        conn.commit()
        return ("OK", reservation_id)
    except IntegrityError:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT reservation_id FROM reservation WHERE fingerprint = %s",
                (fingerprint,),
            )
            row = cur.fetchone()
        if row:
            return ("DUPLICATE", row[0])
        return ("DUPLICATE_ACTIVE", None)
    except OperationalError:
        conn.rollback()
        return ("RETRY", None)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _lock_reservation(cur, reservation_id):
    cur.execute(
        "SELECT product_id FROM reservation WHERE reservation_id = %s",
        (reservation_id,),
    )
    hint = cur.fetchone()
    if hint is None:
        return None
    cur.execute(
        "SELECT product_id, status FROM product WHERE product_id = %s FOR UPDATE",
        (hint[0],),
    )
    cur.execute(
        "SELECT r.quantity, r.status, r.product_id, r.buyer_id, r.seller_id "
        "FROM reservation r WHERE r.reservation_id = %s FOR UPDATE",
        (reservation_id,),
    )
    return cur.fetchone()


def _release_and_close(conn, reservation_id, new_status, cancel_reason=None):
    with conn.cursor() as cur:
        row = _lock_reservation(cur, reservation_id)
        if row is None or row[1] not in ("pending_confirm", "confirmed"):
            conn.rollback()
            return ("REJECTED", None)
        quantity, product_id, buyer_id, seller_id = row[0], row[2], row[3], row[4]
        if cancel_reason is None:
            cur.execute(
                "UPDATE reservation SET status = %s, active_buyer = NULL "
                "WHERE reservation_id = %s AND status = %s",
                (new_status, reservation_id, row[1]),
            )
        else:
            cur.execute(
                "UPDATE reservation SET status = %s, active_buyer = NULL, "
                "cancel_reason = %s WHERE reservation_id = %s AND status = %s",
                (new_status, cancel_reason, reservation_id, row[1]),
            )
        cur.execute(
            "UPDATE product SET reserved_qty = reserved_qty - %s "
            "WHERE product_id = %s",
            (quantity, product_id),
        )
    conn.commit()
    return ("OK", {
        "product_id": product_id, "buyer_id": buyer_id,
        "seller_id": seller_id, "quantity": quantity,
    })


def confirm_reservation(reservation_id, confirmed_deadline):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            row = _lock_reservation(cur, reservation_id)
            if row is None or row[1] != "pending_confirm":
                conn.rollback()
                return ("REJECTED", None)
            cur.execute(
                "UPDATE reservation SET status = 'confirmed', confirm_time = NOW(), "
                "valid_deadline = %s WHERE reservation_id = %s "
                "AND status = 'pending_confirm'",
                (confirmed_deadline, reservation_id),
            )
        conn.commit()
        return ("OK", {
            "product_id": row[2], "buyer_id": row[3],
            "seller_id": row[4], "quantity": row[0],
        })
    finally:
        conn.close()


def reject_reservation(reservation_id):
    conn = get_connection()
    try:
        return _release_and_close(conn, reservation_id, "rejected")
    finally:
        conn.close()


def cancel_reservation(reservation_id, reason):
    conn = get_connection()
    try:
        return _release_and_close(conn, reservation_id, "cancelled", reason)
    finally:
        conn.close()


def expire_reservation(reservation_id):
    conn = get_connection()
    try:
        return _release_and_close(conn, reservation_id, "expired")
    finally:
        conn.close()


def complete_trade(reservation_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            row = _lock_reservation(cur, reservation_id)
            if row is None or row[1] != "confirmed":
                conn.rollback()
                return ("REJECTED", None)
            quantity, product_id = row[0], row[2]
            cur.execute(
                "UPDATE product SET stock_qty = stock_qty - %s, "
                "reserved_qty = reserved_qty - %s, "
                "status = IF(stock_qty - %s = 0, 'sold', status) "
                "WHERE product_id = %s",
                (quantity, quantity, quantity, product_id),
            )
            cur.execute(
                "UPDATE reservation SET status = 'completed', finish_time = NOW(), "
                "active_buyer = NULL WHERE reservation_id = %s "
                "AND status = 'confirmed'",
                (reservation_id,),
            )
        conn.commit()
        return ("OK", {
            "product_id": product_id, "buyer_id": row[3],
            "seller_id": row[4], "quantity": quantity,
        })
    finally:
        conn.close()


def confirm_completion(reservation_id, party):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            row = _lock_reservation(cur, reservation_id)
            if row is None or row[1] != "confirmed":
                conn.rollback()
                return ("REJECTED", None)
            quantity, product_id, buyer_id, seller_id = row[0], row[2], row[3], row[4]
            if party == "buyer":
                cur.execute(
                    "UPDATE reservation SET buyer_confirmed_at = NOW() "
                    "WHERE reservation_id = %s AND buyer_confirmed_at IS NULL",
                    (reservation_id,),
                )
            else:
                cur.execute(
                    "UPDATE reservation SET seller_confirmed_at = NOW() "
                    "WHERE reservation_id = %s AND seller_confirmed_at IS NULL",
                    (reservation_id,),
                )
            cur.execute(
                "SELECT buyer_confirmed_at, seller_confirmed_at "
                "FROM reservation WHERE reservation_id = %s",
                (reservation_id,),
            )
            flags = cur.fetchone()
            completed = flags[0] is not None and flags[1] is not None
            if completed:
                cur.execute(
                    "UPDATE product SET stock_qty = stock_qty - %s, "
                    "reserved_qty = reserved_qty - %s, "
                    "status = IF(stock_qty - %s = 0, 'sold', status) "
                    "WHERE product_id = %s",
                    (quantity, quantity, quantity, product_id),
                )
                cur.execute(
                    "UPDATE reservation SET status = 'completed', "
                    "finish_time = NOW(), active_buyer = NULL "
                    "WHERE reservation_id = %s AND status = 'confirmed'",
                    (reservation_id,),
                )
        conn.commit()
        return ("OK", {
            "product_id": product_id, "buyer_id": buyer_id,
            "seller_id": seller_id, "quantity": quantity,
            "completed": completed,
        })
    finally:
        conn.close()


def find_reservation(reservation_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT reservation_id, product_id, buyer_id, seller_id, "
                "quantity, status, valid_deadline "
                "FROM reservation WHERE reservation_id = %s",
                (reservation_id,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def find_expired_reservations():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT reservation_id, status, buyer_id, seller_id "
                "FROM reservation WHERE status IN ('pending_confirm','confirmed') "
                "AND valid_deadline < NOW()"
            )
            return cur.fetchall()
    finally:
        conn.close()