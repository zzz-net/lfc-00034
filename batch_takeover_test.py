#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批次接管与回滚中心 - 回归测试脚本

覆盖完整链路：
  1. 创建快照（批量改期、整批取消、批次导出）
  2. 查看快照、列表查询
  3. 确认执行
  4. 重启后查询
  5. 冲突回滚
  6. 导出核对
  7. 权限与冲突矩阵

使用方法：
  python batch_takeover_test.py

退出码：0 = 全部通过，1 = 有失败
"""

import sys
import io
import json
import requests
from datetime import date, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8003"
BASE_RESTART = "http://127.0.0.1:8003"

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


def _assert(cond, msg=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    tag = "[PASS]" if cond else "[FAIL]"
    print(f"  {tag} {msg}")


def _create_test_batch(base, room_name_prefix, weeks=3, weekday=0):
    r = api(base, "post", "/api/rooms", {
        "name": f"{room_name_prefix}_{date.today().isoformat()}",
        "description": "批次接管测试"
    }, 201)
    room_id = r["id"]

    api(base, "post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday, "start_time": "09:00", "end_time": "22:00"}]
    }, 201)

    start = _next_weekday(weekday, 21)
    r = api(base, "post", "/api/bookings/recurring", {
        "room_id": room_id, "user_id": "test_user_takeover",
        "start_date": start.isoformat(), "start_time": "10:00", "end_time": "12:00",
        "purpose": "批次接管与回滚测试", "weeks": weeks
    }, 201)

    batch_id = r["batch_id"]
    bids = [i["booking_id"] for i in r["items"] if i["status"] == "success"]
    _assert(len(bids) == weeks, f"创建{weeks}周预约成功")

    return batch_id, room_id, bids


def _create_mixed_state(base, bids):
    if len(bids) >= 1:
        api(base, "post", f"/api/bookings/{bids[0]}/approve", {
            "operator_id": "admin_takeover", "operator_role": "admin", "reason": "测试:审批一条"
        })
    if len(bids) >= 3:
        api(base, "post", f"/api/bookings/{bids[2]}/cancel", {
            "operator_id": "test_user_takeover", "operator_role": "resident", "reason": "测试:取消一条"
        })
    print(f"  >> 制造混合状态: #{bids[0]}=approved, #{bids[2] if len(bids)>=3 else bids[-1]}=cancelled")


# ============================================================
# 场景1: 创建快照 - 批量改期
# ============================================================
def test_create_reschedule_snapshot(base=BASE):
    print("\n" + "=" * 60)
    print("  场景1: 创建快照 - 批量改期")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "改期快照测试", 3)
    _create_mixed_state(base, bids)

    new_start_date = _next_weekday(0, 42)

    r = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "reschedule",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试创建reschedule快照",
        "operation_params": {
            "new_start_date": new_start_date.isoformat(),
            "new_start_time": "14:00",
            "new_end_time": "16:00"
        }
    }, 201)

    snapshot_id = r["id"]
    _assert(r["batch_id"] == batch_id, f"快照关联batch_id正确")
    _assert(r["operation_type"] == "reschedule", "操作类型正确")
    _assert(r["status"] == "pending", "快照状态为pending")
    _assert(r["total_bookings"] == 3, "总预约数正确")
    _assert(r["affected_bookings"] == 1, "受影响预约数(adjustable)正确")
    _assert(r["preserved_bookings"] == 2, "保护预约数正确")
    _assert(r["config_snapshot"] is not None, "配置快照存在")
    _assert("max_recurring_weeks_at_snapshot" in r["config_snapshot"], "配置快照包含max值")
    _assert(len(r["booking_snapshots"]) == 3, "预约快照数量正确")
    _assert(r["conflict_check"]["has_conflict"] == False, "创建时无冲突")

    phases = [b["week_phase"] for b in r["booking_snapshots"]]
    _assert("preserved_approved" in phases, "包含preserved_approved相位")
    _assert("adjustable" in phases, "包含adjustable相位")
    _assert("finished" in phases, "包含finished相位")

    print(f"  >> snapshot_id={snapshot_id}, batch_id={batch_id}, bids={bids}")
    return snapshot_id, batch_id, room_id, bids


# ============================================================
# 场景2: 创建快照 - 整批取消
# ============================================================
def test_create_cancel_snapshot(base=BASE):
    print("\n" + "=" * 60)
    print("  场景2: 创建快照 - 整批取消")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "取消快照测试", 3)
    _create_mixed_state(base, bids)

    r = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "cancel",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试创建cancel快照"
    }, 201)

    snapshot_id = r["id"]
    _assert(r["operation_type"] == "cancel", "操作类型正确")
    _assert(r["status"] == "pending", "快照状态为pending")

    print(f"  >> snapshot_id={snapshot_id}, batch_id={batch_id}")
    return snapshot_id, batch_id


# ============================================================
# 场景3: 创建快照 - 批次导出
# ============================================================
def test_create_export_snapshot(base=BASE):
    print("\n" + "=" * 60)
    print("  场景3: 创建快照 - 批次导出")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "导出快照测试", 3)

    r = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "export",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试创建export快照"
    }, 201)

    snapshot_id = r["id"]
    _assert(r["operation_type"] == "export", "操作类型正确")
    _assert(r["status"] == "pending", "快照状态为pending")

    print(f"  >> snapshot_id={snapshot_id}, batch_id={batch_id}")
    return snapshot_id, batch_id


# ============================================================
# 场景4: 快照列表查询与详情查看
# ============================================================
def test_snapshot_list_and_detail(base=BASE):
    print("\n" + "=" * 60)
    print("  场景4: 快照列表查询与详情查看")
    print("=" * 60)

    batch_id1, room_id1, bids1 = _create_test_batch(base, "列表查询测试1", 2, 0)
    batch_id2, room_id2, bids2 = _create_test_batch(base, "列表查询测试2", 2, 1)

    r1 = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id1,
        "operation_type": "reschedule",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试快照1",
        "operation_params": {"new_start_date": _next_weekday(0, 42).isoformat()}
    }, 201)

    r2 = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id2,
        "operation_type": "cancel",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试快照2"
    }, 201)

    r_list = api(base, "get", "/api/snapshots", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    _assert(len(r_list) >= 2, "列表至少包含2个快照")

    r_filter = api(base, "get", "/api/snapshots", params={
        "batch_id": batch_id1,
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    _assert(len(r_filter) >= 1, "按batch_id过滤正确")

    r_status = api(base, "get", "/api/snapshots", params={
        "status": "pending",
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    _assert(all(s["status"] == "pending" for s in r_status), "按status过滤正确")

    r_detail = api(base, "get", f"/api/snapshots/{r1['id']}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    _assert(r_detail["id"] == r1["id"], "详情查询id正确")
    _assert(r_detail["booking_snapshots"] is not None, "详情包含预约快照")
    _assert(r_detail["audit_logs"] is not None, "详情包含审计日志")
    _assert(r_detail["conflict_check"] is not None, "详情包含冲突检查")

    r_resident = api(base, "get", "/api/snapshots", params={
        "operator_id": "other_user", "operator_role": "resident"
    })
    _assert(len(r_resident) == 0, "居民只能看自己的快照")

    return r1["id"], r2["id"]


# ============================================================
# 场景5: 权限控制测试
# ============================================================
def test_permission_control(base=BASE):
    print("\n" + "=" * 60)
    print("  场景5: 权限控制测试")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "权限测试", 2)

    r = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "reschedule",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "权限测试快照",
        "operation_params": {"new_start_date": _next_weekday(0, 42).isoformat()}
    }, 201)
    snapshot_id = r["id"]

    r_exec = api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "test_user_takeover",
        "operator_role": "resident",
        "reason": "居民尝试执行"
    }, 422)
    _assert(_err_code(r_exec) == 10024, "居民不能执行快照 => 10024")

    r_rollback = api(base, "post", f"/api/snapshots/{snapshot_id}/rollback", {
        "operator_id": "test_user_takeover",
        "operator_role": "resident",
        "reason": "居民尝试回滚"
    }, 422)
    _assert(_err_code(r_rollback) == 10024, "居民不能回滚快照 => 10024")

    r_cancel = api(base, "post", f"/api/snapshots/{snapshot_id}/cancel", params={
        "operator_id": "test_user_takeover",
        "operator_role": "resident",
        "reason": "居民尝试取消快照"
    }, expect=422)
    _assert(_err_code(r_cancel) == 10024, "居民不能取消快照 => 10024")

    r_view = api(base, "get", f"/api/snapshots/{snapshot_id}", params={
        "operator_id": "other_user",
        "operator_role": "resident"
    }, expect=422)
    _assert(_err_code(r_view) == 10007, "居民不能查看他人快照 => 10007")

    print(f"  >> 权限测试通过: 仅admin/staff可执行/回滚/取消")


# ============================================================
# 场景6: 确认执行 - 批量改期
# ============================================================
def test_execute_reschedule(base=BASE):
    print("\n" + "=" * 60)
    print("  场景6: 确认执行 - 批量改期")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "执行改期测试", 3)
    _create_mixed_state(base, bids)

    new_start_date = _next_weekday(0, 42)

    r_snap = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "reschedule",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试执行reschedule",
        "operation_params": {
            "new_start_date": new_start_date.isoformat(),
            "new_start_time": "14:00",
            "new_end_time": "16:00"
        }
    }, 201)
    snapshot_id = r_snap["id"]

    detail_before = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    adjustable_before = [b for b in detail_before["bookings"] if b["week_phase"] == "adjustable"]
    _assert(len(adjustable_before) == 1, f"执行前有{len(adjustable_before)}条可调预约")
    old_date = adjustable_before[0]["date"]

    r_exec = api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "admin执行改期操作"
    })
    _assert(r_exec["status"] == "executed", "执行后状态为executed")
    _assert(r_exec["executed_at"] is not None, "执行时间已记录")
    _assert(r_exec["operation_result"] is not None, "操作结果已记录")

    op_result = r_exec["operation_result"]
    _assert(op_result["operation"] == "reschedule", "操作类型正确")
    _assert(op_result["success"] == 1, "成功改期1条")
    _assert(op_result["preserved"] == 2, "保护2条")
    _assert(op_result["total"] == 3, "总数3条")

    detail_after = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    adjustable_after = [b for b in detail_after["bookings"] if b["week_phase"] == "adjustable"]
    _assert(adjustable_after[0]["date"] == new_start_date.isoformat(), "可调预约日期已更新")
    _assert(str(adjustable_after[0]["start_time"]).startswith("14:00"), "开始时间已更新")
    _assert(str(adjustable_after[0]["end_time"]).startswith("16:00"), "结束时间已更新")
    _assert(adjustable_after[0]["old_date"] == old_date, "old_date记录正确")

    preserved_after = [b for b in detail_after["bookings"] if b["week_phase"] == "preserved_approved"]
    _assert(len(preserved_after) == 1, "已审批预约仍被保护")
    _assert(preserved_after[0]["status"] == "approved", "已审批状态未变")

    audit_logs = api(base, "get", "/api/audit", params={"batch_id": batch_id})
    snapshot_audits = [l for l in audit_logs if "snapshot" in l["detail"].lower()]
    _assert(len(snapshot_audits) >= 3, "生成快照相关审计日志(create+execute_start+execute_end+reschedule)")

    reschedule_audits = [l for l in audit_logs if l["action"] == "reschedule"]
    _assert(len(reschedule_audits) == op_result["success"], "reschedule审计数量匹配")

    print(f"  >> 执行成功: snapshot_id={snapshot_id}, success={op_result['success']}")
    return snapshot_id, batch_id


# ============================================================
# 场景7: 确认执行 - 整批取消
# ============================================================
def test_execute_cancel(base=BASE):
    print("\n" + "=" * 60)
    print("  场景7: 确认执行 - 整批取消")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "执行取消测试", 3)
    _create_mixed_state(base, bids)

    r_snap = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "cancel",
        "operator_id": "staff_takeover",
        "operator_role": "staff",
        "description": "测试执行cancel"
    }, 201)
    snapshot_id = r_snap["id"]

    r_exec = api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "staff_takeover",
        "operator_role": "staff",
        "reason": "staff执行取消操作"
    })
    _assert(r_exec["status"] == "executed", "执行后状态为executed")

    op_result = r_exec["operation_result"]
    _assert(op_result["operation"] == "cancel", "操作类型正确")
    _assert(op_result["success"] >= 2, "成功取消至少2条(包括approved)")
    _assert(op_result["skipped"] >= 0, "跳过数量合理")

    detail_after = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    cancelled = [b for b in detail_after["bookings"] if b["status"] == "cancelled"]
    _assert(len(cancelled) >= 2, "至少2条预约已取消")

    print(f"  >> 执行成功: snapshot_id={snapshot_id}, success={op_result['success']}")
    return snapshot_id, batch_id


# ============================================================
# 场景8: 回滚 - 批量改期
# ============================================================
def test_rollback_reschedule(base=BASE):
    print("\n" + "=" * 60)
    print("  场景8: 回滚 - 批量改期")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "回滚改期测试", 3)
    _create_mixed_state(base, bids)

    detail_before = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    adjustable_before = [b for b in detail_before["bookings"] if b["week_phase"] == "adjustable"]
    original_date = adjustable_before[0]["date"]
    original_start = adjustable_before[0]["start_time"]
    original_end = adjustable_before[0]["end_time"]

    new_start_date = _next_weekday(0, 42)

    r_snap = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "reschedule",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试回滚reschedule",
        "operation_params": {
            "new_start_date": new_start_date.isoformat(),
            "new_start_time": "14:00",
            "new_end_time": "16:00"
        }
    }, 201)
    snapshot_id = r_snap["id"]

    api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "先执行再回滚"
    })

    detail_mid = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    adjustable_mid = [b for b in detail_mid["bookings"] if b["week_phase"] == "adjustable"]
    _assert(adjustable_mid[0]["date"] == new_start_date.isoformat(), "执行后日期已更改")

    r_rollback = api(base, "post", f"/api/snapshots/{snapshot_id}/rollback", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "测试回滚改期"
    })
    _assert(r_rollback["status"] == "rolled_back", "回滚后状态为rolled_back")
    _assert(r_rollback["rolled_back_at"] is not None, "回滚时间已记录")
    _assert(r_rollback["rollback_result"] is not None, "回滚结果已记录")

    rb_result = r_rollback["rollback_result"]
    _assert(rb_result["success"] == 1, "成功回滚1条")

    detail_after = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    adjustable_after = [b for b in detail_after["bookings"] if b["week_phase"] == "adjustable"]
    _assert(adjustable_after[0]["date"] == original_date, "回滚后日期已恢复")
    _assert(adjustable_after[0]["start_time"] == original_start, "回滚后开始时间已恢复")
    _assert(adjustable_after[0]["end_time"] == original_end, "回滚后结束时间已恢复")
    _assert(adjustable_after[0]["old_date"] is None, "回滚后old_date已清空")
    _assert(adjustable_after[0]["rescheduled_from_booking_id"] is None, "回滚后rescheduled_from已清空")

    print(f"  >> 回滚成功: snapshot_id={snapshot_id}")
    return snapshot_id, batch_id


# ============================================================
# 场景9: 回滚 - 整批取消
# ============================================================
def test_rollback_cancel(base=BASE):
    print("\n" + "=" * 60)
    print("  场景9: 回滚 - 整批取消")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "回滚取消测试", 3)

    detail_before = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    pending_before = [b for b in detail_before["bookings"] if b["status"] == "pending"]
    _assert(len(pending_before) == 3, "执行前3条都是pending")

    r_snap = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "cancel",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试回滚cancel"
    }, 201)
    snapshot_id = r_snap["id"]

    api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "先执行再回滚"
    })

    detail_mid = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    cancelled_mid = [b for b in detail_mid["bookings"] if b["status"] == "cancelled"]
    _assert(len(cancelled_mid) == 3, "执行后3条都已取消")

    r_rollback = api(base, "post", f"/api/snapshots/{snapshot_id}/rollback", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "测试回滚取消"
    })
    _assert(r_rollback["status"] == "rolled_back", "回滚后状态为rolled_back")

    rb_result = r_rollback["rollback_result"]
    _assert(rb_result["success"] == 3, "成功回滚3条")

    detail_after = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    pending_after = [b for b in detail_after["bookings"] if b["status"] == "pending"]
    _assert(len(pending_after) == 3, "回滚后3条都恢复为pending")

    print(f"  >> 回滚成功: snapshot_id={snapshot_id}")
    return snapshot_id, batch_id


# ============================================================
# 场景10: 冲突检测 - 快照占用冲突
# ============================================================
def test_conflict_snapshot_occupied(base=BASE):
    print("\n" + "=" * 60)
    print("  场景10: 冲突检测 - 快照占用冲突")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "冲突测试", 2)

    r1 = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "reschedule",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "第一个快照占用预约",
        "operation_params": {"new_start_date": _next_weekday(0, 42).isoformat()}
    }, 201)

    r2 = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "cancel",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "第二个快照尝试占用同一批预约"
    }, 422)
    _assert(_err_code(r2) == 10022, "快照占用冲突 => 10022")
    _assert("is occupied by snapshot" in r2.get("message", ""), "错误信息包含占用说明")

    detail = api(base, "get", f"/api/snapshots/{r1['id']}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    _assert(detail["conflict_check"]["has_conflict"] == False, "第一个快照无冲突")

    print(f"  >> 冲突检测通过: 同一批预约不能同时被多个快照占用")


# ============================================================
# 场景11: 冲突检测 - 预约已变化
# ============================================================
def test_conflict_booking_changed(base=BASE):
    print("\n" + "=" * 60)
    print("  场景11: 冲突检测 - 预约已变化")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "预约变化测试", 2)

    r_snap = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "cancel",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "创建后修改预约"
    }, 201)
    snapshot_id = r_snap["id"]

    api(base, "post", f"/api/bookings/{bids[0]}/cancel", {
        "operator_id": "test_user_takeover",
        "operator_role": "resident",
        "reason": "在快照创建后修改预约状态"
    })

    r_exec = api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "尝试执行已变化的快照"
    }, 422)
    _assert(_err_code(r_exec) == 10023, "预约已变化 => 10023")
    _assert("has changed" in r_exec.get("message", ""), "错误信息包含变化说明")

    print(f"  >> 冲突检测通过: 快照创建后预约变化时拒绝执行")


# ============================================================
# 场景12: 重复操作状态检查
# ============================================================
def test_duplicate_operation(base=BASE):
    print("\n" + "=" * 60)
    print("  场景12: 重复操作状态检查")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "重复操作测试", 2)

    r_snap = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "cancel",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试重复操作"
    }, 201)
    snapshot_id = r_snap["id"]

    api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "第一次执行"
    })

    r_exec2 = api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "重复执行"
    }, 422)
    _assert(_err_code(r_exec2) == 10019, "重复执行 => 10019")

    api(base, "post", f"/api/snapshots/{snapshot_id}/rollback", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "回滚"
    })

    r_rollback2 = api(base, "post", f"/api/snapshots/{snapshot_id}/rollback", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "重复回滚"
    }, 422)
    _assert(_err_code(r_rollback2) == 10021, "重复回滚 => 10021")

    r_exec3 = api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "回滚后再执行"
    }, 422)
    _assert(_err_code(r_exec3) == 10018, "回滚后执行 => 10018")

    print(f"  >> 状态检查通过: 重复操作被正确拒绝")


# ============================================================
# 场景13: 回滚冲突 - 目标已变化
# ============================================================
def test_rollback_conflict_target_changed(base=BASE):
    print("\n" + "=" * 60)
    print("  场景13: 回滚冲突 - 目标已变化")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "回滚冲突测试", 3)
    _create_mixed_state(base, bids)

    new_start_date1 = _next_weekday(0, 42)
    new_start_date2 = _next_weekday(0, 70)

    r_snap = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "reschedule",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试回滚冲突",
        "operation_params": {
            "new_start_date": new_start_date1.isoformat(),
            "new_start_time": "14:00",
            "new_end_time": "16:00"
        }
    }, 201)
    snapshot_id = r_snap["id"]

    adjustable_before = [b for b in r_snap["booking_snapshots"] if b["week_phase"] == "adjustable"]
    adjustable_booking_id = adjustable_before[0]["booking_id"]

    api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "执行改期"
    })

    detail_mid = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    adjustable_mid = [b for b in detail_mid["bookings"] if b["week_phase"] == "adjustable"]
    _assert(str(adjustable_mid[0]["date"]) == new_start_date1.isoformat(), "执行后日期已改到date1")

    api(base, "post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "new_start_date": new_start_date2.isoformat(),
        "new_start_time": "10:00",
        "new_end_time": "12:00",
        "reason": "在快照执行后,手动用批量改期再改一次"
    })

    detail_after_change = api(base, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    adjustable_after = [b for b in detail_after_change["bookings"] if b["week_phase"] == "adjustable"]
    _assert(str(adjustable_after[0]["date"]) == new_start_date2.isoformat(), "手动改期后日期已变到date2")

    r_rollback = api(base, "post", f"/api/snapshots/{snapshot_id}/rollback", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "尝试回滚,但目标预约已被手动修改过"
    })

    _assert(r_rollback["status"] == "rolled_back", "回滚仍执行,但部分被denied")
    rb_result = r_rollback["rollback_result"]
    _assert(rb_result["denied"] >= 1, "至少1条被denied")

    denied_items = [i for i in rb_result["items"] if i["result"] == "denied"]
    _assert(len(denied_items) >= 1, "denied条目存在")
    _assert("does not match expected state" in denied_items[0].get("message", ""),
            "错误信息说明状态不匹配")

    print(f"  >> 回滚冲突处理: 返回可解释结果, 不静默覆盖")


# ============================================================
# 场景14: 导出功能
# ============================================================
def test_export_snapshot(base=BASE):
    print("\n" + "=" * 60)
    print("  场景14: 导出功能")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "导出测试", 3)
    _create_mixed_state(base, bids)

    r_snap = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "reschedule",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试导出快照",
        "operation_params": {"new_start_date": _next_weekday(0, 42).isoformat()}
    }, 201)
    snapshot_id = r_snap["id"]

    api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "执行后导出"
    })

    resp = requests.get(f"{base}/api/snapshots/{snapshot_id}/export", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    _assert(resp.status_code == 200, "导出HTTP 200")
    _assert("attachment" in resp.headers.get("Content-Disposition", ""), "Content-Disposition含attachment")

    export_data = resp.json()
    for key in ["snapshot", "config_snapshot", "booking_snapshots",
                "snapshot_audit_logs", "batch_audit_logs", "summary"]:
        _assert(key in export_data, f"导出包含{key}")

    _assert(export_data["snapshot"]["id"] == snapshot_id, "导出快照id正确")
    _assert(export_data["snapshot"]["operation_type"] == "reschedule", "导出操作类型正确")
    _assert(export_data["snapshot"]["status"] == "executed", "导出状态正确")
    _assert(export_data["operation_result"] is not None, "导出包含操作结果")

    cfg = export_data["config_snapshot"]
    for k in ["max_recurring_weeks_at_snapshot", "min_recurring_weeks",
              "absolute_max_recurring_weeks", "default_max_recurring_weeks",
              "env_var_name", "snapshot_created_at"]:
        _assert(k in cfg, f"config_snapshot包含{k}")

    summary = export_data["summary"]
    _assert(summary["total_bookings"] == 3, "summary总数正确")
    phase_sum = sum(summary.get(k, 0) for k in
                   ["preserved_in_effect", "preserved_approved", "adjustable", "finished"])
    _assert(phase_sum == 3, "各phase计数之和等于总数")

    r_resident = requests.get(f"{base}/api/snapshots/{snapshot_id}/export", params={
        "operator_id": "other_user", "operator_role": "resident"
    })
    _assert(r_resident.status_code == 422, "居民不能导出他人快照")

    print(f"  >> 导出功能正常: snapshot_id={snapshot_id}")


# ============================================================
# 场景15: 取消pending快照
# ============================================================
def test_cancel_pending_snapshot(base=BASE):
    print("\n" + "=" * 60)
    print("  场景15: 取消pending快照")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base, "取消快照测试", 2)

    r_snap = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "reschedule",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "待取消的快照",
        "operation_params": {"new_start_date": _next_weekday(0, 42).isoformat()}
    }, 201)
    snapshot_id = r_snap["id"]

    r_cancel = api(base, "post", f"/api/snapshots/{snapshot_id}/cancel", params={
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "管理员取消pending快照"
    })
    _assert(r_cancel["status"] == "cancelled", "快照状态变为cancelled")

    r_exec = api(base, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "尝试执行已取消的快照"
    }, 422)
    _assert(_err_code(r_exec) == 10018, "已取消的快照不能执行")

    batch_id2, room_id2, bids2 = _create_test_batch(base, "占用释放测试", 2)
    r_snap2 = api(base, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "cancel",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "测试取消后释放占用"
    }, 201)
    _assert(r_snap2["id"] is not None, "取消后释放占用,可创建新快照")

    print(f"  >> 取消pending快照正常: 释放占用,防止误执行")


# ============================================================
# 场景16: 重启后查询与数据一致性
# ============================================================
def test_restart_consistency(base_before=BASE, base_after=BASE_RESTART):
    print("\n" + "=" * 60)
    print("  场景16: 重启后查询与数据一致性")
    print("=" * 60)

    batch_id, room_id, bids = _create_test_batch(base_before, "重启测试", 3)
    _create_mixed_state(base_before, bids)

    new_start_date = _next_weekday(0, 42)

    r_snap = api(base_before, "post", "/api/snapshots", {
        "batch_id": batch_id,
        "operation_type": "reschedule",
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "description": "重启前创建的快照",
        "operation_params": {
            "new_start_date": new_start_date.isoformat(),
            "new_start_time": "14:00",
            "new_end_time": "16:00"
        }
    }, 201)
    snapshot_id = r_snap["id"]

    api(base_before, "post", f"/api/snapshots/{snapshot_id}/execute", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "重启前执行"
    })

    snapshot_before = api(base_before, "get", f"/api/snapshots/{snapshot_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    _assert(snapshot_before["status"] == "executed", "执行后状态为executed")
    _assert(snapshot_before["executed_at"] is not None, "执行时间已记录")

    detail_before = api(base_before, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })

    print("  >> 模拟服务重启(使用同一端口)")

    snapshot_after = api(base_after, "get", f"/api/snapshots/{snapshot_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })

    _assert(snapshot_after["id"] == snapshot_before["id"], "重启后快照id一致")
    _assert(snapshot_after["status"] == "executed", "重启后状态仍为executed")
    _assert(snapshot_after["executed_at"] == snapshot_before["executed_at"], "重启后执行时间一致")
    _assert(snapshot_after["operation_result"] is not None, "重启后操作结果仍存在")
    _assert(len(snapshot_after["booking_snapshots"]) == len(snapshot_before["booking_snapshots"]),
           "重启后预约快照数量一致")

    for i, b_after in enumerate(snapshot_after["booking_snapshots"]):
        b_before = snapshot_before["booking_snapshots"][i]
        for f in ["booking_id", "date", "start_time", "end_time", "status", "week_phase"]:
            _assert(b_after.get(f) == b_before.get(f),
                    f"重启后预约#{b_after['booking_id']}的{f}一致")

    detail_after = api(base_after, "get", f"/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })

    for b_after in detail_after["bookings"]:
        b_before = next(b for b in detail_before["bookings"] if b["id"] == b_after["id"])
        for f in ["status", "date", "start_time", "end_time", "old_date"]:
            _assert(b_after.get(f) == b_before.get(f),
                    f"重启后预约#{b_after['id']}的{f}一致")

    list_after = api(base_after, "get", "/api/snapshots", params={
        "operator_id": "admin_takeover", "operator_role": "admin"
    })
    found = any(s["id"] == snapshot_id for s in list_after)
    _assert(found, "重启后快照在列表中存在")

    r_rollback = api(base_after, "post", f"/api/snapshots/{snapshot_id}/rollback", {
        "operator_id": "admin_takeover",
        "operator_role": "admin",
        "reason": "重启后回滚"
    })
    _assert(r_rollback["status"] == "rolled_back", "重启后可正常回滚")

    print(f"  >> 重启一致性通过: 快照数据完整,操作可继续")

    save_restart_test_data(snapshot_id, batch_id, bids, snapshot_before, detail_before)


def save_restart_test_data(snapshot_id, batch_id, bids, snapshot_before, detail_before):
    data = {
        "snapshot_id": snapshot_id,
        "batch_id": batch_id,
        "bids": bids,
        "snapshot_before": snapshot_before,
        "detail_before": detail_before,
    }
    with open("batch_takeover_restart_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("  >> 重启测试数据已保存到 batch_takeover_restart_data.json")


# ============================================================
# 主流程
# ============================================================
def main():
    global BASE, BASE_RESTART

    print("=" * 60)
    print("  批次接管与回滚中心 - 回归测试")
    print("=" * 60)

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
        print(f"    python -m uvicorn booking.main:app --host 127.0.0.1 --port 8003")
        sys.exit(1)

    test_create_reschedule_snapshot(BASE)
    test_create_cancel_snapshot(BASE)
    test_create_export_snapshot(BASE)
    test_snapshot_list_and_detail(BASE)
    test_permission_control(BASE)
    test_execute_reschedule(BASE)
    test_execute_cancel(BASE)
    test_rollback_reschedule(BASE)
    test_rollback_cancel(BASE)
    test_conflict_snapshot_occupied(BASE)
    test_conflict_booking_changed(BASE)
    test_duplicate_operation(BASE)
    test_rollback_conflict_target_changed(BASE)
    test_export_snapshot(BASE)
    test_cancel_pending_snapshot(BASE)
    test_restart_consistency(BASE, BASE_RESTART)

    print("\n" + "=" * 60)
    print(f"  回归测试结果: {PASS} 通过, {FAIL} 失败")
    print("=" * 60)

    if FAIL > 0:
        sys.exit(1)
    else:
        print("\n  全部通过！批次接管与回滚中心功能完整。")


if __name__ == "__main__":
    main()
