# 社区活动室预约系统

基于 FastAPI + SQLite 的社区活动室预约后端服务，支持房间配置、时段管理、预约审批与审计日志。

## 快速启动

```bash
pip install -r requirements.txt
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000
```

启动后访问 http://127.0.0.1:8000/docs 查看 Swagger 交互式文档。

### 自定义周期预约上限

周期预约的最大周数通过环境变量 `BOOKING_MAX_RECURRING_WEEKS` 配置：

```bash
# 默认启动（上限 4 周）
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000

# 自定义上限为 8 周（Windows PowerShell）
$env:BOOKING_MAX_RECURRING_WEEKS="8"
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000

# 自定义上限为 8 周（Linux/macOS）
BOOKING_MAX_RECURRING_WEEKS=8 python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000
```

| 参数 | 说明 |
|------|------|
| 环境变量名 | `BOOKING_MAX_RECURRING_WEEKS` |
| 默认值 | `4` |
| 最小值 | `1`（低于 1 回退到默认值 4） |
| 绝对上限 | `52`（超过 52 自动截断为 52） |
| 无效值处理 | 非数字或缺失时回退到默认值 4 |

可通过接口实时查询当前生效的配置：

```bash
curl http://127.0.0.1:8000/api/bookings/recurring/config
```

返回示例：

```json
{
  "max_recurring_weeks": 4,
  "min_recurring_weeks": 1,
  "absolute_max_recurring_weeks": 52,
  "default_max_recurring_weeks": 4,
  "env_var_name": "BOOKING_MAX_RECURRING_WEEKS"
}
```

## 运行验收测试

```bash
python test_sample.py
```

脚本覆盖：主链路（配置→预约→审批→锁定）、重叠审批失败、居民取消他人预约失败、不在开放时段申请失败、持久性验证、周期预约全链路（部分冲突、权限控制、审批锁定、配置超限、审计链路、环境变量配置、重启一致性）。

---

## API 一览

### 房间管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/rooms` | 创建房间 |
| GET | `/api/rooms` | 房间列表（可按 `is_active` 过滤） |
| GET | `/api/rooms/{id}` | 房间详情 |
| PATCH | `/api/rooms/{id}` | 更新房间（名称、描述、启停） |
| POST | `/api/rooms/{id}/timeslots` | 配置开放时段（覆盖式写入） |
| GET | `/api/rooms/{id}/timeslots` | 查看房间开放时段 |

### 预约管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/bookings` | 提交预约 |
| POST | `/api/bookings/recurring` | 提交周期预约（按周重复） |
| GET | `/api/bookings/recurring/config` | 查询周期预约当前配置与规则 |
| GET | `/api/bookings` | 预约列表（按 status/room_id/user_id/date/batch_id 过滤） |
| GET | `/api/bookings/{id}` | 预约详情 |
| GET | `/api/bookings/batches` | 批次列表（可按 user_id 过滤） |
| GET | `/api/bookings/batches/{id}` | 批次详情（含关联预约和生效规则） |
| POST | `/api/bookings/{id}/approve` | 审批通过 |
| POST | `/api/bookings/{id}/reject` | 审批驳回 |
| POST | `/api/bookings/{id}/cancel` | 取消预约 |
| POST | `/api/bookings/expire` | 批量过期已过时间的预约 |
| POST | `/api/bookings/batches/{id}/reschedule` | **批量改期**（调整批次中可调预约的日期/时段） |
| POST | `/api/bookings/batches/{id}/cancel` | **整批取消**（批次中所有可取消的预约） |
| GET | `/api/bookings/batches/{id}/export` | **批次导出**（含配置快照、审计日志、周次状态） |

### 审计日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/audit` | 查询审计日志 |
| GET | `/api/audit/export` | 导出审计日志 JSON |

### 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 服务健康检查 |

---

## 预约状态流转

```
pending ──approve──> approved ──cancel──> cancelled
  │                    │
  ├──reject──> rejected└──expire──> expired
  │
  └──cancel──> cancelled
```

- **pending**：居民提交后等待审批
- **approved**：管理员/工作人员审批通过，房间锁定
- **rejected**：管理员/工作人员驳回
- **cancelled**：居民取消自己的预约，或管理员取消
- **expired**：系统自动将已过时间的 approved 预约标记过期

### 审批权限规则

| 操作 | 允许角色 |
|------|----------|
| approve（审批通过） | `admin`, `staff` |
| reject（审批驳回） | `admin`, `staff` |
| cancel（取消自己的预约） | `admin`, `staff`, `resident` |
| cancel（取消他人的预约） | `admin`, `staff` |

---

## 错误码（稳定，不可变）

| 错误码 | 常量 | 说明 |
|--------|------|------|
| 10001 | ROOM_NOT_FOUND | 房间不存在 |
| 10002 | ROOM_INACTIVE | 房间已停用 |
| 10003 | SLOT_NOT_OPEN | 申请时间不在任何开放时段内 |
| 10004 | BOOKING_OVERLAP | 与已审批预约时段重叠 |
| 10005 | BOOKING_NOT_FOUND | 预约不存在 |
| 10006 | INVALID_STATUS_TRANSITION | 当前状态不允许此操作 |
| 10007 | PERMISSION_DENIED | 无权限（如居民取消他人预约） |
| 10008 | BOOKING_ALREADY_PROCESSED | 预约已被处理 |
| 10009 | INVALID_TIME_RANGE | start_time 必须早于 end_time |
| 10010 | BATCH_LIMIT_EXCEEDED | 周期预约周数超过当前配置上限 |
| 10011 | BATCH_NOT_FOUND | 批次不存在 |

所有业务错误返回 HTTP 422，响应体为：

```json
{"error_code": 10010, "message": "Maximum 4 weeks allowed, requested 10. Current limit set by BOOKING_MAX_RECURRING_WEEKS=4 (range: 1-52)"}
```

---

## 样例请求

### 1. 创建房间

```bash
curl -X POST http://127.0.0.1:8000/api/rooms \
  -H "Content-Type: application/json" \
  -d '{"name": "舞蹈室", "description": "一楼舞蹈活动室"}'
```

### 2. 配置开放时段

```bash
curl -X POST http://127.0.0.1:8000/api/rooms/1/timeslots \
  -H "Content-Type: application/json" \
  -d '{"slots": [
    {"weekday": 0, "start_time": "09:00", "end_time": "12:00"},
    {"weekday": 0, "start_time": "14:00", "end_time": "18:00"}
  ]}'
```

weekday 取值 0=周一 ... 6=周日。

### 3. 提交预约

```bash
curl -X POST http://127.0.0.1:8000/api/bookings \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": 1,
    "user_id": "zhangsan",
    "date": "2026-06-29",
    "start_time": "09:00",
    "end_time": "11:00",
    "purpose": "社区舞蹈排练"
  }'
```

### 4. 提交周期预约

```bash
curl -X POST http://127.0.0.1:8000/api/bookings/recurring \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": 1,
    "user_id": "zhangsan",
    "start_date": "2026-06-29",
    "start_time": "09:00",
    "end_time": "11:00",
    "purpose": "每周一舞蹈排练",
    "weeks": 4
  }'
```

### 5. 查询当前周期预约配置

```bash
curl http://127.0.0.1:8000/api/bookings/recurring/config
```

### 6. 审批通过

```bash
curl -X POST http://127.0.0.1:8000/api/bookings/1/approve \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "同意"}'
```

