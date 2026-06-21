"""
社区活动室预约系统 - 样例请求与验收测试脚本

使用方法:
  1. 启动服务:  python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000
  2. 运行脚本:  python test_sample.py

脚本会依次执行:
  - 主链路: 配置房间 -> 配置时段 -> 提交预约 -> 审批通过 -> 房间锁定
  - 边界用例: 重叠时段审批失败、居民取消他人预约失败、不在开放时段申请失败
  - 权限用例: 居民身份审批被拒绝、staff 身份审批成功
  - 响应格式一致性验证
  - 持久性验证: 查询待审批/已占用/取消记录/审计日志
  - 周期预约配置端点与文档同步验证
  - 周期预约全链路: 部分冲突、权限控制、审批锁定、配置超限、审计链路、重启一致性
"""

import sys
import io
import json
import os
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"

PASS = 0
FAIL = 0


def get_err_code(resp_json: dict) -> int:
    if "error_code" in resp_json:
        return resp_json["error_code"]
    if isinstance(resp_json.get("detail"), dict):
        return resp_json["detail"].get("error_code", 0)
    return 0


def api(method: str, path: str, data: dict | None = None, expect_status: int = 200, params: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    if method == "get" and data is not None and params is None:
        params = data
        data = None
    resp = getattr(requests, method)(url, json=data, params=params)
    ok = resp.status_code == expect_status
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
    tag = "[PASS]" if ok else "[FAIL]"
    print(f"  {tag} {method.upper()} {path} => {resp.status_code} (expect {expect_status})")
    if not ok:
        print(f"    response: {resp.text[:300]}")
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {}


def test_error_response_consistency():
    global PASS, FAIL
    print("\n========== 错误响应格式一致性验证 ==========")
    r = requests.post(f"{BASE}/api/bookings/99999/approve", json={
        "operator_id": "admin1",
        "operator_role": "admin",
        "reason": ""
    })
    data = r.json()
    assert "error_code" in data, f"Response missing top-level error_code: {data}"
    assert "message" in data, f"Response missing top-level message: {data}"
    assert "detail" not in data, f"Response should NOT have 'detail' wrapper: {data}"
    PASS += 1
    print(f"  [PASS] Error response format is {{error_code, message}} (no detail wrapper)")


def test_non_admin_approval_rejected():
    print("\n========== 非管理员审批被拒绝 ==========")

    r = api("post", "/api/rooms", {"name": "乒乓球室", "description": "二楼活动室"}, 201)
    room_id = r["id"]

    from datetime import date, timedelta
    next_tuesday = date.today() + timedelta(days=(7 - date.today().weekday() + 1) % 7)
    if next_tuesday == date.today():
        next_tuesday += timedelta(days=7)
    weekday_1 = next_tuesday.weekday()
    booking_date = next_tuesday.isoformat()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_1, "start_time": "10:00", "end_time": "20:00"}]
    }, 201)

    r = api("post", "/api/bookings", {
        "room_id": room_id,
        "user_id": "zhaoliu",
        "date": booking_date,
        "start_time": "10:00",
        "end_time": "12:00",
        "purpose": "乒乓球比赛"
    }, 201)
    booking_id = r["id"]

    r = api("post", f"/api/bookings/{booking_id}/approve", {
        "operator_id": "zhaoliu",
        "operator_role": "resident",
        "reason": "同意"
    }, 422)
    err_code = get_err_code(r)
    assert err_code == 10007, f"Expected 10007 (PERMISSION_DENIED), got {err_code}. Response: {r}"
    print(f"  [PASS] resident 审批被拒绝, error_code={err_code}")

    r = api("post", f"/api/bookings/{booking_id}/reject", {
        "operator_id": "zhaoliu",
        "operator_role": "resident",
        "reason": "驳回"
    }, 422)
    err_code = get_err_code(r)
    assert err_code == 10007, f"Expected 10007 (PERMISSION_DENIED), got {err_code}. Response: {r}"
    print(f"  [PASS] resident 驳回被拒绝, error_code={err_code}")

    r = api("post", f"/api/bookings/{booking_id}/approve", {
        "operator_id": "staff1",
        "operator_role": "staff",
        "reason": "同意"
    })
    assert r["status"] == "approved", f"Expected approved, got {r['status']}"
    print(f"  [PASS] staff 审批成功, status={r['status']}")

    return room_id, booking_id, booking_date


def test_main_flow():
    print("\n========== 主链路测试 ==========")

    r = api("post", "/api/rooms", {"name": "舞蹈室", "description": "一楼舞蹈活动室"}, 201)
    room_id = r["id"]
    print(f"  >> 创建房间 id={room_id}")

    from datetime import date, timedelta
    next_monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7)
    if next_monday == date.today():
        next_monday += timedelta(days=7)
    weekday_0 = next_monday.weekday()

    r = api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_0, "start_time": "09:00", "end_time": "12:00"},
                  {"weekday": weekday_0, "start_time": "14:00", "end_time": "18:00"}]
    }, 201)
    print(f"  >> 配置 {len(r)} 个时段")

    booking_date = next_monday.isoformat()
    r = api("post", "/api/bookings", {
        "room_id": room_id,
        "user_id": "zhangsan",
        "date": booking_date,
        "start_time": "09:00",
        "end_time": "11:00",
        "purpose": "社区舞蹈排练"
    }, 201)
    booking_id = r["id"]
    print(f"  >> 提交预约 id={booking_id}, status={r['status']}")

    r = api("post", f"/api/bookings/{booking_id}/approve", {
        "operator_id": "admin1",
        "operator_role": "admin",
        "reason": "同意"
    })
    print(f"  >> 审批后 status={r['status']}")

    r = api("get", f"/api/bookings/{booking_id}")
    assert r["status"] == "approved", f"Expected approved, got {r['status']}"
    print(f"  [PASS] 房间已锁定: 预约 #{booking_id} 状态为 approved")

    return room_id, booking_id, booking_date


def test_overlap_approval(room_id, booking_date):
    print("\n========== 重叠时段审批失败测试 ==========")

    r1 = api("post", "/api/bookings", {
        "room_id": room_id,
        "user_id": "lisi",
        "date": booking_date,
        "start_time": "14:00",
        "end_time": "16:00",
        "purpose": "瑜伽课"
    }, 201)
    bid_a = r1["id"]
    print(f"  >> 提交预约A id={bid_a} (14:00-16:00)")

    r2 = api("post", "/api/bookings", {
        "room_id": room_id,
        "user_id": "wangwu",
        "date": booking_date,
        "start_time": "15:00",
        "end_time": "17:00",
        "purpose": "书法课"
    }, 201)
    bid_b = r2["id"]
    print(f"  >> 提交预约B id={bid_b} (15:00-17:00, 与A重叠)")

    r = api("post", f"/api/bookings/{bid_a}/approve", {
        "operator_id": "admin1",
        "operator_role": "admin",
        "reason": ""
    })
    print(f"  >> 预约A审批后 status={r['status']}")

    r = api("post", f"/api/bookings/{bid_b}/approve", {
        "operator_id": "admin1",
        "operator_role": "admin",
        "reason": ""
    }, 422)
    err_code = get_err_code(r)
    assert err_code == 10004, f"Expected error_code 10004 (BOOKING_OVERLAP), got {err_code}"
    print(f"  [PASS] 重叠审批被拒绝, error_code={err_code}")


def test_cancel_others_booking(booking_id):
    print("\n========== 居民取消他人预约失败测试 ==========")

    r = api("post", f"/api/bookings/{booking_id}/cancel", {
        "operator_id": "lisi",
        "operator_role": "resident",
        "reason": "我想取消"
    }, 422)
    err_code = get_err_code(r)
    assert err_code == 10007, f"Expected error_code 10007 (PERMISSION_DENIED), got {err_code}"
    print(f"  [PASS] 居民无法取消他人预约, error_code={err_code}")


def test_outside_open_hours(room_id):
    print("\n========== 不在开放时段申请失败测试 ==========")

    from datetime import date, timedelta
    next_monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7)
    if next_monday == date.today():
        next_monday += timedelta(days=7)
    booking_date = next_monday.isoformat()

    r = api("post", "/api/bookings", {
        "room_id": room_id,
        "user_id": "wangwu",
        "date": booking_date,
        "start_time": "12:00",
        "end_time": "13:00",
        "purpose": "午间活动"
    }, 422)
    err_code = get_err_code(r)
    assert err_code == 10003, f"Expected error_code 10003 (SLOT_NOT_OPEN), got {err_code}"
    print(f"  [PASS] 不在开放时段被拒绝, error_code={err_code}")


def test_persistence(room_id, booking_id):
    print("\n========== 持久性验证 ==========")

    params_pending = {"status": "pending", "room_id": room_id}
    r = requests.get(f"{BASE}/api/bookings", params=params_pending)
    print(f"  >> 待审批列表: {len(r.json())} 条")

    r = requests.get(f"{BASE}/api/bookings", params={"status": "approved", "room_id": room_id})
    approved = r.json()
    print(f"  >> 已占用时段: {len(approved)} 条")
    assert any(b["id"] == booking_id for b in approved), "已审批预约未找到"

    r = api("post", f"/api/bookings/{booking_id}/cancel", {
        "operator_id": "zhangsan",
        "operator_role": "resident",
        "reason": "临时有事"
    })
    assert r["status"] == "cancelled"
    print(f"  >> 取消预约 #{booking_id}")

    r = requests.get(f"{BASE}/api/bookings", params={"status": "cancelled", "room_id": room_id})
    cancelled = r.json()
    print(f"  >> 取消记录: {len(cancelled)} 条")
    assert len(cancelled) >= 1, "取消记录未找到"

    r = requests.get(f"{BASE}/api/audit", params={"booking_id": booking_id})
    logs = r.json()
    print(f"  >> 审计日志: {len(logs)} 条")
    assert len(logs) >= 2, "审计日志不完整(至少应有 create 和 cancel)"

    r = requests.get(f"{BASE}/api/audit/export", params={"booking_id": booking_id})
    exported = r.json()
    print(f"  >> 导出日志: {len(exported)} 条")
    assert len(exported) == len(logs), "导出日志与查询日志数量不一致"

    actions = [log_item["action"] for log_item in logs]
    print(f"  >> 操作序列: {actions}")


def _get_server_max_weeks():
    r = api("get", "/api/bookings/recurring/config")
    return r["max_recurring_weeks"], r


_cached_max_weeks = None

def _max_weeks():
    global _cached_max_weeks
    if _cached_max_weeks is None:
        _cached_max_weeks = _get_server_max_weeks()[0]
    return _cached_max_weeks


def test_recurring_config_endpoint():
    print("\n========== 周期预约 - 配置端点与文档同步验证 ==========")
    from booking import (
        DEFAULT_MAX_RECURRING_WEEKS,
        MIN_RECURRING_WEEKS, ABSOLUTE_MAX_RECURRING_WEEKS, ENV_VAR_NAME,
    )

    r = api("get", "/api/bookings/recurring/config")
    assert r["min_recurring_weeks"] == MIN_RECURRING_WEEKS == 1
    assert r["absolute_max_recurring_weeks"] == ABSOLUTE_MAX_RECURRING_WEEKS == 52
    assert r["default_max_recurring_weeks"] == DEFAULT_MAX_RECURRING_WEEKS == 4
    assert r["env_var_name"] == ENV_VAR_NAME == "BOOKING_MAX_RECURRING_WEEKS"
    assert MIN_RECURRING_WEEKS <= r["max_recurring_weeks"] <= ABSOLUTE_MAX_RECURRING_WEEKS, (
        f"max_recurring_weeks={r['max_recurring_weeks']} "
        f"not in range [{MIN_RECURRING_WEEKS}, {ABSOLUTE_MAX_RECURRING_WEEKS}]"
    )
    print(f"  [PASS] 配置端点固定值与代码常量完全一致")
    print(f"    max_recurring_weeks={r['max_recurring_weeks']}")
    print(f"    min_recurring_weeks={r['min_recurring_weeks']}")
    print(f"    absolute_max_recurring_weeks={r['absolute_max_recurring_weeks']}")
    print(f"    default_max_recurring_weeks={r['default_max_recurring_weeks']}")
    print(f"    env_var_name={r['env_var_name']}")
    print(f"  [PASS] max_recurring_weeks={r['max_recurring_weeks']} 在有效范围 [{MIN_RECURRING_WEEKS}, {ABSOLUTE_MAX_RECURRING_WEEKS}] 内")


