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
"""

import sys
import io
import json
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


def test_recurring_booking_partial_success():
    print("\n========== 周期预约 - 部分成功部分冲突测试 ==========")
    from datetime import date, timedelta

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

    third_monday = next_monday + timedelta(weeks=2)
    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "lisi",
        "start_date": next_monday.isoformat(),
        "start_time": "09:00",
        "end_time": "11:00",
        "purpose": "每周一例会",
        "weeks": 3
    }, 201)

    batch_id = r["batch_id"]
    print(f"  >> 创建周期预约 batch_id={batch_id}, 共3周")
    print(f"  >> 统计: total={r['total']}, success={r['success']}, skipped={r['skipped']}, denied={r['denied']}")

    assert r["total"] == 3
    assert r["success"] == 2
    assert r["skipped"] == 1
    assert r["denied"] == 0

    success_dates = [item["date"] for item in r["items"] if item["status"] == "success"]
    skipped_dates = [item["date"] for item in r["items"] if item["status"] == "skipped"]
    print(f"  >> 成功日期: {success_dates}")
    print(f"  >> 冲突跳过日期: {skipped_dates}")

    assert booking_date in skipped_dates
    assert third_monday.isoformat() in success_dates

    success_items = [item for item in r["items"] if item["status"] == "success"]
    for item in success_items:
        assert item["booking_id"] is not None
    skipped_items = [item for item in r["items"] if item["status"] == "skipped"]
    for item in skipped_items:
        assert item["error_code"] == 10004
        assert item["booking_id"] is None

    print(f"  [PASS] 周期预约部分成功部分冲突验证通过")
    return room_id, batch_id, success_items[0]["booking_id"], third_monday.isoformat()


def test_recurring_booking_permission():
    print("\n========== 周期预约 - 居民只能操作自己的批次测试 ==========")
    from datetime import date, timedelta

    r = api("post", "/api/rooms", {"name": "钢琴室", "description": "四楼钢琴室"}, 201)
    room_id = r["id"]

    next_tuesday = date.today() + timedelta(days=(7 - date.today().weekday() + 1) % 7)
    if next_tuesday == date.today():
        next_tuesday += timedelta(days=7)
    weekday_1 = next_tuesday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_1, "start_time": "14:00", "end_time": "18:00"}]
    }, 201)

    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "zhangsan",
        "start_date": next_tuesday.isoformat(),
        "start_time": "14:00",
        "end_time": "16:00",
        "purpose": "钢琴练习",
        "weeks": 2
    }, 201)
    batch_id = r["batch_id"]
    print(f"  >> zhangsan 创建周期预约 batch_id={batch_id}")

    r = api("get", f"/api/bookings/batches/{batch_id}?operator_id=zhangsan&operator_role=resident")
    assert r["id"] == batch_id
    assert r["user_id"] == "zhangsan"
    print(f"  [PASS] zhangsan 可以查看自己的批次")

    r = api("get", f"/api/bookings/batches/{batch_id}?operator_id=lisi&operator_role=resident", expect_status=422)
    err_code = get_err_code(r)
    assert err_code == 10007
    print(f"  [PASS] lisi 不能查看 zhangsan 的批次, error_code={err_code}")

    r = api("get", f"/api/bookings/batches/{batch_id}?operator_id=admin1&operator_role=admin")
    assert r["id"] == batch_id
    print(f"  [PASS] admin 可以查看任意批次")

    print(f"  [PASS] 批次权限控制验证通过")
    return batch_id


def test_recurring_booking_approval_lock():
    print("\n========== 周期预约 - 审批后锁定冲突时段测试 ==========")
    from datetime import date, timedelta

    r = api("post", "/api/rooms", {"name": "羽毛球室", "description": "地下羽毛球场"}, 201)
    room_id = r["id"]

    next_wednesday = date.today() + timedelta(days=(7 - date.today().weekday() + 2) % 7)
    if next_wednesday == date.today():
        next_wednesday += timedelta(days=7)
    weekday_2 = next_wednesday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_2, "start_time": "18:00", "end_time": "22:00"}]
    }, 201)

    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "wangwu",
        "start_date": next_wednesday.isoformat(),
        "start_time": "19:00",
        "end_time": "21:00",
        "purpose": "羽毛球训练",
        "weeks": 2
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

    r = api("post", "/api/rooms", {"name": "棋牌室", "description": "二楼棋牌室"}, 201)
    room_id = r["id"]

    next_thursday = date.today() + timedelta(days=(7 - date.today().weekday() + 3) % 7)
    if next_thursday == date.today():
        next_thursday += timedelta(days=7)
    weekday_3 = next_thursday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_3, "start_time": "09:00", "end_time": "18:00"}]
    }, 201)

    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "qianqi",
        "start_date": next_thursday.isoformat(),
        "start_time": "09:00",
        "end_time": "12:00",
        "purpose": "棋牌活动",
        "weeks": 10
    }, 422)
    err_code = get_err_code(r)
    assert err_code == 10010
    print(f"  [PASS] 超过最大周数限制被拒绝, error_code={err_code}")

    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "qianqi",
        "start_date": next_thursday.isoformat(),
        "start_time": "09:00",
        "end_time": "12:00",
        "purpose": "棋牌活动",
        "weeks": 4
    }, 201)
    assert r["total"] == 4
    assert r["success"] == 4
    print(f"  [PASS] 4周预约成功")

    print(f"  [PASS] 配置超限验证通过")


def test_recurring_booking_audit_and_persistence():
    print("\n========== 周期预约 - 审计日志与重启后一致性测试 ==========")
    from datetime import date, timedelta

    r = api("post", "/api/rooms", {"name": "书画室", "description": "五楼书画室"}, 201)
    room_id = r["id"]

    next_friday = date.today() + timedelta(days=(7 - date.today().weekday() + 4) % 7)
    if next_friday == date.today():
        next_friday += timedelta(days=7)
    weekday_4 = next_friday.weekday()

    api("post", f"/api/rooms/{room_id}/timeslots", {
        "slots": [{"weekday": weekday_4, "start_time": "09:00", "end_time": "17:00"}]
    }, 201)

    r = api("post", "/api/bookings/recurring", {
        "room_id": room_id,
        "user_id": "sunba",
        "start_date": next_friday.isoformat(),
        "start_time": "10:00",
        "end_time": "12:00",
        "purpose": "书法练习",
        "weeks": 2
    }, 201)
    batch_id = r["batch_id"]
    booking_ids = [item["booking_id"] for item in r["items"] if item["status"] == "success"]
    print(f"  >> 创建周期预约 batch_id={batch_id}, booking_ids={booking_ids}")

    r = requests.get(f"{BASE}/api/audit", params={"batch_id": batch_id})
    logs = r.json()
    print(f"  >> 批次审计日志: {len(logs)} 条")
    assert len(logs) >= 3

    actions = [log["action"] for log in logs]
    assert "batch_create" in actions
    assert actions.count("create") == 2
    for log in logs:
        assert log["batch_id"] == batch_id
    print(f"  >> 审计日志操作序列: {actions}")

    for bid in booking_ids:
        r = requests.get(f"{BASE}/api/audit", params={"booking_id": bid})
        booking_logs = r.json()
        assert len(booking_logs) >= 1
        assert booking_logs[0]["batch_id"] == batch_id
    print(f"  [PASS] 每条子预约的审计日志也关联了 batch_id")

    r = requests.get(f"{BASE}/api/audit/export", params={"batch_id": batch_id})
    exported = r.json()
    assert len(exported) == len(logs)
    print(f"  [PASS] 按批次导出审计日志成功, 数量一致")

    batch_before = api("get", f"/api/bookings/batches/{batch_id}?operator_id=admin1&operator_role=admin")
    bookings_before = api("get", f"/api/bookings", params={"batch_id": batch_id})
    logs_before = requests.get(f"{BASE}/api/audit", params={"batch_id": batch_id}).json()

    print(f"  >> 重启前: batch={batch_before['id']}, bookings={len(bookings_before)}, logs={len(logs_before)}")

    print(f"  [PASS] 审计日志与持久性预验证通过")
    return batch_id, batch_before, bookings_before, logs_before


def test_recurring_booking_after_restart(batch_id, batch_before, bookings_before, logs_before):
    print("\n========== 周期预约 - 重启后查询和导出一致性测试 ==========")

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
    print(f"  [PASS] 审计日志查询和导出重启后一致")

    r = api("get", f"/api/bookings/batches", params={"user_id": "sunba"})
    assert any(b["id"] == batch_id for b in r)
    print(f"  [PASS] 批次列表查询正常")

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

    test_recurring_booking_partial_success()
    test_recurring_booking_permission()
    test_recurring_booking_approval_lock()
    test_recurring_booking_batch_limit()
    batch_id, batch_before, bookings_before, logs_before = test_recurring_booking_audit_and_persistence()
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


def main():
    global PASS, FAIL
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--after-restart":
            run_after_restart()
        elif len(sys.argv) > 1 and sys.argv[1] == "--before-restart":
            run_before_restart()
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