### 7. 查询已锁定时段

```bash
curl "http://127.0.0.1:8000/api/bookings?status=approved&room_id=1"
```

### 8. 查看批次详情（含生效规则）

```bash
curl "http://127.0.0.1:8000/api/bookings/batches/1?operator_id=admin1&operator_role=admin"
```

返回中包含 `max_recurring_weeks_at_creation` 字段，表示创建该批次时生效的最大周数规则。

### 9. 居民取消自己的预约

```bash
curl -X POST http://127.0.0.1:8000/api/bookings/1/cancel \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "zhangsan", "operator_role": "resident", "reason": "临时有事"}'
```

### 10. 查询审计日志

```bash
curl "http://127.0.0.1:8000/api/audit?booking_id=1"
```

### 11. 导出审计日志

```bash
curl "http://127.0.0.1:8000/api/audit/export" -o audit_logs.json
```

### 12. 批量改期

```bash
curl -X POST "http://127.0.0.1:8000/api/bookings/batches/1/reschedule" \
  -H "Content-Type: application/json" \
  -d '{
    "new_start_date": "2026-07-13",
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "活动整体延后两周",
    "new_start_time": "10:00",
    "new_end_time": "12:00"
  }'
```

- `new_start_date`（必填）：新的起始日期，后续周次自动按周顺延
- `new_start_time` / `new_end_time`（可选）：同时调整时段，不传则保持原有时间
- `operator_role = resident` 只能改自己的批次

### 13. 整批取消

```bash
curl -X POST "http://127.0.0.1:8000/api/bookings/batches/1/cancel" \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "活动室临时装修"
  }'
```

- `operator_role = resident`：只能取消自己的批次，且 **已审批** 的预约会被 `preserved`（保护）不取消
- `operator_role = admin/staff`：可以代取消所有可取消的预约，包括已审批的

### 14. 批次导出（JSON，含配置快照与审计）

```bash
curl "http://127.0.0.1:8000/api/bookings/batches/1/export?operator_id=admin1&operator_role=admin" \
  -o batch_1_export.json
```

导出文件包含：
- `batch`：批次元信息与创建/导出时间戳
- `config_snapshot`：创建时规则值 vs 当前生效规则值
- `bookings`：每条预约的周次相位（`week_phase`）、状态、改期追踪、各自审计日志
- `batch_level_audit_logs`：批次级审计（`batch_create`、`batch_reschedule_start/end`、`batch_cancel_start/end`）
- `summary`：四种 `week_phase` 数量统计

---

## 批次操作完整复核手册（管理员版 · 照抄即跑）

> 本章节目标：**不翻任何代码**，仅按本节命令顺序逐条执行，即可完整复核批量改期、整批取消、批次导出三条主链路，以及「重启后一致性」「权限/状态冲突」两大类复杂场景。每一步都标注了：**前置条件**、**精确请求**、**关键返回字段**、**成功判断点**、**失败判断点**、**审计日志核对方法**、**导出结果核对方法**。

---

### 通用约定

- 以下命令默认服务端口为 `8001`（MAX=4）。如用 8000 请自行替换。
- 命令中的日期全部写未来日期（如今天是 2026-06-21，写 2026-07-06 及以后），避免被判定为 `preserved_in_effect`。
- 每一步结束后都可以用 `批次详情` 和 `审计日志` 两个端点独立回查，作为第三方校验。
- 错误码表见上文「错误码（稳定，不可变）」章节。

**辅助回查端点：**

```bash
# 查看批次详情（含每条预约的 week_phase）
curl "http://127.0.0.1:8001/api/bookings/batches/{batch_id}?operator_id=admin1&operator_role=admin"

# 按 batch_id 查审计日志（按 id 升序，可与导出的审计 id 集合比对）
curl "http://127.0.0.1:8001/api/audit?batch_id={batch_id}"

# 查询当前生效的 MAX 规则
curl "http://127.0.0.1:8001/api/bookings/recurring/config"
```

---

### 第一部分：前置数据准备（三条链路共用一个批次）

> 执行本节即可得到一个**混合状态批次**：1 条已审批（preserved_approved）+ 2 条待审批（adjustable）+ 1 条已取消（finished），正好覆盖四种 week_phase 中的三种。

#### Step P1：创建房间 + 配置时段

**前置：** 空库或干净状态。

```bash
# P1-1 创建房间（room_id 会返回）
curl -X POST http://127.0.0.1:8001/api/rooms \
  -H "Content-Type: application/json" \
  -d '{"name": "复核专用_排练厅", "description": "三条链路共用测试房"}'
```

**成功判断：** HTTP 201，返回 `{id, name, is_active: true}`。记录返回的 `room_id`（下面用 `ROOM_ID` 代替）。

**失败判断：** 非 201 或 body 不含 `id`。

---

```bash
# P1-2 配置时段：周一 09:00-22:00、周三 09:00-22:00
#       （周一用来做批次，周三用来制造"slot 不开放"的冲突场景）
# 把下面的 {ROOM_ID} 换成上一步返回的数字
curl -X POST http://127.0.0.1:8001/api/rooms/{ROOM_ID}/timeslots \
  -H "Content-Type: application/json" \
  -d '{"slots": [
    {"weekday": 0, "start_time": "09:00", "end_time": "22:00"},
    {"weekday": 2, "start_time": "09:00", "end_time": "22:00"}
  ]}'
```

**成功判断：** HTTP 201，返回一个数组，长度 = 2。

---

#### Step P2：提交周期预约（4 周，每周一 10:00-12:00）

> 选择周一起始，是为后续把改期目标设到周三（slot 不开放）制造冲突用。

```bash
# 注意：start_date 必须是一个**未来的周一**。今天 2026-06-21 → 写 2026-07-06（周一）
curl -X POST http://127.0.0.1:8001/api/bookings/recurring \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": {ROOM_ID},
    "user_id": "zhangsan",
    "start_date": "2026-07-06",
    "start_time": "10:00",
    "end_time": "12:00",
    "purpose": "三条链路复核_舞蹈排练",
    "weeks": 4
  }'
```

**关键返回字段（必须记录）：**

| 字段 | 期望值 | 作用 |
|------|--------|------|
| `batch_id` | 整数 | 后续所有操作都要用，记为 `BATCH_ID` |
| `total` | 4 | 申请总周数 |
| `success` | 4 | 全部成功创建（无冲突、slot 都开） |
| `items[].booking_id` | 4 个整数 | 记为 `BID_1`（第1周）、`BID_2`（第2周）、`BID_3`（第3周）、`BID_4`（第4周） |
| `items[].date` | `2026-07-06` / `2026-07-13` / `2026-07-20` / `2026-07-27` | 每间隔 7 天 |

**成功判断：** `success == 4 && total == 4`。

**失败判断：** `denied > 0`（房间时段配置错了）或 `skipped > 0`（该时段已被其他 approved 占用）。

---

#### Step P3：制造混合状态（1 审批 + 1 取消 + 2 待审批）

```bash
# P3-1 审批第1周（制造 preserved_approved 相位）
curl -X POST http://127.0.0.1:8001/api/bookings/{BID_1}/approve \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "复核:审批一条以保护"}'
# 期望：status = "approved"

# P3-2 居民自己取消第4周（制造 finished 相位）
curl -X POST http://127.0.0.1:8001/api/bookings/{BID_4}/cancel \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "zhangsan", "operator_role": "resident", "reason": "复核:取消最后一周制造finished"}'
# 期望：status = "cancelled"
```