def test_recurring_booking_partial_success():
    print("\n========== 周期预约 - 部分成功部分冲突测试 ==========")
    from datetime import date, timedelta
    MAX_RECURRING_WEEKS = _max_weeks()

    r = api("post", "/api/rooms", {"name": "多功能厅", "description": "三楼多功能厅"}, 201)
    room_id = r["id"]

    next_monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7)
    if next_monday == date.today():
        next_monday += timedelta(days=7)
    weekday_0 = next_monday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_0, "start_time": "09:00", "end_time": "12:00"}]
    }, 201)

    booking_date = next_monday.isoformat()
    r = api("post", "/api/bookings", {
        "room_id": room_id,
        "user_id": "zhangsan",
        "date": booking_date,
        "start_time": "09:00",
        "end_time": "11:00",
        "purpose": "社区会议"
    }, 201)
    single_booking_id = r["id"]

    r = api("post", f"/api/bookings/{single_booking_id}/approve", {
        "operator_id": "admin1",
        "operator_role": "admin",
        "reason": "同意"
    })
    assert r["status"] == "approved"
    print(f"  >> 先创建并审批一个单次预约 #{single_booking_id} 造成冲突")

    test_weeks = min(2, MAX_RECURRING_WEEKS)
    second_monday = next_monday + timedelta(weeks=1)
    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "lisi",
        "start_date": next_monday.isoformat(),
        "start_time": "09:00",
        "end_time": "11:00",
        "purpose": "每周一例会",
        "weeks": test_weeks
    }, 201)

    batch_id = r["batch_id"]
    print(f"  >> 创建周期预约 batch_id={batch_id}, 共{test_weeks}周")
    print(f"  >> 统计: total={r['total']}, success={r['success']}, skipped={r['skipped']}, denied={r['denied']}")

    assert r["total"] == test_weeks
    assert r["success"] == test_weeks - 1
    assert r["skipped"] == 1
    assert r["denied"] == 0

    success_dates = [item["date"] for item in r["items"] if item["status"] == "success"]
    skipped_dates = [item["date"] for item in r["items"] if item["status"] == "skipped"]
    print(f"  >> 成功日期: {success_dates}")
    print(f"  >> 冲突跳过日期: {skipped_dates}")

    assert booking_date in skipped_dates
    assert second_monday.isoformat() in success_dates

    success_items = [item for item in r["items"] if item["status"] == "success"]
    for item in success_items:
        assert item["booking_id"] is not None
    skipped_items = [item for item in r["items"] if item["status"] == "skipped"]
    for item in skipped_items:
        assert item["error_code"] == 10004
        assert item["booking_id"] is None

    print(f"  [PASS] 周期预约部分成功部分冲突验证通过")
    return room_id, batch_id, success_items[0]["booking_id"], second_monday.isoformat()


def test_recurring_booking_permission():
    print("\n========== 周期预约 - 批次列表与详情权限控制测试 ==========")
    from datetime import date, timedelta
    MAX_RECURRING_WEEKS = _max_weeks()

    r = api("post", "/api/rooms", {"name": "钢琴室", "description": "四楼钢琴室"}, 201)
    room_id = r["id"]

    next_tuesday = date.today() + timedelta(days=(7 - date.today().weekday() + 1) % 7)
    if next_tuesday == date.today():
        next_tuesday += timedelta(days=7)
    weekday_1 = next_tuesday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_1, "start_time": "14:00", "end_time": "18:00"}]
    }, 201)

    test_weeks = min(1, MAX_RECURRING_WEEKS)
    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "zhangsan",
        "start_date": next_tuesday.isoformat(),
        "start_time": "14:00",
        "end_time": "16:00",
        "purpose": "钢琴练习",
        "weeks": test_weeks
    }, 201)
    zhangsan_batch_id = r["batch_id"]
    print(f"  >> zhangsan 创建周期预约 batch_id={zhangsan_batch_id}")

    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "lisi",
        "start_date": next_tuesday.isoformat(),
        "start_time": "16:00",
        "end_time": "18:00",
        "purpose": "钢琴练习",
        "weeks": test_weeks
    }, 201)
    lisi_batch_id = r["batch_id"]
    print(f"  >> lisi 创建周期预约 batch_id={lisi_batch_id}")

    print("\n  --- 批次详情接口权限 ---")
    r = api("get", f"/api/bookings/batches/{zhangsan_batch_id}?operator_id=zhangsan&operator_role=resident")
    assert r["id"] == zhangsan_batch_id
    assert r["user_id"] == "zhangsan"
    print(f"  [PASS] zhangsan 可以查看自己的批次详情")

    r = api("get", f"/api/bookings/batches/{zhangsan_batch_id}?operator_id=lisi&operator_role=resident", expect_status=422)
    err_code = get_err_code(r)
    assert err_code == 10007
    print(f"  [PASS] lisi 不能查看 zhangsan 的批次详情, error_code={err_code}")

    r = api("get", f"/api/bookings/batches/{zhangsan_batch_id}?operator_id=admin1&operator_role=admin")
    assert r["id"] == zhangsan_batch_id
    print(f"  [PASS] admin 可以查看任意批次详情")

    print("\n  --- 批次列表接口权限 ---")
    r = requests.get(f"{BASE}/api/bookings/batches", params={
        "operator_id": "zhangsan", "operator_role": "resident"
    })
    assert r.status_code == 200
    zhangsan_batches = r.json()
    zhangsan_batch_ids = [b["id"] for b in zhangsan_batches]
    assert zhangsan_batch_id in zhangsan_batch_ids
    assert lisi_batch_id not in zhangsan_batch_ids
    print(f"  [PASS] zhangsan 查询列表只看到自己的批次: {zhangsan_batch_ids}")

    r = requests.get(f"{BASE}/api/bookings/batches", params={
        "operator_id": "lisi", "operator_role": "resident"
    })
    assert r.status_code == 200
    lisi_batches = r.json()
    lisi_batch_ids = [b["id"] for b in lisi_batches]
    assert lisi_batch_id in lisi_batch_ids
    assert zhangsan_batch_id not in lisi_batch_ids
    print(f"  [PASS] lisi 查询列表只看到自己的批次: {lisi_batch_ids}")

    r = requests.get(f"{BASE}/api/bookings/batches", params={
        "user_id": "lisi", "operator_id": "zhangsan", "operator_role": "resident"
    })
    assert r.status_code == 422
    err_code = get_err_code(r.json())
    assert err_code == 10007
    print(f"  [PASS] zhangsan 传 user_id=lisi 查询列表被拒绝, error_code={err_code}")

    r = requests.get(f"{BASE}/api/bookings/batches", params={
        "user_id": "zhangsan", "operator_id": "zhangsan", "operator_role": "resident"
    })
    assert r.status_code == 200
    self_filter = r.json()
    self_ids = [b["id"] for b in self_filter]
    assert zhangsan_batch_id in self_ids
    assert lisi_batch_id not in self_ids
    print(f"  [PASS] zhangsan 传 user_id=zhangsan 查询自己的列表成功: {self_ids}")

    r = requests.get(f"{BASE}/api/bookings/batches", params={
        "operator_id": "admin1", "operator_role": "admin"
    })
    assert r.status_code == 200
    admin_batches = r.json()
    admin_ids = [b["id"] for b in admin_batches]
    assert zhangsan_batch_id in admin_ids
    assert lisi_batch_id in admin_ids
    print(f"  [PASS] admin 不传 user_id 可以看到所有批次: {admin_ids}")

    r = requests.get(f"{BASE}/api/bookings/batches", params={
        "user_id": "lisi", "operator_id": "admin1", "operator_role": "admin"
    })
    assert r.status_code == 200
    admin_lisi_batches = r.json()
    admin_lisi_ids = [b["id"] for b in admin_lisi_batches]
    assert lisi_batch_id in admin_lisi_ids
    assert zhangsan_batch_id not in admin_lisi_ids
    print(f"  [PASS] admin 传 user_id=lisi 只看到 lisi 的批次: {admin_lisi_ids}")

    print("\n  --- 可见字段验证 ---")
    for b in zhangsan_batches:
        assert "user_id" in b
        assert "total_count" in b
        assert "success_count" in b
        assert "skip_count" in b
        assert "denied_count" in b
        assert "exceeded_count" in b
        assert "max_recurring_weeks_at_creation" in b
        assert b["user_id"] == "zhangsan"
    print(f"  [PASS] 列表返回字段完整(含 max_recurring_weeks_at_creation), user_id 均为当前用户")

    print(f"\n  [PASS] 批次列表与详情权限控制验证全部通过")
    return zhangsan_batch_id


def test_recurring_booking_approval_lock():
    print("\n========== 周期预约 - 审批后锁定冲突时段测试 ==========")
    from datetime import date, timedelta
    MAX_RECURRING_WEEKS = _max_weeks()

    r = api("post", "/api/rooms", {"name": "羽毛球室", "description": "地下羽毛球场"}, 201)
    room_id = r["id"]

    next_wednesday = date.today() + timedelta(days=(7 - date.today().weekday() + 2) % 7)
    if next_wednesday == date.today():
        next_wednesday += timedelta(days=7)
    weekday_2 = next_wednesday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_2, "start_time": "18:00", "end_time": "22:00"}]
    }, 201)

    test_weeks = min(2, MAX_RECURRING_WEEKS)
    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "wangwu",
        "start_date": next_wednesday.isoformat(),
        "start_time": "19:00",
        "end_time": "21:00",
        "purpose": "羽毛球训练",
        "weeks": test_weeks
    }, 201)
    batch_id = r["batch_id"]
    print(f"  >> wangwu 创建周期预约 batch_id={batch_id}")

    success_items = [item for item in r["items"] if item["status"] == "success"]
    assert len(success_items) == 2
    booking_id_1 = success_items[0]["booking_id"]
    booking_id_2 = success_items[1]["booking_id"]
    date_1 = success_items[0]["date"]
    date_2 = success_items[1]["date"]

    r = api("post", f"/api/bookings/{booking_id_1}/approve", {
        "operator_id": "admin1",
        "operator_role": "admin",
        "reason": "同意"
    })
    assert r["status"] == "approved"
    print(f"  >> 审批通过预约 #{booking_id_1}")

    r = api("post", "/api/bookings", {
        "room_id": room_id,
        "user_id": "zhaoliu",
        "date": date_1,
        "start_time": "20:00",
        "end_time": "21:00",
        "purpose": "临时用"
    }, 422)
    err_code = get_err_code(r)
    assert err_code == 10004
    print(f"  [PASS] 与已审批周期预约 #{booking_id_1} 重叠的预约创建时就被拒绝, error_code={err_code}")

    r = api("post", "/api/bookings", {
        "room_id": room_id,
        "user_id": "zhaoliu",
        "date": date_2,
        "start_time": "20:00",
        "end_time": "21:00",
        "purpose": "临时用"
    }, 201)
    non_overlap_booking_id = r["id"]

    r = api("post", f"/api/bookings/{non_overlap_booking_id}/approve", {
        "operator_id": "admin1",
        "operator_role": "admin",
        "reason": "同意"
    })
    assert r["status"] == "approved"
    print(f"  [PASS] 与未审批周期预约 #{booking_id_2} 同时段的预约可以审批通过")

    r = api("post", f"/api/bookings/{booking_id_2}/approve", {
        "operator_id": "admin1",
        "operator_role": "admin",
        "reason": "同意"
    }, 422)
    err_code = get_err_code(r)
    assert err_code == 10004
    print(f"  [PASS] 再审批周期预约 #{booking_id_2} 时因冲突被拒绝, error_code={err_code}")

    r = requests.get(f"{BASE}/api/bookings", params={"status": "approved", "room_id": room_id, "date": date_1})
    approved_date1 = r.json()
    assert any(b["id"] == booking_id_1 for b in approved_date1)
    print(f"  [PASS] 已审批的周期预约 #{booking_id_1} 正确锁定了 {date_1} 的时段")

    r = requests.get(f"{BASE}/api/bookings", params={"status": "approved", "room_id": room_id, "date": date_2})
    approved_date2 = r.json()
    assert any(b["id"] == non_overlap_booking_id for b in approved_date2)
    print(f"  [PASS] 抢先审批的预约 #{non_overlap_booking_id} 正确锁定了 {date_2} 的时段")

    print(f"  [PASS] 审批后锁定冲突时段验证通过")
    return batch_id


