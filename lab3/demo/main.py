import sys
import uuid

import db
import models
from services import auth, notify, product, reservation, stats

ERROR_MESSAGES = {
    "INVALID_INPUT": "输入不合法，请检查后重试",
    "INVALID_ROLE": "角色只能选择买家或卖家",
    "INVALID_QTY": "预约数量必须不少于 1",
    "INVALID_RANGE": "价格区间无效（下限不能大于上限）",
    "INVALID_TRANSITION": "当前状态不允许该操作",
    "ACCOUNT_EXISTS": "该账号已被注册",
    "AUTH_FAILED": "账号或密码错误",
    "PRODUCT_NOT_FOUND": "商品不存在",
    "NOT_FOUND": "预约不存在",
    "FORBIDDEN": "没有权限执行该操作",
    "REASON_REQUIRED": "该操作必须填写原因",
    "STOCK_CONFLICT": "库存调整失败：不能低于有效预约总量",
    "RESERVATIONS_EXIST": "商品存在有效预约，仅允许调整库存",
    "ACTIVE_RESERVATION_EXISTS": "您已有该商品的有效预约",
    "UNAVAILABLE": "商品当前不可预约或库存不足，请刷新重试",
    "SELF_RESERVATION": "不能预约自己发布的商品",
    "CONFLICT_RETRY": "操作与其它并发修改冲突，请重试",
}

def fail(e):
    print("✗", ERROR_MESSAGES.get(e.code, e.message))

class OperationCancelled(Exception):
    pass

CANCEL_MARK = ":q"

def ask(prompt):
    raw = input(prompt).strip()
    if raw == CANCEL_MARK:
        raise OperationCancelled
    return raw

def ask_int(prompt, allow_empty=False):
    while True:
        raw = ask(prompt)
        if raw == "":
            if allow_empty:
                return None
            print("✗ 不能为空，请输入整数")
            continue
        try:
            return int(raw)
        except ValueError:
            print("✗ 请输入整数")

def ask_float(prompt, allow_empty=False):
    while True:
        raw = ask(prompt)
        if raw == "":
            if allow_empty:
                return None
            print("✗ 不能为空，请输入数字")
            continue
        try:
            return float(raw)
        except ValueError:
            print("✗ 请输入数字")