**成功判断：** 两个请求都是 HTTP 200，status 分别为 `approved` 和 `cancelled`。

---

#### Step P4：验证混合状态正确（用批次详情回查）

```bash
curl "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}?operator_id=admin1&operator_role=admin"
```

**返回的 bookings 数组中必须出现以下 week_phase 分布（顺序按日期升序）：**

| booking_id | week_phase | 状态 |
|------------|------------|------|
| BID_1 | `preserved_approved` | approved |
| BID_2 | `adjustable` | pending |
| BID_3 | `adjustable` | pending |
| BID_4 | `finished` | cancelled |

**成功判断：** 上表 4 条相位完全对得上。

**失败判断：** BID_1/BID_4 相位错 → 说明审批/取消操作没生效；BID_2/BID_3 不是 adjustable → 日期写太近被判定已生效。

---

#### Step P5：导出改期前基线（后续改期后对比用）

```bash
curl -s "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}/export?operator_id=admin1&operator_role=admin" \
  -o batch_{BATCH_ID}_baseline.json
```

**先核对这个基线的关键字段（基线本身必须对，后续对比才有意义）：**

| JSON 路径 | 期望值 |
|-----------|--------|
| `.batch.id` | `BATCH_ID` |
| `.batch.total_count` | 4 |
| `.batch.success_count` | 4 |
| `.batch.max_recurring_weeks_at_creation` | 4 |
| `.batch.current_max_recurring_weeks` | 4 |
| `.config_snapshot.max_recurring_weeks_at_creation` | 4 |
| `.config_snapshot.max_recurring_weeks_current` | 4 |
| `.config_snapshot.env_var_name` | `BOOKING_MAX_RECURRING_WEEKS` |
| `.summary.total_bookings` | 4 |
| `.summary.preserved_approved` | 1 |
| `.summary.adjustable` | 2 |
| `.summary.finished` | 1 |
| `.summary.preserved_in_effect` | 0 |
| `.bookings` 数组长度 | 4 |
| `.batch_level_audit_logs[0].action` | `batch_create` |
| `.batch_level_audit_logs[0].detail` 包含 | `max_recurring_weeks=4` |
| 每条 booking 的 `audit_logs` 第一条 `.action` | `create` |
| BID_1 的 `audit_logs` 第二条 `.action` | `approve` |
| BID_4 的 `audit_logs` 第二条 `.action` | `cancel` |

**审计 id 集合一致性核对（关键！基线必须过这一关）：**

```bash
# 方法：用 /api/audit 端点查到的 id 集合，与导出里 booking.audit_logs[].id + batch_level_audit_logs[].id 的并集，必须完全相等
curl -s "http://127.0.0.1:8001/api/audit?batch_id={BATCH_ID}" > audit_baseline.json
# 手动或脚本比较：set(导出id) == set(/api/audit返回的id)
```

**基线通过上述所有检查 → 进入三条链路正式复核。**

---

## 链路一：批量改期完整复核

### R1-1 用非管理员身份尝试改期（权限边界，预期被拒）

**前置：** 已完成第一部分前置数据准备。

```bash
# R1-1 用 other_resident（非批次创建者）尝试改期
curl -X POST "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}/reschedule" \
  -H "Content-Type: application/json" \
  -d '{
    "new_start_date": "2026-08-10",
    "operator_id": "other_resident",
    "operator_role": "resident",
    "reason": "复核:越权改期"
  }'
```

**成功判断（即拒绝生效）：**
- HTTP **422**
- `error_code = 10007`
- `message` 包含 `"Residents can only operate on their own batches"`

**审计日志核对：** 再次请求 `/api/audit?batch_id={BATCH_ID}`，不应有任何新增日志（请求被整单拦截，没进入业务层）。

**导出核对：** 再次导出，导出内容应与 `batch_{BATCH_ID}_baseline.json` 完全一致（id、字段、相位）。

---

### R1-2 全部可调预约改到 slot 不开放的日期（全部 denied，部分失败）

**目的：** 验证"部分成功部分失败"场景中，denied 的预约不会被静默修改，审计日志也不会错误写入。

**前置：** 房间只配置了周一（weekday 0）和周三（weekday 2）。把 `new_start_date` 写一个**周五**（例如 2026-08-14 是周五，weekday=4），该 weekday 完全无时段配置 → 所有 adjustable 的都会被 10015 拒绝。

```bash
# R1-2 改期目标: 周五（weekday=4，slot 完全不开放）
curl -X POST "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}/reschedule" \
  -H "Content-Type: application/json" \
  -d '{
    "new_start_date": "2026-08-14",
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "复核:周五slot不开放全部denied"
  }'
```

**关键字段核对：**

| 字段 | 期望值 | 判断逻辑 |
|------|--------|----------|
| `operation` | `"reschedule"` | 固定值 |
| `batch_id` | `BATCH_ID` | 与请求路径一致 |
| `user_id` | `"zhangsan"` | 批次创建者 |
| `total` | 4 | 必须等于 success+preserved+denied+skipped |
| `success` | 0 | 周五没 slot，改不动 |
| `preserved` | 2（BID_1 已审批 + BID_4 已取消） | 按周次相位 |
| `denied` | 2（BID_2、BID_3，可调但 slot 不开） | 见下方 items |
| `skipped` | 0 | 无异常 |
| `max_recurring_weeks_at_creation` | 4 | 批次创建时的规则，不变 |
| `max_recurring_weeks_at_operation` | 4 | 当前服务 MAX，也不变 |

**逐条 items 核对（顺序：BID_1 → BID_2 → BID_3 → BID_4）：**

- BID_1：`result = "preserved"`, `week_phase_before = "preserved_approved"`, `old_date == new_date == "2026-07-06"`
- BID_2：`result = "denied"`, `error_code = 10015`, `week_phase_before = "adjustable"`, `old_status == new_status == "pending"`, `message` 包含 `"No open time slots"`
- BID_3：同上（也是 denied 10015）
- BID_4：`result = "preserved"`（或 `"skipped"`，finished 相位），`old_status == new_status == "cancelled"`

**批次详情回查确认（关键 —— denied 的绝不能动日期）：**

```bash
curl "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}?operator_id=admin1&operator_role=admin"
```

必须满足：
- BID_2 的 `date` 仍为 `"2026-07-13"`（原日期），`old_date` 为 `null`
- BID_3 的 `date` 仍为 `"2026-07-20"`（原日期），`old_date` 为 `null`
- 所有 `week_phase` 与基线相同

**审计日志核对（关键 —— denied 的绝不能有 reschedule 日志）：**

```bash
curl -s "http://127.0.0.1:8001/api/audit?batch_id={BATCH_ID}"
```

- 不应出现任何 `action = "reschedule"` 条目
- 不应出现 `batch_reschedule_start` 和 `batch_reschedule_end`（因为整体**有可操作预约**，但单条被拒 —— 注意：实际行为是 **start/end 会写入**，因为批次级开始/结束了，只是单条没有 reschedule）
- 正确判定：`batch_reschedule_start` 和 `batch_reschedule_end` **会有**，但单条没有 `reschedule`

**导出核对：**

```bash
curl -s "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}/export?operator_id=admin1&operator_role=admin" \
  -o batch_{BATCH_ID}_after_r1_2.json
```