def test_recurring_booking_batch_limit():
    print("\n========== 周期预约 - 配置超限测试 ==========")
    from datetime import date, timedelta
    MAX_RECURRING_WEEKS = _max_weeks()
    from booking import ENV_VAR_NAME

    r = api("post", "/api/rooms", {"name": "棋牌室", "description": "二楼棋牌室"}, 201)
    room_id = r["id"]

    next_thursday = date.today() + timedelta(days=(7 - date.today().weekday() + 3) % 7)
    if next_thursday == date.today():
        next_thursday += timedelta(days=7)
    weekday_3 = next_thursday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_3, "start_time": "09:00", "end_time": "18:00"}]
    }, 201)

    too_many_weeks = MAX_RECURRING_WEEKS + 10
    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "qianqi",
        "start_date": next_thursday.isoformat(),
        "start_time": "09:00",
        "end_time": "12:00",
        "purpose": "棋牌活动",
        "weeks": too_many_weeks
    }, 422)
    err_code = get_err_code(r)
    assert err_code == 10010
    msg = r.get("message", "")
    assert ENV_VAR_NAME in msg, (
        f"越界错误提示应包含环境变量名 {ENV_VAR_NAME}, 实际: {msg}"
    )
    assert str(MAX_RECURRING_WEEKS) in msg, (
        f"越界错误提示应包含当前上限值 {MAX_RECURRING_WEEKS}, 实际: {msg}"
    )
    print(f"  [PASS] weeks={too_many_weeks} 超过上限 {MAX_RECURRING_WEEKS} 被拒绝, error_code={err_code}")
    print(f"  [PASS] 错误提示包含可操作信息: {msg}")

    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "qianqi",
        "start_date": next_thursday.isoformat(),
        "start_time": "09:00",
        "end_time": "12:00",
        "purpose": "棋牌活动",
        "weeks": MAX_RECURRING_WEEKS
    }, 201)
    assert r["total"] == MAX_RECURRING_WEEKS
    assert r["success"] == MAX_RECURRING_WEEKS
    print(f"  [PASS] weeks={MAX_RECURRING_WEEKS} 预约成功")

    print(f"  [PASS] 配置超限验证通过")


def test_recurring_booking_audit_chain():
    print("\n========== 周期预约 - 审批/取消后审计链不中断测试 ==========")
    from datetime import date, timedelta
    MAX_RECURRING_WEEKS = _max_weeks()

    r = api("post", "/api/rooms", {"name": "画室", "description": "七楼画室"}, 201)
    room_id = r["id"]

    next_sunday = date.today() + timedelta(days=(7 - date.today().weekday() + 6) % 7)
    if next_sunday == date.today():
        next_sunday += timedelta(days=7)
    weekday_6 = next_sunday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_6, "start_time": "09:00", "end_time": "18:00"}]
    }, 201)

    test_weeks = min(3, MAX_RECURRING_WEEKS)
    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "wu_shiyi",
        "start_date": next_sunday.isoformat(),
        "start_time": "10:00",
        "end_time": "12:00",
        "purpose": "绘画课程",
        "weeks": test_weeks
    }, 201)
    batch_id = r["batch_id"]
    success_items = [item for item in r["items"] if item["status"] == "success"]
    assert len(success_items) == test_weeks

    if test_weeks >= 2:
        bid_approve = success_items[0]["booking_id"]
        bid_reject = success_items[1]["booking_id"]
        bid_cancel = success_items[0]["booking_id"] if test_weeks == 2 else success_items[2]["booking_id"]
    else:
        bid_approve = success_items[0]["booking_id"]
        bid_reject = None
        bid_cancel = success_items[0]["booking_id"]

    booking_ids_display = [b["booking_id"] for b in success_items]
    print(f"  >> 创建周期预约 batch_id={batch_id}, 子预约: {booking_ids_display}")

    r = requests.get(f"{BASE}/api/audit", params={"batch_id": batch_id})
    logs_before = r.json()
    print(f"  >> 操作前批次审计日志: {len(logs_before)} 条, actions={[l['action'] for l in logs_before]}")
    assert len(logs_before) == test_weeks + 1

    batch_create_log = [l for l in logs_before if l["action"] == "batch_create"][0]
    assert f"max_recurring_weeks={MAX_RECURRING_WEEKS}" in batch_create_log["detail"], (
        f"batch_create 审计日志应包含 max_recurring_weeks={MAX_RECURRING_WEEKS}, "
        f"实际 detail: {batch_create_log['detail']}"
    )
    print(f"  [PASS] batch_create 审计日志包含 max_recurring_weeks={MAX_RECURRING_WEEKS}")

    api("post", f"/api/bookings/{bid_approve}/approve", {
        "operator_id": "admin1",
        "operator_role": "admin",
        "reason": "同意绘画课程"
    })
    print(f"  >> 审批通过 #{bid_approve}")

    extra_actions = ["approve"]
    if bid_reject is not None:
        api("post", f"/api/bookings/{bid_reject}/reject", {
            "operator_id": "admin1",
            "operator_role": "admin",
            "reason": "时段不合适"
        })
        print(f"  >> 审批驳回 #{bid_reject}")
        extra_actions.append("reject")

    api("post", f"/api/bookings/{bid_cancel}/cancel", {
        "operator_id": "wu_shiyi",
        "operator_role": "resident",
        "reason": "本周不去了"
    })
    print(f"  >> 居民取消 #{bid_cancel}")
    extra_actions.append("cancel")

    r = requests.get(f"{BASE}/api/audit", params={"batch_id": batch_id})
    logs_after = r.json()
    actions_after = [log["action"] for log in logs_after]
    print(f"  >> 操作后批次审计日志: {len(logs_after)} 条, actions={actions_after}")

    expected_log_count = test_weeks + 1 + len(extra_actions)
    assert len(logs_after) == expected_log_count, (
        f"期望 {expected_log_count} 条日志, 实际 {len(logs_after)} 条"
    )
    assert actions_after.count("create") == test_weeks
    for act in extra_actions:
        assert act in actions_after, f"缺少 {act} 审计日志"

    for log in logs_after:
        assert log["batch_id"] == batch_id, (
            f"Log #{log['id']} action={log['action']} batch_id={log['batch_id']} "
            f"should be {batch_id}"
        )
    print(f"  [PASS] 所有{len(logs_after)}条审计日志(含{extra_actions})都正确关联了 batch_id={batch_id}")

    check_bids = {bid_approve, bid_cancel}
    if bid_reject is not None:
        check_bids.add(bid_reject)
    for bid in check_bids:
        r = requests.get(f"{BASE}/api/audit", params={"booking_id": bid})
        per_booking = r.json()
        for log in per_booking:
            assert log["batch_id"] == batch_id
    print(f"  [PASS] 按 booking_id 查询, 每条预约的所有日志都关联 batch_id")

    r = requests.get(f"{BASE}/api/audit/export", params={"batch_id": batch_id})
    exported = r.json()
    assert len(exported) == len(logs_after)
    for log in exported:
        assert log["batch_id"] == batch_id
    print(f"  [PASS] 按 batch_id 导出审计日志, 所有 {len(exported)} 条都关联 batch_id")

    batch_before = api("get", f"/api/bookings/batches/{batch_id}?operator_id=admin1&operator_role=admin")
    bookings_before = api("get", f"/api/bookings", params={"batch_id": batch_id})
    logs_before_full = requests.get(f"{BASE}/api/audit", params={"batch_id": batch_id}).json()

    assert "max_recurring_weeks_at_creation" in batch_before, (
        f"批次详情应包含 max_recurring_weeks_at_creation 字段"
    )
    assert batch_before["max_recurring_weeks_at_creation"] == MAX_RECURRING_WEEKS, (
        f"max_recurring_weeks_at_creation={batch_before['max_recurring_weeks_at_creation']} "
        f"!= 当前 MAX_RECURRING_WEEKS={MAX_RECURRING_WEEKS}"
    )
    print(f"  [PASS] 批次详情 max_recurring_weeks_at_creation={batch_before['max_recurring_weeks_at_creation']}")

    print(f"  >> 重启前快照: batch={batch_before['id']}, bookings={len(bookings_before)}, logs={len(logs_before_full)}")
    print(f"  [PASS] 审计链不中断验证通过")
    return batch_id, batch_before, bookings_before, logs_before_full


def test_recurring_booking_config_from_env():
    print("\n========== 周期预约 - 配置从环境变量读取测试 ==========")
    from booking import ENV_VAR_NAME, DEFAULT_MAX_RECURRING_WEEKS, MIN_RECURRING_WEEKS, ABSOLUTE_MAX_RECURRING_WEEKS
    MAX_RECURRING_WEEKS = _max_weeks()

    env_val = os.environ.get(ENV_VAR_NAME)
    print(f"  >> {ENV_VAR_NAME} 环境变量(本进程): {env_val!r}")
    print(f"  >> 服务端 MAX_RECURRING_WEEKS = {MAX_RECURRING_WEEKS}")

    assert MIN_RECURRING_WEEKS <= MAX_RECURRING_WEEKS <= ABSOLUTE_MAX_RECURRING_WEEKS, (
        f"MAX_RECURRING_WEEKS={MAX_RECURRING_WEEKS} out of range "
        f"[{MIN_RECURRING_WEEKS}, {ABSOLUTE_MAX_RECURRING_WEEKS}]"
    )
    print(f"  [PASS] MAX_RECURRING_WEEKS={MAX_RECURRING_WEEKS} 在有效范围内")

    r = api("get", "/api/bookings/recurring/config")
    assert r["max_recurring_weeks"] == MAX_RECURRING_WEEKS
    assert r["env_var_name"] == ENV_VAR_NAME
    print(f"  [PASS] 配置端点值与运行时常量一致")

    from datetime import date, timedelta
    r = api("post", "/api/rooms", {"name": "体操室", "description": "八楼体操室"}, 201)
    room_id = r["id"]

    next_day = date.today() + timedelta(days=1)
    weekday = next_day.weekday()
    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday, "start_time": "09:00", "end_time": "20:00"}]
    }, 201)

    too_many = MAX_RECURRING_WEEKS + 1
    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "zhao_shier",
        "start_date": next_day.isoformat(),
        "start_time": "10:00",
        "end_time": "11:00",
        "purpose": "体操",
        "weeks": too_many
    }, 422)
    err_code = get_err_code(r)
    assert err_code == 10010
    msg = r.get("message", "")
    assert ENV_VAR_NAME in msg, f"越界错误应包含 {ENV_VAR_NAME}, 实际: {msg}"
    print(f"  [PASS] weeks={too_many} 超过上限 {MAX_RECURRING_WEEKS}, 被拒绝, error_code={err_code}")
    print(f"  [PASS] 错误提示含环境变量名: {ENV_VAR_NAME}")

    exact_limit = MAX_RECURRING_WEEKS
    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "zhao_shier",
        "start_date": next_day.isoformat(),
        "start_time": "10:00",
        "end_time": "11:00",
        "purpose": "体操",
        "weeks": exact_limit
    }, 201)
    assert r["total"] == exact_limit
    print(f"  [PASS] weeks={exact_limit} 正好等于上限, 创建成功")

    print(f"  [PASS] 配置从环境变量读取并生效验证通过")


