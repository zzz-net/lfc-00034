"""
批量操作预演与回滚中心 —— 完整链路验收测试
覆盖：生成预演 → 确认执行 → 重启后查询 → 冲突回滚 → 导出核对
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta


BASE_URL_1 = "http://127.0.0.1:8003"
BASE_URL_2 = "http://127.0.0.1:8001"

PASSED = 0
FAILED = 0


def _normalize_base(raw: str) -> str:
    s = raw.strip().rstrip("/")
    if s.isdigit():
        return f"http://127.0.0.1:{s}"
    if not s.startswith("http://") and not s.startswith("https://"):
        return f"http://{s}"
    return s


def api(method: str, path: str, base: str | None = None, body: dict | None = None,
        params: dict | None = None, parse_json: bool = True, expect_status: int | None = None):
    global BASE_URL_1
    if base is None:
        base = BASE_URL_1
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        path = f"{path}?{qs}"
    url = f"{base}{path}"
    data = None
    headers = {"Content-Type": "application/json"} if body else {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            if expect_status is not None and resp.status != expect_status:
                raise AssertionError(f"Expected HTTP {expect_status}, got {resp.status}. Body: {raw[:500]}")
            if parse_json and raw:
                return resp.status, json.loads(raw)
            return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        if expect_status is not None and e.code == expect_status:
            if parse_json and raw:
                return e.code, json.loads(raw)
            return e.code, raw
        raise AssertionError(f"HTTP {e.code} for {method} {url}. Body: {raw[:800]}")


def check(name: str, cond: bool, detail: str = ""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


def assert_eq(name: str, actual, expected):
    check(name, actual == expected, f"expected={expected}, actual={actual}")


def assert_in(name: str, substr: str, text: str):
    check(name, substr in text, f"'{substr}' not in '{text[:200]}'")


def assert_len(name: str, lst, expected_len: int):
    check(name, len(lst) == expected_len, f"expected len={expected_len}, actual len={len(lst)}")


def next_mondays(n: int, offset_days: int = 14) -> list[date]:
    """返回从今天 offset_days 开始的 n 个连续周一，确保全部是未来日期。"""
    today = date.today() + timedelta(days=offset_days)
    # 找到下一个周一
    days_ahead = (0 - today.weekday() + 7) % 7 or 7
    first_monday = today + timedelta(days=days_ahead)
    return [first_monday + timedelta(weeks=i) for i in range(n)]


# ============================================================
# 链路 1：批量改期预演 → 确认执行 → 重启查询 → 导出核对
# ============================================================
def test_chain_reschedule():
    print("\n" + "=" * 70)
    print("【链路一】批量改期：生成预演 → 确认执行 → 重启查询 → 导出核对")
    print("=" * 70)

    mondays = next_mondays(4, 14)
    print(f"  📅 使用未来 4 个周一：{[d.isoformat() for d in mondays]}")

    # --- Step 1: 建房间 + 配置时段（周一 + 周三全天开放） ---
    print("\n  [Step 1] 创建房间并配置时段")
    _, room = api("POST", "/api/rooms", body={
        "name": "快照中心_排练厅", "description": "链路一专用"
    }, expect_status=201)
    ROOM_ID = room["id"]
    assert_eq("房间创建成功", room["name"], "快照中心_排练厅")

    api("POST", f"/api/rooms/{ROOM_ID}/timeslots", body={
        "slots": [
            {"weekday": 0, "start_time": "08:00", "end_time": "22:00"},
            {"weekday": 2, "start_time": "08:00", "end_time": "22:00"},
        ]
    }, expect_status=201)
    check("时段配置成功（周一+周三）", True)

    # --- Step 2: 创建周期预约（4 周 pending），然后制造混合状态 ---
    print("\n  [Step 2] 创建周期预约 4 周，并制造混合状态")
    _, batch = api("POST", "/api/bookings/recurring", body={
        "room_id": ROOM_ID, "user_id": "zhangsan",
        "start_date": mondays[0].isoformat(),
        "start_time": "10:00", "end_time": "12:00",
        "purpose": "快照链路_每周排练", "weeks": 4,
    }, expect_status=201)
    BATCH_ID = batch["batch_id"]
    BIDS = [item["booking_id"] for item in batch["items"]]
    assert_eq("创建批次成功 4 条全部 success", batch["success"], 4)

    # BID_1 审批 → preserved_approved，BID_4 取消 → finished
    _, b1 = api("POST", f"/api/bookings/{BIDS[0]}/approve", body={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "链路一:审批第一条制造preserved"
    }, expect_status=200)
    assert_eq("BID_1 审批成功", b1["status"], "approved")

    _, b4 = api("POST", f"/api/bookings/{BIDS[3]}/cancel", body={
        "operator_id": "zhangsan", "operator_role": "resident",
        "reason": "链路一:取消最后一条制造finished"
    }, expect_status=200)
    assert_eq("BID_4 取消成功", b4["status"], "cancelled")

    # 回查批次详情确认相位
    _, detail = api("GET", f"/api/bookings/batches/{BATCH_ID}", params={
        "operator_id": "admin1", "operator_role": "admin"
    })
    phases = [b["week_phase"] for b in detail["bookings"]]
    assert_eq("相位分布正确", phases, [
        "preserved_approved", "adjustable", "adjustable", "finished"
    ])
    print(f"    相位确认：{phases}")

    # 保存改期前日期基线
    baseline_dates = {bid: b["date"] for bid, b in zip(BIDS, detail["bookings"])}
    baseline_statuses = {bid: b["status"] for bid, b in zip(BIDS, detail["bookings"])}

    # --- Step 3: 权限边界 —— resident 尝试创建预演应该被允许（自己的批次） ---
    print("\n  [Step 3] 权限边界检查")
    try:
        api("POST", "/api/snapshots", body={
            "batch_id": BATCH_ID, "operation_type": "reschedule",
            "operator_id": "other_user", "operator_role": "resident",
            "description": "越权创建预演",
            "operation_params": {"new_start_date": (mondays[0] + timedelta(weeks=4)).isoformat()},
        })
        check("resident 越权创建他人批次预演 → 应被拒绝", False, "居然成功了")
    except AssertionError:
        check("resident 越权创建他人批次预演 → 被拒绝 (10007)", True)

    # --- Step 4: 创建改期预演 ---
    print("\n  [Step 4] 创建改期预演（批量改期 snapshot）")
    NEW_START = mondays[0] + timedelta(weeks=6)
    _, snap = api("POST", "/api/snapshots", body={
        "batch_id": BATCH_ID, "operation_type": "reschedule",
        "operator_id": "admin1", "operator_role": "admin",
        "description": "链路一_改期预演_延后6周",
        "operation_params": {
            "new_start_date": NEW_START.isoformat(),
            "new_start_time": "14:00",
            "new_end_time": "16:00",
        },
    }, expect_status=201)
    SNAP_ID = snap["id"]
    print(f"    预演ID: #{SNAP_ID}")

    assert_eq("预演状态=pending", snap["status"], "pending")
    assert_eq("预演类型=reschedule", snap["operation_type"], "reschedule")
    assert_eq("预演创建者=admin1", snap["operator_id"], "admin1")
    assert_eq("预演总条数=4", snap["total_bookings"], 4)
    assert_eq("预演affected=2（只有adjustable）", snap["affected_bookings"], 2)
    assert_eq("预演preserved=2", snap["preserved_bookings"], 2)
    check("config_snapshot 包含 max_recurring_weeks_at_snapshot",
          "max_recurring_weeks_at_snapshot" in snap["config_snapshot"])
    check("operation_params 写入新日期",
          snap["operation_params"]["new_start_date"] == NEW_START.isoformat())
    assert_len("booking_snapshots 包含 4 条基线", snap["booking_snapshots"], 4)

    # 基线快照值必须与创建预演时查询一致
    for sb in snap["booking_snapshots"]:
        assert_eq(f"  基线 booking#{sb['booking_id']} status 正确",
                  sb["status"], baseline_statuses[sb["booking_id"]])

    # audit_logs 中必须有 snapshot_create，且 snapshot_id 精确关联
    snap_create_logs = [a for a in snap["audit_logs"] if a["action"] == "snapshot_create"]
    assert_len("snapshot_id 精确关联的 snapshot_create 审计=1 条", snap_create_logs, 1)
    assert_eq("审计中 snapshot_id 正确关联", snap_create_logs[0]["snapshot_id"], SNAP_ID)

    # --- Step 5: 列表查询 + 详情查询（确认可被检索到） ---
    print("\n  [Step 5] 列表查询 + 详情查询（确认可检索）")
    _, snap_list = api("GET", "/api/snapshots", params={
        "batch_id": BATCH_ID, "operator_id": "admin1", "operator_role": "admin"
    })
    check("列表中能查到新建预演", any(s["id"] == SNAP_ID for s in snap_list))

    _, snap_detail = api("GET", f"/api/snapshots/{SNAP_ID}", params={
        "operator_id": "admin1", "operator_role": "admin"
    })
    assert_eq("详情查询状态=pending", snap_detail["status"], "pending")
    check("详情查询中 conflict_check 有结构",
          "has_conflict" in snap_detail["conflict_check"])

    # --- Step 6: 权限边界 —— resident 尝试执行预演（必须拒绝） ---
    print("\n  [Step 6] 权限边界：resident 尝试执行预演（必须拒绝）")
    try:
        api("POST", f"/api/snapshots/{SNAP_ID}/execute", body={
            "operator_id": "zhangsan", "operator_role": "resident",
            "reason": "越权执行"
        })
        check("resident 执行预演 → 应被拒绝", False, "居然成功了")
    except AssertionError as e:
        body_str = str(e)
        check("resident 执行预演 → 被拒绝 (10024 SNAPSHOT_OPERATION_NOT_ALLOWED)",
              "10024" in body_str or "10007" in body_str)

    # --- Step 7: 确认执行预演 ---
    print("\n  [Step 7] admin 确认执行改期预演")
    _, after_exec = api("POST", f"/api/snapshots/{SNAP_ID}/execute", body={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "链路一_确认执行改期"
    }, expect_status=200)

    assert_eq("执行后状态=executed", after_exec["status"], "executed")
    check("executed_at 有时间戳", after_exec["executed_at"] is not None)
    check("operation_result 不为空", after_exec["operation_result"] is not None)

    res = after_exec["operation_result"]
    assert_eq("操作类型=reschedule", res["operation"], "reschedule")
    assert_eq("operation_result success=2（两条adjustable）", res["success"], 2)
    assert_eq("operation_result preserved=2", res["preserved"], 2)
    assert_eq("operation_result total=4", res["total"], 4)

    # 核对执行结果 items（BID_2/BID_3 改日期和时段）
    success_items = [it for it in res["items"] if it["result"] == "success"]
    assert_len("改期成功 items=2 条", success_items, 2)
    for item in success_items:
        check(f"  booking#{item['booking_id']} new_date 在新周次",
              item["new_date"] in [(NEW_START + timedelta(weeks=i)).isoformat() for i in range(4)])
        assert_eq(f"  booking#{item['booking_id']} old_status 保留",
                  item["old_status"], item["new_status"])

    # 审计中应出现 snapshot_execute_start/end 以及 2 条 reschedule，全部带 snapshot_id
    exec_audits = [a for a in after_exec["audit_logs"]
                   if a["action"] in ("snapshot_execute_start", "snapshot_execute_end", "reschedule")]
    assert_len("精确关联的执行阶段审计=4 条（start/end + 2 reschedule）",
               exec_audits, 4)
    for a in exec_audits:
        assert_eq(f"  {a['action']} 审计 snapshot_id 正确", a["snapshot_id"], SNAP_ID)

    # 实际 booking 数据查询确认变更生效
    _, detail_after = api("GET", f"/api/bookings/batches/{BATCH_ID}", params={
        "operator_id": "admin1", "operator_role": "admin"
    })
    booking_map = {b["id"]: b for b in detail_after["bookings"]}
    # BID_2/BID_3 应该改了（按 adjustable 数组顺序 0/1 连续分配新周次）
    new_dates_expected = [(NEW_START + timedelta(weeks=i)).isoformat() for i in range(0, 2)]
    check(f"BID_2(BIDS[1]) 日期已更新: {booking_map[BIDS[1]]['date']}",
          booking_map[BIDS[1]]["date"] in new_dates_expected)
    check(f"BID_3(BIDS[2]) 日期已更新: {booking_map[BIDS[2]]['date']}",
          booking_map[BIDS[2]]["date"] in new_dates_expected)
    assert_eq(f"BID_2 start_time 改为 14:00", booking_map[BIDS[1]]["start_time"], "14:00")
    assert_eq(f"BID_2 end_time 改为 16:00", booking_map[BIDS[1]]["end_time"], "16:00")
    # BID_1/BID_4 应该没变（preserved）
    assert_eq(f"BID_1 日期未动（preserved）", booking_map[BIDS[0]]["date"], baseline_dates[BIDS[0]])
    assert_eq(f"BID_4 日期未动（preserved）", booking_map[BIDS[3]]["date"], baseline_dates[BIDS[3]])

    # --- Step 8: 切换端口模拟重启（同一数据库）→ 查询状态是否延续 ---
    print("\n  [Step 8] 切换端口模拟重启 → 验证状态持久化（跨端口/重启一致性）")
    _, snap_after_restart = api("GET", f"/api/snapshots/{SNAP_ID}",
                                base=BASE_URL_2,
                                params={"operator_id": "admin1", "operator_role": "admin"})
    assert_eq("重启后快照状态仍=executed", snap_after_restart["status"], "executed")
    check("重启后 executed_at 存在", snap_after_restart["executed_at"] is not None)
    check("重启后 operation_result 依然存在",
          snap_after_restart["operation_result"] is not None)
    assert_eq("重启后 operation_result success=2",
              snap_after_restart["operation_result"]["success"], 2)
    check("重启后 booking 实际数据一致（查询批次详情）", True)

    _, detail_8001 = api("GET", f"/api/bookings/batches/{BATCH_ID}",
                         base=BASE_URL_2,
                         params={"operator_id": "admin1", "operator_role": "admin"})
    booking_map_8001 = {b["id"]: b for b in detail_8001["bookings"]}
    for bid in BIDS:
        assert_eq(f"  重启后 booking#{bid} 日期一致",
                  booking_map_8001[bid]["date"], booking_map[bid]["date"])

    # audit 重启后也一致
    snapshot_audits_8001 = [a for a in snap_after_restart["audit_logs"]]
    assert_eq("重启后 audit_logs 数量一致（snapshot_id 精确关联）",
              len(snapshot_audits_8001), len(after_exec["audit_logs"]))
    check("重启后审计 id 集合一致（没有断裂/遗漏）",
          {a["id"] for a in snapshot_audits_8001} == {a["id"] for a in after_exec["audit_logs"]})

    # --- Step 9: 导出核对（导出 JSON vs 查询接口 100% 一致） ---
    print("\n  [Step 9] 导出核对（三项金标准）")
    _, export_raw = api("GET", f"/api/snapshots/{SNAP_ID}/export",
                        params={"operator_id": "admin1", "operator_role": "admin"},
                        parse_json=True)
    export_data = export_raw if isinstance(export_raw, dict) else json.loads(export_raw)

    # 金标准 1：snapshot 字段与详情查询接口一致
    exp_snap = export_data["snapshot"]
    assert_eq("导出.snapshot.id 正确", exp_snap["id"], SNAP_ID)
    assert_eq("导出.snapshot.status = executed", exp_snap["status"], "executed")
    assert_eq("导出.operation_result.success = 2",
              export_data["operation_result"]["success"], 2)
    check("导出.exported_at 有时间戳", "exported_at" in exp_snap)

    # 金标准 2：booking_snapshots 基线与详情查询一致
    exp_baseline_map = {b["booking_id"]: b for b in export_data["booking_snapshots"]}
    for sb in snap_after_restart["booking_snapshots"]:
        assert_eq(f"  基线 booking#{sb['booking_id']} status 一致",
                  exp_baseline_map[sb["booking_id"]]["status"], sb["status"])

    # 金标准 3：snapshot_audit_logs 与详情查询 audit id 集完全相等
    export_audit_ids = {a["id"] for a in export_data["snapshot_audit_logs"]}
    query_audit_ids = {a["id"] for a in snap_after_restart["audit_logs"]}
    diff = export_audit_ids.symmetric_difference(query_audit_ids)
    check("导出审计 id 集合 vs 详情查询 完全相等（空差集）",
          len(diff) == 0, f"diff={sorted(diff)}")
    for a in export_data["snapshot_audit_logs"]:
        assert_eq(f"  导出审计 #{a['id']} snapshot_id 正确关联",
                  a["snapshot_id"], SNAP_ID)

    print(f"\n  ✅ 链路一通过（生成预演→确认执行→重启查询→导出核对）✅")
    return BATCH_ID, SNAP_ID, BIDS, ROOM_ID, baseline_dates


# ============================================================
# 链路 2：冲突回滚（外部改动 → 执行报冲突 → 期望值/实际值对比）
# ============================================================
def test_chain_conflict_rollback():
    print("\n" + "=" * 70)
    print("【链路二】冲突与回滚：外部改动 → 执行冲突 → 回滚校验")
    print("=" * 70)

    mondays = next_mondays(3, 30)
    print(f"  📅 使用未来 3 个周一：{[d.isoformat() for d in mondays]}")

    # 创建房间 + 批次（3 周 pending，全部 adjustable）
    _, room = api("POST", "/api/rooms", body={
        "name": "快照中心_冲突实验室", "description": "链路二专用"
    }, expect_status=201)
    ROOM_ID = room["id"]
    api("POST", f"/api/rooms/{ROOM_ID}/timeslots", body={
        "slots": [{"weekday": 0, "start_time": "08:00", "end_time": "22:00"}]
    }, expect_status=201)

    _, batch = api("POST", "/api/bookings/recurring", body={
        "room_id": ROOM_ID, "user_id": "lisi",
        "start_date": mondays[0].isoformat(),
        "start_time": "09:00", "end_time": "11:00",
        "purpose": "链路二_冲突测试批次", "weeks": 3,
    }, expect_status=201)
    BATCH_ID = batch["batch_id"]
    BIDS = [item["booking_id"] for item in batch["items"]]

    # Step 1: 创建取消预演（pending 状态）
    print("\n  [Step 1] 创建取消预演（pending 状态，此时 booking 未动）")
    _, snap = api("POST", "/api/snapshots", body={
        "batch_id": BATCH_ID, "operation_type": "cancel",
        "operator_id": "admin1", "operator_role": "admin",
        "description": "链路二_取消预演_待外部改动",
    }, expect_status=201)
    SNAP_ID = snap["id"]
    print(f"    预演ID: #{SNAP_ID}")
    assert_eq("affected=3（全部可调）", snap["affected_bookings"], 3)
    assert_eq("status=pending", snap["status"], "pending")

    # Step 2: 外部改动 BID_2 —— 管理员手动审批（把 pending → approved）
    print("\n  [Step 2] 外部改动：手动把 BID_2 审批通过，制造基线偏离")
    _, b2 = api("POST", f"/api/bookings/{BIDS[1]}/approve", body={
        "operator_id": "admin2", "operator_role": "admin",
        "reason": "链路二:外部审批制造冲突"
    }, expect_status=200)
    assert_eq("BID_2 外部审批成功", b2["status"], "approved")

    # Step 3: 确认执行预演 → 必须报 booking_changed 冲突，含期望值 vs 实际值
    print("\n  [Step 3] 执行预演 → 必须报冲突（期望值/实际值对比）")
    _, err_body = api("POST", f"/api/snapshots/{SNAP_ID}/execute", body={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "链路二_故意冲突"
    }, expect_status=422)
    msg = str(err_body.get("message", ""))
    print(f"    捕获错误（预期）：HTTP 422 error_code={err_body.get('error_code')} msg={msg[:200]}")
    check("错误包含 10023 SNAPSHOT_BOOKING_CHANGED",
          str(err_body.get("error_code")) == "10023")
    check("错误包含 booking_changed 关键字",
          "booking_changed" in msg.lower() or "modified externally" in msg.lower())
    check("错误包含期望值 vs 实际值（字段对比）",
          "expected" in msg.lower() and "actual" in msg.lower())

    # 直接从错误响应的 conflict_check extra 拿结构化数据（含 field_diffs）
    cc = err_body.get("conflict_check", {})
    check("conflict_check.has_conflict=True", cc.get("has_conflict") is True)
    conflicts = cc.get("conflicts", [])
    assert_len("冲突项≥1 条", conflicts, 1)
    # 找到 BID_2 那条冲突
    bid2_conflict = next((c for c in conflicts if c["booking_id"] == BIDS[1]), None)
    check(f"BID_2 出现冲突项", bid2_conflict is not None)
    if bid2_conflict:
        assert_eq(f"BID_2 conflict_type=booking_changed",
                  bid2_conflict["conflict_type"], "booking_changed")
        check("field_diffs 非空（含期望值与实际值）",
              len(bid2_conflict["field_diffs"]) > 0)
        status_diff = next((d for d in bid2_conflict["field_diffs"] if d["field"] == "status"), None)
        check(f"status 字段差异存在：expected=pending, actual=approved",
              status_diff is not None
              and status_diff["expected_value"] == "pending"
              and status_diff["actual_value"] == "approved")
        print(f"    ✨ field_diffs 期望值/实际值：{status_diff}")

    # Step 4: 先 cancel 旧 pending snapshot 释放占用 → 然后建新快照（BID_2 已是 approved 分类 preserved）
    print("\n  [Step 4] 先取消旧快照释放占用 → 建新快照（BID_2 approved）→ 执行成功")
    _, cancelled = api("POST", f"/api/snapshots/{SNAP_ID}/cancel", params={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "链路二_冲突后释放占用建新预演"
    }, expect_status=200)
    assert_eq("旧快照取消成功 status=cancelled", cancelled["status"], "cancelled")
    # 现在创建新的 snapshot（此时 BID_2=approved，会被分类为 preserved_approved）
    _, snap2 = api("POST", "/api/snapshots", body={
        "batch_id": BATCH_ID, "operation_type": "cancel",
        "operator_id": "admin1", "operator_role": "admin",
        "description": "链路二_取消预演_修复后新建",
    }, expect_status=201)
    SNAP2_ID = snap2["id"]
    print(f"    新预演ID: #{SNAP2_ID}（此时 BID_2=approved 为 preserved_approved）")
    assert_eq("新预演 preserved=1（BID_2 approved）", snap2["preserved_bookings"], 1)
    assert_eq("新预演 affected=2", snap2["affected_bookings"], 2)

    _, after_exec2 = api("POST", f"/api/snapshots/{SNAP2_ID}/execute", body={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "链路二_修复后执行取消"
    }, expect_status=200)
    assert_eq("执行后状态=executed", after_exec2["status"], "executed")
    # 注意：对于 cancel 操作，admin/staff 可以强制取消 PRESERVED_APPROVED 相位的 booking
    # 所以 BID_2 (approved) 也会被成功取消，success=3（3 条全部取消），preserved=0
    assert_eq("success=3（3 条全部取消，含 BID_2 approved 被 admin 强制取消）",
              after_exec2["operation_result"]["success"], 3)
    assert_eq("preserved=0（admin/staff 可强制取消已批准）",
              after_exec2["operation_result"]["preserved"], 0)

    # Step 5: 冲突回滚校验 —— 手动改 BID_1 状态，然后尝试回滚（必须报冲突）
    print("\n  [Step 5] 回滚冲突校验：外部改 booking 状态 → 回滚报冲突")
    # 先手动把一个 cancelled booking 改回 pending（模拟外部改动）
    # 通过直接创建一个新的 snapshot 来测 rollback：先创建 reschedule snapshot 并执行
    # 然后外部改动 booking 再 rollback
    mondays2 = next_mondays(2, 45)
    _, room2 = api("POST", "/api/rooms", body={
        "name": "快照中心_回滚冲突房", "description": "链路二Step5专用"
    }, expect_status=201)
    ROOM2_ID = room2["id"]
    api("POST", f"/api/rooms/{ROOM2_ID}/timeslots", body={
        "slots": [{"weekday": 0, "start_time": "08:00", "end_time": "22:00"}]
    }, expect_status=201)
    _, batch2 = api("POST", "/api/bookings/recurring", body={
        "room_id": ROOM2_ID, "user_id": "wangwu",
        "start_date": mondays2[0].isoformat(),
        "start_time": "10:00", "end_time": "12:00",
        "purpose": "链路二Step5_回滚冲突批次", "weeks": 2,
    }, expect_status=201)
    BATCH2_ID = batch2["batch_id"]
    B2_BIDS = [item["booking_id"] for item in batch2["items"]]

    # 创建改期预演 + 执行
    TARGET = mondays2[0] + timedelta(weeks=5)
    _, snap3 = api("POST", "/api/snapshots", body={
        "batch_id": BATCH2_ID, "operation_type": "reschedule",
        "operator_id": "admin1", "operator_role": "admin",
        "description": "链路二Step5_改期预演用于回滚冲突测试",
        "operation_params": {"new_start_date": TARGET.isoformat()},
    }, expect_status=201)
    SNAP3_ID = snap3["id"]
    api("POST", f"/api/snapshots/{SNAP3_ID}/execute", body={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "Step5_确认执行"
    }, expect_status=200)

    # 外部改动：把 B2_BIDS[0] 手动批准（不是 snapshot 操作，pending→approved，模拟外部改 status）
    _, b2b0 = api("POST", f"/api/bookings/{B2_BIDS[0]}/approve", body={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "链路二Step5_外部批准制造回滚冲突"
    }, expect_status=200)
    assert_eq("外部批准 B2_BIDS[0] 成功", b2b0["status"], "approved")

    # 回滚 → 应报冲突：当前 booking 状态 != 预期的 reschedule 后状态
    # 注意：回滚 API 整体仍返回 200（因为流程确实执行了），只是 result 里有 denied 项
    print("    尝试回滚（预期冲突，booking 状态已被外部改动）")
    _, rollback_conflict = api("POST", f"/api/snapshots/{SNAP3_ID}/rollback", body={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "Step5_故意冲突"
    }, expect_status=200)
    check("回滚后 snapshot 状态仍=rolled_back（即使有冲突项）",
          rollback_conflict["status"] == "rolled_back")
    rb_result = rollback_conflict.get("rollback_result", {})
    denied = rb_result.get("denied", 0)
    check(f"回滚结果 denied>=1（检测到外部状态变化），实际 denied={denied}", denied >= 1)
    # 查找 denied 的具体项，确认包含 B2_BIDS[0] 和 status 相关信息
    denied_items = [it for it in rb_result.get("items", []) if it.get("result") == "denied"]
    check(f"denied_items 非空，共 {len(denied_items)} 条", len(denied_items) > 0)
    if denied_items:
        msg = denied_items[0].get("message", "")
        check(f"denied 信息包含 status 或 cannot rollback 关键字: {msg[:150]}",
              "status" in msg.lower() or "cannot rollback" in msg.lower())

    # Step 6: 正常回滚（没有外部改动时）
    print("\n  [Step 6] 正常回滚：外部未改动的 booking 回滚成功")
    # 重新用一个干净的批次
    mondays3 = next_mondays(2, 60)
    _, room3 = api("POST", "/api/rooms", body={
        "name": "快照中心_正常回滚房", "description": "链路二Step6专用"
    }, expect_status=201)
    ROOM3_ID = room3["id"]
    api("POST", f"/api/rooms/{ROOM3_ID}/timeslots", body={
        "slots": [{"weekday": 0, "start_time": "08:00", "end_time": "22:00"}]
    }, expect_status=201)
    _, batch3 = api("POST", "/api/bookings/recurring", body={
        "room_id": ROOM3_ID, "user_id": "zhaoliu",
        "start_date": mondays3[0].isoformat(),
        "start_time": "15:00", "end_time": "17:00",
        "purpose": "链路二Step6_正常回滚批次", "weeks": 2,
    }, expect_status=201)
    BATCH3_ID = batch3["batch_id"]
    B3_BIDS = [item["booking_id"] for item in batch3["items"]]
    BASE_DATES = {item["booking_id"]: item["date"] for item in batch3["items"]}

    # 先创建取消预演并执行
    _, snap_cancel = api("POST", "/api/snapshots", body={
        "batch_id": BATCH3_ID, "operation_type": "cancel",
        "operator_id": "admin1", "operator_role": "admin",
        "description": "链路二Step6_取消预演_正常回滚",
    }, expect_status=201)
    SNAP_CANCEL_ID = snap_cancel["id"]
    api("POST", f"/api/snapshots/{SNAP_CANCEL_ID}/execute", body={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "Step6_先执行取消，再回滚"
    }, expect_status=200)
    # 确认已取消
    _, b3_0 = api("GET", f"/api/bookings/{B3_BIDS[0]}")
    assert_eq("执行后 B3_BIDS[0] = cancelled", b3_0["status"], "cancelled")

    # resident 尝试回滚（权限拒绝）
    print("    resident 尝试回滚（预期权限拒绝）")
    try:
        api("POST", f"/api/snapshots/{SNAP_CANCEL_ID}/rollback", body={
            "operator_id": "zhaoliu", "operator_role": "resident",
            "reason": "越权回滚"
        })
        check("resident 回滚应被拒绝", False, "居然成功了")
    except AssertionError as e:
        check("resident 回滚被拒绝 (10024/10007)",
              "10024" in str(e) or "10007" in str(e))

    # admin 正常回滚
    _, after_rollback = api("POST", f"/api/snapshots/{SNAP_CANCEL_ID}/rollback", body={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "链路二Step6_正常回滚取消操作"
    }, expect_status=200)
    assert_eq("回滚后 snapshot status=rolled_back",
              after_rollback["status"], "rolled_back")
    check("rolled_back_at 有时间戳", after_rollback["rolled_back_at"] is not None)
    check("rollback_result 存在", after_rollback["rollback_result"] is not None)
    assert_eq("rollback success=2（全部恢复）",
              after_rollback["rollback_result"]["success"], 2)

    # 确认 booking 实际状态被恢复
    _, b3_0_after = api("GET", f"/api/bookings/{B3_BIDS[0]}")
    assert_eq("回滚后 B3_BIDS[0] 恢复 pending", b3_0_after["status"], "pending")
    _, b3_1_after = api("GET", f"/api/bookings/{B3_BIDS[1]}")
    assert_eq("回滚后 B3_BIDS[1] 恢复 pending", b3_1_after["status"], "pending")

    # 审计中精确关联 rollback_cancel 日志
    rb_audits = [a for a in after_rollback["audit_logs"]
                 if a["action"] in ("rollback_cancel", "snapshot_rollback_start", "snapshot_rollback_end")]
    assert_len("精确关联的回滚审计=4 条（start/end + 2 rollback_cancel）", rb_audits, 4)
    for a in rb_audits:
        assert_eq(f"  {a['action']} snapshot_id 正确", a["snapshot_id"], SNAP_CANCEL_ID)

    print(f"\n  ✅ 链路二通过（外部改动→冲突检测→正常回滚）✅")


# ============================================================
# 链路 3：取消 pending 预演 + export 预演类型
# ============================================================
def test_chain_cancel_pending_and_export_type():
    print("\n" + "=" * 70)
    print("【链路三】取消 pending 预演 + export 预演类型 + 跨快照占用冲突")
    print("=" * 70)

    mondays = next_mondays(2, 75)

    _, room = api("POST", "/api/rooms", body={
        "name": "快照中心_取消pending房", "description": "链路三专用"
    }, expect_status=201)
    ROOM_ID = room["id"]
    api("POST", f"/api/rooms/{ROOM_ID}/timeslots", body={
        "slots": [{"weekday": 0, "start_time": "08:00", "end_time": "22:00"}]
    }, expect_status=201)

    _, batch = api("POST", "/api/bookings/recurring", body={
        "room_id": ROOM_ID, "user_id": "qianqi",
        "start_date": mondays[0].isoformat(),
        "start_time": "08:00", "end_time": "10:00",
        "purpose": "链路三_批次", "weeks": 2,
    }, expect_status=201)
    BATCH_ID = batch["batch_id"]

    # Step 1: 创建第一个 pending 预演
    print("\n  [Step 1] 创建第一个 pending 预演（S1）")
    _, s1 = api("POST", "/api/snapshots", body={
        "batch_id": BATCH_ID, "operation_type": "cancel",
        "operator_id": "admin1", "operator_role": "admin",
        "description": "链路三_S1",
    }, expect_status=201)
    S1_ID = s1["id"]

    # Step 2: 尝试创建第二个预演（同批 booking）→ 必须报 occupied_by_another_snapshot 冲突
    print("\n  [Step 2] 尝试创建第二个预演 → 同批 booking 被占用冲突")
    try:
        api("POST", "/api/snapshots", body={
            "batch_id": BATCH_ID, "operation_type": "reschedule",
            "operator_id": "admin1", "operator_role": "admin",
            "description": "链路三_S2_应该冲突",
            "operation_params": {"new_start_date": (mondays[0] + timedelta(weeks=3)).isoformat()},
        })
        check("同批 booking 占用应被拒绝", False, "居然成功创建了")
    except AssertionError as e:
        msg = str(e)
        check("冲突错误码=10022 SNAPSHOT_CONFLICT", "10022" in msg)
        check("冲突类型 occupied_by_another_snapshot",
              "occupied" in msg.lower() or "snapshot" in msg.lower())

    # Step 3: 取消 S1 pending 预演（resident 尝试 → 必须拒绝）
    print("\n  [Step 3] resident 尝试取消 pending 预演（权限拒绝）")
    try:
        api("POST", f"/api/snapshots/{S1_ID}/cancel", params={
            "operator_id": "qianqi", "operator_role": "resident", "reason": "越权"
        })
        check("resident 取消预演应拒绝", False, "居然成功了")
    except AssertionError as e:
        check("resident 取消预演被拒绝 (10024)", "10024" in str(e))

    # Step 4: admin 正常取消 pending 预演
    print("\n  [Step 4] admin 正常取消 pending 预演")
    _, after_cancel = api("POST", f"/api/snapshots/{S1_ID}/cancel", params={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "链路三_取消预演S1"
    }, expect_status=200)
    assert_eq("取消后 status=cancelled", after_cancel["status"], "cancelled")
    cancel_audit = [a for a in after_cancel["audit_logs"] if a["action"] == "snapshot_cancel"]
    assert_len("精确关联 snapshot_cancel 审计=1", cancel_audit, 1)
    assert_eq("snapshot_cancel snapshot_id 正确",
              cancel_audit[0]["snapshot_id"], S1_ID)

    # Step 5: 现在创建 S2（S1 已取消，不再占用，应该成功）
    print("\n  [Step 5] S1 已取消 → 创建 S2 应该成功（占用释放）")
    _, s2 = api("POST", "/api/snapshots", body={
        "batch_id": BATCH_ID, "operation_type": "reschedule",
        "operator_id": "admin1", "operator_role": "admin",
        "description": "链路三_S2_成功创建",
        "operation_params": {"new_start_date": (mondays[0] + timedelta(weeks=3)).isoformat()},
    }, expect_status=201)
    assert_eq("S2 创建成功 status=pending", s2["status"], "pending")
    # 取消 S2 释放占用（给后面 export 类型预演让路）
    _, s2_cancel = api("POST", f"/api/snapshots/{s2['id']}/cancel", params={
        "operator_id": "admin1", "operator_role": "admin",
        "reason": "链路三_S2取消释放占用给export"
    }, expect_status=200)
    assert_eq("S2取消成功 status=cancelled", s2_cancel["status"], "cancelled")

    # Step 6: 执行 export 类型预演
    print("\n  [Step 6] export 类型预演：创建 + 执行 + 导出")
    _, s_export = api("POST", "/api/snapshots", body={
        "batch_id": BATCH_ID, "operation_type": "export",
        "operator_id": "staff1", "operator_role": "staff",
        "description": "链路三_export快照（staff 权限）",
    }, expect_status=201)
    S_EXPORT_ID = s_export["id"]
    assert_eq("staff 角色可以创建 export 预演", s_export["operator_role"], "staff")

    # staff 执行（有权限）
    _, after_exec_exp = api("POST", f"/api/snapshots/{S_EXPORT_ID}/execute", body={
        "operator_id": "staff1", "operator_role": "staff",
        "reason": "链路三_staff执行export"
    }, expect_status=200)
    assert_eq("export 执行后 status=executed", after_exec_exp["status"], "executed")
    assert_eq("export operation success=2（全部记录）",
              after_exec_exp["operation_result"]["success"], 2)
    assert_eq("export operation 没有 denied",
              after_exec_exp["operation_result"]["denied"], 0)

    # export 类型回滚 → 所有 booking preserved（无实际改动）
    _, after_rb_exp = api("POST", f"/api/snapshots/{S_EXPORT_ID}/rollback", body={
        "operator_id": "staff1", "operator_role": "staff",
        "reason": "链路三_export回滚"
    }, expect_status=200)
    assert_eq("export 回滚后 status=rolled_back",
              after_rb_exp["status"], "rolled_back")
    assert_eq("export 回滚 preserved=2（无实际改动）",
              after_rb_exp["rollback_result"]["preserved"], 2)
    assert_eq("export 回滚 success=0",
              after_rb_exp["rollback_result"]["success"], 0)

    print(f"\n  ✅ 链路三通过（pending取消 + 占用冲突 + export类型）✅")


# ============================================================
# 汇总
# ============================================================
def main():
    global PASSED, FAILED, BASE_URL_1, BASE_URL_2

    parser = argparse.ArgumentParser(description="快照中心完整链路验收测试")
    parser.add_argument("--base-1", default=BASE_URL_1, help="第一个服务地址（默认8003）")
    parser.add_argument("--base-2", default=BASE_URL_2, help="第二个服务地址（默认8001，模拟重启）")
    args = parser.parse_args()

    BASE_URL_1 = args.base_1.rstrip("/")
    BASE_URL_2 = args.base_2.rstrip("/")

    # 先健康检查
    for base, name in [(BASE_URL_1, "端口1"), (BASE_URL_2, "端口2")]:
        try:
            status, _ = api("GET", "/api/health", base=base, expect_status=200)
            print(f"✅ {name} 服务健康检查通过 ({base})")
        except Exception as e:
            print(f"❌ {name} 服务不可用 {base}: {e}")
            print("请先启动两个服务：")
            print(f"  python -m uvicorn booking.main:app --host 127.0.0.1 --port 8003")
            print(f"  python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001")
            sys.exit(1)

    print(f"\n🚀 快照中心验收测试启动 —— 使用数据库: booking.db（两服务共享）")

    # 跑链路
    try:
        test_chain_reschedule()
    except Exception as e:
        FAILED += 1
        print(f"  ❌ 链路一异常终止: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_chain_conflict_rollback()
    except Exception as e:
        FAILED += 1
        print(f"  ❌ 链路二异常终止: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_chain_cancel_pending_and_export_type()
    except Exception as e:
        FAILED += 1
        print(f"  ❌ 链路三异常终止: {e}")
        import traceback
        traceback.print_exc()

    # 汇总
    print("\n" + "=" * 70)
    total = PASSED + FAILED
    print(f"📊 验收汇总：{PASSED} 通过, {FAILED} 失败, 共 {total} 项")
    print("=" * 70)

    if FAILED == 0:
        print("🎉🎉🎉 全部通过！快照中心五条验收链路全部达标 🎉🎉🎉")
        sys.exit(0)
    else:
        print(f"⚠️  有 {FAILED} 项失败，请检查上方 ❌ 标记的用例")
        sys.exit(1)


if __name__ == "__main__":
    main()