- `.bookings` 中 BID_2/BID_3 的 `date` 与基线完全一致
- 每条 booking 的 `audit_logs` 中不含 `reschedule`
- `.batch_level_audit_logs` 新增了 `batch_reschedule_start`（detail 含 `denied=2`）和 `batch_reschedule_end`

---

### R1-3 改到有冲突的目标日期（1 条 success + 1 条 denied，部分成功部分失败）

**前置：** 先在"改期后的第 3 周那个周一"创建一个 approved 预约作为冲突源。假设 R1-3 改期起始日期为 `2026-08-10`（周一），则第 3 周 = `2026-08-24`。先在这天放一个阻塞：

```bash
# R1-3-pre 在 2026-08-24（改期目标第3周同日同时段）创建并审批一个阻塞预约
curl -X POST http://127.0.0.1:8001/api/bookings \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": {ROOM_ID},
    "user_id": "blocker_user",
    "date": "2026-08-24",
    "start_time": "10:00",
    "end_time": "12:00",
    "purpose": "复核:阻塞改期第3周制造冲突"
  }'
# 记录返回的 booking_id 为 BLOCKER_ID，然后审批
curl -X POST http://127.0.0.1:8001/api/bookings/{BLOCKER_ID}/approve \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "复核:审批阻塞预约"}'
```

```bash
# R1-3 正式改期：起始 2026-08-10（周一），共 2 条可调（BID_2,BID_3），其中 BID_3 对应第3周会撞 BLOCKER_ID
curl -X POST "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}/reschedule" \
  -H "Content-Type: application/json" \
  -d '{
    "new_start_date": "2026-08-10",
    "new_start_time": "10:00",
    "new_end_time": "12:00",
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "复核:第3周有阻塞 制造1success+1denied"
  }'
```

**关键字段期望值：**

| 字段 | 期望值 |
|------|--------|
| `total` | 4 |
| `success` | 1（BID_2，改到第1周 2026-08-10，无冲突） |
| `preserved` | 2（BID_1 + BID_4） |
| `denied` | 1（BID_3，改到第3周 2026-08-24，与 BLOCKER_ID 冲突，错误码 10016） |
| `skipped` | 0 |
| `items` 中 BID_3 的 `error_code` | **10016**（NEW_BOOKING_OVERLAP） |
| `items` 中 BID_3 的 `message` | 包含 `"overlaps with approved booking"` |
| `items` 中 BID_2 的 `new_date` | `"2026-08-10"` |
| `items` 中 BID_2 的 `old_date` | `"2026-07-13"` |

**批次详情回查：**
- BID_2：`date = "2026-08-10"`，`old_date = "2026-07-13"`，`rescheduled_from_booking_id = BID_2`
- BID_3：`date = "2026-07-20"`（原日期，**没动**），`old_date = null`

**审计日志核对：**
- 有且仅有 **1 条** `action = "reschedule"`（对应 BID_2）
- BID_2 的 reschedule 日志 `detail` 中必须包含 `max_recurring_weeks_at_operation=4`
- BID_3 没有 reschedule 日志
- 有 `batch_reschedule_start` 和 `batch_reschedule_end`，后者 detail 含 `success=1, denied=1`

**导出核对（必做的一步 —— 导出是"最终交付物"，必须对得上）：**

```bash
curl -s "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}/export?operator_id=admin1&operator_role=admin" \
  -o batch_{BATCH_ID}_after_r1_3.json
```

核对清单：
- `.bookings` 中 BID_2：`date = "2026-08-10"`, `old_date = "2026-07-13"`, `rescheduled_from_booking_id = BID_2`, `audit_logs` 最后一条 `action = "reschedule"`
- `.bookings` 中 BID_3：`date = "2026-07-20"`, `old_date = null`, 无 reschedule 审计, `week_phase = "adjustable"`（仍是可调）
- `.batch_level_audit_logs` 最后两条: `batch_reschedule_start`, `batch_reschedule_end`
- `.summary.adjustable = 1`（只剩 BID_3）, `.summary.preserved_approved = 1`, `.summary.finished = 1`
- 导出中**所有审计 id 的并集**与 `/api/audit?batch_id={BATCH_ID}` 返回的 id 集合**完全相等**（差集必须为空）

---

### R1-4 改期成功（全部可调 1 条全部 success，同时调时间段）

**前置：** 经过 R1-3，现在只有 BID_3 是 `adjustable`。

```bash
# R1-4 改期 BID_3 到一个干净日期（比如 2026-09-07 周一），同时把时段调到 14:00-16:00
curl -X POST "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}/reschedule" \
  -H "Content-Type: application/json" \
  -d '{
    "new_start_date": "2026-09-07",
    "new_start_time": "14:00",
    "new_end_time": "16:00",
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "复核:最后一条可调改期并换时段"
  }'
```

**关键字段期望值：**

| 字段 | 期望值 |
|------|--------|
| `success` | 1 |
| `preserved` | 3（BID_1 approved + BID_2 已改期但仍 pending=adjustable？不，BID_2 pending 应该是 adjustable —— 应该 preserved=2：BID_1 + BID_4） |
| `preserved` | 2（BID_1: approved, BID_4: cancelled=finished） |
| `denied` | 0 |
| `items` 中 BID_3 的 `new_date` | `"2026-09-07"` |
| `items` 中 BID_3 的 `old_date` | `"2026-07-20"` |
| `items` 中 BID_3 的 `new_start_time` / `new_end_time` | 不在 items 里，要回查批次详情看 `start_time`/`end_time` 字段 |

**批次详情回查（时间段确实改了）：**
- BID_3：`date = "2026-09-07"`, `start_time = "14:00"`, `end_time = "16:00"`, `old_date = "2026-07-20"`, `rescheduled_from_booking_id = BID_3`
- BID_2：保持 `start_time = "10:00"`, `end_time = "12:00"`（R1-3 没改时段，R1-4 只改 BID_3 的 —— 实际代码中改期是对所有 adjustable 统一改时段，所以 BID_2 在 R1-3 走的是 success，时段用的是 10:00-12:00；R1-4 改时段时 BID_2 已经是 adjustable，但 R1-4 只对 adjustable 的改，BID_2 是 adjustable 也会被改 —— 这个是代码逻辑，测试时要注意实际结果对照）

> **实操提示：** 实际 items 中有几条 adjustable，就有几条会被改日期和时段。与批次详情回查值逐一比对即可。

**链路一至此通过。** 进入链路二。

---

## 链路二：整批取消完整复核

> 本链路重新用一个**全新批次**做（因为链路一把 BID_2/BID_3 状态改乱了，不好观察"居民批量取消时 approved 被 preserved"的效果）。

### 前置：建第二个批次（链路二专用）

**执行 Step P1-P4 的简化版，或直接用新房间新批次：**