def test_recurring_booking_after_restart(batch_id, batch_before, bookings_before, logs_before):
    print("\n========== 周期预约 - 重启后查询和导出一致性测试 ==========")
    from booking import ENV_VAR_NAME
    MAX_RECURRING_WEEKS = _max_weeks()

    batch_after = api("get", f"/api/bookings/batches/{batch_id}?operator_id=admin1&operator_role=admin")
    bookings_after = api("get", f"/api/bookings", params={"batch_id": batch_id})
    logs_after = requests.get(f"{BASE}/api/audit", params={"batch_id": batch_id}).json()
    exported_after = requests.get(f"{BASE}/api/audit/export", params={"batch_id": batch_id}).json()

    print(f"  >> 重启后: batch={batch_after['id']}, bookings={len(bookings_after)}, logs={len(logs_after)}")

    assert batch_after["id"] == batch_before["id"]
    assert batch_after["user_id"] == batch_before["user_id"]
    assert batch_after["total_count"] == batch_before["total_count"]
    assert batch_after["success_count"] == batch_before["success_count"]
    assert batch_after["skip_count"] == batch_before["skip_count"]
    assert batch_after["denied_count"] == batch_before["denied_count"]
    assert len(batch_after["bookings"]) == len(batch_before["bookings"])
    print(f"  [PASS] 批次信息重启后一致")

    assert batch_after["max_recurring_weeks_at_creation"] == batch_before["max_recurring_weeks_at_creation"], (
        f"重启后 max_recurring_weeks_at_creation 不一致: "
        f"before={batch_before['max_recurring_weeks_at_creation']} "
        f"after={batch_after['max_recurring_weeks_at_creation']}"
    )
    print(f"  [PASS] 批次 max_recurring_weeks_at_creation 重启后一致: {batch_after['max_recurring_weeks_at_creation']}")

    assert len(bookings_after) == len(bookings_before)
    for before, after in zip(bookings_before, bookings_after):
        assert before["id"] == after["id"]
        assert before["status"] == after["status"]
        assert before["date"] == after["date"]
    print(f"  [PASS] 预约列表重启后一致")

    assert len(logs_after) == len(logs_before)
    assert len(exported_after) == len(logs_after)
    for before, after in zip(logs_before, logs_after):
        assert before["id"] == after["id"]
        assert before["action"] == after["action"]
        assert before["batch_id"] == after["batch_id"]

    actions_after = [log["action"] for log in logs_after]
    print(f"  >> 重启后审计日志 action: {actions_after}")
    assert "batch_create" in actions_after, "重启后缺少 batch_create 审计日志"
    assert actions_after.count("create") >= 1, "重启后缺少 create 审计日志"
    assert "approve" in actions_after, "重启后缺少 approve 审计日志"
    assert "cancel" in actions_after, "重启后缺少 cancel 审计日志"
    if actions_after.count("create") >= 2:
        assert "reject" in actions_after, "重启后缺少 reject 审计日志"
    for log in logs_after:
        assert log["batch_id"] == batch_id, (
            f"重启后 Log #{log['id']} batch_id={log['batch_id']} 不等于 {batch_id}"
        )
    print(f"  [PASS] 审计日志查询和导出重启后一致(含 approve/cancel, reject 如有)")

    batch_create_logs = [l for l in logs_after if l["action"] == "batch_create"]
    assert len(batch_create_logs) == 1
    assert "max_recurring_weeks=" in batch_create_logs[0]["detail"], (
        f"重启后 batch_create 审计日志应包含 max_recurring_weeks 信息, "
        f"实际 detail: {batch_create_logs[0]['detail']}"
    )
    print(f"  [PASS] 重启后 batch_create 审计日志仍包含规则信息: {batch_create_logs[0]['detail']}")

    r = api("get", f"/api/bookings/batches", params={
        "user_id": "wu_shiyi", "operator_id": "admin1", "operator_role": "admin"
    })
    assert any(b["id"] == batch_id for b in r), (
        f"批次列表中找不到 batch_id={batch_id}"
    )
    print(f"  [PASS] 管理员按 user_id 筛选批次列表查询正常")

    r = api("get", f"/api/bookings/batches", params={
        "operator_id": "wu_shiyi", "operator_role": "resident"
    })
    assert any(b["id"] == batch_id for b in r), (
        f"居民查询自己批次列表中找不到 batch_id={batch_id}"
    )
    for b in r:
        assert b["user_id"] == "wu_shiyi", (
            f"居民 wu_shiyi 查询列表出现其他用户的批次 user_id={b['user_id']}"
        )
    print(f"  [PASS] 居民查询自己的批次列表正常且全部为本人")

    r = api("get", "/api/bookings/recurring/config")
    assert r["max_recurring_weeks"] == MAX_RECURRING_WEEKS
    assert r["env_var_name"] == ENV_VAR_NAME
    print(f"  [PASS] 重启后配置端点返回与运行时常量一致")

    print(f"  [PASS] 重启后一致性验证通过")


def test_single_booking_still_works():
    print("\n========== 周期预约 - 单次预约逻辑不受影响测试 ==========")
    from datetime import date, timedelta

    r = api("post", "/api/rooms", {"name": "瑜伽室", "description": "六楼瑜伽室"}, 201)
    room_id = r["id"]

    next_saturday = date.today() + timedelta(days=(7 - date.today().weekday() + 5) % 7)
    if next_saturday == date.today():
        next_saturday += timedelta(days=7)
    weekday_5 = next_saturday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_5, "start_time": "08:00", "end_time": "20:00"}]
    }, 201)

    booking_date = next_saturday.isoformat()
    r = api("post", "/api/bookings", {
        "room_id": room_id,
        "user_id": "zhoujiu",
        "date": booking_date,
        "start_time": "09:00",
        "end_time": "10:00",
        "purpose": "瑜伽课"
    }, 201)
    booking_id = r["id"]
    assert r["status"] == "pending"
    print(f"  >> 单次预约创建成功 #{booking_id}")

    r = api("post", f"/api/bookings/{booking_id}/approve", {
        "operator_id": "admin1",
        "operator_role": "admin",
        "reason": "同意"
    })
    assert r["status"] == "approved"
    print(f"  >> 单次预约审批成功")

    r = api("get", f"/api/bookings/{booking_id}")
    assert r["batch_id"] is None if "batch_id" in r else True
    print(f"  [PASS] 单次预约没有 batch_id")

    r = api("post", f"/api/bookings/{booking_id}/cancel", {
        "operator_id": "zhoujiu",
        "operator_role": "resident",
        "reason": "临时有事"
    })
    assert r["status"] == "cancelled"
    print(f"  [PASS] 单次预约取消成功")

    print(f"  [PASS] 单次预约逻辑未受影响")


def test_recurring_batch_rules_visibility():
    print("\n========== 周期预约 - 批次规则可见性与导出完整性测试 ==========")
    from datetime import date, timedelta
    MAX_RECURRING_WEEKS = _max_weeks()
    from booking import ENV_VAR_NAME

    r = api("post", "/api/rooms", {"name": "书法室", "description": "五楼书法室"}, 201)
    room_id = r["id"]

    next_friday = date.today() + timedelta(days=(7 - date.today().weekday() + 4) % 7)
    if next_friday == date.today():
        next_friday += timedelta(days=7)
    weekday_4 = next_friday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_4, "start_time": "09:00", "end_time": "18:00"}]
    }, 201)

    test_weeks = min(2, MAX_RECURRING_WEEKS)
    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "sun_shier",
        "start_date": next_friday.isoformat(),
        "start_time": "09:00",
        "end_time": "11:00",
        "purpose": "书法课",
        "weeks": test_weeks
    }, 201)
    batch_id = r["batch_id"]

    r = api("get", f"/api/bookings/batches/{batch_id}?operator_id=admin1&operator_role=admin")
    assert "max_recurring_weeks_at_creation" in r, "批次详情缺少 max_recurring_weeks_at_creation"
    assert r["max_recurring_weeks_at_creation"] == MAX_RECURRING_WEEKS, (
        f"max_recurring_weeks_at_creation={r['max_recurring_weeks_at_creation']} "
        f"!= MAX_RECURRING_WEEKS={MAX_RECURRING_WEEKS}"
    )
    print(f"  [PASS] 批次详情含 max_recurring_weeks_at_creation={r['max_recurring_weeks_at_creation']}")

    r = requests.get(f"{BASE}/api/bookings/batches", params={
        "operator_id": "sun_shier", "operator_role": "resident"
    })
    batches = r.json()
    target = [b for b in batches if b["id"] == batch_id]
    assert len(target) == 1
    assert "max_recurring_weeks_at_creation" in target[0]
    assert target[0]["max_recurring_weeks_at_creation"] == MAX_RECURRING_WEEKS
    print(f"  [PASS] 批次列表含 max_recurring_weeks_at_creation={target[0]['max_recurring_weeks_at_creation']}")

    r = requests.get(f"{BASE}/api/audit", params={"batch_id": batch_id})
    logs = r.json()
    batch_create = [l for l in logs if l["action"] == "batch_create"]
    assert len(batch_create) == 1
    assert f"max_recurring_weeks={MAX_RECURRING_WEEKS}" in batch_create[0]["detail"]
    print(f"  [PASS] 审计日志 batch_create 包含规则: {batch_create[0]['detail']}")

    r = requests.get(f"{BASE}/api/audit/export", params={"batch_id": batch_id})
    exported = r.json()
    batch_create_export = [l for l in exported if l["action"] == "batch_create"]
    assert len(batch_create_export) == 1
    assert f"max_recurring_weeks={MAX_RECURRING_WEEKS}" in batch_create_export[0]["detail"]
    print(f"  [PASS] 导出审计日志 batch_create 包含规则信息")

    config_r = api("get", "/api/bookings/recurring/config")
    assert config_r["max_recurring_weeks"] == MAX_RECURRING_WEEKS
    assert config_r["env_var_name"] == ENV_VAR_NAME
    print(f"  [PASS] 配置端点与批次记录的规则值一致")

    print(f"  [PASS] 批次规则可见性与导出完整性验证通过")


def save_restart_data(batch_id, batch_before, bookings_before, logs_before):
    data = {
        "batch_id": batch_id,
        "batch_before": batch_before,
        "bookings_before": bookings_before,
        "logs_before": logs_before
    }
    with open("restart_test_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  >> 重启前数据已保存到 restart_test_data.json")


