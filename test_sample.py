"""
社区活动室预约系统 - 样例请求与验收测试脚本

使用方法:
  1. 启动服务:  python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000
  2. 运行脚本:  python test_sample.py

脚本会依次执行:
  - 主链路: 配置房间 -> 配置时段 -> 提交预约 -> 审批通过 -> 房间锁定
  - 边界用例: 重叠时段审批失败、居民取消他人预约失败、不在开放时段申请失败
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


def api(method: str, path: str, data: dict | None = None, expect_status: int = 200) -> dict:
    url = f"{BASE}{path}"
    resp = getattr(requests, method)(url, json=data)
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
    return resp.json()


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
    err_code = r.get("error_code", r.get("detail", {}).get("error_code", 0))
    assert err_code == 10004, f"Expected error_code 10004 (BOOKING_OVERLAP), got {err_code}"
    print(f"  [PASS] 重叠审批被拒绝, error_code={err_code}")


def test_cancel_others_booking(booking_id):
    print("\n========== 居民取消他人预约失败测试 ==========")

    r = api("post", f"/api/bookings/{booking_id}/cancel", {
        "operator_id": "lisi",
        "operator_role": "resident",
        "reason": "我想取消"
    }, 422)
    err_code = r.get("error_code", r.get("detail", {}).get("error_code", 0))
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
    err_code = r.get("error_code", r.get("detail", {}).get("error_code", 0))
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


def main():
    global PASS, FAIL
    try:
        room_id, booking_id, booking_date = test_main_flow()
        test_overlap_approval(room_id, booking_date)
        test_cancel_others_booking(booking_id)
        test_outside_open_hours(room_id)
        test_persistence(room_id, booking_id)
    except requests.exceptions.ConnectionError:
        print("\n[FAIL] 无法连接服务, 请先启动:")
        print("  python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000")
        sys.exit(1)

    print(f"\n========== 结果: {PASS} 通过, {FAIL} 失败 ==========")
    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