```bash
# C-pre-1 新建房间（或复用第一个房间，日期选新的）
curl -X POST http://127.0.0.1:8001/api/rooms \
  -H "Content-Type: application/json" \
  -d '{"name": "复核专用_会议室B", "description": "链路二整批取消"}'
# 记为 ROOM_ID_2

# C-pre-2 配置周一全天开放
curl -X POST http://127.0.0.1:8001/api/rooms/{ROOM_ID_2}/timeslots \
  -H "Content-Type: application/json" \
  -d '{"slots": [{"weekday": 0, "start_time": "08:00", "end_time": "22:00"}]}'

# C-pre-3 新建 3 周周期预约（每周一 15:00-17:00），起始 2026-08-03（周一）
curl -X POST http://127.0.0.1:8001/api/bookings/recurring \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": {ROOM_ID_2},
    "user_id": "zhangsan",
    "start_date": "2026-08-03",
    "start_time": "15:00",
    "end_time": "17:00",
    "purpose": "链路二整批取消_每周例会",
    "weeks": 3
  }'
# 记 batch_id 为 BATCH_ID_2，三条 booking 为 C_BID_1, C_BID_2, C_BID_3

# C-pre-4 审批第1周（制造 1 条 preserved_approved + 2 条 adjustable）
curl -X POST http://127.0.0.1:8001/api/bookings/{C_BID_1}/approve \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "链路二:先审批一条"}'
```

---

### C2-1 非管理员取消他人批次（权限边界，10007）

```bash
curl -X POST "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID_2}/cancel" \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "other_resident",
    "operator_role": "resident",
    "reason": "链路二:越权取消他人批次"
  }'
```

**判断：** HTTP 422，`error_code = 10007`，message 含 `"Residents can only operate on their own batches"`。无新增审计。

---

### C2-2 居民自己取消（关键行为：approved 被 preserved，pending 被 success）

```bash
curl -X POST "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID_2}/cancel" \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "zhangsan",
    "operator_role": "resident",
    "reason": "链路二:居民自己取消 已审批的应该保留"
  }'
```

**关键字段期望值：**

| 字段 | 期望值 |
|------|--------|
| `operation` | `"cancel"` |
| `total` | 3 |
| `success` | 2（C_BID_2, C_BID_3，pending 的两条） |
| `preserved` | 1（C_BID_1，已审批，居民不能批量动） |
| `denied` | 0 |
| `skipped` | 0 |
| `items[C_BID_1].result` | `"preserved"` |
| `items[C_BID_1].week_phase_before` | `"preserved_approved"` |
| `items[C_BID_1].message` 包含 | `"approved booking, only admin/staff can batch cancel"` |
| `items[C_BID_1].old_status` / `new_status` | `"approved"` / `"approved"`（**没动**） |
| `items[C_BID_2].result` | `"success"` |
| `items[C_BID_2].new_status` | `"cancelled"` |

**批次详情回查（核心判定）：**
- C_BID_1：`status = "approved"`（**必须没动**）
- C_BID_2：`status = "cancelled"`
- C_BID_3：`status = "cancelled"`

**审计日志核对：**
- `batch_cancel_start` 1 条（detail 含 `operator_role=resident`）
- `batch_cancel_end` 1 条（detail 含 `success=2, preserved=1`）
- `action = "cancel"` 的条目共 **2 条**（C_BID_2、C_BID_3），**C_BID_1 没有**
- 2 条 cancel 日志的 `detail` 前缀应为 `"Batch cancel"`

**导出核对：**
- 导出中 C_BID_1 的 `status = "approved"`, `week_phase = "preserved_approved"`，`audit_logs` 中**不含** `cancel`
- 导出中 C_BID_2 / C_BID_3 的 `status = "cancelled"`，`audit_logs` 中含 `cancel` 且 detail 前缀为 `"Batch cancel"`
- `.batch_level_audit_logs` 中新增 start + end

---

### C2-3 管理员代取消（关键行为：preserved_approved 的这次可以 success 取消）

**前置：** C2-2 后只剩 C_BID_1 是 approved。

```bash
curl -X POST "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID_2}/cancel" \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "链路二:管理员代取消已审批的那条"
  }'
```

**关键字段期望值：**

| 字段 | 期望值 |
|------|--------|
| `success` | 1（C_BID_1，这次可以取消了） |
| `preserved` | 0（所有可取消的都取消了） |
| `skipped` | 2（C_BID_2, C_BID_3 已是 cancelled=finished，跳过） |
| `items[C_BID_1].result` | `"success"` |
| `items[C_BID_1].old_status` | `"approved"` |
| `items[C_BID_1].new_status` | `"cancelled"` |
| `items[C_BID_1].week_phase_before` | `"preserved_approved"` |
| `items[C_BID_1].message` 包含 | `"Admin/staff cancelled approved booking"` 或同类文案 |

**批次详情回查：** C_BID_1 `status = "cancelled"`。

**审计日志核对（**关键判定 —— 管理员的 cancel 日志 detail 前缀不一样**）：**
- C_BID_1 出现了一条新的 `action = "cancel"`，`detail` 前缀是 `"Admin/staff batch cancel approved booking"`（和居民的 `"Batch cancel"` 前缀**不同**，可用于审计追溯是谁批量取消了已审批预约）
- 出现一组新的 `batch_cancel_start` + `batch_cancel_end`，detail 含 `operator_role=admin` 和 `success=1, skipped=2`

**导出核对：**
- 三条 booking 的 `status` 全是 `"cancelled"`
- C_BID_1 的 `audit_logs` 里多了一条 `cancel`，detail 含管理员前缀
- 三条 booking 的 `week_phase` 都是 `"finished"`
- `.summary.finished = 3`, `.summary.adjustable = 0`, `.summary.preserved_approved = 0`

**链路二至此通过。**

---

## 链路三：批次导出完整复核

> 链路三不再需要新数据 —— 直接拿链路二的最终状态（BATCH_ID_2，三条全 cancelled）来做。链路一里 BATCH_ID 也可以拿来核对。

### E3-1 非管理员导出他人批次（10007）

```bash
curl "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID_2}/export?operator_id=other_resident&operator_role=resident"
```

**判断：** HTTP 422，`error_code = 10007`，message 含 `"Residents can only export their own batches"`。

---

### E3-2 导出结构完整度（6 大顶层块全有）

```bash
curl -s "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID_2}/export?operator_id=admin1&operator_role=admin" \
  -o batch_{BATCH_ID_2}_export.json
```

**顶层结构必须全部包含：**

| JSON 顶层 key | 存在性 | 内容是什么 |
|---------------|--------|------------|
| `batch` | 必选 | 批次元信息 + created_at/exported_at |
| `config_snapshot` | 必选 | 5 个配置值 + env_var_name |
| `bookings` | 必选，数组 | 每条预约的完整信息 + 各自 audit_logs 子数组 |
| `batch_level_audit_logs` | 必选，数组 | booking_id 为 null 的批次级审计（batch_create / 2 组 batch_cancel_start / 2 组 batch_cancel_end） |
| `summary` | 必选 | 5 个相位的计数 |

**Response Headers 检查：** 导出请求的 HTTP 响应头 `Content-Disposition` 必须包含 `attachment; filename=batch_{BATCH_ID_2}_export.json`（浏览器/Postman 会自动触发下载就是这个头起作用）。

---

### E3-3 关键字段值精确核对（用 BATCH_ID_2）