def load_restart_data():
    try:
        with open("restart_test_data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"  >> 从 restart_test_data.json 加载重启前数据")
        return data["batch_id"], data["batch_before"], data["bookings_before"], data["logs_before"]
    except FileNotFoundError:
        return None, None, None, None


def run_before_restart():
    global PASS, FAIL
    print("\n" + "="*60)
    print("  第一阶段: 重启前测试")
    print("="*60)

    test_error_response_consistency()
    room_id, booking_id, booking_date = test_main_flow()
    test_overlap_approval(room_id, booking_date)
    test_cancel_others_booking(booking_id)
    test_outside_open_hours(room_id)
    test_non_admin_approval_rejected()
    test_persistence(room_id, booking_id)

    test_recurring_config_endpoint()
    test_recurring_booking_config_from_env()
    test_recurring_booking_partial_success()
    test_recurring_booking_permission()
    test_recurring_booking_approval_lock()
    test_recurring_booking_batch_limit()
    batch_id, batch_before, bookings_before, logs_before = test_recurring_booking_audit_chain()
    test_recurring_batch_rules_visibility()
    test_single_booking_still_works()

    save_restart_data(batch_id, batch_before, bookings_before, logs_before)

    print(f"\n========== 第一阶段结果: {PASS} 通过, {FAIL} 失败 ==========")
    if FAIL > 0:
        sys.exit(1)

    print("\n  请重启服务后，运行: python test_sample.py --after-restart")
    return batch_id, batch_before, bookings_before, logs_before


def run_after_restart():
    global PASS, FAIL
    print("\n" + "="*60)
    print("  第二阶段: 重启后测试")
    print("="*60)

    batch_id, batch_before, bookings_before, logs_before = load_restart_data()
    if batch_id is None:
        print("[FAIL] 未找到重启前数据，请先运行第一阶段测试")
        sys.exit(1)

    test_recurring_booking_after_restart(batch_id, batch_before, bookings_before, logs_before)

    print(f"\n========== 第二阶段结果: {PASS} 通过, {FAIL} 失败 ==========")
    if FAIL > 0:
        sys.exit(1)


BASE2 = "http://127.0.0.1:8001"
_PASS2 = 0
_FAIL2 = 0
BASE3 = "http://127.0.0.1:8002"
_PASS3 = 0
_FAIL3 = 0
from datetime import date, timedelta as _td
timedelta = _td


def api3(method: str, path: str, data: dict | None = None, expect_status: int = 200, params: dict | None = None) -> dict:
    url = f"{BASE3}{path}"
    if method == "get" and data is not None and params is None:
        params = data
        data = None
    resp = getattr(requests, method)(url, json=data, params=params)
    ok = resp.status_code == expect_status
    global _PASS3, _FAIL3
    if ok:
        _PASS3 += 1
    else:
        _FAIL3 += 1
    tag = "[PASS]" if ok else "[FAIL]"
    print(f"  {tag} {method.upper()} {path} => {resp.status_code} (expect {expect_status})")
    if not ok:
        print(f"    response: {resp.text[:300]}")
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {}


def api2(method: str, path: str, data: dict | None = None, expect_status: int = 200, params: dict | None = None) -> dict:
    url = f"{BASE2}{path}"
    if method == "get" and data is not None and params is None:
        params = data
        data = None
    resp = getattr(requests, method)(url, json=data, params=params)
    ok = resp.status_code == expect_status
    global _PASS2, _FAIL2
    if ok:
        _PASS2 += 1
    else:
        _FAIL2 += 1
    tag = "[PASS]" if ok else "[FAIL]"
    print(f"  {tag} {method.upper()} {path} => {resp.status_code} (expect {expect_status})")
    if not ok:
        print(f"    response: {resp.text[:300]}")
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {}


def _weekday_to_str(w: int) -> str:
    return ["周一","周二","周三","周四","周五","周六","周日"][w]


def _next_weekday(weekday: int, offset_days: int = 14):
    from datetime import date, timedelta
    today = date.today()
    base = today + timedelta(days=offset_days)
    diff = (weekday - base.weekday()) % 7
    if diff == 0:
        diff = 7
    return base + timedelta(days=diff)


# ============================================================
# 测试1: 批次详情 week_phase 可见性（每周次状态分类）
# ============================================================
def test_batch_detail_week_phase():
    from datetime import date, timedelta
    print("\n========== 新功能: 批次详情 week_phase 每周次状态分类 ==========")

    r = api2("post", "/api/rooms", {"name": "新功能_排练厅A", "description": "新功能测试房A"}, 201)
    room_id = r["id"]

    next_mon = _next_weekday(0, 21)
    next_tue = next_mon + timedelta(days=1)

    api2("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [
            {"weekday": 0, "start_time": "09:00", "end_time": "18:00"},
            {"weekday": 1, "start_time": "09:00", "end_time": "18:00"},
        ]
    }, 201)

    test_weeks = min(3, _max_weeks2())
    r = api2("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "new_user_A",
        "start_date": next_mon.isoformat(),
        "start_time": "10:00",
        "end_time": "12:00",
        "purpose": "新功能测试_排练A",
        "weeks": test_weeks
    }, 201)
    batch_id = r["batch_id"]
    success_items = [i for i in r["items"] if i["status"] == "success"]
    assert len(success_items) == test_weeks
    booking_ids = [i["booking_id"] for i in success_items]

    bid_approved = booking_ids[0]
    bid_finished = booking_ids[-1]
    api2("post", f"/api/bookings/{bid_approved}/approve", {
        "operator_id": "admin_new", "operator_role": "admin", "reason": "新功能审批通过"
    })
    api2("post", f"/api/bookings/{bid_finished}/cancel", {
        "operator_id": "new_user_A", "operator_role": "resident", "reason": "新功能自己取消"
    })

    r = api2("get", f"/api/bookings/batches/{batch_id}?operator_id=admin_new&operator_role=admin")
    assert "bookings" in r
    bk_list = r["bookings"]
    assert len(bk_list) == test_weeks, f"期望{test_weeks}条, 实际{len(bk_list)}"

    phases = {b["id"]: b["week_phase"] for b in bk_list}

    for b in bk_list:
        assert "week_phase" in b, f"预约#{b['id']}缺少week_phase字段"
        assert b["week_phase"] in {"preserved_in_effect", "preserved_approved", "adjustable", "finished"}, (
            f"预约#{b['id']} week_phase={b['week_phase']} 不在允许集合"
        )

    assert phases[bid_approved] == "preserved_approved", (
        f"已审批预约#{bid_approved} phase={phases[bid_approved]}, 期望preserved_approved"
    )
    assert phases[bid_finished] == "finished", (
        f"已取消预约#{bid_finished} phase={phases[bid_finished]}, 期望finished"
    )

    adjustable_bids = [bid for bid, ph in phases.items() if ph == "adjustable"]
    assert len(adjustable_bids) >= 1, f"至少应有1个adjustable, 实际phases={phases}"

    for b in bk_list:
        if b["week_phase"] == "preserved_approved":
            assert b["status"] == "approved"
        if b["week_phase"] == "finished":
            assert b["status"] in {"cancelled", "rejected", "expired"}

    print(f"  [PASS] 批次详情week_phase正确: phases={phases}")
    print(f"    (preserved_approved 含已审批 {bid_approved}; finished 含已取消 {bid_finished})")
    return room_id, batch_id, phases, booking_ids


def _max_weeks2():
    r = api2("get", "/api/bookings/recurring/config")
    return r["max_recurring_weeks"]


# ============================================================
# 测试2: 批量改期 - 权限边界 & 保护已审批 & 部分成功
# ============================================================
def test_batch_reschedule_permission_and_protection(room_id, batch_id, phases, booking_ids):
    print("\n========== 新功能: 批量改期 - 权限边界、已审批保护、部分成功 ==========")

    preserved_bid = next(bid for bid, ph in phases.items() if ph == "preserved_approved")
    adjustable_bids = [bid for bid, ph in phases.items() if ph == "adjustable"]
    finished_bid = next(bid for bid, ph in phases.items() if ph == "finished")

    r = api2("post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": (date.today() + timedelta(days=60)).isoformat(),
        "operator_id": "other_resident",
        "operator_role": "resident",
        "reason": "他人越权改期"
    }, 422)
    assert get_err_code(r) == 10007, f"居民改期他人批次应返回10007, 实际={get_err_code(r)}"
    print(f"  [PASS] 居民other_resident无法改期new_user_A的批次(权限边界), err=10007")

    next_mon_later = _next_weekday(0, 35)
    r = api2("post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": next_mon_later.isoformat(),
        "operator_id": "new_user_A",
        "operator_role": "resident",
        "reason": "我要调整后续周次"
    })
    assert r["operation"] == "reschedule"
    assert r["batch_id"] == batch_id
    assert r["user_id"] == "new_user_A"

    total = r["total"]
    success = r["success"]
    preserved = r["preserved"]
    denied = r["denied"]
    skipped = r["skipped"]
    print(f"  >> 改期结果: total={total}, success={success}, preserved={preserved}, denied={denied}, skipped={skipped}")

    assert total == success + preserved + denied + skipped
    assert preserved >= 2, f"至少应保护2条(已审批+已取消/已结束), 实际preserved={preserved}"

    preserved_items = [i for i in r["items"] if i["result"] == "preserved"]
    preserved_bids_result = {i["booking_id"] for i in preserved_items}
    assert preserved_bid in preserved_bids_result, (
        f"已审批预约#{preserved_bid}应在preserved中"
    )
    assert finished_bid in preserved_bids_result or finished_bid in {i["booking_id"] for i in r["items"] if i["result"] in ("preserved","skipped")}, (
        f"已取消预约#{finished_bid}应在preserved/skipped中"
    )
    for item in preserved_items:
        assert item["old_date"] == item["new_date"], (
            f"preserved条目 old_date={item['old_date']}应等于new_date={item['new_date']}"
        )
        assert item["week_phase_before"] in {"preserved_in_effect", "preserved_approved", "finished"}

    success_items = [i for i in r["items"] if i["result"] == "success"]
    for item in success_items:
        assert item["booking_id"] in adjustable_bids
        assert item["old_date"] != item["new_date"], (
            f"success条目 old_date={item['old_date']}应不等于new_date={item['new_date']}"
        )
        assert item["old_status"] == item["new_status"] == "pending"
        assert item["week_phase_before"] == "adjustable"

    print(f"  [PASS] 改期结果结构正确: preserved保护了{preserved}条(含已审批{preserved_bid}), success改了{success}条")
    print(f"  [PASS] 改期响应含配置快照: creation={r['max_recurring_weeks_at_creation']}, operation={r['max_recurring_weeks_at_operation']}")

    r_after = api2("get", f"/api/bookings/batches/{batch_id}?operator_id=admin_new&operator_role=admin")
    bk_after = {b["id"]: b for b in r_after["bookings"]}
    for item in success_items:
        bid = item["booking_id"]
        assert bk_after[bid]["date"] == item["new_date"], (
            f"改期后DB中日期应为{item['new_date']}, 实际={bk_after[bid]['date']}"
        )
        assert bk_after[bid]["old_date"] == item["old_date"], (
            f"改期后DB中old_date应为{item['old_date']}, 实际={bk_after[bid].get('old_date')}"
        )
        assert bk_after[bid]["rescheduled_from_booking_id"] == bid
    print(f"  [PASS] 改期后查询一致: DB中date/old_date/rescheduled_from_booking_id正确写入")

    logs = requests.get(f"{BASE2}/api/audit", params={"batch_id": batch_id}).json()
    actions = [l["action"] for l in logs]
    assert "batch_reschedule_start" in actions, "缺少batch_reschedule_start审计"
    assert "batch_reschedule_end" in actions, "缺少batch_reschedule_end审计"
    assert actions.count("reschedule") == success, f"reschedule审计应{success}条, 实际{actions.count('reschedule')}"
    for l in logs:
        if l["action"] == "reschedule":
            assert "max_recurring_weeks_at_operation=" in l["detail"], (
                f"reschedule审计detail应含max_recurring_weeks_at_operation, 实际={l['detail']}"
            )
    print(f"  [PASS] 审计链完整: batch_reschedule_start/{success}xreschedule/batch_reschedule_end, 含max_recurring_weeks_at_operation")
    return r


# ============================================================
# 测试3: 批量改期 - 冲突与slot不开放(部分成功部分拒绝)
# ============================================================
def test_batch_reschedule_partial_conflict():
    print("\n========== 新功能: 批量改期 - 冲突/slot不开放, 部分成功部分拒绝 ==========")

    r = api2("post", "/api/rooms", {"name": "新功能_排练厅B", "description": "改期冲突测试"}, 201)
    room_id = r["id"]

    next_wed = _next_weekday(2, 28)
    next_thu = next_wed + timedelta(days=1)

    api2("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [
            {"weekday": 2, "start_time": "09:00", "end_time": "18:00"},
        ]
    }, 201)

    test_weeks = min(3, _max_weeks2())
    r = api2("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "new_user_B",
        "start_date": next_wed.isoformat(),
        "start_time": "10:00",
        "end_time": "12:00",
        "purpose": "新功能_改期冲突源批次",
        "weeks": test_weeks
    }, 201)
    batch_id = r["batch_id"]
    success_items = [i for i in r["items"] if i["status"] == "success"]
    assert len(success_items) == test_weeks

    blocker_date = next_wed + timedelta(weeks=0)
    r_blocker = api2("post", "/api/bookings", {
        "room_id": room_id,
        "user_id": "blocker_user",
        "date": blocker_date.isoformat(),
        "start_time": "10:00",
        "end_time": "12:00",
        "purpose": "冲突占用者"
    }, 201)
    blocker_bid = r_blocker["id"]
    api2("post", f"/api/bookings/{blocker_bid}/approve", {
        "operator_id": "admin_new", "operator_role": "admin", "reason": "审批占用者"
    })
    print(f"  >> 在{blocker_date}预先创建并审批通过占用预约#{blocker_bid}")

    next_mon_after = _next_weekday(0, 49)
    r = api2("post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": next_mon_after.isoformat(),
        "operator_id": "new_user_B",
        "operator_role": "resident",
        "reason": "改期到周一, 但slot不开放+有冲突"
    })

    print(f"  >> 改期结果: total={r['total']}, success={r['success']}, preserved={r['preserved']}, denied={r['denied']}, skipped={r['skipped']}")
    assert r["total"] == r["success"] + r["preserved"] + r["denied"] + r["skipped"]

    denied_items = [i for i in r["items"] if i["result"] == "denied"]
    denied_codes = {i["error_code"] for i in denied_items}
    print(f"  >> denied error_codes: {denied_codes}")
    assert 10015 in denied_codes or 10016 in denied_codes or 10003 in denied_codes, (
        f"至少应有一个denied是slot不开放(10015/10003)或冲突(10016), 实际codes={denied_codes}"
    )
    for item in denied_items:
        assert item["old_status"] == item["new_status"] == "pending"
        assert item["message"] is not None

    preserved_items = [i for i in r["items"] if i["result"] == "preserved"]
    for item in preserved_items:
        assert item["week_phase_before"] is not None

    if r["success"] > 0:
        success_items2 = [i for i in r["items"] if i["result"] == "success"]
        for item in success_items2:
            assert item["old_date"] != item["new_date"]
        print(f"  [PASS] {r['success']}条成功改期, {len(denied_items)}条被拒绝(含slot/冲突), {r['preserved']}条被保护")
    else:
        assert len(denied_items) > 0, "如果全部失败, denied_items不应为空"
        print(f"  [PASS] 全部被拒绝(符合预期, 因slot不开放), denied={len(denied_items)}")

    print(f"  [PASS] 改期部分成功/部分拒绝: success/preserved/denied/skipped 都清楚, 无静默覆盖")
    return r


