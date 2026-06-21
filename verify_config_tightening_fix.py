#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
接口验证脚本：复现「配置收紧后改期整单拦截」bug，验证修复后的逐周处理机制

运行前需启动两个服务：
  终端1: python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001
  终端2: $env:BOOKING_MAX_RECURRING_WEEKS='2'; python -m uvicorn booking.main:app --host 127.0.0.1 --port 8002
"""

import requests
import json
from datetime import date, timedelta

BASE_CREATE = "http://127.0.0.1:8001"  # MAX=4，创建批次用
BASE_OPERATE = "http://127.0.0.1:8002" # MAX=2，模拟重启后配置收紧，改期用


def next_weekday(weekday: int, offset_days: int = 14):
    today = date.today()
    base = today + timedelta(days=offset_days)
    diff = (weekday - base.weekday()) % 7
    if diff == 0:
        diff = 7
    return base + timedelta(days=diff)


def p(title):
    print()
    print("=" * 70)
    print("  " + title)
    print("=" * 70)


def main():
    print("|----------------------------------------------------------------------|")
    print("|  接口验证脚本：批量改期 - 配置收紧后整单拦截 bug 修复验证               |")
    print("|  创建服务: 8001 (MAX=4)   操作服务: 8002 (MAX=2)                     |")
    print("|----------------------------------------------------------------------|")

    # ============== 健康检查 ==============
    p("Step 0: 健康检查")
    for name, base in [("创建(MAX=4)", BASE_CREATE), ("操作(MAX=2)", BASE_OPERATE)]:
        r = requests.get(f"{base}/api/health")
        assert r.status_code == 200, f"{name}服务未启动: {base}"
        cfg = requests.get(f"{base}/api/bookings/recurring/config").json()
        print(f"  [OK] {name}服务: health=200, max_recurring_weeks={cfg['max_recurring_weeks']}")

    # ============== 创建批次（MAX=4） ==============
    p("Step 1: 在 MAX=4 服务上创建 4 周批次")

    r = requests.post(f"{BASE_CREATE}/api/rooms", json={
        "name": "验证脚本_活动室", "description": "bug复现验证"
    })
    assert r.status_code == 201, f"创建房间失败: {r.text}"
    room_id = r.json()["id"]
    print(f"  [OK] 创建房间 #{room_id}")

    start_date = next_weekday(0, 28)  # 4周后的周一
    r = requests.post(f"{BASE_CREATE}/api/rooms/{room_id}/timeslots", json={
        "slots": [{"weekday": 0, "start_time": "14:00", "end_time": "17:00"}]
    })
    assert r.status_code == 201, f"设置时段失败: {r.text}"
    print(f"  [OK] 设置时段: 周一 14:00-17:00, 起始日期={start_date}")

    r = requests.post(f"{BASE_CREATE}/api/bookings/recurring", json={
        "room_id": room_id,
        "start_date": start_date.isoformat(),
        "weekday": 0, "start_time": "14:00", "end_time": "17:00",
        "weeks": 4,
        "user_id": "verify_user", "user_name": "验证用户",
        "purpose": "接口验证 - 配置收紧后改期"
    })
    assert r.status_code == 201, f"创建周期预约失败: {r.text}"
    batch = r.json()
    batch_id = batch["batch_id"]
    print(f"  [OK] 创建批次 #{batch_id}")

    r = requests.get(f"{BASE_CREATE}/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_verify", "operator_role": "admin"
    })
    detail_create = r.json()
    booking_ids = [b["id"] for b in detail_create["bookings"]]
    print(f"       booking_ids={booking_ids} ({len(booking_ids)} 条)")
    assert len(booking_ids) == 4, "应创建4条预约"

    r = requests.post(f"{BASE_CREATE}/api/bookings/{booking_ids[0]}/approve", json={
        "operator_id": "admin_verify", "operator_role": "admin", "note": "验证用"
    })
    assert r.status_code == 200, f"审批失败: {r.text}"
    print(f"  [OK] 审批 #{booking_ids[0]} -> approved (preserved_approved 相位)")

    r = requests.get(f"{BASE_CREATE}/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_verify", "operator_role": "admin"
    })
    detail = r.json()
    phases = {b["id"]: b["week_phase"] for b in detail["bookings"]}
    print(f"  [INFO] 当前相位: {phases}")
    adjustable = [bid for bid, ph in phases.items() if ph == "adjustable"]
    print(f"       adjustable={len(adjustable)}条 (应该=3) > MAX=2")
    max_at_creation = detail["max_recurring_weeks_at_creation"]
    assert max_at_creation >= 4, f"creation值不对: {max_at_creation}"
    print(f"  [INFO] max_at_creation={max_at_creation} (创建时配置, 永久不变)")

    # ============== 关键验证：在 MAX=2 服务上改期 ==============
    p("Step 2: 切换到 MAX=2 服务做改期 (核心验证点)")

    cfg2 = requests.get(f"{BASE_OPERATE}/api/bookings/recurring/config").json()
    max_at_operation = cfg2["max_recurring_weeks"]
    print(f"  [INFO] 操作服务 max_recurring_weeks={max_at_operation}")
    assert max_at_operation == 2, "操作服务MAX应=2"

    new_start = start_date + timedelta(days=56)
    print(f"  [INFO] 改期目标起始日期: {new_start}")

    r = requests.post(f"{BASE_OPERATE}/api/bookings/batches/{batch_id}/reschedule", json={
        "new_start_date": new_start.isoformat(),
        "operator_id": "admin_verify", "operator_role": "admin",
        "reason": "接口验证 - 配置收紧后改期测试"
    })

    print(f"\n  >>> 改期响应状态: {r.status_code}")
    if r.status_code != 200:
        resp = r.json()
        print(f"  [FAIL] 失败: code={resp.get('code')}, msg={resp.get('message')}")
        print(f"     这正是要修复的 bug：整单抛 {resp.get('code')}，没有逐周处理")
        raise SystemExit(1)

    resp = r.json()
    print(f"\n  [PASS] 成功进入逐周处理 (HTTP 200, 没有整单拦截)")
    print(f"     total={resp['total']}, success={resp['success']}, preserved={resp['preserved']}, denied={resp['denied']}, skipped={resp['skipped']}")
    print(f"     max_recurring_weeks_at_creation={resp['max_recurring_weeks_at_creation']}")
    print(f"     max_recurring_weeks_at_operation={resp['max_recurring_weeks_at_operation']}")
    print(f"     operated_at={resp['operated_at']}")

    assert resp["total"] == 4
    assert resp["preserved"] == 1, "已审批的1条应 preserved"
    assert resp["success"] == 3, "3条可调应 success (改期是UPDATE, 不受新配置上限限制)"
    assert resp["denied"] == 0
    assert resp["skipped"] == 0
    assert resp["total"] == resp["success"] + resp["preserved"] + resp["denied"] + resp["skipped"]
    assert resp["max_recurring_weeks_at_creation"] == max_at_creation
    assert resp["max_recurring_weeks_at_operation"] == max_at_operation

    print(f"\n  --- 逐条明细 ---")
    for it in resp["items"]:
        status_icon = {"success": "[OK]", "preserved": "[LOCK]", "denied": "[FAIL]", "skipped": "[SKIP]"}.get(it["result"], "?")
        extra = ""
        if it["result"] == "denied":
            extra = f" code={it['error_code']} msg={it['message'][:50]}"
        print(f"     {status_icon} #{it['booking_id']:3d} {it['result']:10s} "
              f"phase={it['week_phase_before']:20s} "
              f"{it['old_date']} -> {it['new_date']}{extra}")

    preserved_item = [i for i in resp["items"] if i["result"] == "preserved"][0]
    assert preserved_item["booking_id"] == booking_ids[0], "preserved的应是已审批那条"
    assert preserved_item["week_phase_before"] == "preserved_approved"
    assert preserved_item["old_date"] == preserved_item["new_date"], "preserved的日期应不变"
    assert preserved_item["old_status"] == preserved_item["new_status"] == "approved"
    print(f"\n  [OK] 相位保护正确: #{booking_ids[0]} (已审批) 被 preserved, 日期未变")

    success_items = [i for i in resp["items"] if i["result"] == "success"]
    assert len(success_items) == 3
    for i, it in enumerate(success_items):
        expected_date = new_start + timedelta(weeks=i)
        assert it["new_date"] == expected_date.isoformat(), f"第{i}条日期不对"
        assert it["old_date"] != it["new_date"], f"第{i}条日期未更新"
        assert it["week_phase_before"] == "adjustable", f"第{i}条相位不对"
        assert it["old_status"] == it["new_status"] == "pending"
    print(f"  [OK] 3条可调预约全部成功改期, 日期链完整: {[i['new_date'] for i in success_items]}")

    # ============== 冲突场景：部分成功部分拒绝 ==============
    p("Step 3: 冲突场景 - 部分成功部分拒绝")

    new_start2 = new_start + timedelta(weeks=2)
    blocker_date = new_start2 + timedelta(weeks=2)
    print(f"  [INFO] 再次改期目标起始: {new_start2}, 第3周={blocker_date} 与阻塞冲突")
    r = requests.post(f"{BASE_OPERATE}/api/bookings", json={
        "room_id": room_id,
        "date": blocker_date.isoformat(),
        "start_time": "14:00", "end_time": "17:00",
        "user_id": "blocker_verify", "user_name": "阻塞用户",
        "purpose": "阻塞冲突验证"
    })
    blocker_id = r.json()["id"]
    r = requests.post(f"{BASE_OPERATE}/api/bookings/{blocker_id}/approve", json={
        "operator_id": "admin_verify", "operator_role": "admin", "note": "验证用"
    })
    print(f"  [OK] 创建阻塞预约 #{blocker_id}, 日期={blocker_date}, 已审批")

    r = requests.post(f"{BASE_OPERATE}/api/bookings/batches/{batch_id}/reschedule", json={
        "new_start_date": new_start2.isoformat(),
        "operator_id": "admin_verify", "operator_role": "admin",
        "reason": "接口验证 - 冲突场景部分成功部分拒绝"
    })
    resp2 = r.json()
    print(f"\n  >>> 改期结果: total={resp2['total']}, success={resp2['success']}, "
          f"preserved={resp2['preserved']}, denied={resp2['denied']}, skipped={resp2['skipped']}")

    denied_codes = [i["error_code"] for i in resp2["items"] if i["result"] == "denied"]
    print(f"  >>> denied codes: {denied_codes}")
    for it in resp2["items"]:
        if it["result"] == "denied":
            print(f"      [FAIL] #{it['booking_id']}: code={it['error_code']} msg={it['message'][:60]}")

    assert resp2["preserved"] == 1
    assert resp2["denied"] == 1
    assert 10016 in denied_codes, f"应包含冲突码 10016, 实际={denied_codes}"
    assert resp2["total"] == resp2["success"] + resp2["preserved"] + resp2["denied"] + resp2["skipped"]
    print(f"  [OK] 部分成功部分拒绝正确: 1 preserved, {resp2['success']} success, 1 denied(10016), 无静默覆盖")

    # ============== DB 回查一致 ==============
    p("Step 4: DB 回查 - 查询 vs 导出一致")

    detail_q = requests.get(f"{BASE_OPERATE}/api/bookings/batches/{batch_id}", params={
        "operator_id": "admin_verify", "operator_role": "admin"
    }).json()

    export_resp = requests.get(f"{BASE_OPERATE}/api/bookings/batches/{batch_id}/export", params={
        "operator_id": "admin_verify", "operator_role": "admin"
    })
    assert "attachment" in export_resp.headers.get("Content-Disposition", "")
    export = export_resp.json()
    print(f"  [OK] 导出响应头: {export_resp.headers['Content-Disposition']}")

    q_ids = {b["id"]: b for b in detail_q["bookings"]}
    e_ids = {b["id"]: b for b in export["bookings"]}
    assert set(q_ids.keys()) == set(e_ids.keys()), f"id集合不一致: query={set(q_ids.keys())}, export={set(e_ids.keys())}"
    print(f"  [OK] 查询与导出 id 集合一致: {len(q_ids)} 条")

    for bid, qb in q_ids.items():
        eb = e_ids[bid]
        for f in ["status", "week_phase", "date", "old_date", "rescheduled_from_booking_id"]:
            qv = qb.get(f)
            ev = eb.get(f)
            assert qv == ev, f"#{bid} {f} 不一致: query={qv}, export={ev}"
    print(f"  [OK] 查询与导出字段一致: status/week_phase/date/old_date/rescheduled_from_booking_id")

    cs = export["config_snapshot"]
    print(f"  [INFO] 导出 config_snapshot:")
    print(f"         max_recurring_weeks_at_creation = {cs['max_recurring_weeks_at_creation']}")
    print(f"         max_recurring_weeks_current    = {cs['max_recurring_weeks_current']}")
    print(f"         env_var_name                    = {cs['env_var_name']}")
    print(f"         min/absolute/default            = {cs['min_recurring_weeks']}/{cs['absolute_max_recurring_weeks']}/{cs['default_max_recurring_weeks']}")
    assert cs["max_recurring_weeks_at_creation"] == max_at_creation
    assert cs["max_recurring_weeks_current"] == max_at_operation
    assert cs["env_var_name"] == "BOOKING_MAX_RECURRING_WEEKS"
    print(f"  [OK] 配置快照正确, 重启改配置后 creation 值不受影响")

    audit_q = requests.get(f"{BASE_OPERATE}/api/audit", params={"batch_id": batch_id}).json()
    audit_q_ids = {l["id"] for l in audit_q}
    audit_e_ids = set()
    for b in export["bookings"]:
        for lg in b["audit_logs"]:
            audit_e_ids.add(lg["id"])
    for lg in export["batch_level_audit_logs"]:
        audit_e_ids.add(lg["id"])
    assert audit_q_ids == audit_e_ids, f"审计id不一致: query_only={audit_q_ids-audit_e_ids}, export_only={audit_e_ids-audit_q_ids}"
    print(f"  [OK] 审计链路一致: {len(audit_q_ids)} 条审计 id 完全匹配")

    print(f"\n  --- 关键审计摘要 (共 {len(audit_q)} 条) ---")
    for lg in audit_q:
        if lg["action"] in {"batch_reschedule_start", "batch_reschedule_end", "reschedule"}:
            who = "BATCH" if lg["booking_id"] is None else f"#{lg['booking_id']}"
            old_s = lg.get("old_status") or "-"
            new_s = lg.get("new_status") or "-"
            detail = (lg.get("detail") or "")[:70]
            print(f"     [{lg['id']:3d}] {lg['action']:25s} {who:8s} {old_s:8s}->{new_s:8s} {detail}")

    summary = export["summary"]
    print(f"\n  [INFO] 导出 summary: {summary}")

    # ============== 最终结论 ==============
    p("[PASS] 验证结论")
    print()
    print("  修复前: adjustable_count=3 > MAX=2 -> 整单抛 10010, 逐周处理链路根本不执行")
    print("  修复后: adjustable_count=3 > MAX=2 -> HTTP 200, 逐周处理, 明细完整:")
    print("          - 已审批: preserved (日期不变, 状态不变)")
    print("          - 未开始可调: 逐周 slot/冲突检查, 成功则 success")
    print("          - 冲突则 denied (带明确 error_code 和 message)")
    print("          - creation/operation 双轨规则值正确, 审计链路完整")
    print("          - 查询与导出完全一致, 可回查")
    print()
    print("  根因: reschedule_batch 误把『新建预约的上限校验』套用到『改期现有预约』上")
    print("  修复: 删除 adjustable_count > MAX_RECURRING_WEEKS 整批校验 (原 bookings.py L611-617)")
    print("  理由: 改期是 UPDATE 现有行, 不是 INSERT 新行; 创建时已校验过上限;")
    print("        每条 adjustable 会独立做 slot 开放检查 + 冲突检查, 约束足够。")
    print()
    print("|----------------------------------------------------------------------|")
    print("|                         [PASS] 全部验证通过                           |")
    print("|----------------------------------------------------------------------|")


if __name__ == "__main__":
    main()