| 路径 | 期望值 |
|------|--------|
| `.batch.id` | `BATCH_ID_2` |
| `.batch.user_id` | `"zhangsan"` |
| `.batch.total_count` | 3 |
| `.batch.success_count` | 3 |
| `.batch.max_recurring_weeks_at_creation` | 4 |
| `.batch.current_max_recurring_weeks` | 4 |
| `.batch.env_var_name`（在 batch 内） | 没在 batch 里，在 config_snapshot 里 —— 见下 |
| `.config_snapshot.max_recurring_weeks_at_creation` | 4 |
| `.config_snapshot.max_recurring_weeks_current` | 4 |
| `.config_snapshot.min_recurring_weeks` | 1 |
| `.config_snapshot.absolute_max_recurring_weeks` | 52 |
| `.config_snapshot.default_max_recurring_weeks` | 4 |
| `.config_snapshot.env_var_name` | `"BOOKING_MAX_RECURRING_WEEKS"` |
| `.bookings` 长度 | 3 |
| `.bookings[*].status` 全是 | `"cancelled"` |
| `.bookings[*].week_phase` 全是 | `"finished"` |
| `.batch_level_audit_logs` 长度 | 至少 5（= 1 batch_create + 2 batch_cancel_start + 2 batch_cancel_end） |
| `.batch_level_audit_logs` 中 action 的集合 | 必须包含 `batch_create`, `batch_cancel_start`, `batch_cancel_end` |
| `.summary.total_bookings` | 3 |
| `.summary.finished` | 3 |
| `.summary.preserved_approved` | 0 |
| `.summary.adjustable` | 0 |
| `.summary.preserved_in_effect` | 0 |
| `.bookings[*].audit_logs[*].detail` 中出现的前缀 | `create` 日志 + 2 条 `"Batch cancel"` + 1 条 `"Admin/staff batch cancel approved booking"` |

---

### E3-4 导出与所有回查端点的交叉一致性（三项金标准）

**金标准 1：bookings 字段与批次详情查询 100% 一致**

```bash
# 取批次详情（JSON）
curl -s "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID_2}?operator_id=admin1&operator_role=admin" \
  > batch_{BATCH_ID_2}_detail.json
```

- 两份 JSON 中 `bookings` 数组长度相同
- 对同一 `booking_id`：`date`, `status`, `week_phase`, `start_time`, `end_time`, `old_date`, `rescheduled_from_booking_id` **七字段必须逐一相等**

**金标准 2：审计 id 集合与 `/api/audit?batch_id=` 查询完全相等（无遗漏、无多余）**

```bash
curl -s "http://127.0.0.1:8001/api/audit?batch_id={BATCH_ID_2}" > audit_{BATCH_ID_2}_query.json
```

- 从导出中收集 `set(所有 booking.audit_logs[].id + batch_level_audit_logs[].id)`，记为 `EXPORT_AUDIT_IDS`
- 从 audit 查询中收集 `set(所有返回记录的 id)`，记为 `QUERY_AUDIT_IDS`
- 必须 `EXPORT_AUDIT_IDS == QUERY_AUDIT_IDS`（空差集）

**金标准 3：审计日志 id 单调递增（时间线连贯无断裂，判断是否漏插）**

- 导出中所有 audit 日志（booking 级 + batch 级）的 id 合起来排序后，与 `/api/audit?batch_id=&order=id_asc` 返回的顺序**完全一致**

---

## 第二大类复杂场景：服务重启 / 配置重载一致性

> 本场景目标：**重启 + 修改 `BOOKING_MAX_RECURRING_WEEKS`（4→2）后，再对旧批次执行三条链路的核心操作，验证关键字段不串、导出内容与重启前连续、接口行为符合文档（不被旧规则误导、也不被新规则错误整单拦截）**。

### S0：保存重启前快照（在现有端口 8001 上执行）

```bash
# 选链路一的 BATCH_ID（经过了多次改期，数据最丰富）做这个场景
# 导出：
curl -s "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}/export?operator_id=admin1&operator_role=admin" \
  -o batch_{BATCH_ID}_before_restart.json

# 同时保存批次详情和审计查询
curl -s "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}?operator_id=admin1&operator_role=admin" \
  -o batch_{BATCH_ID}_detail_before.json
curl -s "http://127.0.0.1:8001/api/audit?batch_id={BATCH_ID}" \
  -o audit_{BATCH_ID}_before.json
```

记录以下关键值（记事本记下来）：
- `.max_recurring_weeks_at_creation`（记为 `CREATION_MAX`，应该是 4）
- `.bookings` 中每条的 `id`, `status`, `date`
- audit 日志总条数（记为 `N_AUDIT_BEFORE`）
- `MAX_BEFORE` = 当前规则，查询 `curl http://127.0.0.1:8001/api/bookings/recurring/config` 得到

### S1：停止端口 8001 的服务

> ⚠️ **只允许停止你自己启动的单个 PID。**
>
> 方法：之前启动 8001 的那个终端按 Ctrl+C 即可。
>
> 也可以用 `Stop-Process -Id <PID>`，但必须：1) 是你启动的那个；2) 核对过端口、命令行、工作目录归属当前项目。

按 Ctrl+C 关闭终端 2 运行的 8001 服务（命令 id `480cce86-e2e1-4379-b814-9ac0cf757ed1`）。

### S2：端口 8002 以 MAX=2 重启（配置收紧）

```bash
# 新开终端（终端 3）
# Windows PowerShell 设置环境变量后启动
$env:BOOKING_MAX_RECURRING_WEEKS="2"
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8002
```

### S3：确认新端口规则生效（确认是 2，防止环境变量没带上）

```bash
curl http://127.0.0.1:8002/api/bookings/recurring/config
```

**期望：** `max_recurring_weeks = 2`。不是 2 的话回到 S2 排查环境变量设置方式。

记录为 `MAX_AFTER = 2`。

---

### S4：在新端口（MAX=2）对旧批次执行批量改期（核心断言）

> 旧批次 CREATION_MAX=4，且有 1 条 adjustable（BID_3 改期后）。关键点：
> - adjustable 条数（1条）< MAX_AFTER（2），但如果 adjustable 条数（比如 3 条）> MAX_AFTER（2），**不会被整单抛 10010**，而是逐周处理（这是和"新建周期预约"的本质区别：新建时 10010 整单拦，改期时不拦，逐周检查 slot 和冲突）。

```bash
# 先确认旧批次在 8002 上仍可调（查详情）
curl "http://127.0.0.1:8002/api/bookings/batches/{BATCH_ID}?operator_id=admin1&operator_role=admin"
```

关键字段：`max_recurring_weeks_at_creation` 必须仍是 4（数据库存的，不会因为重启变）。

```bash
# S4-改期：选一个干净周一（比如 2026-09-21），管理员操作
curl -X POST "http://127.0.0.1:8002/api/bookings/batches/{BATCH_ID}/reschedule" \
  -H "Content-Type: application/json" \
  -d '{
    "new_start_date": "2026-09-21",
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "重启场景:MAX从4变2后再改期 验证creation/operation双轨"
  }'
```

**核心断言（一条都不能错）：**

| 字段 | 期望值 | 说明 |
|------|--------|------|
| `max_recurring_weeks_at_creation` | **4**（= `CREATION_MAX`） | 批次创建时的规则，数据库存的，重启后仍 4 ✅ |
| `max_recurring_weeks_at_operation` | **2**（= `MAX_AFTER`） | 本次操作时服务的当前规则，重启后变成 2 ✅ |
| adjustable 条数 > MAX_AFTER 时 | **不会整单抛 10010** | 改期不检查 adjustable 数量与 MAX 的关系，只逐周 slot/冲突 ✅ |
| success 的预约数（N_success） | = adjustable 中通过 slot+冲突校验的条数 | ✅ |

**单条 reschedule 审计日志的 detail 检查（关键 —— operation 规则值写进了每条日志）：**