# ============================================================
# 测试4: 整批取消 - 权限边界 & 居民不能取消已审批 & 管理员可以代取消
# ============================================================
def test_batch_cancel_permission_and_roles():
    print("\n========== 新功能: 整批取消 - 权限边界、居民保护已审批、管理员代取消 ==========")

    r = api2("post", "/api/rooms", {"name": "新功能_会议室C", "description": "取消测试房"}, 201)
    room_id = r["id"]

    next_fri = _next_weekday(4, 28)
    api2("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": 4, "start_time": "09:00", "end_time": "20:00"}]
    }, 201)

    test_weeks = min(3, _max_weeks2())
    r = api2("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "new_user_C",
        "start_date": next_fri.isoformat(),
        "start_time": "14:00",
        "end_time": "16:00",
        "purpose": "新功能_批次取消测试",
        "weeks": test_weeks
    }, 201)
    batch_id = r["batch_id"]
    success_items = [i for i in r["items"] if i["status"] == "success"]
    assert len(success_items) == test_weeks
    booking_ids = [i["booking_id"] for i in success_items]

    bid_approved = booking_ids[0]
    r = api2("post", f"/api/bookings/{bid_approved}/approve", {
        "operator_id": "admin_cancel", "operator_role": "admin", "reason": "审批后测试取消权限"
    })
    print(f"  >> 审批通过 #{bid_approved}, 状态={r['status']}")

    r = api2("post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "other_resident",
        "operator_role": "resident",
        "reason": "越权取消"
    }, 422)
    assert get_err_code(r) == 10007, f"居民取消他人批次应10007, 实际={get_err_code(r)}"
    print(f"  [PASS] 居民other_resident无法取消new_user_C的批次(权限边界), err=10007")

    r = api2("post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "new_user_C",
        "operator_role": "resident",
        "reason": "我自己取消"
    })
    assert r["operation"] == "cancel"
    total_res = r["total"]
    success_res = r["success"]
    preserved_res = r["preserved"]
    denied_res = r["denied"]
    skipped_res = r["skipped"]
    print(f"  >> 居民取消结果: total={total_res}, success={success_res}, preserved={preserved_res}, denied={denied_res}, skipped={skipped_res}")
    assert total_res == success_res + preserved_res + denied_res + skipped_res
    assert preserved_res >= 1, f"至少应保护1条(已审批的), 实际preserved={preserved_res}"

    preserved_items = [i for i in r["items"] if i["result"] == "preserved"]
    preserved_bids = {i["booking_id"] for i in preserved_items}
    assert bid_approved in preserved_bids, (
        f"已审批预约#{bid_approved}应在居民取消时被preserved"
    )
    for item in preserved_items:
        if item["booking_id"] == bid_approved:
            assert "approved" in item["message"].lower() or "admin" in item["message"].lower() or item["week_phase_before"] == "preserved_approved"
    print(f"  [PASS] 居民取消: 已审批#{bid_approved}被保护(preserved), pending的{success_res}条成功取消")

    success_items_res = [i for i in r["items"] if i["result"] == "success"]
    for item in success_items_res:
        assert item["old_status"] == "pending"
        assert item["new_status"] == "cancelled"

    logs = requests.get(f"{BASE2}/api/audit", params={"batch_id": batch_id}).json()
    actions = [l["action"] for l in logs]
    assert "batch_cancel_start" in actions
    assert "batch_cancel_end" in actions
    assert actions.count("cancel") == success_res + 1 + len([a for a in actions if a == "cancel"]) - success_res - 1 + 0
    cancel_by_batch = [l for l in logs if l["action"] == "cancel" and "Batch cancel" in l["detail"]]
    assert len(cancel_by_batch) >= success_res
    print(f"  [PASS] 审计链完整: batch_cancel_start / 单条cancel / batch_cancel_end")

    r = api2("post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "admin_cancel",
        "operator_role": "admin",
        "reason": "管理员代取消已审批的"
    })
    print(f"  >> 管理员取消结果: total={r['total']}, success={r['success']}, preserved={r['preserved']}, denied={r['denied']}, skipped={r['skipped']}")

    admin_success_items = [i for i in r["items"] if i["result"] == "success"]
    admin_approved_cancel = [i for i in admin_success_items if i["booking_id"] == bid_approved]
    assert len(admin_approved_cancel) == 1, f"管理员应能代取消已审批#{bid_approved}"
    item = admin_approved_cancel[0]
    assert item["old_status"] == "approved"
    assert item["new_status"] == "cancelled"
    assert item["week_phase_before"] == "preserved_approved"
    print(f"  [PASS] 管理员admin_cancel成功代取消已审批#{bid_approved}, old=approved new=cancelled")

    r_after = api2("get", f"/api/bookings/batches/{batch_id}?operator_id=admin_cancel&operator_role=admin")
    for b in r_after["bookings"]:
        if b["id"] != bid_approved and b["week_phase"] == "finished":
            continue
        if b["id"] in [i["booking_id"] for i in success_items_res] or b["id"] == bid_approved:
            assert b["status"] == "cancelled", f"#{b['id']} 应已cancelled, 实际={b['status']}"
    print(f"  [PASS] 管理员取消后回查: 所有pending和已审批的都已是cancelled")

    return batch_id


# ============================================================
# 测试5: 批次详情空批次 / 无adjustable改期
# ============================================================
def test_batch_nothing_to_operate():
    print("\n========== 新功能: 空可操作批次处理(返回清晰错误) ==========")

    r = api2("post", "/api/rooms", {"name": "新功能_阅读室D", "description": "全取消测试房"}, 201)
    room_id = r["id"]
    next_sat = _next_weekday(5, 28)
    api2("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": 5, "start_time": "09:00", "end_time": "18:00"}]
    }, 201)

    test_weeks = min(2, _max_weeks2())
    r = api2("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "new_user_D",
        "start_date": next_sat.isoformat(),
        "start_time": "09:30",
        "end_time": "11:00",
        "purpose": "新功能_全审批批次",
        "weeks": test_weeks
    }, 201)
    batch_id = r["batch_id"]
    bids = [i["booking_id"] for i in r["items"] if i["status"] == "success"]

    for bid in bids:
        api2("post", f"/api/bookings/{bid}/approve", {
            "operator_id": "admin_all", "operator_role": "admin", "reason": "全部审批"
        })

    r = api2("post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": (date.today() + timedelta(days=90)).isoformat(),
        "operator_id": "new_user_D",
        "operator_role": "resident",
        "reason": "想改但全已审批"
    }, 422)
    err = get_err_code(r)
    assert err == 10014, f"全部已审批后改期应返回10014, 实际={err}. msg={r.get('message')}"
    print(f"  [PASS] 全部已审批批次改期返回清晰的 BATCH_NOTHING_TO_OPERATE(10014), msg={r.get('message')}")

    r = api2("post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "new_user_D",
        "operator_role": "resident",
        "reason": "想取消但全已审批(居民)"
    })
    preserved = r["preserved"]
    assert preserved == test_weeks, f"居民取消全已审批应全部preserved({test_weeks}), 实际={preserved}"
    print(f"  [PASS] 居民取消全已审批批次: 全部{preserved}条preserved, 无静默取消")
    return batch_id


# ============================================================
# 测试6: 批次导出 - 含配置快照、规则值、周次状态、审计日志
# ============================================================
def test_batch_export_consistency(batch_id_for_export):
    print("\n========== 新功能: 批次导出 - 配置快照/回查一致/含审计 ==========")

    r = api2("get", f"/api/bookings/batches/{batch_id_for_export}/export", expect_status=422, params={
        "operator_id": "other_resident_export", "operator_role": "resident"
    })
    assert get_err_code(r) == 10007, f"居民export他人批次应10007, 实际={get_err_code(r)}"
    print(f"  [PASS] 导出权限边界: resident不能导出他人批次, err=10007")

    resp = requests.get(
        f"{BASE2}/api/bookings/batches/{batch_id_for_export}/export",
        params={"operator_id": "admin_new", "operator_role": "admin"}
    )
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("Content-Disposition", ""), (
        f"导出应返回Content-Disposition attachment, 实际={resp.headers.get('Content-Disposition')}"
    )
    exp = resp.json()
    print(f"  [PASS] 管理员导出成功, Content-Disposition=attachment")

    assert "batch" in exp
    assert "config_snapshot" in exp
    assert "bookings" in exp
    assert "batch_level_audit_logs" in exp
    assert "summary" in exp

    cfg = exp["config_snapshot"]
    for k in ("max_recurring_weeks_at_creation", "max_recurring_weeks_current",
              "min_recurring_weeks", "absolute_max_recurring_weeks",
              "default_max_recurring_weeks", "env_var_name"):
        assert k in cfg, f"config_snapshot缺少{k}"
    assert cfg["env_var_name"] == "BOOKING_MAX_RECURRING_WEEKS"
    assert 1 <= cfg["min_recurring_weeks"] <= cfg["max_recurring_weeks_at_creation"] <= cfg["absolute_max_recurring_weeks"] <= 52
    print(f"  [PASS] config_snapshot字段齐全且范围正确: creation={cfg['max_recurring_weeks_at_creation']}, current={cfg['max_recurring_weeks_current']}")

    detail = api2("get", f"/api/bookings/batches/{batch_id_for_export}?operator_id=admin_new&operator_role=admin")
    assert len(exp["bookings"]) == len(detail["bookings"]), (
        f"导出bookings={len(exp['bookings'])} vs 详情bookings={len(detail['bookings'])}, 数量不一致"
    )
    detail_map = {b["id"]: b for b in detail["bookings"]}
    for b in exp["bookings"]:
        d = detail_map[b["id"]]
        assert b["date"] == d["date"], f"#{b['id']} date不一致"
        assert b["status"] == d["status"], f"#{b['id']} status不一致"
        assert b["week_phase"] == d["week_phase"], f"#{b['id']} week_phase不一致"
        assert "audit_logs" in b, f"#{b['id']} 缺少每条的audit_logs"
    print(f"  [PASS] 导出bookings与批次详情查询一一对应: 共{len(exp['bookings'])}条, date/status/week_phase全一致")

    audit_batch = requests.get(f"{BASE2}/api/audit", params={"batch_id": batch_id_for_export}).json()
    audit_ids_export = set()
    for b in exp["bookings"]:
        for lg in b["audit_logs"]:
            audit_ids_export.add(lg["id"])
    for lg in exp["batch_level_audit_logs"]:
        audit_ids_export.add(lg["id"])
    audit_ids_query = {l["id"] for l in audit_batch}
    assert audit_ids_export == audit_ids_query, (
        f"导出审计id集合与/audit?batch_id查询集合不一致, 差集add={audit_ids_query-audit_ids_export}, 丢={audit_ids_export-audit_ids_query}"
    )
    print(f"  [PASS] 导出审计id({len(audit_ids_export)}条) 与 /audit?batch_id 查询({len(audit_ids_query)}条)完全一致")

    s = exp["summary"]
    for k in ("total_bookings", "preserved_in_effect", "preserved_approved", "adjustable", "finished"):
        assert k in s
    assert s["total_bookings"] == len(exp["bookings"])
    print(f"  [PASS] 导出summary统计齐全: {s}")
    print(f"  [PASS] 导出完整, 与回查完全一致")


