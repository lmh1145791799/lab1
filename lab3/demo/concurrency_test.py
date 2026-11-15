import datetime
import threading

import db
from services import auth, product

STEP = "[conc] "
DEADLOCK_ERRNO = 1213

def say(msg):
    print(STEP + msg)

def deadline():
    return datetime.datetime.now() + datetime.timedelta(days=14)

def run_concurrently(work, n):
    barrier = threading.Barrier(n)
    results = [None] * n
    errors = [None] * n
    threads = []
    def wrapper(i):
        try:
            barrier.wait(timeout=10)
            results[i] = work(i)
        except Exception as e:
            errors[i] = e
    for i in range(n):
        t = threading.Thread(target=wrapper, args=(i,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results, errors

def summarize(results, errors):
    ok = sum(1 for r in results if r and r[0] == "OK")
    deadlock = sum(1 for e in errors
                   if isinstance(e, db.OperationalError)
                   and e.args[0] == DEADLOCK_ERRNO)
    other = sum(1 for e in errors
                if e is not None
                and not (isinstance(e, db.OperationalError)
                         and e.args[0] == DEADLOCK_ERRNO))
    return ok, deadlock, other

def admin_user():
    return auth.login("admin", "admin-pw")

def make_users():
    auth.seed_admin("admin", "admin-pw")
    auth.register("seller", "pw", "seller", "c-seller", ("buyer", "seller"))
    seller = auth.login("seller", "pw")
    buyers = []
    for i in range(24):
        account = "buyer%d" % i
        auth.register(account, "pw", account, "c-%s" % account, ("buyer",))
        buyers.append(auth.login(account, "pw"))
    return seller, buyers

def publish(seller, stock):
    pid = product.create_draft(seller, "压测商品", "并发压测", "数码", 10.0,
                               "新", "北京", "线上", stock)
    product.submit_for_review(seller, pid)
    product.audit(admin_user(), pid, True)
    return pid

def scenario1_oversell(seller, buyers):
    say("场景1：库存5，24买家各约1件 → 成功数必须恰好5")
    pid = publish(seller, 5)
    seller_id = seller.user_id
    def work(i):
        return db.create_reservation(pid, buyers[i].user_id, seller_id, 1,
                                     deadline(), "s1-fp-%d" % i)
    results, errors = run_concurrently(work, 24)
    ok, dead, other = summarize(results, errors)
    p = db.find_product(pid)
    a = (ok == 5
         and sum(1 for r in results if r and r[0] == "REJECTED") == 19
         and other == 0
         and p[5] == 5 and p[6] == 5)
    say("成功=%d 拒绝=%d 死锁=%d 其它异常=%d 库存=%s 预约占用量=%s"
        % (ok, sum(1 for r in results if r and r[0] == "REJECTED"),
           dead, other, p[5], p[6]))
    report("场景1 无超卖（条件 UPDATE 串行化）", a)
    return a

def scenario2_active_buyer_unique(seller, buyers):
    say("场景2：同一买家16线程同时预约库存充足商品 → 恰好1个成功")
    pid = publish(seller, 100)
    seller_id = seller.user_id
    buyer = buyers[0]
    def work(i):
        return db.create_reservation(pid, buyer.user_id, seller_id, 1,
                                     deadline(), "s2-fp-%d" % i)
    results, errors = run_concurrently(work, 16)
    ok, dead, other = summarize(results, errors)
    dup_active = sum(1 for r in results if r and r[0] == "DUPLICATE_ACTIVE")
    p = db.find_product(pid)
    a = (ok == 1 and dup_active == 15 and other == 0
         and p[6] == 1)
    say("成功=%d 重复活跃=%d 死锁=%d 其它异常=%d 预约占用量=%s"
        % (ok, dup_active, dead, other, p[6]))
    report("场景2 active_buyer 唯一约束保证并发安全", a)
    return a

def scenario3_fingerprint_idempotent(seller, buyers):
    say("场景3：同一买家同指纹16线程同时创建 → 全部返回同一 rid")
    pid = publish(seller, 100)
    seller_id = seller.user_id
    buyer = buyers[0]
    def work(_i):
        return db.create_reservation(pid, buyer.user_id, seller_id, 1,
                                     deadline(), "same-fingerprint")
    results, errors = run_concurrently(work, 16)
    ok, dead, other = summarize(results, errors)
    rids = set(r[1] for r in results if r and r[1] is not None)
    p = db.find_product(pid)
    a = (len(rids) == 1 and other == 0 and p[6] == 1)
    say("成功=%d 重复=%d 死锁=%d 其它异常=%d rid集合大小=%d 占用量=%s"
        % (ok, sum(1 for r in results if r and r[0] == "DUPLICATE"),
           dead, other, len(rids), p[6]))
    report("场景3 指纹幂等并发安全", a)
    return a

def scenario4_confirm_cancel_race(seller, buyers):
    say("场景4：卖家确认与买家取消同时提交 → 串行化后终态二选一")
    pid = publish(seller, 10)
    seller_id = seller.user_id
    buyer = buyers[0]
    _, rid = db.create_reservation(pid, buyer.user_id, seller_id, 2,
                                   deadline(), "s4-fp")
    def work(i):
        if i == 0:
            return db.confirm_reservation(rid, deadline())
        return db.cancel_reservation(rid, "不想买了")
    results, errors = run_concurrently(work, 2)
    ok, dead, other = summarize(results, errors)
    row = db.find_reservation(rid)
    a = (ok >= 1 and other == 0
         and row[5] in ("confirmed", "cancelled"))
    say("成功=%d 拒绝=%d 死锁=%d 其它异常=%d 终态=%s"
        % (ok, sum(1 for r in results if r and r[0] == "REJECTED"),
           dead, other, row[5]))
    report("场景4 confirm/cancel 竞态（无损更新，终态合法）", a)
    return a

def scenario5_complete_takedown_race(seller, buyers):
    say("场景5：完成交易与下架取消同时提交 → 库存守恒二选一")
    pid = publish(seller, 10)
    seller_id = seller.user_id
    buyer = buyers[1]
    _, rid = db.create_reservation(pid, buyer.user_id, seller_id, 3,
                                   deadline(), "s5-fp")
    db.confirm_reservation(rid, deadline())
    def work(i):
        if i == 0:
            return db.complete_trade(rid)
        return db.take_down_and_cancel(pid, "taken_down", "违规测试")
    results, errors = run_concurrently(work, 2)
    ok, dead, other = summarize(results, errors)
    row = db.find_reservation(rid)
    p = db.find_product(pid)
    done = row[5] == "completed"
    a = (ok >= 1 and other == 0
         and row[5] in ("completed", "cancelled") and p[6] == 0
         and p[5] == (7 if done else 10))
    say("成功=%d 拒绝=%d 死锁=%d 其它异常=%d 终态=%s 库存=%s 占用=%s"
        % (ok, sum(1 for r in results if r and r[0] == "REJECTED"),
           dead, other, row[5], p[5], p[6]))
    report("场景5 complete/take_down 竞态（product 串行化点无死锁）", a)
    return a

def scenario6_double_completion_race(seller, buyers):
    say("场景6：买卖双方同时确认完成 → 交易恰好完成一次")
    pid = publish(seller, 10)
    seller_id = seller.user_id
    buyer = buyers[2]
    _, rid = db.create_reservation(pid, buyer.user_id, seller_id, 4,
                                   deadline(), "s6-fp")
    db.confirm_reservation(rid, deadline())
    def work(i):
        return db.confirm_completion(rid, "buyer" if i == 0 else "seller")
    results, errors = run_concurrently(work, 2)
    ok, dead, other = summarize(results, errors)
    row = db.find_reservation(rid)
    p = db.find_product(pid)
    a = (ok == 2 and other == 0 and row[5] == "completed"
         and p[5] == 6 and p[6] == 0)
    say("成功=%d 死锁=%d 其它异常=%d 终态=%s 库存=%s 占用=%s"
        % (ok, dead, other, row[5], p[5], p[6]))
    report("场景6 双方确认竞态（party 计数恰好完成一次）", a)
    return a

def report(desc, ok):
    say("%s %s" % ("√" if ok else "✗", desc))

def main():
    db.init_db(rebuild=True)
    say("数据库已重建")
    seller, buyers = make_users()
    r1 = scenario1_oversell(seller, buyers)
    r2 = scenario2_active_buyer_unique(seller, buyers)
    r3 = scenario3_fingerprint_idempotent(seller, buyers)
    r4 = scenario4_confirm_cancel_race(seller, buyers)
    r5 = scenario5_complete_takedown_race(seller, buyers)
    r6 = scenario6_double_completion_race(seller, buyers)
    passed = sum([r1, r2, r3, r4, r5, r6])
    say("=== 全部完成：%d/6 场景通过 ===" % passed)
    return 0 if passed == 6 else 1

if __name__ == "__main__":
    raise SystemExit(main())