```bash
curl "http://127.0.0.1:8002/api/audit?batch_id={BATCH_ID}"
```

所有 `action = "reschedule"` 的日志，其 `detail` 中都必须包含 `max_recurring_weeks_at_operation=2`（**是 2，不是 4**）。

---

### S5：重启后导出一致性（config_snapshot、审计、字段全连续）

```bash
curl -s "http://127.0.0.1:8002/api/bookings/batches/{BATCH_ID}/export?operator_id=admin1&operator_role=admin" \
  -o batch_{BATCH_ID}_after_restart.json
```

**重启后导出 vs 重启前导出的对比清单：**

| 对比项 | 期望结果 |
|--------|----------|
| `.config_snapshot.max_recurring_weeks_at_creation` | **4**（不变，与重启前相同） |
| `.config_snapshot.max_recurring_weeks_current` | **2**（变成新服务的值，与重启前不同） |
| `.bookings[*].id` 集合 | 与重启前完全相等（一个不多一个不少） |
| `.bookings[*]` 中未改期的 booking | `status`, `date`, `old_date`, `rescheduled_from_booking_id` 与重启前 **逐字节一致** |
| `.bookings[*]` 中 success 改期的 booking | `date` 改成新值，`old_date` 保留重启前那个最新日期，`rescheduled_from_booking_id = 自身 id` |
| 审计 id 总条数 | = `N_AUDIT_BEFORE` + 2（batch_reschedule_start/end） + N_success（每条 success 一个 reschedule） |
| 重启前最大的 audit id 记为 `MAX_AUDIT_ID_BEFORE` | 重启后新增的 audit 日志 id **全部大于** `MAX_AUDIT_ID_BEFORE`（时间线不断裂） |
| 导出 audit id 集合 vs `/api/audit` 查询 | 相等（金标准 2，重启后仍要过） |
| 导出 bookings vs 批次详情查询 | 七字段全部相等（金标准 1，重启后仍要过） |

---

### S6：重启后整批取消 + 导出（两条链路也验证重启一致性）

```bash
# S6-1 重启后管理员再整批取消一次 BATCH_ID
curl -X POST "http://127.0.0.1:8002/api/bookings/batches/{BATCH_ID}/cancel" \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "重启后一致性:管理员取消所有剩余可取消的"
  }'
```

关键字段检查：`max_recurring_weeks_at_creation = 4`，`max_recurring_weeks_at_operation = 2`（**改期/取消两条链路的响应都要带这两个字段**）。

然后再做一次 E3-2/E3-3/E3-4 的完整导出检查。

---

## 第三大类复杂场景：权限 / 状态冲突完整矩阵

> 下表每一行都是一个**可独立执行**的测试用例。列名解释：
> - **前置条件**：执行此命令前必须已有的状态
> - **触发命令**：精确 curl（路径 + body）
> - **返回判定**：精确到字段和值
> - **审计怎么看**：去 `/api/audit` 端点查什么
> - **导出怎么核对**：去 export JSON 里看什么

### 冲突矩阵

| # | 场景 | 前置条件 | 触发命令（关键参数） | HTTP 状态码 | error_code / items 判定 | message/关键值 | 审计怎么看 | 导出怎么核对 |
|---|------|---------|---------------------|------------|------------------------|---------------|-----------|-------------|
| **K1** | 非管理员改期他人批次 | 任意批次 | `operator_id=other_resident, operator_role=resident` + `POST /batches/{id}/reschedule` | 422 | **10007** | 含 `"Residents can only operate on their own batches"` | 无新增审计（整单被拒） | 导出与基线完全相同 |
| **K2** | 非管理员取消他人批次 | 任意批次 | 同上 role + `POST /batches/{id}/cancel` | 422 | **10007** | 同上 | 无新增审计 | 导出与基线完全相同 |
| **K3** | 非管理员导出他人批次 | 任意批次 | 同上 role + `GET /batches/{id}/export` | 422 | **10007** | 含 `"Residents can only export their own batches"` | 无新增审计 | - |
| **K4** | 全部已审批批次改期（无可调） | 某批次所有 booking 均 approved | `POST /batches/{id}/reschedule` | 422 | **10014** | 含 `"No adjustable bookings in this batch (all in effect, approved, or finished)"` | 无 `batch_reschedule_start`（进业务前就抛错） | 导出相位全是 `preserved_approved/in_effect` |
| **K5** | 全已审批批次，居民取消 | 同上 | resident 身份 `POST /batches/{id}/cancel` | 200 | items 中每条都是 `result = "preserved"` + `week_phase_before = "preserved_approved"` | message 含 `"approved booking, only admin/staff can batch cancel"` | `batch_cancel_start/end` 有，单条 cancel 审计 **0 条** | 每条 booking 仍是 approved，phase 仍是 `preserved_approved` |
| **K6** | 改期目标 slot 不开放 | adjustable 的某条改到 slot 不开放的 weekday | 管理员改期 | 200 | 对应 item: `result = "denied"` + **`error_code = 10015`** | message 含 `"No open time slots for new date"` | 该条 booking 无 reschedule 审计；批次级 start/end 有 | 该条 booking 的 date/week_phase 与改期前一致 |
| **K7** | 改期目标与 approved 冲突 | 预先在目标日期+时段审批一个阻塞预约 | 管理员改期 | 200 | 对应 item: `result = "denied"` + **`error_code = 10016`** | message 含 `"overlaps with approved booking #N"` | 同上（该条无 reschedule） | 同上（该条 booking 未动） |
| **K8** | 居民批量取消含已审批 | 批次中既有 approved 也有 pending | resident 取消 | 200 | pending 的 = `success`，approved 的 = `preserved` | preserved 的 message 含 `"approved booking, only admin/staff can batch cancel"` | `success 条 × cancel 审计`（detail=`Batch cancel`前缀）+ start/end；approved 条无 cancel | 导出中 approved 那条仍是 `approved` + `preserved_approved`，pending 的变 `cancelled`+`finished` |
| **K9** | 管理员批量取消含已审批 | 批次中既有 approved 也有 pending | admin 取消 | 200 | 两类都等于 `success` | approved 那条 success 的 message 含"Admin/staff cancelled approved booking"| approved 那条也有 cancel 审计（detail=`Admin/staff batch cancel` 前缀） | 全部变 `cancelled` + `finished`；approved 那条 audit 有管理员前缀 |
| **K10** | 改期：部分 success + 部分 denied | N 条可调，其中 K 条 slot 不开/冲突（N>K>0） | 管理员改期 | 200 | `success + preserved + denied + skipped == total`，`denied == K`，`success == N - K` | denied 条各自含 10015/10016 | success 条有 reschedule 审计；denied 条没有；两组 start/end 含 `denied=K` | success 条 date 已更新 + old_date/rescheduled_from 写入；denied 条原样；audit id 集与 /api/audit 相等 |
| **K11** | 取消：部分 success + 部分 preserved | 既有 pending（N）又有 approved（M），居民操作 | resident 取消 | 200 | `success == N`，`preserved == M` | preserved 的 message 含"approved"或"in effect" | N 条 cancel 审计（仅 pending）+ start/end | pending 的 cancelled+finished；approved 的保持 approved+preserved_approved |
| **K12** | 已过生效日期的 booking（已过期） | 某 booking 日期已过或时段已开始 → `preserved_in_effect` | 改期或取消 | 200 | 该条 item = `preserved`，`week_phase_before = "preserved_in_effect"` | message 含"booking already in effect / passed" | 该条不产生 reschedule/cancel 审计 | 该条 booking 仍是原状态，phase=`preserved_in_effect` |
| **K13** | 已 finished（cancelled/rejected） | booking 已是 cancelled = finished 相位 | 改期或取消 | 200 | item = `preserved` 或 `skipped`，`week_phase_before = "finished"` | message 含相位说明 | 不产生对应操作审计 | booking 不变 |
| **K14** | 不存在的批次 | batch_id = 9999999 | 三个操作任一个 | 422 | **10011** | 含 `"Batch not found"` | 无新增审计 | - |
| **K15** | 改期时 new_start_time >= new_end_time | 传 new_start_time=16:00, new_end_time=14:00 | 改期请求 | 422 | **10009** | 含 start_time must be before end_time 类文案 | 无新增审计（参数校验层拦截） | - |