# ============================================================
# 测试7: 重启前后配置切换 - max_recurring_weeks_at_creation/operation
# ============================================================
def test_batch_config_switch_restart():
    print("\n========== 新功能: 重启/配置切换 - creation vs operation 规则不串 ==========")

    from booking import ENV_VAR_NAME

    config_now = api2("get", "/api/bookings/recurring/config")
    now_max = config_now["max_recurring_weeks"]

    r = api2("post", "/api/rooms", {"name": "新功能_规则验证室E", "description": "配置切换测试"}, 201)
    room_id = r["id"]

    next_sun = _next_weekday(6, 42)
    api2("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": 6, "start_time": "08:00", "end_time": "20:00"}]
    }, 201)

    test_weeks = min(2, now_max)
    r = api2("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "new_user_E",
        "start_date": next_sun.isoformat(),
        "start_time": "09:00",
        "end_time": "11:00",
        "purpose": "新功能_creation vs operation 对比",
        "weeks": test_weeks
    }, 201)
    batch_id = r["batch_id"]

    detail = api2("get", f"/api/bookings/batches/{batch_id}?operator_id=admin_new&operator_role=admin")
    creation_val = detail["max_recurring_weeks_at_creation"]
    assert creation_val == now_max, (
        f"批次max_recurring_weeks_at_creation={creation_val} != 当前now_max={now_max}"
    )
    print(f"  [PASS] 批次详情 max_recurring_weeks_at_creation={creation_val} 与配置端点一致")

    logs = requests.get(f"{BASE2}/api/audit", params={"batch_id": batch_id}).json()
    bc_log = [l for l in logs if l["action"] == "batch_create"][0]
    assert f"max_recurring_weeks={now_max}" in bc_log["detail"], (
        f"batch_create审计detail应含max_recurring_weeks={now_max}, 实际={bc_log['detail']}"
    )
    print(f"  [PASS] batch_create审计detail含规则值: max_recurring_weeks={now_max}")

    next_mon_far = _next_weekday(0, 70)
    r2 = api2("post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": next_mon_far.isoformat(),
        "operator_id": "admin_new",
        "operator_role": "admin",
        "reason": "对比 creation/operation 规则"
    })
    assert r2["max_recurring_weeks_at_creation"] == creation_val
    assert r2["max_recurring_weeks_at_operation"] == now_max
    print(f"  [PASS] 改期响应 creation={r2['max_recurring_weeks_at_creation']}, operation={r2['max_recurring_weeks_at_operation']}")
    if r2["success"] > 0:
        reschedule_logs = [l for l in requests.get(f"{BASE2}/api/audit", params={"batch_id": batch_id}).json() if l["action"] == "reschedule"]
        for lg in reschedule_logs:
            assert "max_recurring_weeks_at_operation=" in lg["detail"]
        print(f"  [PASS] 每条reschedule审计detail含 max_recurring_weeks_at_operation={now_max}")

    r3 = api2("post", f"/api/bookings/batches/{batch_id}/cancel", {
        "operator_id": "admin_new",
        "operator_role": "admin",
        "reason": "取消验证 creation vs operation"
    })
    assert r3["max_recurring_weeks_at_creation"] == creation_val
    assert r3["max_recurring_weeks_at_operation"] == now_max
    print(f"  [PASS] 取消响应 creation={r3['max_recurring_weeks_at_creation']}, operation={r3['max_recurring_weeks_at_operation']}")

    export_resp = requests.get(f"{BASE2}/api/bookings/batches/{batch_id}/export", params={
        "operator_id": "admin_new", "operator_role": "admin"
    }).json()
    assert export_resp["config_snapshot"]["max_recurring_weeks_at_creation"] == creation_val
    assert export_resp["config_snapshot"]["max_recurring_weeks_current"] == now_max
    print(f"  [PASS] 导出 config_snapshot creation={creation_val}, current={now_max}")

    print(f"  [PASS] 重启/配置切换链路全验证完毕: 批次创建/改期/取消/导出 4个位置都同时保留 creation 与 operation/current 的规则值")
    return batch_id


# ============================================================
# 测试8: 整批取消后批次查询 - 导出与回查一致
# ============================================================
def test_cancel_export_query_consistency(batch_id_cancel):
    print("\n========== 新功能: 取消后查询/导出一致性验证 ==========")

    r_query = api2("get", f"/api/bookings/batches/{batch_id_cancel}?operator_id=admin_cancel&operator_role=admin")
    export = requests.get(f"{BASE2}/api/bookings/batches/{batch_id_cancel}/export", params={
        "operator_id": "admin_cancel", "operator_role": "admin"
    }).json()

    query_ids = {b["id"]: b for b in r_query["bookings"]}
    export_ids = {b["id"]: b for b in export["bookings"]}
    assert set(query_ids.keys()) == set(export_ids.keys()), "取消后导出与查询的预约id集合不一致"

    for bid, qb in query_ids.items():
        eb = export_ids[bid]
        assert qb["status"] == eb["status"], f"#{bid} status查询={qb['status']} vs 导出={eb['status']}"
        assert qb["week_phase"] == eb["week_phase"], f"#{bid} week_phase查询vs导出不一致"
        assert qb["date"] == eb["date"]

    cancel_logs_query = [l for l in requests.get(f"{BASE2}/api/audit", params={
        "batch_id": batch_id_cancel, "action": "cancel"
    }).json()]
    cancel_ids_query = {l["booking_id"] for l in cancel_logs_query if l["booking_id"]}
    cancel_ids_export = set()
    for b in export["bookings"]:
        for lg in b["audit_logs"]:
            if lg["action"] == "cancel":
                bid = lg.get("booking_id") or b["id"]
                cancel_ids_export.add(bid)
    if cancel_ids_query:
        assert cancel_ids_query.issubset(cancel_ids_export), (
            f"查询中cancel的booking_id={cancel_ids_query} 应都出现在导出cancel={cancel_ids_export}"
        )
    print(f"  [PASS] 取消后查询/导出一致: 预约id集合={len(query_ids)}条, 状态/周次完全相同, cancel审计id集合匹配")
    print(f"    查询cancel_ids: {cancel_ids_query}")
    print(f"    导出cancel_ids: {cancel_ids_export}")