def print_table(headers, rows):
    data = [[str(v) if v is not None else "-" for v in r] for r in rows]
    widths = [max([len(h)] + [len(row[c]) for row in data])
              for c, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for row in data:
        print("  ".join(v.ljust(w) for v, w in zip(row, widths)))

def show_products(rows):
    print_table(["编号", "卖家", "名称", "分类", "价格", "库存", "已预约", "状态"],
                rows)
    print("共 %d 件商品" % len(rows))

def show_buyer_reservations(rows):
    view = [(r[0], r[1], r[2], r[5], r[4], r[8]) for r in rows]
    print_table(["编号", "商品", "数量", "状态", "有效期至", "取消原因"], view)

def do_login():
    account = ask("账号: ")
    password = ask("密码: ")
    user = auth.login(account, password)
    print("√ 欢迎，%s（角色：%s）"
          % (user.nickname, "/".join(sorted(r.value for r in user.roles))))
    return user

def do_register():
    account = ask("账号: ")
    password = ask("密码: ")
    nickname = ask("昵称: ")
    contact = ask("联系方式: ")
    roles_raw = ask("角色（buyer / seller，多个用逗号分隔）: ")
    roles = [r.strip() for r in roles_raw.split(",") if r.strip()]
    auth.register(account, password, nickname, contact, roles)
    print("√ 注册成功，请登录")

def browse(user):
    keyword = ask("关键词（可空）: ") or None
    category = ask("分类（可空）: ") or None
    min_price = ask_float("最低价（可空）: ", True)
    max_price = ask_float("最高价（可空）: ", True)
    location = ask("地点（可空）: ") or None
    sort_desc = ask("按发布时间新的在前? (y/N): ").lower() == "y"
    show_products(stats.search(user, keyword, category, min_price, max_price,
                               location, sort_desc))

def reserve(user):
    product_id = ask_int("商品编号: ")
    quantity = ask_int("数量: ")
    rid = reservation.create_reservation(user, product_id, quantity,
                                         uuid.uuid4().hex)
    print("√ 预约成功，编号 %s（14 天内有效，请等待卖家确认）" % rid)

def my_reservations(user):
    show_buyer_reservations(notify.my_reservations(user))

def cancel_reservation(user):
    rid = ask_int("预约编号: ")
    reason = ask("取消原因（已确认的预约必填）: ") or None
    reservation.cancel(user, rid, reason)
    print("√ 已取消")

def complete_trade(user):
    rid = ask_int("预约编号: ")
    reservation.confirm_completion(user, rid)
    print("√ 已确认完成")

def my_notices(user):
    print_table(["编号", "内容", "类型", "时间"], notify.my_notifications(user))

ROLE_LABELS = {"buyer": "买家", "seller": "卖家", "admin": "管理员"}

def _available_roles(user):
    return sorted((r.value for r in user.roles if r.value in ROLE_MENUS))

def _finalize_items(items, user):
    items = list(items)
    if len(_available_roles(user)) > 1:
        items.append(("切换角色", lambda u: "switch"))
    items.append(("退出登录", lambda u: False))
    return items

def buyer_menu(user):
    items = [
        ("浏览商品", browse),
        ("预约商品", reserve),
        ("我的预约", my_reservations),
        ("取消预约", cancel_reservation),
        ("确认完成交易", complete_trade),
        ("我的通知", my_notices),
    ]
    return _run_menu("买家菜单", _finalize_items(items, user), user)

def _print_menu(title, items, user):
    print("\n=== %s（%s）===" % (title, user.nickname))
    for i, (label, _) in enumerate(items, 1):
        print("%d. %s" % (i, label))

def _run_menu(title, items, user):
    _print_menu(title, items, user)
    while True:
        choice = input("请选择（help 显示菜单）: ").strip()
        if choice.lower() == "help":
            _print_menu(title, items, user)
            continue
        if not choice.isdigit() or not 1 <= int(choice) <= len(items):
            print("✗ 无效选项")
            continue
        try:
            result = items[int(choice) - 1][1](user)
        except OperationCancelled:
            print("✗ 已中止当前操作")
            continue
        except models.Rejection as e:
            fail(e)
            continue
        if result is False:
            return False
        if result == "switch":
            return "switch"

def _ask_product_fields():
    title = ask("名称: ")
    description = ask("描述: ")
    category = ask("分类: ")
    price = ask_float("价格: ")
    condition_grade = ask("成色: ")
    location = ask("地点: ")
    trade_method = ask("交易方式（可空）: ") or None
    stock_qty = ask_int("库存: ")
    return (title, description, category, price, condition_grade,
            location, trade_method, stock_qty)

def _show_my_products(user, statuses):
    rows = [r for r in notify.my_products(user) if r[7] in statuses]
    if not rows:
        print("（没有符合条件的商品）")
        return False
    view = [(r[0], r[2], r[5], r[6], r[7]) for r in rows]
    print_table(["编号", "名称", "库存", "已预约", "状态"], view)
    return True

def publish(user):
    fields = _ask_product_fields()
    pid = product.create_draft(user, *fields)
    print("√ 商品已保存为草稿，编号 %s（提交审核后才会上架）" % pid)

def submit_review(user):
    if not _show_my_products(user, ("draft",)):
        return
    pid = ask_int("商品编号: ")
    product.submit_for_review(user, pid)
    print("√ 已提交审核")

def modify(user):
    if not _show_my_products(user, ("draft", "rejected", "published")):
        return
    pid = ask_int("商品编号: ")
    fields = _ask_product_fields()
    product.modify_product(user, pid, *fields)
    print("√ 已修改")

def adjust_stock(user):
    if not _show_my_products(user, ("draft", "published")):
        return
    pid = ask_int("商品编号: ")
    new_qty = ask_int("新库存: ")
    product.adjust_stock(user, pid, new_qty)
    print("√ 库存已调整为 %d" % new_qty)

def take_down(user):
    if not _show_my_products(user, ("published",)):
        return
    pid = ask_int("商品编号: ")
    product.take_down(user, pid)
    print("√ 已下架，其有效预约已全部取消")

def republish(user):
    if not _show_my_products(user, ("taken_down",)):
        return
    pid = ask_int("商品编号: ")
    product.republish(user, pid)
    print("√ 已重新上架")

def pending_reservations(user):
    print_table(["编号", "商品", "买家", "数量", "预约时间", "状态"],
                notify.reservations_to_handle(user))

def confirm_reservation(user):
    rid = ask_int("预约编号: ")
    reservation.confirm(user, rid)
    print("√ 已确认，等待买家完成交易")

def reject_reservation(user):
    rid = ask_int("预约编号: ")
    reservation.reject(user, rid)
    print("√ 已拒绝")

def seller_complete(user):
    pending_reservations(user)
    rid = ask_int("预约编号: ")
    reservation.confirm_completion(user, rid)
    print("√ 已确认完成（双方确认后交易即完成）")

def seller_stats(user):
    s = stats.seller_view(user)
    print("商品总数: %d" % s["product_count"])
    print("有效预约量: %d" % s["active_reserved_qty"])
    print("完成交易量: %d" % s["completed_qty"])
    print("已售出商品数: %d" % s["sold_count"])

def show_logs(rows):
    print_table(["编号", "操作人", "动作", "详情", "结果", "对象类型", "对象", "时间"],
                rows)

def seller_logs(user):
    show_logs(notify.logs_for_seller(user))

def seller_menu(user):
    items = [
        ("发布商品（草稿）", publish),
        ("提交审核", submit_review),
        ("修改商品", modify),
        ("调整库存", adjust_stock),
        ("下架商品", take_down),
        ("重新上架", republish),
        ("待处理预约", pending_reservations),
        ("确认预约", confirm_reservation),
        ("拒绝预约", reject_reservation),
        ("确认完成交易", seller_complete),
        ("销量统计", seller_stats),
        ("我的操作日志", seller_logs),
        ("我的通知", my_notices),
    ]
    return _run_menu("卖家菜单", _finalize_items(items, user), user)

def audit_product(user):
    if not _show_my_products(user, ("pending_review",)):
        return
    pid = ask_int("商品编号: ")
    approved = ask("是否通过? (y/N): ").lower() == "y"
    reason = None if approved else (ask("驳回原因: ") or None)
    product.audit(user, pid, approved, reason)
    print("√ 审核完成：%s" % ("通过并上架" if approved else "已驳回"))

def handle_violation(user):
    if not _show_my_products(user, ("published",)):
        return
    pid = ask_int("商品编号: ")
    reason = ask("违规原因: ")
    product.handle_violation(user, pid, reason)
    print("√ 已强制下架，其有效预约已全部取消")

def restore_product(user):
    if not _show_my_products(user, ("violation_taken_down",)):
        return
    pid = ask_int("商品编号: ")
    product.restore_from_violation(user, pid)
    print("√ 已恢复上架")

def admin_stats(user):
    s = stats.admin_view(user)
    print("用户总数: %d" % s["user_count"])
    print("商品总数: %d（在售 %d，违规下架 %d）"
          % (s["product_count"], s["published_count"], s["violation_count"]))
    print("完成交易量: %d" % s["trade_qty"])

def admin_logs(user):
    show_logs(notify.all_logs(user))

def admin_menu(user):
    items = [
        ("审核商品", audit_product),
        ("违规处理", handle_violation),
        ("恢复违规商品", restore_product),
        ("平台统计", admin_stats),
        ("全部操作日志", admin_logs),
        ("我的通知", my_notices),
    ]
    return _run_menu("管理员菜单", _finalize_items(items, user), user)

ROLE_MENUS = {"buyer": buyer_menu, "seller": seller_menu, "admin": admin_menu}

def run_session(user):
    while True:
        roles = _available_roles(user)
        if not roles:
            print("（该账号没有可用的角色菜单，已退出登录）")
            return
        if len(roles) == 1:
            if ROLE_MENUS[roles[0]](user) is False:
                return
            continue
        print("当前账号可用角色，请选择进入：")
        for i, rv in enumerate(roles, 1):
            print("%d. %s" % (i, ROLE_LABELS[rv]))
        choice = ask("请选择: ")
        if not choice.isdigit() or not 1 <= int(choice) <= len(roles):
            print("✗ 无效选项")
            continue
        if ROLE_MENUS[roles[int(choice) - 1]](user) is False:
            return

def main():
    if "--init" in sys.argv:
        db.init_db(rebuild=True)
        auth.seed_admin("admin", "admin123")
        print("√ 数据库已重建，管理员账号 admin / admin123")
    while True:
        print("\n===== 二手交易系统 =====")
        print("1. 登录\n2. 注册\n0. 退出")
        choice = ask("请选择: ")
        try:
            if choice == "0":
                print("再见！")
                return
            if choice == "1":
                run_session(do_login())
            elif choice == "2":
                do_register()
            else:
                print("✗ 无效选项")
        except OperationCancelled:
            print("✗ 已中止，返回主界面")
        except models.Rejection as e:
            fail(e)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n再见！")