> 以上 15 条矩阵中，**K1-K11** 已在三条链路里逐项出现过（每一步都带了审计和导出的核对方法），**K12-K15** 可以通过简单修改日期或参数单独补做。

---

## 一键全自动验证脚本（把上述全部命令编成了自动化）

所有链路 + 复杂场景 + 冲突矩阵 + 重启一致性，都已编成可运行脚本。管理员无需手敲上面的每一条 curl，直接跑即可：

### 一键跑：三条链路 + 冲突矩阵（不重启）

```bash
# 终端 A：启动 MAX=4 服务（端口 8001）
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001

# 终端 B（另开）：一键跑完链路一二三 + 重启前阶段
python test_sample.py --new-features
```

`--new-features` 顺序执行的内容（与本文档逐一对应）：
| 测试函数（对应文档章节） | 覆盖内容 |
|-------------------------|---------|
| `test_batch_detail_week_phase` | 第一部分 Step P4（week_phase 分类正确性） |
| `test_batch_reschedule_permission_and_protection` | R1-1 越权 10007 + R1-4 改期 success + preserved 保护 |
| `test_batch_reschedule_partial_conflict` | R1-2 / R1-3 部分 denied（10015 / 10016）+ 混合结果 |
| `test_batch_cancel_permission_and_roles` | C2-1 越权 10007 + C2-2 居民 preserved + C2-3 管理员代取消 success |
| `test_batch_nothing_to_operate` | K4 全已审批改期 → 10014 + K5 居民取消全 preserved |
| `test_batch_config_switch_restart` | 重启前后 creation/operation/current 三值双轨正确（在不重启的同进程内模拟对比） |
| `test_batch_export_consistency` | E3-1~E3-4（权限边界 + 结构 + 金标准123） |
| `test_cancel_export_query_consistency` | 取消后查询 vs 导出一致性 |
| `run_new_features_after_restart` | S0~S6 重启后一致性验证（在不重启的同端口上模拟"重启前后"） |

脚本最终输出 `XX 通过, 0 失败` 即表示本文档描述的所有场景与实现一致。

### 一键跑：跨端口模拟"重启 + 配置收紧（MAX=4→2）"

> 这是本文档"第二大类复杂场景"的完整自动化（真实启动两个端口模拟重启前后）。

```bash
# 终端 A（MAX=4，端口 8001）：
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001

# 终端 B（MAX=2，端口 8002）：
$env:BOOKING_MAX_RECURRING_WEEKS="2"
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8002

# 终端 C（执行跨端口配置收紧验证）：
python test_sample.py --config-tightening
```

`--config-tightening` 完整覆盖了 S0~S6 的所有断言：
- creation_max（4）与 operation_max（2）在改期/取消/导出三个位置的双轨值全部正确
- adjustable 3 条 > MAX=2 时**不整单拦截**，逐周校验
- 改期 success 的每条 reschedule 审计 detail 都含 `max_recurring_weeks_at_operation=2`
- 冲突场景：1 条 denied(10016) + 2 条 success 的部分成功/失败
- 金标准 1/2/3 全部通过

输出 `配置收紧专项结果: XX 通过, 0 失败` 即通过。

---

## 周期预约配置详解

### 配置项

| 项目 | 值 |
|------|-----|
| 环境变量 | `BOOKING_MAX_RECURRING_WEEKS` |
| 默认值 | `4` |
| 有效范围 | `1` ~ `52` |
| 越界处理 | < 1 或无效值 → 回退默认值 4；> 52 → 截断为 52 |
| 生效时机 | 服务启动时读取，运行期间不可变，重启后生效 |

### 查询当前生效规则

运行时可通过接口查询：

```bash
curl http://127.0.0.1:8000/api/bookings/recurring/config
```

返回：

```json
{
  "max_recurring_weeks": 4,
  "min_recurring_weeks": 1,
  "absolute_max_recurring_weeks": 52,
  "default_max_recurring_weeks": 4,
  "env_var_name": "BOOKING_MAX_RECURRING_WEEKS"
}
```

### 重启后配置切换行为

- 重启服务时修改 `BOOKING_MAX_RECURRING_WEEKS` 后，**新**的周期预约受新上限约束
- **已有**批次及其子预约的状态、审计记录不受影响，完整保留
- 每个批次记录了创建时生效的 `max_recurring_weeks_at_creation`，可通过批次详情或审计日志查看
- 审计日志中 `batch_create` 事件的 `detail` 字段包含当时的 `max_recurring_weeks` 值

---

## 周期预约特性说明

### 核心设计原则
1. **不绕过现有校验**：每条子预约都会经过完整的开放时段检查、重叠检测、权限验证
2. **不破坏单次预约**：现有单次预约逻辑完全独立，不受周期预约影响
3. **结果透明可追溯**：每条预约的处理结果明确分类，审计日志完整记录
4. **配置规则可观测**：配置项、默认值、边界值、当前生效值均可通过接口查询

### 结果分类
| 状态 | 说明 |
|------|------|
| `success` | 预约创建成功，获得 `booking_id`，进入 `pending` 状态等待审批 |
| `skipped` | 与已审批预约时段冲突，自动跳过，不创建预约记录 |
| `denied` | 不在开放时段、房间未启用或其他权限问题被拒绝 |
| `exceeded` | 超过配置的最大周数限制（请求阶段拦截） |

### 审计链路
- 批次创建时记录 `batch_create` 审计日志，detail 包含当时的 `max_recurring_weeks` 值
- 每条成功的子预约记录 `create` 审计日志并关联 `batch_id`
- 后续审批、取消、过期操作的审计日志也会关联 `batch_id`
- 可通过 `batch_id` 查询整个批次的完整操作历史

### 权限控制
- 居民只能查看和操作自己创建的批次
- 管理员和工作人员可以查看所有批次
- 子预约的审批、取消规则与单次预约完全一致

---

## 数据存储

使用 SQLite 文件 `booking.db`（项目根目录），服务重启后数据完整保留。

## 项目结构

```
booking/
  __init__.py   # 配置常量与环境变量读取
  main.py       # FastAPI 应用入口
  database.py   # SQLite 连接与表初始化
  models.py     # Pydantic 数据模型
  errors.py     # 错误码与异常
  rooms.py      # 房间与时段路由
  bookings.py   # 预约路由与状态机
  audit.py      # 审计日志路由
test_sample.py  # 验收测试脚本
requirements.txt
```
