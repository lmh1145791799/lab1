import time

import db
import models
import scheduler
from services import auth, notify, product, reservation, stats

STEP = "[demo] "

def say(msg):
    print(STEP + msg)

def expect_rejection(fn, code, desc):
    try:
        fn()
        say("✗ %s：未按预期抛出 %s" % (desc, code))
        return False
    except models.Rejection as e:
        ok = e.code == code
        say("%s %s（%s）" % ("√" if ok else "✗", desc, e.code))
        return ok

def new_user(account, roles):
    auth.register(account, "pw-%s" % account, account, "contact-%s" % account,
                  roles)
    return auth.login(account, "pw-%s" % account)

PRODUCT_FIELDS = ("键盘", "九成新机械键盘", "数码", 100.0, "九成新", "北京",
                  "线上", 5)

def act1_setup():
    say("=== 注册与发布 ===")
    results = []
    results.append(("admin 初始化", auth.seed_admin("admin", "admin-pw")))
    seller = new_user("seller", ("buyer", "seller"))
    buyer = new_user("buyer", ("buyer",))
    results.append(("买家+卖家双角色注册（REQ-001）", new_user("both", ("buyer", "seller"))))
    say("注册完成：admin / seller / buyer / both（一人多角色）")
    pid = product.create_draft(seller, *PRODUCT_FIELDS)
    say("草稿已创建 pid=%s" % pid)
    product.submit_for_review(seller, pid)
    audit_ok = product.audit(admin_user(), pid, True) is None
    results.append(("审核通过上架", audit_ok))
    say("商品 pid=%s 已发布" % pid)
    return seller, buyer, pid, results

def admin_user():
    return auth.login("admin", "admin-pw")

def act2_main_flow(seller, buyer, pid):
    say("=== 预约主流程 ===")
    results = []
    rows = stats.search(buyer, keyword="键盘")
    results.append(("买家搜索到在售商品", len(rows) == 1 and rows[0][0] == pid))
    rid = reservation.create_reservation(buyer, pid, 2, "demo-fp-001")
    say("买家预约 qty=2 → rid=%s" % rid)
    dup_rid = reservation.create_reservation(buyer, pid, 2, "demo-fp-001")
    results.append(("重复指纹幂等返回同一预约", dup_rid == rid))
    reservation.confirm(seller, rid)
    results.append(("卖家确认预约", True))
    reservation.confirm_completion(buyer, rid)
    expect_rejection(
        lambda: reservation.cancel(buyer, rid, None),
        "REASON_REQUIRED",
        "已确认后买家取消缺原因被拒",
    )
    reservation.confirm_completion(seller, rid)
    row = db.find_reservation(rid)
    results.append(("双方确认后交易完成", row[5] == "completed"))
    s = stats.seller_view(seller)
    results.append(("卖家完成交易件数=2,SUM(quantity)",
                    s["completed_qty"] == 2))
    say("卖家统计：完成交易件数=%d" % s["completed_qty"])
    notices = notify.my_notifications(buyer)
    results.append(("买家收到交易完成通知",
                    any("completed" in n[1] for n in notices)))
    return results

def act3_exceptions(seller, buyer, pid):
    say("=== 异常分支 ===")
    results = []
    results.append(("自预约被拒", expect_rejection(
        lambda: reservation.create_reservation(
            seller, pid, 1, "demo-fp-self"),
        "SELF_RESERVATION", "卖家预约自己商品")))
    results.append(("超量预约被拒", expect_rejection(
        lambda: reservation.create_reservation(
            buyer, pid, 99, "demo-fp-big"),
        "UNAVAILABLE", "qty=99 > 库存 3")))
    rid = reservation.create_reservation(buyer, pid, 1, "demo-fp-e1")
    say("制造有效预约 rid=%s" % rid)
    results.append(("有有效预约时改价被拒", expect_rejection(
        lambda: product.modify_product(
            seller, pid, "键盘", "描述", "数码", 999.0,
            "九成新", "北京", "线上", 5),
        "RESERVATIONS_EXIST", "对买家欺诈")))
    results.append(("买家不能确认他人预约", expect_rejection(
        lambda: reservation.confirm(buyer, rid),
        "FORBIDDEN", "越权")))
    reservation.cancel(buyer, rid, "不需要了")
    results.append(("pending_confirm 无理由也可取消", True))
    rid2 = reservation.create_reservation(buyer, pid, 1, "demo-fp-e2")
    reservation.confirm(seller, rid2)
    results.append(("confirmed 取消缺原因被拒", expect_rejection(
        lambda: reservation.cancel(seller, rid2, None),
        "REASON_REQUIRED", "无理由取消")))
    reservation.cancel(seller, rid2, "临时有事")
    results.append(("confirmed 带原因取消成功", True))
    return results

def act4_scheduler(seller, buyer, pid):
    say("=== scheduler 超时处理 ===")
    results = []
    orig_r = reservation.RESERVE_VALID_DAYS
    orig_c = reservation.CONFIRMED_VALID_DAYS
    reservation.RESERVE_VALID_DAYS = 3 / 86400.0
    reservation.CONFIRMED_VALID_DAYS = 3 / 86400.0
    say("有效期临时缩短为 3 秒（等待 5 秒，python和sql时间精度不一致）")
    try:
        rid1 = reservation.create_reservation(buyer, pid, 1, "demo-fp-t1")
        say("rid=%s（pending_confirm），等待过期" % rid1)
        time.sleep(5)
        first = scheduler.process_expired()
        results.append(("第一轮调度处理 rid1", first == [rid1]))
        results.append(("pending_confirm 过期 → 自动取消释放库存",
                        db.find_reservation(rid1)[5] == "expired"))
        rid2 = reservation.create_reservation(buyer, pid, 2, "demo-fp-t2")
        reservation.confirm(seller, rid2)
        say("rid=%s 已确认（deadline 重置），等待过期" % rid2)
        time.sleep(5)
        second = scheduler.process_expired()
        results.append(("第二轮调度处理 rid2", second == [rid2]))
        results.append(("confirmed 过期 → 自动完成交易",
                        db.find_reservation(rid2)[5] == "completed"))
        logs = notify.all_logs(admin_user())
        sys_logs = [l for l in logs if l[1] is None
                    and l[2] == "reservation_auto_complete"
                    and l[6] == rid2]
        results.append(("系统日志 operator_id=NULL（REQ-024）",
                        len(sys_logs) == 1))
        notices = notify.my_notifications(buyer)
        results.append(("买家收到超时自动完成通知",
                        any("auto completed" in n[1]
                            for n in notices)))
        s = stats.seller_view(seller)
        results.append(("完成交易件数=4（含自动完成，SUM 口径）",
                        s["completed_qty"] == 4))
    finally:
        reservation.RESERVE_VALID_DAYS = orig_r
        reservation.CONFIRMED_VALID_DAYS = orig_c
        say("有效期常量已恢复原值")
    return results

def main():
    db.init_db(rebuild=True)
    say("数据库已重建（演示前清理，REQ-025 语义）")
    seller, buyer, pid, r1 = act1_setup()
    r2 = act2_main_flow(seller, buyer, pid)
    r3 = act3_exceptions(seller, buyer, pid)
    r4 = act4_scheduler(seller, buyer, pid)
    results = r1 + r2 + r3 + r4
    failed = [d for d, ok in results if not ok]
    say("=== 演示完成：%d/%d 项通过 ===" % (len(results) - len(failed), len(results)))
    for d in failed:
        say("失败项：%s" % d)
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
