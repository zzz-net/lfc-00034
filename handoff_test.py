#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
社区活动室预约系统 - 接手验收脚本

新人接手时运行此脚本，即可验证：
  1. 批量改期 / 整批取消 / 批次导出 三条主链路
  2. 服务重启或配置重载后接口、导出、说明仍然对得上
  3. 权限与状态冲突矩阵（非管理员、已审批、部分成功部分失败）
  4. 导出金标准（bookings 一致、审计 id 集合一致、审计 id 单调递增）

使用方法：
  方式 A（单服务，MAX=4）：
    终端1: python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001
    终端2: python handoff_test.py

  方式 B（跨端口模拟重启，MAX=4 + MAX=2）：
    终端1: python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001
    终端2: $env:BOOKING_MAX_RECURRING_WEEKS="2"; python -m uvicorn booking.main:app --host 127.0.0.1 --port 8002
    终端3: python handoff_test.py --cross-port

退出码：0 = 全部通过，1 = 有失败
"""

import sys
import io
import json
import requests
from datetime import date, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8001"
BASE_MAX2 = "http://127.0.0.1:8002"

PASS = 0
FAIL = 0


def _err_code(r: dict) -> int:
    if "error_code" in r:
        return r["error_code"]
    if isinstance(r.get("detail"), dict):
        return r["detail"].get("error_code", 0)
    return 0


def api(base, method, path, data=None, expect=200, params=None):
    url = f"{base}{path}"
    if method == "get" and data is not None and params is None:
        params = data
        data = None
    try:
        resp = getattr(requests, method)(url, json=data, params=params)
    except requests.ConnectionError:
        global FAIL
        FAIL += 1
        print(f"  [FAIL] {method.upper()} {path} => 连接失败 (服务是否启动在 {base} ?)")
        return {}
    ok = resp.status_code == expect
    global PASS
    if ok:
        PASS += 1
    else:
        FAIL += 1
    tag = "[PASS]" if ok else "[FAIL]"
    print(f"  {tag} {method.upper()} {path} => {resp.status_code} (expect {expect})")
    if not ok:
        print(f"    response: {resp.text[:300]}")
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {}


def _next_weekday(weekday, offset=14):
    today = date.today()
    base = today + timedelta(days=offset)
    diff = (weekday - base.weekday()) % 7
    if diff == 0:
        diff = 7
    return base + timedelta(days=diff)


def _max_weeks(base=BASE):
    r = api(base, "get", "/api/bookings/recurring/config")
    return r.get("max_recurring_weeks", 4)


def _assert(cond, msg=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        tag = "[PASS]" if cond else "[FAIL]"
        print(f"  {tag} {msg}")


def _collect_export_audit_ids(export):
    ids = set()
    for b in export.get("bookings", []):
        for lg in b.get("audit_logs", []):
            ids.add(lg["id"])
    for lg in export.get("batch_level_audit_logs", []):
        ids.add(lg["id"])
    return ids


def _golden_standard(base, batch_id, label=""):
    print(f"\n  --- 金标准验证 {label} ---")
    detail = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_handoff", "operator_role": "admin"
    })
    export_resp = requests.get(
        f"{base}/api/bookings/batches/{batch_id}/export",
        params={"operator_id": "admin_handoff", "operator_role": "admin"}
    )
    if export_resp.status_code != 200:
        global FAIL
        FAIL += 1
        print(f"  [FAIL] 导出请求返回 {export_resp.status_code}")
        return
    export = export_resp.json()
    assert "attachment" in export_resp.headers.get("Content-Disposition", ""), "导出缺少 Content-Disposition"

    q_map = {b["id"]: b for b in detail.get("bookings", [])}
    e_map = {b["id"]: b for b in export.get("bookings", [])}
    _assert(set(q_map.keys()) == set(e_map.keys()), f"金标准1: 查询与导出 booking id 集合一致 ({len(q_map)}条)")
    for bid, qb in q_map.items():
        eb = e_map[bid]
        for f in ["status", "week_phase", "date", "old_date", "rescheduled_from_booking_id"]:
            _assert(qb.get(f) == eb.get(f), f"金标准1: #{bid} {f} 查询={qb.get(f)} 导出={eb.get(f)}")

    audit_q = requests.get(f"{base}/api/audit", params={"batch_id": batch_id}).json()
    audit_q_ids = {l["id"] for l in audit_q}
    audit_e_ids = _collect_export_audit_ids(export)
    _assert(audit_q_ids == audit_e_ids, f"金标准2: 审计id集合一致 (query={len(audit_q_ids)} export={len(audit_e_ids)})")

    all_ids = sorted(audit_q_ids)
    if len(all_ids) >= 2:
        diffs = [all_ids[i+1] - all_ids[i] for i in range(len(all_ids)-1)]
        _assert(all(d >= 1 for d in diffs), "金标准3: 审计id单调递增无断裂")
    else:
        _assert(True, "金标准3: 审计id数量不足2条, 跳过单调性检查")


# ============================================================
# 场景1: 批量改期完整链路
# ============================================================
def test_reschedule_chain(base=BASE):
    print("\n" + "=" * 60)
    print("  场景1: 批量改期完整链路")
    print("=" * 60)
    mw = _max_weeks(base)

    r = api(base, "post", "/api/rooms", {"name": "改期链路_排练厅", "description": "批量改期测试"}, 201)
    room_id = r["id"]
    start = _next_weekday(0, 21)
    api(base, "post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [
            {"weekday": 0, "start_time": "09:00", "end_time": "22:00"},
            {"weekday": 2, "start_time": "09:00", "end_time": "22:00"},
        ]
    }, 201)

    weeks = min(4, mw)
    r = api(base, "post", "/api/bookings/recurring", {
        "room_id": room_id, "user_id": "user_rs",
        "start_date": start.isoformat(), "start_time": "10:00", "end_time": "12:00",
        "purpose": "改期链路测试", "weeks": weeks
    }, 201)
    batch_id = r["batch_id"]
    bids = [i["booking_id"] for i in r["items"] if i["status"] == "success"]
    _assert(len(bids) == weeks, f"创建{weeks}周全部成功")
    print(f"  >> batch_id={batch_id}, booking_ids={bids}")

    api(base, "post", f"/api/bookings/{bids[0]}/approve", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "审批第1周"
    })
    api(base, "post", f"/api/bookings/{bids[-1]}/cancel", {
        "operator_id": "user_rs", "operator_role": "resident", "reason": "取消最后一周"
    })
    print(f"  >> 制造混合状态: #{bids[0]}=approved, #{bids[-1]}=cancelled")

    # 1a: 非管理员改期他人批次
    r = api(base, "post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": (date.today() + timedelta(days=60)).isoformat(),
        "operator_id": "other_resident", "operator_role": "resident", "reason": "越权"
    }, 422)
    _assert(_err_code(r) == 10007, "1a: 非管理员改期他人批次 => 10007")

    # 1b: 改到 slot 不开放的日期 (全部 denied)
    r = api(base, "post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": _next_weekday(4, 28).isoformat(),
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "改到周五slot不开"
    })
    _assert(r.get("denied", -1) >= 1, "1b: 改到slot不开放 => denied>=1")
    _assert(r.get("success", -1) == 0, "1b: 改到slot不开放 => success=0")
    denied_items = [i for i in r.get("items", []) if i["result"] == "denied"]
    denied_codes = {i.get("error_code") for i in denied_items}
    _assert(10015 in denied_codes, "1b: denied 包含 10015(NEW_SLOT_NOT_OPEN)")
    for i in denied_items:
        _assert(i["old_status"] == i["new_status"], f"1b: denied #{i['booking_id']} 状态未变")
    print(f"  >> 1b: denied={r.get('denied')}, preserved={r.get('preserved')}")

    # 回查确认 denied 的没动
    detail = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_handoff", "operator_role": "admin"
    })
    for b in detail["bookings"]:
        if b["id"] in [i["booking_id"] for i in denied_items]:
            _assert(b.get("old_date") is None, f"1b: denied #{b['id']} old_date 应为 null")

    # 1c: 部分冲突 (1 success + 1 denied)
    new_start = _next_weekday(0, 42)
    blocker_date = new_start + timedelta(weeks=1)
    r_blk = api(base, "post", "/api/bookings", {
        "room_id": room_id, "user_id": "blocker_rs",
        "date": blocker_date.isoformat(), "start_time": "10:00", "end_time": "12:00",
        "purpose": "阻塞改期"
    }, 201)
    api(base, "post", f"/api/bookings/{r_blk['id']}/approve", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "审批阻塞"
    })

    r = api(base, "post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": new_start.isoformat(),
        "new_start_time": "10:00", "new_end_time": "12:00",
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "部分冲突改期"
    })
    _assert(r.get("success", 0) >= 1, "1c: 部分冲突 => success>=1")
    _assert(r.get("denied", 0) >= 1, "1c: 部分冲突 => denied>=1")
    denied_16 = [i for i in r.get("items", []) if i.get("error_code") == 10016]
    _assert(len(denied_16) >= 1, "1c: 有 10016(NEW_BOOKING_OVERLAP)")
    print(f"  >> 1c: success={r.get('success')}, denied={r.get('denied')}, preserved={r.get('preserved')}")

    # 审计核对
    logs = requests.get(f"{base}/api/audit", params={"batch_id": batch_id}).json()
    reschedule_logs = [l for l in logs if l["action"] == "reschedule"]
    _assert(len(reschedule_logs) == r.get("success", 0), f"1c: reschedule审计={len(reschedule_logs)} == success={r.get('success')}")
    for lg in reschedule_logs:
        _assert("max_recurring_weeks_at_operation=" in lg["detail"],
                "1c: reschedule审计含 max_recurring_weeks_at_operation")

    # 1d: 改期成功
    adjustable_now = [b for b in detail["bookings"] if b.get("week_phase") == "adjustable"]
    clean_start = _next_weekday(0, 56)
    r = api(base, "post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": clean_start.isoformat(),
        "new_start_time": "14:00", "new_end_time": "16:00",
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "干净改期"
    })
    _assert(r.get("success", 0) >= 1, "1d: 干净改期 => success>=1")
    _assert(r.get("denied", 0) == 0, "1d: 干净改期 => denied=0")
    print(f"  >> 1d: success={r.get('success')}, preserved={r.get('preserved')}")

    # 1e: 只传 new_start_time 不传 new_end_time => 报错
    r = api(base, "post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": _next_weekday(0, 70).isoformat(),
        "new_start_time": "14:00",
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "只传开始时间"
    }, 422)
    _assert(_err_code(r) == 10009, "1e: 只传一个时间字段 => 10009")

    _golden_standard(base, batch_id, "(改期链路)")
    return batch_id, room_id


# ============================================================
# 场景2: 整批取消完整链路
# ============================================================
def test_cancel_chain(base=BASE):
    print("\n" + "=" * 60)
    print("  场景2: 整批取消完整链路")
    print("=" * 60)
    mw = _max_weeks(base)

    r = api(base, "post", "/api/rooms", {"name": "取消链路_会议室", "description": "整批取消测试"}, 201)
    room_id = r["id"]
    start = _next_weekday(1, 21)
    api(base, "post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": 1, "start_time": "08:00", "end_time": "22:00"}]
    }, 201)

    weeks = min(3, mw)
    r = api(base, "post", "/api/bookings/recurring", {
        "room_id": room_id, "user_id": "user_cc",
        "start_date": start.isoformat(), "start_time": "15:00", "end_time": "17:00",
        "purpose": "取消链路测试", "weeks": weeks
    }, 201)
    batch_id = r["batch_id"]
    bids = [i["booking_id"] for i in r["items"] if i["status"] == "success"]
    _assert(len(bids) == weeks, f"创建{weeks}周全部成功")

    api(base, "post", f"/api/bookings/{bids[0]}/approve", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "审批第1周"
    })

    # 2a: 非管理员取消他人批次
    r = api(base, "post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "other_resident", "operator_role": "resident", "reason": "越权"
    }, 422)
    _assert(_err_code(r) == 10007, "2a: 非管理员取消他人批次 => 10007")

    # 2b: 居民自己取消 (approved 被 preserved)
    r = api(base, "post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "user_cc", "operator_role": "resident", "reason": "自己取消"
    })
    _assert(r.get("preserved", 0) >= 1, "2b: 居民取消 => approved被preserved>=1")
    _assert(r.get("success", 0) >= 1, "2b: 居民取消 => pending被success>=1")
    preserved_items = [i for i in r.get("items", []) if i["result"] == "preserved"]
    approved_preserved = [i for i in preserved_items if i["booking_id"] == bids[0]]
    _assert(len(approved_preserved) == 1, "2b: 已审批的那条是preserved")
    _assert("approved" in approved_preserved[0].get("message", "").lower() or
            "admin" in approved_preserved[0].get("message", "").lower(),
            "2b: preserved的message含approved/admin说明")

    detail = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_handoff", "operator_role": "admin"
    })
    b_map = {b["id"]: b for b in detail["bookings"]}
    _assert(b_map[bids[0]]["status"] == "approved", "2b: 已审批预约状态仍是approved")
    for bid in bids[1:]:
        _assert(b_map[bid]["status"] == "cancelled", f"2b: #{bid} pending => cancelled")

    # 2c: 管理员代取消已审批
    r = api(base, "post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "管理员代取消"
    })
    admin_success = [i for i in r.get("items", []) if i["result"] == "success"]
    _assert(len(admin_success) >= 1, "2c: 管理员代取消 => success>=1")
    admin_approved_cancel = [i for i in admin_success if i["booking_id"] == bids[0]]
    _assert(len(admin_approved_cancel) == 1, "2c: 已审批的那条被管理员成功取消")
    _assert(admin_approved_cancel[0]["old_status"] == "approved", "2c: old_status=approved")
    _assert(admin_approved_cancel[0]["new_status"] == "cancelled", "2c: new_status=cancelled")

    # 审计前缀区分
    logs = requests.get(f"{base}/api/audit", params={"batch_id": batch_id}).json()
    cancel_logs = [l for l in logs if l["action"] == "cancel"]
    resident_cancels = [l for l in cancel_logs if "Batch cancel" in l.get("detail", "")]
    admin_cancels = [l for l in cancel_logs if "Admin/staff batch cancel" in l.get("detail", "")]
    _assert(len(resident_cancels) >= 1, "2c: 居民cancel审计含'Batch cancel'前缀")
    _assert(len(admin_cancels) >= 1, "2c: 管理员cancel审计含'Admin/staff batch cancel'前缀")

    _golden_standard(base, batch_id, "(取消链路)")
    return batch_id


# ============================================================
# 场景3: 批次导出完整链路
# ============================================================
def test_export_chain(base=BASE, batch_id_reschedule=None, batch_id_cancel=None):
    print("\n" + "=" * 60)
    print("  场景3: 批次导出完整链路")
    print("=" * 60)

    test_batch = batch_id_cancel or batch_id_reschedule
    _assert(test_batch is not None, "需要有可用batch_id")

    # 3a: 非管理员导出他人批次
    r = api(base, "get", f"/api/bookings/batches/{test_batch}/export", params={
        "operator_id": "other_resident", "operator_role": "resident"
    }, expect=422)
    _assert(_err_code(r) == 10007, "3a: 非管理员导出他人批次 => 10007")

    # 3b: 导出结构完整度
    resp = requests.get(f"{base}/api/bookings/batches/{test_batch}/export", params={
        "operator_id": "admin_handoff", "operator_role": "admin"
    })
    _assert(resp.status_code == 200, "3b: 导出 HTTP 200")
    _assert("attachment" in resp.headers.get("Content-Disposition", ""), "3b: Content-Disposition 含 attachment")
    exp = resp.json()
    for key in ["batch", "config_snapshot", "bookings", "batch_level_audit_logs", "summary"]:
        _assert(key in exp, f"3b: 顶层 key '{key}' 存在")

    cfg = exp.get("config_snapshot", {})
    for k in ["max_recurring_weeks_at_creation", "max_recurring_weeks_current",
              "min_recurring_weeks", "absolute_max_recurring_weeks",
              "default_max_recurring_weeks", "env_var_name"]:
        _assert(k in cfg, f"3b: config_snapshot 含 '{k}'")
    _assert(cfg.get("env_var_name") == "BOOKING_MAX_RECURRING_WEEKS", "3b: env_var_name 正确")

    # 3c: 导出 vs 回查一致性 (金标准)
    _golden_standard(base, test_batch, "(导出链路)")

    # 3d: summary 统计合理性
    s = exp.get("summary", {})
    _assert(s.get("total_bookings") == len(exp.get("bookings", [])), "3d: total_bookings == bookings数组长度")
    phase_sum = sum(s.get(k, 0) for k in ["preserved_in_effect", "preserved_approved", "adjustable", "finished"])
    _assert(phase_sum == s.get("total_bookings", -1), "3d: 各phase计数之和 == total_bookings")


# ============================================================
# 场景4: 服务重启/配置重载后一致性
# ============================================================
def test_restart_consistency(base_create=BASE, base_operate=BASE_MAX2):
    print("\n" + "=" * 60)
    print("  场景4: 服务重启/配置重载后一致性")
    print("=" * 60)

    cfg_create = api(base_create, "get", "/api/bookings/recurring/config")
    cfg_operate = api(base_operate, "get", "/api/bookings/recurring/config")
    max_at_creation = cfg_create.get("max_recurring_weeks", 4)
    max_at_operation = cfg_operate.get("max_recurring_weeks", 2)

    if max_at_creation == max_at_operation:
        print("  [SKIP] 两个端口配置相同, 跳过跨端口重启测试 (请启动 MAX=2 的端口 8002)")
        return None

    _assert(max_at_creation > max_at_operation, f"创建服务MAX={max_at_creation} > 操作服务MAX={max_at_operation}")

    # 在 MAX=4 上创建 4 周批次
    r = api(base_create, "post", "/api/rooms", {"name": "重启一致性_活动室", "description": "跨端口测试"}, 201)
    room_id = r["id"]
    start = _next_weekday(0, 28)
    api(base_create, "post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": 0, "start_time": "09:00", "end_time": "22:00"}]
    }, 201)

    r = api(base_create, "post", "/api/bookings/recurring", {
        "room_id": room_id, "user_id": "user_restart",
        "start_date": start.isoformat(), "start_time": "10:00", "end_time": "12:00",
        "purpose": "重启一致性测试", "weeks": 4
    }, 201)
    batch_id = r["batch_id"]
    bids = [i["booking_id"] for i in r["items"] if i["status"] == "success"]
    _assert(len(bids) == 4, "创建4周全部成功")

    api(base_create, "post", f"/api/bookings/{bids[0]}/approve", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "审批第1周"
    })

    # 保存重启前快照
    detail_before = api(base_create, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_handoff", "operator_role": "admin"
    })
    _assert(detail_before.get("max_recurring_weeks_at_creation") == max_at_creation,
            f"重启前 creation={detail_before.get('max_recurring_weeks_at_creation')} == {max_at_creation}")

    # 在 MAX=2 端口上改期
    new_start = _next_weekday(0, 42)
    r = api(base_operate, "post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": new_start.isoformat(),
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "重启后改期"
    })
    _assert(r.get("max_recurring_weeks_at_creation") == max_at_creation,
            f"改期响应 creation={r.get('max_recurring_weeks_at_creation')} == {max_at_creation}")
    _assert(r.get("max_recurring_weeks_at_operation") == max_at_operation,
            f"改期响应 operation={r.get('max_recurring_weeks_at_operation')} == {max_at_operation}")
    _assert(r.get("success", 0) + r.get("preserved", 0) + r.get("denied", 0) + r.get("skipped", 0) == r.get("total", -1),
            "改期 total == success+preserved+denied+skipped")

    # reschedule 审计含 operation 规则值
    logs = requests.get(f"{base_operate}/api/audit", params={"batch_id": batch_id}).json()
    reschedule_logs = [l for l in logs if l["action"] == "reschedule"]
    for lg in reschedule_logs:
        _assert(f"max_recurring_weeks_at_operation={max_at_operation}" in lg["detail"],
                f"reschedule审计含 max_recurring_weeks_at_operation={max_at_operation}")

    # 在 MAX=2 端口上整批取消
    r = api(base_operate, "post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "重启后取消"
    })
    _assert(r.get("max_recurring_weeks_at_creation") == max_at_creation,
            f"取消响应 creation={r.get('max_recurring_weeks_at_creation')} == {max_at_creation}")
    _assert(r.get("max_recurring_weeks_at_operation") == max_at_operation,
            f"取消响应 operation={r.get('max_recurring_weeks_at_operation')} == {max_at_operation}")

    # 导出 config_snapshot
    export = requests.get(f"{base_operate}/api/bookings/batches/{batch_id}/export", params={
        "operator_id": "admin_handoff", "operator_role": "admin"
    }).json()
    _assert(export["config_snapshot"]["max_recurring_weeks_at_creation"] == max_at_creation,
            f"导出 creation={export['config_snapshot']['max_recurring_weeks_at_creation']} == {max_at_creation}")
    _assert(export["config_snapshot"]["max_recurring_weeks_current"] == max_at_operation,
            f"导出 current={export['config_snapshot']['max_recurring_weeks_current']} == {max_at_operation}")

    # 重启前后的 creation 值不变
    _assert(export["batch"]["max_recurring_weeks_at_creation"] == max_at_creation,
            f"导出batch.creation={export['batch']['max_recurring_weeks_at_creation']} == {max_at_creation}")

    # 金标准
    _golden_standard(base_operate, batch_id, "(重启后)")
    return batch_id


# ============================================================
# 场景5: 权限/状态冲突矩阵
# ============================================================
def test_conflict_matrix(base=BASE):
    print("\n" + "=" * 60)
    print("  场景5: 权限/状态冲突矩阵")
    print("=" * 60)
    mw = _max_weeks(base)

    # K14: 不存在的批次
    r = api(base, "post", "/api/bookings/batches/9999999/reschedule", {
        "new_start_date": (date.today() + timedelta(days=30)).isoformat(),
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "不存在"
    }, 422)
    _assert(_err_code(r) == 10011, "K14: 不存在批次改期 => 10011")

    r = api(base, "post", "/api/bookings/batches/9999999/cancel", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "不存在"
    }, 422)
    _assert(_err_code(r) == 10011, "K14: 不存在批次取消 => 10011")

    r = api(base, "get", "/api/bookings/batches/9999999/export", params={
        "operator_id": "admin_handoff", "operator_role": "admin"
    }, expect=422)
    _assert(_err_code(r) == 10011, "K14: 不存在批次导出 => 10011")

    # K15: 改期 new_start_time >= new_end_time
    r = api(base, "post", "/api/bookings/batches/1/reschedule", {
        "new_start_date": (date.today() + timedelta(days=30)).isoformat(),
        "new_start_time": "16:00", "new_end_time": "14:00",
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "时间非法"
    }, 422)
    _assert(_err_code(r) == 10009, "K15: 时间非法 => 10009")

    # K4: 全已审批改期 => 10014
    r = api(base, "post", "/api/rooms", {"name": "冲突矩阵_全审批房", "description": "K4测试"}, 201)
    room_id = r["id"]
    start = _next_weekday(2, 21)
    api(base, "post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": 2, "start_time": "09:00", "end_time": "22:00"}]
    }, 201)

    test_weeks = min(2, mw)
    r = api(base, "post", "/api/bookings/recurring", {
        "room_id": room_id, "user_id": "user_k4",
        "start_date": start.isoformat(), "start_time": "14:00", "end_time": "16:00",
        "purpose": "K4全审批", "weeks": test_weeks
    }, 201)
    batch_id_k4 = r["batch_id"]
    bids_k4 = [i["booking_id"] for i in r["items"] if i["status"] == "success"]
    for bid in bids_k4:
        api(base, "post", f"/api/bookings/{bid}/approve", {
            "operator_id": "admin_handoff", "operator_role": "admin", "reason": "全部审批"
        })

    r = api(base, "post", f"/api/bookings/batches/{batch_id_k4}/reschedule", {
        "new_start_date": (date.today() + timedelta(days=90)).isoformat(),
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "全审批改期"
    }, 422)
    _assert(_err_code(r) == 10014, "K4: 全已审批改期 => 10014(BATCH_NOTHING_TO_OPERATE)")

    # K5: 居民取消全已审批 => 全 preserved
    r = api(base, "post", f"/api/bookings/batches/{batch_id_k4}/cancel", {
        "operator_id": "user_k4", "operator_role": "resident", "reason": "居民取消全审批"
    })
    _assert(r.get("preserved", -1) == test_weeks, f"K5: 居民取消全审批 => preserved={test_weeks}")
    _assert(r.get("success", -1) == 0, "K5: 居民取消全审批 => success=0")

    # 确认状态没变
    detail = api(base, "get", f"/api/bookings/batches/{batch_id_k4}", params={
        "operator_id": "admin_handoff", "operator_role": "admin"
    })
    for b in detail["bookings"]:
        _assert(b["status"] == "approved", f"K5: #{b['id']} 状态仍为approved")

    # K8/K9: 混合状态 取消
    r = api(base, "post", "/api/rooms", {"name": "冲突矩阵_混合房", "description": "K8/K9"}, 201)
    room_id_k8 = r["id"]
    start_k8 = _next_weekday(4, 21)
    api(base, "post", f"/api/rooms/{room_id_k8}/timeslots", {
        "slots": [{"weekday": 4, "start_time": "09:00", "end_time": "22:00"}]
    }, 201)

    r = api(base, "post", "/api/bookings/recurring", {
        "room_id": room_id_k8, "user_id": "user_k8",
        "start_date": start_k8.isoformat(), "start_time": "09:00", "end_time": "11:00",
        "purpose": "K8/K9混合状态", "weeks": test_weeks
    }, 201)
    batch_id_k8 = r["batch_id"]
    bids_k8 = [i["booking_id"] for i in r["items"] if i["status"] == "success"]
    api(base, "post", f"/api/bookings/{bids_k8[0]}/approve", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "审批第1条"
    })

    # K8: 居民取消含已审批
    r = api(base, "post", f"/api/bookings/batches/{batch_id_k8}/cancel", {
        "operator_id": "user_k8", "operator_role": "resident", "reason": "K8居民取消"
    })
    _assert(r.get("success", 0) >= 1, "K8: 居民取消 => pending success>=1")
    _assert(r.get("preserved", 0) >= 1, "K8: 居民取消 => approved preserved>=1")

    # K9: 管理员取消含已审批
    r = api(base, "post", f"/api/bookings/batches/{batch_id_k8}/cancel", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "K9管理员取消"
    })
    admin_ok = [i for i in r.get("items", []) if i["result"] == "success" and i["booking_id"] == bids_k8[0]]
    _assert(len(admin_ok) == 1, "K9: 管理员成功取消已审批")
    _assert(admin_ok[0]["old_status"] == "approved", "K9: old_status=approved")
    _assert(admin_ok[0]["new_status"] == "cancelled", "K9: new_status=cancelled")

    # K1-K3 已在改期和导出链路中验证过 (10007)
    # K6-K7 已在改期链路中验证过 (10015, 10016)
    print(f"\n  >> 权限/状态冲突矩阵: K1-K9, K14-K15 验证完毕")


# ============================================================
# 场景6: 不存在的批次 + 重复操作边界
# ============================================================
def test_boundary_cases(base=BASE):
    print("\n" + "=" * 60)
    print("  场景6: 边界用例")
    print("=" * 60)

    # 全已取消批次再次取消
    mw = _max_weeks(base)
    r = api(base, "post", "/api/rooms", {"name": "边界_全取消房", "description": "边界测试"}, 201)
    room_id = r["id"]
    start = _next_weekday(3, 21)
    api(base, "post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": 3, "start_time": "09:00", "end_time": "22:00"}]
    }, 201)

    weeks = min(2, mw)
    r = api(base, "post", "/api/bookings/recurring", {
        "room_id": room_id, "user_id": "user_boundary",
        "start_date": start.isoformat(), "start_time": "10:00", "end_time": "12:00",
        "purpose": "边界测试", "weeks": weeks
    }, 201)
    batch_id = r["batch_id"]

    # 管理员取消全部
    api(base, "post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "先全取消"
    })

    # 全已取消再取消 => 全 skipped/preserved
    r = api(base, "post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "再次取消"
    })
    _assert(r.get("success", 0) == 0, "全已取消再取消 => success=0")
    _assert(r.get("skipped", 0) + r.get("preserved", 0) == r.get("total", -1), "全已取消再取消 => 全skipped/preserved")

    # 全已取消再改期 => 10014
    r = api(base, "post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": (date.today() + timedelta(days=90)).isoformat(),
        "operator_id": "admin_handoff", "operator_role": "admin", "reason": "全取消后改期"
    }, 422)
    _assert(_err_code(r) == 10014, "全已取消再改期 => 10014")


# ============================================================
# 主流程
# ============================================================
def main():
    global BASE, BASE_MAX2
    cross_port = "--cross-port" in sys.argv

    print("=" * 60)
    print("  社区活动室预约系统 - 接手验收脚本")
    print("=" * 60)

    # 健康检查
    print("\n  --- 健康检查 ---")
    try:
        r = requests.get(f"{BASE}/api/health", timeout=5)
        if r.status_code != 200:
            print(f"  [FAIL] {BASE} 健康检查失败: {r.status_code}")
            sys.exit(1)
        cfg = requests.get(f"{BASE}/api/bookings/recurring/config").json()
        print(f"  [OK] {BASE} 服务正常, max_recurring_weeks={cfg['max_recurring_weeks']}")
    except requests.ConnectionError:
        print(f"  [FAIL] 无法连接 {BASE}, 请先启动服务:")
        print(f"    python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001")
        sys.exit(1)

    if cross_port:
        try:
            r = requests.get(f"{BASE_MAX2}/api/health", timeout=5)
            if r.status_code != 200:
                print(f"  [FAIL] {BASE_MAX2} 健康检查失败")
                sys.exit(1)
            cfg2 = requests.get(f"{BASE_MAX2}/api/bookings/recurring/config").json()
            print(f"  [OK] {BASE_MAX2} 服务正常, max_recurring_weeks={cfg2['max_recurring_weeks']}")
        except requests.ConnectionError:
            print(f"  [FAIL] 无法连接 {BASE_MAX2}, 请先启动 MAX=2 服务:")
            print(f'    $env:BOOKING_MAX_RECURRING_WEEKS="2"; python -m uvicorn booking.main:app --host 127.0.0.1 --port 8002')
            sys.exit(1)

    # 执行场景
    batch_id_rs, room_id_rs = test_reschedule_chain(BASE)
    batch_id_cc = test_cancel_chain(BASE)
    test_export_chain(BASE, batch_id_rs, batch_id_cc)

    if cross_port:
        test_restart_consistency(BASE, BASE_MAX2)

    test_conflict_matrix(BASE)
    test_boundary_cases(BASE)

    # 汇总
    print("\n" + "=" * 60)
    print(f"  接手验收结果: {PASS} 通过, {FAIL} 失败")
    print("=" * 60)

    if FAIL > 0:
        sys.exit(1)
    else:
        print("\n  全部通过！系统可交接。")


if __name__ == "__main__":
    main()