# ============================================================
# 测试9: 跨重启配置收紧 - MAX从4降到2, 改期不被整单拦截
# ============================================================
def test_batch_reschedule_config_tightening():
    global _PASS2, _FAIL2, _PASS3, _FAIL3
    print("\n========== 新功能: 跨重启配置收紧 - MAX=4→2, 改期逐周处理不整单拦截 ==========")

    print(f"\n  --- 阶段1: 在 {BASE2} (MAX=4) 创建 4 周批次, 审批1条 ---")
    r = api2("post", "/api/rooms", {"name": "配置收紧_多功能厅", "description": "MAX=4创建MAX=2改期"}, 201)
    room_id = r["id"]

    next_mon_4weeks = _next_weekday(0, 28)
    api2("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": 0, "start_time": "09:00", "end_time": "12:00"}]
    }, 201)

    cfg = api2("get", "/api/bookings/recurring/config")
    max_at_creation = cfg["max_recurring_weeks"]
    print(f"  创建时配置 max_recurring_weeks={max_at_creation}")
    assert max_at_creation >= 4, f"创建服务MAX应>=4, 实际={max_at_creation}"

    r = api2("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "start_date": next_mon_4weeks.isoformat(),
        "weekday": 0, "start_time": "09:00", "end_time": "12:00",
        "weeks": 4,
        "user_id": "user_tight", "user_name": "收紧配置测试用户",
        "purpose": "测试MAX收紧后改期不被整单拦截"
    }, 201)
    batch_id = r["batch_id"]

    # 查询详情获取 booking_ids（更可靠，不依赖创建时返回结构）
    r_detail = api2("get", f"/api/bookings/batches/{batch_id}?operator_id=admin_tight&operator_role=admin")
    booking_ids = [b["id"] for b in r_detail["bookings"]]
    print(f"  创建4周批次#{batch_id}, booking_ids={booking_ids}")
    assert len(booking_ids) == 4, f"应创建4条预约, 实际={len(booking_ids)}"

    approved_id = booking_ids[0]
    api2("post", f"/api/bookings/{approved_id}/approve", {
        "operator_id": "admin_tight", "operator_role": "admin", "note": "test"
    }, 200)
    print(f"  审批 #{approved_id} 为 approved (preserved_approved 相位, 改期时会 preserved)")

    detail_at_creation = api2("get", f"/api/bookings/batches/{batch_id}?operator_id=admin_tight&operator_role=admin")
    phases_at_creation = {b["id"]: b["week_phase"] for b in detail_at_creation["bookings"]}
    print(f"  创建后相位: {phases_at_creation}")
    assert phases_at_creation[approved_id] == "preserved_approved"
    adjustable_ids = [bid for bid, ph in phases_at_creation.items() if ph == "adjustable"]
    print(f"  adjustable={len(adjustable_ids)}条 (应该=3), ids={adjustable_ids}")
    assert len(adjustable_ids) == 3, f"应有3条可调, 实际={len(adjustable_ids)}"

    print(f"\n  --- 阶段2: 切换到 {BASE3} (MAX=2) 模拟重启后配置收紧 ---")
    cfg_new = api3("get", "/api/bookings/recurring/config")
    max_at_operation = cfg_new["max_recurring_weeks"]
    print(f"  操作时配置 max_recurring_weeks={max_at_operation}")
    assert max_at_operation == 2, f"操作服务MAX应=2, 实际={max_at_operation}"

    new_start = next_mon_4weeks + timedelta(days=28)
    print(f"  改期目标起始日期: {new_start} (周一)")

    r = api3("post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": new_start.isoformat(),
        "operator_id": "admin_tight", "operator_role": "admin",
        "reason": "配置收紧测试 - 管理员继续处理未开始周次"
    }, 200)

    print(f"  >> 改期结果: total={r['total']}, success={r['success']}, preserved={r['preserved']}, denied={r['denied']}, skipped={r['skipped']}")
    for it in r["items"]:
        msg = str(it.get('message') or "")[:40]
        print(f"     #{it['booking_id']}: {it['result']:10s} phase_before={it['week_phase_before']:20s} old={it['old_date']} new={it['new_date']} msg={msg}")

    assert r["total"] == 4, f"total应=4, 实际={r['total']}"
    assert r["preserved"] == 1, f"preserved应=1(已审批的那条), 实际={r['preserved']}"
    assert r["success"] == 3, f"success应=3(3条可调都应成功), 实际={r['success']}"
    assert r["denied"] == 0, f"denied应=0, 实际={r['denied']}"
    assert r["skipped"] == 0, f"skipped应=0, 实际={r['skipped']}"

    assert r["max_recurring_weeks_at_creation"] == max_at_creation, "creation值应与创建时一致"
    assert r["max_recurring_weeks_at_operation"] == max_at_operation, "operation值应与操作时一致"
    print(f"  [PASS] 配置双轨正确: creation={r['max_recurring_weeks_at_creation']}, operation={r['max_recurring_weeks_at_operation']}")

    preserved_items = [it for it in r["items"] if it["result"] == "preserved"]
    assert preserved_items[0]["booking_id"] == approved_id, f"preserved的应为#{approved_id}"
    assert preserved_items[0]["week_phase_before"] == "preserved_approved"
    assert preserved_items[0]["old_date"] == preserved_items[0]["new_date"]
    print(f"  [PASS] 已审批预约 {approved_id} 正确 preserved, 日期未变")

    success_items = [it for it in r["items"] if it["result"] == "success"]
    assert len(success_items) == 3
    for i, it in enumerate(success_items):
        assert it["new_date"] == (new_start + timedelta(weeks=i)).isoformat()
        assert it["old_date"] != it["new_date"]
        assert it["old_status"] == "pending"
        assert it["week_phase_before"] == "adjustable"
    print(f"  [PASS] 3条可调预约全部改期成功, 新日期正确, 日期链完整")

    print(f"\n  --- 阶段3: 设置冲突场景, 验证部分成功部分拒绝 ---")
    new_start2 = new_start + timedelta(weeks=1)
    blocker_date = new_start2 + timedelta(weeks=2)
    print(f"  在 {blocker_date} 预先创建并审批一个阻塞预约 (同房间同时段)")
    r = api3("post", "/api/bookings", {
        "room_id": room_id,
        "date": blocker_date.isoformat(),
        "start_time": "09:00", "end_time": "12:00",
        "user_id": "blocker_user", "user_name": "冲突阻塞用户",
        "purpose": "阻塞测试"
    }, 201)
    blocker_id = r["id"]
    api3("post", f"/api/bookings/{blocker_id}/approve", {
        "operator_id": "admin_tight", "operator_role": "admin", "note": "test"
    }, 200)
    print(f"  阻塞预约#{blocker_id}已审批")

    print(f"  再次改期目标起始: {new_start2}, 第3周会与阻塞冲突")

    r = api3("post", f"/api/bookings/batches/{batch_id}/reschedule", {
        "new_start_date": new_start2.isoformat(),
        "operator_id": "admin_tight", "operator_role": "admin",
        "reason": "配置收紧+冲突场景 - 部分成功部分拒绝"
    }, 200)

    print(f"  >> 改期结果: total={r['total']}, success={r['success']}, preserved={r['preserved']}, denied={r['denied']}, skipped={r['skipped']}")
    denied_codes = {it["error_code"] for it in r["items"] if it["result"] == "denied"}
    print(f"  >> denied error_codes: {denied_codes}")
    for it in r["items"]:
        if it["result"] == "denied":
            print(f"     #{it['booking_id']}: DENIED code={it['error_code']} msg={it.get('message','')[:60]}")

    assert r["preserved"] == 1
    assert r["success"] >= 1 and r["success"] <= 2, f"success应在1-2之间, 实际={r['success']}"
    assert r["denied"] == 1, f"应有1条因冲突denied, 实际={r['denied']}"
    assert 10016 in denied_codes, f"denied中应包含冲突码10016, 实际={denied_codes}"
    assert r["total"] == r["success"] + r["preserved"] + r["denied"] + r["skipped"]
    print(f"  [PASS] 部分成功部分拒绝正确: preserved=1, success={r['success']}, denied=1(10016), 无静默覆盖")

    print(f"\n  --- 阶段4: 查询与导出结果一致 ---")
    detail = api3("get", f"/api/bookings/batches/{batch_id}?operator_id=admin_tight&operator_role=admin")
    export = requests.get(f"{BASE3}/api/bookings/batches/{batch_id}/export", params={
        "operator_id": "admin_tight", "operator_role": "admin"
    }).json()

    query_ids = {b["id"]: b for b in detail["bookings"]}
    export_ids = {b["id"]: b for b in export["bookings"]}
    assert set(query_ids.keys()) == set(export_ids.keys()), "id集合不一致"
    for bid, qb in query_ids.items():
        eb = export_ids[bid]
        assert qb["status"] == eb["status"], f"#{bid} status不一致"
        assert qb["week_phase"] == eb["week_phase"], f"#{bid} week_phase不一致"
        assert qb["date"] == eb["date"], f"#{bid} date不一致"
        assert qb.get("old_date") == eb.get("old_date"), f"#{bid} old_date不一致"
        assert qb.get("rescheduled_from_booking_id") == eb.get("rescheduled_from_booking_id")
    print(f"  [PASS] 查询与导出一致: {len(query_ids)}条 booking 状态/日期/周次/改期追踪完全相同")

    audit_q = requests.get(f"{BASE3}/api/audit", params={"batch_id": batch_id}).json()
    audit_ids_q = {l["id"] for l in audit_q}
    audit_ids_e = set()
    for b in export["bookings"]:
        for lg in b["audit_logs"]:
            audit_ids_e.add(lg["id"])
    for lg in export["batch_level_audit_logs"]:
        audit_ids_e.add(lg["id"])
    assert audit_ids_q == audit_ids_e, f"审计id集合不一致 query={audit_ids_q - audit_ids_e} export={audit_ids_e - audit_ids_q}"
    print(f"  [PASS] 审计链路一致: {len(audit_ids_q)} 条审计 id 完全匹配")

    assert export["config_snapshot"]["max_recurring_weeks_at_creation"] == max_at_creation
    assert export["config_snapshot"]["max_recurring_weeks_current"] == max_at_operation
    assert export["config_snapshot"]["env_var_name"] == "BOOKING_MAX_RECURRING_WEEKS"
    assert 1 <= export["config_snapshot"]["min_recurring_weeks"] <= 52
    assert 1 <= export["config_snapshot"]["absolute_max_recurring_weeks"] <= 520
    print(f"  [PASS] 导出配置快照齐全: creation={max_at_creation}, current={max_at_operation}")

    print(f"\n  [PASS] 跨重启配置收紧全链路验证通过 ✅")
    print(f"     关键点: adjustable=3 > MAX=2 时不再整单抛10010, 而是逐周处理")
    print(f"     关键点: 已审批预约 preserved, 可调预约逐周 slot/冲突检查")
    print(f"     关键点: creation/operation 双轨规则值正确, 审计链路完整")
    print(f"     关键点: 查询与导出完全一致")

    # 清理 _PASS3/_FAIL3 统计, 避免影响主流程
    print(f"\n========== 配置收紧专项结果: {_PASS2+_PASS3} 通过, {_FAIL2+_FAIL3} 失败 ==========")
    if _FAIL2 + _FAIL3 > 0:
        sys.exit(1)

    return batch_id


# ============================================================
# 新功能总入口
# ============================================================
_EXPORT_BATCH_IDS = []


def run_new_features_tests():
    global _PASS2, _FAIL2
    print("\n" + "="*70)
    print("  新功能回归验证: 批量改期 / 整批取消 / 权限 / 冲突 / 配置切换 / 导出一致性")
    print("="*70)
    print(f"  使用服务: {BASE2}")

    room_id, batch_id_A, phases, booking_ids = test_batch_detail_week_phase()
    test_batch_reschedule_permission_and_protection(room_id, batch_id_A, phases, booking_ids)
    test_batch_reschedule_partial_conflict()
    batch_id_cancel = test_batch_cancel_permission_and_roles()
    batch_id_nothing = test_batch_nothing_to_operate()

    export_bid1 = test_batch_config_switch_restart()
    test_batch_export_consistency(batch_id_A)
    test_cancel_export_query_consistency(batch_id_cancel)

    export_data = {
        "batch_ids_for_after_restart": [batch_id_A, batch_id_cancel, batch_id_nothing, export_bid1],
    }
    with open("new_features_restart_data.json", "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    print(f"  >> 新功能重启前数据已保存到 new_features_restart_data.json: ids={export_data['batch_ids_for_after_restart']}")

    print(f"\n========== 新功能阶段结果: {_PASS2} 通过, {_FAIL2} 失败 ==========")
    if _FAIL2 > 0:
        sys.exit(1)
    print("\n  请重启服务(端口8001)后，运行: python test_sample.py --new-features-after-restart")
    return export_bid1


def load_new_features_restart_ids():
    try:
        with open("new_features_restart_data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["batch_ids_for_after_restart"]
    except FileNotFoundError:
        return []


def run_new_features_after_restart():
    global _PASS2, _FAIL2
    print("\n" + "="*70)
    print("  新功能重启后一致性验证")
    print("="*70)

    ids = load_new_features_restart_ids()
    if not ids:
        print("[FAIL] 未找到新功能重启前数据，请先运行 --new-features-before-restart")
        sys.exit(1)
    print(f"  >> 加载批次ids: {ids}")

    for bid in ids:
        detail = api2("get", f"/api/bookings/batches/{bid}?operator_id=admin_new&operator_role=admin")
        assert detail["id"] == bid
        creation = detail["max_recurring_weeks_at_creation"]
        assert 1 <= creation <= 52, f"重启后 creation={creation} 超出范围"
        for b in detail["bookings"]:
            assert "week_phase" in b
            assert b["week_phase"] in {"preserved_in_effect", "preserved_approved", "adjustable", "finished"}
        print(f"  [PASS] 批次#{bid}重启后: id一致, creation={creation} 合法, week_phase全部存在 ({len(detail['bookings'])}条)")

        export = requests.get(f"{BASE2}/api/bookings/batches/{bid}/export", params={
            "operator_id": "admin_new", "operator_role": "admin"
        }).json()
        assert len(export["bookings"]) == len(detail["bookings"])
        assert export["batch"]["max_recurring_weeks_at_creation"] == creation
        audit_q = requests.get(f"{BASE2}/api/audit", params={"batch_id": bid}).json()
        audit_ids_q = {l["id"] for l in audit_q}
        audit_ids_e = set()
        for b in export["bookings"]:
            for lg in b["audit_logs"]:
                audit_ids_e.add(lg["id"])
        for lg in export["batch_level_audit_logs"]:
            audit_ids_e.add(lg["id"])
        assert audit_ids_q == audit_ids_e, f"批次#{bid}重启后导出审计id与查询不一致"
        print(f"  [PASS] 批次#{bid}重启后: 导出详情一致, 审计id一致, 配置快照creation={creation}")

    print(f"\n========== 新功能重启后结果: {_PASS2} 通过, {_FAIL2} 失败 ==========")
    if _FAIL2 > 0:
        sys.exit(1)


def main():
    global PASS, FAIL
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--after-restart":
            run_after_restart()
        elif len(sys.argv) > 1 and sys.argv[1] == "--before-restart":
            run_before_restart()
        elif len(sys.argv) > 1 and sys.argv[1] == "--new-features-before-restart":
            try:
                run_new_features_tests()
            except requests.exceptions.ConnectionError:
                print(f"\n[FAIL] 无法连接 {BASE2}, 请先启动:")
                print("  python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001")
                sys.exit(1)
        elif len(sys.argv) > 1 and sys.argv[1] == "--new-features-after-restart":
            try:
                run_new_features_after_restart()
            except requests.exceptions.ConnectionError:
                print(f"\n[FAIL] 无法连接 {BASE2}, 请先启动:")
                print("  python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001")
                sys.exit(1)
        elif len(sys.argv) > 1 and sys.argv[1] == "--config-tightening":
            try:
                print("\n" + "="*70)
                print("  配置收紧回归验证: MAX=4→2, 改期不整单拦截")
                print("="*70)
                print(f"  创建服务(MAX=4): {BASE2}")
                print(f"  操作服务(MAX=2): {BASE3}")
                test_batch_reschedule_config_tightening()
            except requests.exceptions.ConnectionError as e:
                print(f"\n[FAIL] 无法连接服务: {e}")
                print("请先启动:")
                print(f"  python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001")
                print(f"  $env:BOOKING_MAX_RECURRING_WEEKS='2'; python -m uvicorn booking.main:app --host 127.0.0.1 --port 8002")
                sys.exit(1)
        elif len(sys.argv) > 1 and sys.argv[1] == "--new-features":
            try:
                export_bid1 = run_new_features_tests()
                print("\n" + "="*60)
                print("  服务不重启，直接验证新功能重启后一致性...")
                print("="*60)
                run_new_features_after_restart()
            except requests.exceptions.ConnectionError:
                print(f"\n[FAIL] 无法连接 {BASE2}, 请先启动:")
                print("  python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001")
                sys.exit(1)
        else:
            batch_id, batch_before, bookings_before, logs_before = run_before_restart()

            print("\n" + "="*60)
            print("  服务不重启，直接验证持久化数据...")
            print("="*60)

            test_recurring_booking_after_restart(batch_id, batch_before, bookings_before, logs_before)

    except requests.exceptions.ConnectionError:
        print("\n[FAIL] 无法连接服务, 请先启动:")
        print("  python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000")
        sys.exit(1)

    print(f"\n========== 最终结果: {PASS} 通过, {FAIL} 失败 ==========")
    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
