# 社区活动室预约系统

基于 FastAPI + SQLite 的社区活动室预约后端服务，支持房间配置、时段管理、预约审批与审计日志。

## 快速启动

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动服务

```bash
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000
```

默认周期预约上限为 4 周。

### 自定义周期预约上限启动

通过环境变量 `BOOKING_MAX_RECURRING_WEEKS` 配置周期预约最大周数：

```bash
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000

$env:BOOKING_MAX_RECURRING_WEEKS="8"
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000

BOOKING_MAX_RECURRING_WEEKS=8 python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000
```

| 参数 | 说明 |
|------|------|
| 环境变量名 | `BOOKING_MAX_RECURRING_WEEKS` |
| 默认值 | `4` |
| 最小值 | `1`（低于 1 回退到默认值 4） |
| 绝对上限 | `52`（超过 52 自动截断为 52） |
| 无效值处理 | 非数字或缺失时回退到默认值 4 |

### 验证服务运行

启动后访问以下端点确认服务正常：

```bash
curl http://127.0.0.1:8000/api/health
```

正常返回 HTTP 200 即表示服务已启动。

访问 http://127.0.0.1:8000/docs 查看 Swagger 交互式文档。

查询当前周期预约配置：

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

### 停止服务

在启动该服务的终端按 Ctrl+C 即可停止服务。

如需用进程管理工具停止，必须先确认目标 PID 归属当前项目：

```bash
netstat -ano | findstr :8000
```

找到监听该端口的 PID 后，核对命令行和工作目录归属当前项目，再执行：

```bash
Stop-Process -Id <PID>
```

禁止按进程名批量结束进程。

### 重启服务（更换配置）

如需以不同周期预约上限重启服务：

1. 在原终端按 Ctrl+C 停止当前服务
2. 设置新的环境变量后重新启动：

```bash
$env:BOOKING_MAX_RECURRING_WEEKS="2"
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000
```

3. 用健康检查端点确认新服务已启动
4. 用配置查询端点确认新规则已生效

如不想停掉原有服务，也可在另一个端口启动新实例：

```bash
$env:BOOKING_MAX_RECURRING_WEEKS="2"
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8002
```

---

## 运行验收测试

### 基础测试

```bash
python test_sample.py
```

脚本覆盖：主链路（配置→预约→审批→锁定）、重叠审批失败、居民取消他人预约失败、不在开放时段申请失败、持久性验证、周期预约全链路（部分冲突、权限控制、审批锁定、配置超限、审计链路、环境变量配置、重启一致性）。

### 接手验收（新人必跑）

接手验收脚本覆盖批量改期、整批取消、批次导出三条主链路，以及重启一致性、权限/状态冲突矩阵、边界用例，并验证导出金标准（查询一致、审计 id 集合一致、审计 id 单调递增）。

单服务（MAX=4）：

```bash
python handoff_test.py
```

跨端口模拟重启（MAX=4 + MAX=2）：

```bash
python handoff_test.py --cross-port
```

运行 `--cross-port` 前需同时启动两个服务：

```bash
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001
$env:BOOKING_MAX_RECURRING_WEEKS="2"; python -m uvicorn booking.main:app --host 127.0.0.1 --port 8002
```

退出码 0 = 全部通过，1 = 有失败。

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
| 10012 | BOOKING_ALREADY_IN_EFFECT | 预约已生效（日期已过或时段已开始） |
| 10013 | BOOKING_APPROVED_PROTECTED | 已审批预约受保护，不可改期，需单独取消 |
| 10014 | BATCH_NOTHING_TO_OPERATE | 批次中无符合条件的可操作预约（全部已生效、已审批、已结束） |
| 10015 | NEW_SLOT_NOT_OPEN | 改期目标时间不在任何开放时段内 |
| 10016 | NEW_BOOKING_OVERLAP | 改期目标时间与已审批预约冲突 |

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
curl "http://127.0.0.1:8001/api/bookings/batches/{batch_id}?operator_id=admin1&operator_role=admin"

curl "http://127.0.0.1:8001/api/audit?batch_id={batch_id}"

curl "http://127.0.0.1:8001/api/bookings/recurring/config"
```

---

### 第一部分：前置数据准备（三条链路共用一个批次）

> 执行本节即可得到一个**混合状态批次**：1 条已审批（preserved_approved）+ 2 条待审批（adjustable）+ 1 条已取消（finished），正好覆盖四种 week_phase 中的三种。

#### Step P1：创建房间 + 配置时段

**前置：** 空库或干净状态。

```bash
curl -X POST http://127.0.0.1:8001/api/rooms \
  -H "Content-Type: application/json" \
  -d '{"name": "复核专用_排练厅", "description": "三条链路共用测试房"}'
```

**成功判断：** HTTP 201，返回 `{id, name, is_active: true}`。记录返回的 `room_id`（下面用 `ROOM_ID` 代替）。

**失败判断：** 非 201 或 body 不含 `id`。

---

```bash
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
curl -X POST http://127.0.0.1:8001/api/bookings/{BID_1}/approve \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "复核:审批一条以保护"}'

curl -X POST http://127.0.0.1:8001/api/bookings/{BID_4}/cancel \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "zhangsan", "operator_role": "resident", "reason": "复核:取消最后一周制造finished"}'
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
curl -s "http://127.0.0.1:8001/api/audit?batch_id={BATCH_ID}" > audit_baseline.json
```

用 `/api/audit` 端点查到的 id 集合，与导出里 booking.audit_logs[].id + batch_level_audit_logs[].id 的并集，必须完全相等。

**基线通过上述所有检查 → 进入三条链路正式复核。**

---

## 链路一：批量改期完整复核

### R1-1 用非管理员身份尝试改期（权限边界，预期被拒）

**前置：** 已完成第一部分前置数据准备。

```bash
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
curl -X POST http://127.0.0.1:8001/api/bookings/{BLOCKER_ID}/approve \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "复核:审批阻塞预约"}'
```

```bash
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
| `preserved` | 2（BID_1: approved, BID_4: cancelled=finished） |
| `denied` | 0 |
| `items` 中 BID_3 的 `new_date` | `"2026-09-07"` |
| `items` 中 BID_3 的 `old_date` | `"2026-07-20"` |

**批次详情回查（时间段确实改了）：**
- BID_3：`date = "2026-09-07"`, `start_time = "14:00"`, `end_time = "16:00"`, `old_date = "2026-07-20"`, `rescheduled_from_booking_id = BID_3`

> **实操提示：** 实际 items 中有几条 adjustable，就有几条会被改日期和时段。与批次详情回查值逐一比对即可。

**链路一至此通过。** 进入链路二。

---

## 链路二：整批取消完整复核

> 本链路重新用一个**全新批次**做（因为链路一把 BID_2/BID_3 状态改乱了，不好观察"居民批量取消时 approved 被 preserved"的效果）。

### 前置：建第二个批次（链路二专用）

```bash
curl -X POST http://127.0.0.1:8001/api/rooms \
  -H "Content-Type: application/json" \
  -d '{"name": "复核专用_会议室B", "description": "链路二整批取消"}'

curl -X POST http://127.0.0.1:8001/api/rooms/{ROOM_ID_2}/timeslots \
  -H "Content-Type: application/json" \
  -d '{"slots": [{"weekday": 0, "start_time": "08:00", "end_time": "22:00"}]}'

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

**审计日志核对（关键判定 —— 管理员的 cancel 日志 detail 前缀不一样）：**
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
curl -s "http://127.0.0.1:8001/api/bookings/batches/{BATCH_ID}/export?operator_id=admin1&operator_role=admin" \
  -o batch_{BATCH_ID}_before_restart.json

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

### S1：停止当前服务

在启动端口 8001 服务的终端按 Ctrl+C 停止该服务。

如需用进程管理工具停止，必须先确认目标 PID 归属当前项目：

```bash
netstat -ano | findstr :8001
```

找到监听该端口的 PID 后，核对命令行和工作目录归属当前项目，再执行：

```bash
Stop-Process -Id <PID>
```

禁止按进程名批量结束进程。

### S2：以新配置重启（配置收紧 MAX=2）

在原终端或新终端中设置环境变量后启动：

```bash
$env:BOOKING_MAX_RECURRING_WEEKS="2"
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8002
```

如果不想停掉 8001 端口的服务，也可以直接在另一个端口启动新实例。此时 8001 端口（MAX=4）和 8002 端口（MAX=2）同时运行，后续操作指向 8002 即可。

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
curl "http://127.0.0.1:8002/api/bookings/batches/{BATCH_ID}?operator_id=admin1&operator_role=admin"
```

关键字段：`max_recurring_weeks_at_creation` 必须仍是 4（数据库存的，不会因为重启变）。

```bash
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
| `max_recurring_weeks_at_creation` | **4**（= `CREATION_MAX`） | 批次创建时的规则，数据库存的，重启后仍 4 |
| `max_recurring_weeks_at_operation` | **2**（= `MAX_AFTER`） | 本次操作时服务的当前规则，重启后变成 2 |
| adjustable 条数 > MAX_AFTER 时 | **不会整单抛 10010** | 改期不检查 adjustable 数量与 MAX 的关系，只逐周 slot/冲突 |
| success 的预约数（N_success） | = adjustable 中通过 slot+冲突校验的条数 | |

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

## 一键全自动验证脚本

所有链路 + 复杂场景 + 冲突矩阵 + 重启一致性，都已编成可运行脚本。管理员无需手敲上面的每一条 curl，直接跑即可：

### 一键跑：三条链路 + 冲突矩阵（不重启）

```bash
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001

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
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8001

$env:BOOKING_MAX_RECURRING_WEEKS="2"
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8002

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
- 子预约的审批、取消等权限与单次预约规则一致（admin/staff 可审批，居民可取消自己的）

---

## 操作预演与回退中心（高风险批次操作收口）

### 设计动机

批量改期、整批取消、批次导出均属于**高风险不可逆操作**。直接操作一旦出错（选错批次、日期算错、时段冲突），恢复成本极高。

**操作预演与回退中心**将这三条高风险链路收口成一条"先预演→再确认→后回退→留档导出"的完整可验收链路：

```
管理员发起 ──► 创建【快照】(pending)
                    │
                    ├─► 查看详情（受影响记录、当时配置、相位分类、冲突预检）
                    │
                    ├─► 不想要了？【取消快照】(cancelled) ──► 释放占用，结束
                    │
                    ▼
              管理员【确认执行】(executed)
                    │
                    ├─► 真正写入数据库 + 审计日志
                    ├─► 保存操作结果（success/preserved/denied/skipped）
                    │
                    ▼
              结果不满意？管理员【一次性回退】(rolled_back)
                    │
                    ├─► 按快照原始状态逐条恢复（遇到状态不一致的拒绝覆盖，明确报冲突原因）
                    ├─► 保存回退结果
                    │
                    ▼
              任何阶段都可以【导出留档】(JSON)
                    │
                    └─► 快照元信息 + 配置快照 + 预约快照 + 快照审计 + 批次审计 + 相位汇总
```

### 核心保证

| 保证项 | 实现方式 |
|--------|----------|
| **服务重启后数据不丢** | 快照、预约快照、执行结果、回退结果、审计日志全部写入 SQLite 持久化表 |
| **配置切换前后不串数据** | 每个快照保存独立的 `config_snapshot`（创建时 MAX 值、env 名等），与后续服务重启后的新配置完全隔离 |
| **只有 admin/staff 能确认和回退** | `_check_operation_permission` 在 execute/rollback/cancel 入口强校验，返回 `10024` |
| **预约已变化时拒绝执行** | `_verify_booking_unchanged` 在执行前对比 date/start_time/end_time/status 四字段，变化则返回 `10023` |
| **被别的快照占用时报冲突** | 创建快照时检查同一批 booking 是否被其他 pending/executed 快照占用，返回 `10022` |
| **回退时目标状态不一致** | 回退时验证当前状态应等于"快照执行后期望状态"，不匹配则标记 denied，message 明确说明 Expected vs Actual，绝不静默覆盖 |
| **重复操作被正确拒绝** | pending→不能回退(10020)；executed→不能重执行(10019)；rolled_back→不能重回退(10021) 也不能再执行(10018)；cancelled→什么都不能做(10018) |

### 快照里保存了什么

每个快照（`batch_snapshots` 表 + `snapshot_bookings` 表）至少包含以下信息：

**快照元信息（顶层）：**
- `id` / `batch_id` / `batch_user_id`：归属哪个批次、哪个居民
- `operation_type`：`reschedule` | `cancel` | `export`（三种操作类型）
- `status`：`pending` | `executed` | `rolled_back` | `cancelled`（状态机）
- `operator_id` / `operator_role`：**谁创建了**这个快照（审计追溯）
- `description`：操作备注（必填时填入业务理由）
- `operation_params`：JSON，存 `new_start_date/new_start_time/new_end_time` 等参数
- `operation_result` / `rollback_result`：执行/回退的逐项结果（success/preserved/denied/skipped 计数 + 每条详情）
- `config_snapshot`：创建快照那一刻的配置（见下文）
- `created_at` / `executed_at` / `rolled_back_at`：三个关键时间戳

**配置快照（`config_snapshot` JSON）：**
- `max_recurring_weeks_at_snapshot`：创建时的 MAX 周数（核心隔离字段）
- `min_recurring_weeks` / `absolute_max_recurring_weeks` / `default_max_recurring_weeks`：配置全貌
- `env_var_name`：环境变量名（防止后续改了 env 名找不到来源）
- `snapshot_created_at`：配置快照生成时刻

**每条预约的完整快照（`snapshot_bookings` 表，每条 booking 一行）：**
- `booking_id` / `room_id` / `room_name` / `user_id`：定位唯一预约
- `date` / `start_time` / `end_time`：**创建快照当时的日期时段**（回退时的恢复目标）
- `status`：创建快照当时的状态（回退时的状态恢复依据）
- `purpose` / `old_date` / `rescheduled_from_booking_id`：改期追踪字段
- `week_phase`：创建快照当时的周次相位（`preserved_in_effect` / `preserved_approved` / `adjustable` / `finished`），决定这条是受影响的还是被保护的

**审计日志（通过 `audit_logs` 表 + 模糊匹配 `snapshot #{id}` 关联）：**
- `snapshot_create`：快照创建
- `snapshot_execute_start` / `snapshot_execute_end`：执行开始/结束
- `snapshot_rollback_start` / `snapshot_rollback_end`：回退开始/结束
- `snapshot_cancel`：快照取消
- `snapshot_export`：导出类快照的执行标记
- 以及每条 booking 实际产生的 `reschedule` / `cancel` / `rollback_reschedule` / `rollback_cancel` 审计

### API 一览（快照相关）

| 方法 | 路径 | 说明 | 最低角色 |
|------|------|------|----------|
| POST | `/api/snapshots` | 创建快照（预演，不修改 booking） | resident(本人) / admin / staff |
| GET | `/api/snapshots` | 快照列表（可按 batch_id / status 过滤） | resident 只看自己的；admin/staff 看全部 |
| GET | `/api/snapshots/{id}` | 快照详情（含 booking 快照 + 审计 + 冲突预检） | 同上 |
| POST | `/api/snapshots/{id}/execute` | **确认执行**（真正写库） | admin / staff 专属 |
| POST | `/api/snapshots/{id}/rollback` | **一次性回退**（按快照恢复） | admin / staff 专属 |
| GET | `/api/snapshots/{id}/export` | **导出留档**（JSON，含全部信息） | resident(本人) / admin / staff |
| POST | `/api/snapshots/{id}/cancel` | **取消 pending 快照**（释放占用） | admin / staff 专属 |

---

## 快照操作完整复核手册（管理员版 · 照抄即跑）

> 目标：**不翻任何代码**，按本节命令顺序逐条执行，即可完整复核"建快照 → 确认执行 → 重启后查询 → 冲突回退 → 导出核对"这条完整链路。

### 通用约定

- 默认服务端口 `8003`。用 8000/8001 请自行替换。
- 日期全部用**未来日期**（如今天 2026-06-21，写 2026-07-13 及以后），避免被判定为 `preserved_in_effect`。
- 辅助回查端点：
  ```bash
  curl "http://127.0.0.1:8003/api/bookings/batches/{BATCH_ID}?operator_id=admin1&operator_role=admin"
  curl "http://127.0.0.1:8003/api/audit?batch_id={BATCH_ID}"
  curl "http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_ID}?operator_id=admin1&operator_role=admin"
  ```

---

### 第一部分：前置数据准备（混合状态批次）

#### Step P1：创建房间 + 配置时段

```bash
curl -X POST http://127.0.0.1:8003/api/rooms \
  -H "Content-Type: application/json" \
  -d '{"name": "快照复核_排练厅", "description": "操作预演与回退中心测试"}'
```
记录返回的 `id` 为 `ROOM_ID`。

```bash
curl -X POST http://127.0.0.1:8003/api/rooms/{ROOM_ID}/timeslots \
  -H "Content-Type: application/json" \
  -d '{"slots": [
    {"weekday": 0, "start_time": "09:00", "end_time": "22:00"},
    {"weekday": 2, "start_time": "09:00", "end_time": "22:00"}
  ]}'
```

#### Step P2：提交 3 周周期预约（每周一 10:00-12:00）

```bash
curl -X POST http://127.0.0.1:8003/api/bookings/recurring \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": {ROOM_ID},
    "user_id": "zhangsan",
    "start_date": "2026-07-13",
    "start_time": "10:00",
    "end_time": "12:00",
    "purpose": "快照复核_每周排练",
    "weeks": 3
  }'
```
记录 `batch_id` 为 `BATCH_ID`，三条 `booking_id` 为 `BID_W1`（第1周）、`BID_W2`（第2周）、`BID_W3`（第3周）。

#### Step P3：制造混合状态（1 审批 + 1 取消 + 1 待审批）

```bash
curl -X POST http://127.0.0.1:8003/api/bookings/{BID_W1}/approve \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "快照:审批第1周"}'

curl -X POST http://127.0.0.1:8003/api/bookings/{BID_W3}/cancel \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "zhangsan", "operator_role": "resident", "reason": "快照:取消第3周"}'
```

此时三条 booking 的 week_phase 应为：
| id | week_phase | status |
|----|------------|--------|
| BID_W1 | preserved_approved | approved |
| BID_W2 | adjustable | pending |
| BID_W3 | finished | cancelled |

**成功判断：** 批次详情返回的 bookings 数组对上表。

---

## 链路一：创建快照 → 确认执行 → 回退（批量改期）

### S1-1 创建批量改期快照（pending，不修改 booking）

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots \
  -H "Content-Type: application/json" \
  -d '{
    "batch_id": {BATCH_ID},
    "operation_type": "reschedule",
    "operator_id": "admin1",
    "operator_role": "admin",
    "description": "链路一:批量改期预演",
    "operation_params": {
      "new_start_date": "2026-08-17",
      "new_start_time": "14:00",
      "new_end_time": "16:00"
    }
  }'
```

**关键返回字段核对：**

| 字段 | 期望值 | 说明 |
|------|--------|------|
| `status` | `"pending"` | 预演状态，未执行 |
| `operation_type` | `"reschedule"` | |
| `total_bookings` | `3` | |
| `affected_bookings` | `1` | 只有 BID_W2 是 adjustable |
| `preserved_bookings` | `2` | BID_W1(approved) + BID_W3(cancelled=finished) |
| `config_snapshot.max_recurring_weeks_at_snapshot` | 当前服务 MAX（默认 4） | 配置快照已固化 |
| `config_snapshot.snapshot_created_at` | 非空 | 时间戳 |
| `booking_snapshots` 长度 | `3` | 每条 booking 一行 |
| `booking_snapshots[*].week_phase` 集合 | 必须包含 `preserved_approved` + `adjustable` + `finished` | 三相位齐全 |
| `conflict_check.has_conflict` | `false` | 创建时无占用冲突 |

记录返回的 `id` 为 `SNAPSHOT_RESCHED_ID`。

**此时回查批次详情：** BID_W2 的 `date` 仍为 `2026-07-20`（快照只做预演，**不动数据**）。

---

### S1-2 用居民身份尝试执行（权限边界，预期被拒）

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_RESCHED_ID}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "other_resident",
    "operator_role": "resident",
    "reason": "越权尝试执行"
  }'
```

**成功判断（即拒绝生效）：**
- HTTP **422**
- `error_code = 10024`
- `message` 包含 `"Only ['admin', 'staff'] can execute or rollback snapshots"`

回查批次详情：BID_W2 日期**未变**（权限层拦住了，没进业务层）。

---

### S1-3 在快照创建后手动修改 BID_W2（模拟"预约已变化"冲突）

```bash
curl -X POST http://127.0.0.1:8003/api/bookings/{BID_W2}/cancel \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "zhangsan", "operator_role": "resident", "reason": "在快照创建后手动取消BID_W2制造冲突"}'
```

### S1-4 尝试执行快照 → 预约已变化拒绝（10023）

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_RESCHED_ID}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "尝试执行但预约已变"
  }'
```

**判断：** HTTP 422，`error_code = 10023`，`message` 包含 `"has changed"` 和 `"status: pending -> cancelled"` 等具体字段变化说明。

> **这就是收口的价值**：如果没有收口直接批量改期，BID_W2 被取消后改期操作可能漏判或产生脏数据。收口模式下直接拒绝，管理员先处理掉外部变化再重新建快照。

### S1-5 取消这个冲突快照（cancelled，释放占用）

```bash
curl -X POST "http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_RESCHED_ID}/cancel?operator_id=admin1&operator_role=admin&reason=BID_W2已被手动取消，作废此快照"
```

**判断：** 返回 `status = "cancelled"`。后续对同一批 booking 建快照不会再被占用冲突拦截。

---

### S1-6 恢复 BID_W2 为 pending（重新建一条干净快照继续验证）

> 因为上面取消了 BID_W2，为继续走"确认执行→回退"链路，需要重新建一个 3 周批次。下面用一个新批次演示。

```bash
curl -X POST http://127.0.0.1:8003/api/bookings/recurring \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": {ROOM_ID},
    "user_id": "zhangsan",
    "start_date": "2026-07-20",
    "start_time": "10:00",
    "end_time": "12:00",
    "purpose": "快照复核_第二批_执行回退链路",
    "weeks": 3
  }'
```

记录新 `batch_id` = `BATCH_ID_2`，三条 booking id = `B2_W1` / `B2_W2` / `B2_W3`。

```bash
curl -X POST http://127.0.0.1:8003/api/bookings/{B2_W1}/approve \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "审批B2_W1制造preserved_approved"}'
curl -X POST http://127.0.0.1:8003/api/bookings/{B2_W3}/cancel \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "zhangsan", "operator_role": "resident", "reason": "取消B2_W3制造finished"}'
```

批次 `BATCH_ID_2` 现在的相位：B2_W1=preserved_approved, B2_W2=adjustable, B2_W3=finished。

### S1-7 创建干净快照 + 确认执行

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots \
  -H "Content-Type: application/json" \
  -d '{
    "batch_id": {BATCH_ID_2},
    "operation_type": "reschedule",
    "operator_id": "admin1",
    "operator_role": "admin",
    "description": "链路一:确认执行+回退",
    "operation_params": {
      "new_start_date": "2026-08-24",
      "new_start_time": "14:00",
      "new_end_time": "16:00"
    }
  }'
```

记录 `SNAPSHOT_ID = 返回的 id`。

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_ID}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "管理员确认执行批量改期"
  }'
```

**执行结果关键字段核对：**
| 字段 | 期望值 |
|------|--------|
| `status` | `"executed"` |
| `executed_at` | 非空 |
| `operation_result.operation` | `"reschedule"` |
| `operation_result.total` | `3` |
| `operation_result.success` | `1`（只有 B2_W2 adjustable） |
| `operation_result.preserved` | `2`（B2_W1 approved + B2_W3 finished） |
| `operation_result.denied` | `0` |
| `operation_result.items` 中 success 的那条 | `new_date = "2026-08-24"`（B2_W2 的新日期） |
| `operation_result.items` 中 success 的那条 | `week_phase_before = "adjustable"` |

**批次详情回查（核心判定）：**
- B2_W1：`status = "approved"`，`date` 仍是原来的 `2026-07-20`（**preserved_approved 被保护不动**）
- B2_W2：`date = "2026-08-24"`，`start_time = "14:00"`，`end_time = "16:00"`，`old_date = "2026-07-27"`，`rescheduled_from_booking_id = B2_W2`
- B2_W3：`status = "cancelled"`，日期不变（finished 相位）

---

### S1-8 重启后查询（持久化验证）

> 重启端口 8003 的服务（Ctrl+C 后再启动，同一个端口同一个 booking.db），不换数据。

重启后执行：

```bash
curl "http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_ID}?operator_id=admin1&operator_role=admin"
```

**重启后一致性核对清单（逐项对照执行完后的结果）：**
| 字段 | 期望值 |
|------|--------|
| `id` | 仍等于 `SNAPSHOT_ID` |
| `status` | 仍是 `"executed"` |
| `executed_at` | 与重启前完全相同（时间戳字符串逐字节一致） |
| `operation_result` | 非空，`success/preserved/denied/skipped` 计数与重启前一致 |
| `booking_snapshots` 长度 | 仍为 3 |
| 每条 `booking_snapshots[*].booking_id / date / start_time / end_time / status / week_phase` | 与重启前**逐字节一致** |
| `config_snapshot.max_recurring_weeks_at_snapshot` | 与重启前一致（创建时的 MAX，不会因重启/换配置而变） |

```bash
curl "http://127.0.0.1:8003/api/snapshots?operator_id=admin1&operator_role=admin"
```
重启后列表中**必须能找到**这个 `SNAPSHOT_ID`。

---

### S1-9 在手动修改 B2_W2 后尝试回退（冲突回退，denied 明确报原因）

> 故意先手动把 B2_W2 改到另一个日期，模拟"快照执行后，管理员又通过别的渠道改了一次"，此时回退应该**拒绝覆盖**。

```bash
curl -X POST "http://127.0.0.1:8003/api/bookings/batches/{BATCH_ID_2}/reschedule" \
  -H "Content-Type: application/json" \
  -d '{
    "new_start_date": "2026-09-28",
    "new_start_time": "10:00",
    "new_end_time": "12:00",
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "在快照执行后又用直接批量改期改了一次，制造回退冲突"
  }'
```

确认 B2_W2 的 `date` 已经变成 `"2026-09-28"`（不等于快照执行后的期望日期 `"2026-08-24"`）。

现在回退：

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_ID}/rollback \
  -H "Content-Type: application/json" \
  -d '{
    "operator_id": "admin1",
    "operator_role": "admin",
    "reason": "尝试回退但目标已被手动修改"
  }'
```

**冲突回退结果核对：**
| 字段 | 期望值 |
|------|--------|
| `status` | `"rolled_back"`（回退流程仍执行完毕，但部分条目被 denied） |
| `rolled_back_at` | 非空 |
| `rollback_result.denied` | **≥ 1**（B2_W2 因为目标状态不匹配被拒绝） |
| `rollback_result.items` 中 denied 的那条 | `result = "denied"`，`error_code = 10023` |
| denied 条目的 `message` | **必须包含** `Expected: date=2026-08-24, time=14:00-16:00. Actual: date=2026-09-28, time=10:00-12:00` 这类精确说明（明确告诉管理员 Expected vs Actual，不静默覆盖） |

> **收口的又一价值**：回退也不是"一把梭哈恢复"，遇到外部修改过的条目精准拒绝，并列出 Expected vs Actual，管理员可以**判断是先手动恢复再回退，还是接受现状**。

---

### S1-10 重新走一次"干净执行 → 正常回退"（没有外部干扰的情况）

建第三个批次：

```bash
curl -X POST http://127.0.0.1:8003/api/bookings/recurring \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": {ROOM_ID},
    "user_id": "zhangsan",
    "start_date": "2026-07-27",
    "start_time": "10:00",
    "end_time": "12:00",
    "purpose": "快照复核_第三批_正常回退",
    "weeks": 3
  }'
```
记录 `BATCH_ID_3`。三条 booking：`B3_W1`/`B3_W2`/`B3_W3`。无需制造混合状态（三条都是 pending adjustable，回退效果最直观）。

创建快照并执行：
```bash
curl -X POST http://127.0.0.1:8003/api/snapshots \
  -H "Content-Type: application/json" \
  -d '{
    "batch_id": {BATCH_ID_3},
    "operation_type": "reschedule",
    "operator_id": "admin1",
    "operator_role": "admin",
    "description": "链路一:正常回退演示",
    "operation_params": {
      "new_start_date": "2026-09-14",
      "new_start_time": "15:00",
      "new_end_time": "17:00"
    }
  }'
```
记录 `SNAPSHOT_ID_3`。

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_ID_3}/execute \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "正常改期执行"}'
```

回查：三条 booking 的 date 都变了（2026-09-14 / 09-21 / 09-28），时段 = 15:00-17:00，`old_date` 都填入了原来的日期。

**执行回退：**

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_ID_3}/rollback \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "恢复到改期前的状态"}'
```

**正常回退结果核对：**
| 字段 | 期望值 |
|------|--------|
| `status` | `"rolled_back"` |
| `rollback_result.success` | `3`（三条全部成功恢复） |
| `rollback_result.denied` | `0` |

**批次详情回查（核心判定 —— 回退到位）：**
- B3_W1/B3_W2/B3_W3 的 `date` 全部恢复为 `2026-07-27` / `2026-08-03` / `2026-08-10`（快照创建时的日期）
- `start_time` / `end_time` 恢复为 `"10:00"` / `"12:00"`
- `old_date` 全部清空为 `null`
- `rescheduled_from_booking_id` 全部清空为 `null`
- 三条 status 都是 `"pending"`

> **至此，"建快照 → 确认执行 → 重启后查询 → 冲突回退 → 正常回退"链路全部闭环。**

---

## 链路二：整批取消快照 + 导出核对

### S2-1 创建整批取消快照 → 执行 → 回退

（复用 BATCH_ID_3 已回退为三条 pending 的状态，如果不是就新建一个 3 周批次即可）

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots \
  -H "Content-Type: application/json" \
  -d '{
    "batch_id": {BATCH_ID_3},
    "operation_type": "cancel",
    "operator_id": "staff1",
    "operator_role": "staff",
    "description": "链路二:整批取消+导出"
  }'
```
记录 `SNAPSHOT_CANCEL_ID`。

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_CANCEL_ID}/execute \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "staff1", "operator_role": "staff", "reason": "staff确认执行整批取消"}'
```

**核对：** 三条 booking status 全变 `cancelled`，`operation_result.success = 3`。

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_CANCEL_ID}/rollback \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "回退整批取消"}'
```

**核对：** 三条 booking status 恢复为 `pending`，`rollback_result.success = 3`。

---

### S2-2 导出核对（JSON 结构 + 交叉一致性）

对已执行 + 已回退的 `SNAPSHOT_ID_3`（链路一改期那条）做导出：

```bash
curl -s "http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_ID_3}/export?operator_id=admin1&operator_role=admin" \
  -o snapshot_{SNAPSHOT_ID_3}_export.json
```

**Response Headers 检查：** `Content-Disposition` 必须包含 `attachment; filename=snapshot_{SNAPSHOT_ID_3}_export.json`。

**导出文件 6 大顶层块必须全部存在：**

| 顶层 key | 内容说明 |
|----------|----------|
| `snapshot` | 快照元信息（id/batch_id/status/操作类型/三个时间戳/计数等） |
| `config_snapshot` | 创建快照时的配置（与当前服务配置独立，不会因为重启而变） |
| `operation_params` | 创建时传入的参数（new_start_date 等） |
| `operation_result` | 执行结果（逐项） |
| `rollback_result` | 回退结果（逐项） |
| `booking_snapshots` | 每条 booking 的创建时快照（回退依据） |
| `snapshot_audit_logs` | 与该快照直接相关的审计日志（snapshot_create/execute_start/...） |
| `batch_audit_logs` | 该批次的**全部**审计日志（含快照外的操作，交叉核对用） |
| `summary` | 四种 week_phase 计数汇总 |

**关键字段核对（S2-2 用 SNAPSHOT_ID_3 做）：**

| 路径 | 期望值 |
|------|--------|
| `.snapshot.id` | `SNAPSHOT_ID_3` |
| `.snapshot.operation_type` | `"reschedule"` |
| `.snapshot.status` | `"rolled_back"` |
| `.snapshot.total_bookings` | `3` |
| `.snapshot.affected_bookings` | `3`（三条都是 adjustable） |
| `.snapshot.executed_at` / `.rolled_back_at` | 均非空 |
| `.config_snapshot.max_recurring_weeks_at_snapshot` | 创建时的 MAX 值 |
| `.config_snapshot.env_var_name` | `"BOOKING_MAX_RECURRING_WEEKS"` |
| `.config_snapshot.snapshot_created_at` | 非空 |
| `.operation_result.operation` | `"reschedule"` |
| `.operation_result.success` | `3` |
| `.rollback_result.operation` | `"rollback_reschedule"` |
| `.rollback_result.success` | `3` |
| `.booking_snapshots` 长度 | `3` |
| `.booking_snapshots[*].week_phase` | 全是 `"adjustable"` |
| `.summary.total_bookings` | `3` |
| `.summary.adjustable` | `3` |
| 其余相位之和 | `0` |
| `.summary.adjustable + preserved_in_effect + preserved_approved + finished` | `== .summary.total_bookings` |

**交叉一致性（三项金标准）：**

**金标准 1：`booking_snapshots` 与快照详情查询 100% 一致**
- 导出的 `.booking_snapshots` 数组 vs `GET /api/snapshots/{id}` 返回的 `booking_snapshots`：长度、每条的 `booking_id/date/start_time/end_time/status/week_phase` 六字段逐一相等。

**金标准 2：snapshot_audit_logs id 集合与快照详情查询的 audit_logs 一致**
- `set(导出的 .snapshot_audit_logs[*].id)` 必须等于 `set(详情查询的 audit_logs[*].id)`（空差集）。

**金标准 3：batch_audit_logs id 集合与 `/api/audit?batch_id=` 查询完全相等**
- 从导出的 `.batch_audit_logs[*].id` 收 id 集合，对比 `curl "http://127.0.0.1:8003/api/audit?batch_id={BATCH_ID_3}"` 返回的每条 id，必须完全相等（无遗漏，无多余）。

---

## 链路三：快照占用冲突 + 重复操作状态机 + 居民权限边界

### S3-1 同一批 booking 不能被多个 pending/executed 快照占用

对 BATCH_ID_3（假设现在三条都是 pending）连建两个快照：

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots \
  -H "Content-Type: application/json" \
  -d '{
    "batch_id": {BATCH_ID_3},
    "operation_type": "reschedule",
    "operator_id": "admin1",
    "operator_role": "admin",
    "description": "占用测试_第一个快照",
    "operation_params": {"new_start_date": "2026-10-05"}
  }'
```
返回 `SNAPSHOT_OCCUPY_1`。

```bash
curl -X POST http://127.0.0.1:8003/api/snapshots \
  -H "Content-Type: application/json" \
  -d '{
    "batch_id": {BATCH_ID_3},
    "operation_type": "cancel",
    "operator_id": "admin1",
    "operator_role": "admin",
    "description": "占用测试_第二个快照_应被拒"
  }'
```

**判断：** HTTP 422，`error_code = 10022`，`message` 包含 `"is occupied by snapshot"` + 占用者的 snapshot id。

> **收口价值之三**：防止管理员 A 正在预演改期、管理员 B 又对同一批做取消，两个操作互相覆盖导致数据错乱。

### S3-2 取消第一个快照后可重新创建（占用释放）

```bash
curl -X POST "http://127.0.0.1:8003/api/snapshots/{SNAPSHOT_OCCUPY_1}/cancel?operator_id=admin1&operator_role=admin&reason=作废第一个快照释放占用"
```

再建第二个快照 → 这次应该成功（201）。

---

### S3-3 重复操作状态机（完整矩阵）

拿一个刚创建的 pending 快照 `SNAPSHOT_FSM`（operation_type 任意）做下面的矩阵测试：

| # | 当前状态 | 操作 | 预期结果 |
|---|----------|------|----------|
| F1 | `pending` | `/execute` → 执行成功 | → `executed`，HTTP 200 |
| F2 | `executed` | 再调一次 `/execute` | HTTP 422，error_code **10019**（Already Executed） |
| F3 | `executed` | `/rollback` → 回退成功 | → `rolled_back`，HTTP 200 |
| F4 | `rolled_back` | 再调一次 `/rollback` | HTTP 422，error_code **10021**（Already Rolled Back） |
| F5 | `rolled_back` | 调 `/execute` | HTTP 422，error_code **10018**（Invalid Status：回退后不允许再执行，避免重复应用） |
| F6 | 新建一个 pending，调 `/cancel` | → `cancelled`，HTTP 200 |
| F7 | `cancelled` | 调 `/execute` | HTTP 422，error_code **10018**（已取消不能执行） |

**矩阵全部通过 → 状态机正确。**

---

### S3-4 居民权限边界（完整矩阵）

对任意快照做以下测试（快照创建者可以是 admin，也可以是居民本人）：

| # | 操作 | 居民身份 | 预期 error_code |
|---|------|----------|-----------------|
| P1 | `GET /api/snapshots` 列表（`operator_role=resident`，`operator_id` 不是 batch 创建者） | 非本人 | 返回空数组（居民只看自己的快照） |
| P2 | `GET /api/snapshots/{id}` 详情（居民 + 非本人） | 非本人 | **10007**（Permission Denied） |
| P3 | `POST /execute`（居民） | 任意居民 | **10024**（Operation Not Allowed） |
| P4 | `POST /rollback`（居民） | 任意居民 | **10024** |
| P5 | `POST /cancel`（居民） | 任意居民 | **10024** |
| P6 | `GET /export`（居民 + 非本人） | 非本人 | **10007** |

**矩阵全部通过 → 权限隔离正确。**

---

## 一键全自动验证（16 场景 · 300 断言 · 0 失败）

所有链路 + 复杂场景 + 冲突矩阵 + 重启一致性，都已编成脚本。直接跑即可：

### 一键跑：完整链路

```bash
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8003

python batch_takeover_test.py
```

`batch_takeover_test.py` 覆盖的 16 个场景（与文档逐一对应）：

| 场景函数 | 覆盖内容 |
|----------|---------|
| `test_create_reschedule_snapshot` | S1-1 创建批量改期快照 |
| `test_create_cancel_snapshot` | S2-1 创建整批取消快照 |
| `test_create_export_snapshot` | 创建批次导出类快照 |
| `test_snapshot_list_and_detail` | 列表查询 + 详情查询 + 过滤 + 居民只看自己 |
| `test_permission_control` | S3-4 权限边界矩阵（execute/rollback/cancel/view 四项 10024/10007） |
| `test_execute_reschedule` | S1-7 确认执行批量改期 |
| `test_execute_cancel` | S2-1 确认执行整批取消（含 staff 角色） |
| `test_rollback_reschedule` | S1-10 正常回退批量改期 |
| `test_rollback_cancel` | S2-1 正常回退整批取消 |
| `test_conflict_snapshot_occupied` | S3-1 快照占用冲突（10022）+ S3-2 取消后可重建 |
| `test_conflict_booking_changed` | S1-3/S1-4 预约已变化拒绝执行（10023） |
| `test_duplicate_operation` | S3-3 状态机矩阵 F1-F7（10018/10019/10021） |
| `test_rollback_conflict_target_changed` | S1-9 回退时目标状态不一致，denied 含精确 Expected vs Actual |
| `test_export_snapshot` | S2-2 导出功能（结构 + 权限边界 + Content-Disposition + phase 求和） |
| `test_cancel_pending_snapshot` | S1-5 取消 pending 快照 + 占用释放验证 |
| `test_restart_consistency` | S1-8 重启后查询一致性 + 重启后回退依然可行 |

脚本输出 `回归测试结果: 300 通过, 0 失败` 且退出码 0 → 本文档描述的所有场景与实现完全一致。

---

## 错误码补充（快照专项）

| 错误码 | 常量 | 说明 | 触发场景 |
|--------|------|------|----------|
| 10017 | SNAPSHOT_NOT_FOUND | 快照不存在 | 查询/执行/回退/导出 id 不存在的快照 |
| 10018 | SNAPSHOT_INVALID_STATUS | 快照状态不允许此操作 | rolled_back/cancelled 后尝试执行，或非 pending 时尝试取消 |
| 10019 | SNAPSHOT_ALREADY_EXECUTED | 快照已执行过 | executed 状态重复调用 /execute |
| 10020 | SNAPSHOT_NOT_EXECUTED | 快照尚未执行 | pending 状态下调用 /rollback |
| 10021 | SNAPSHOT_ALREADY_ROLLED_BACK | 快照已回退过 | rolled_back 状态重复调用 /rollback |
| 10022 | SNAPSHOT_CONFLICT | 快照占用冲突 | 创建时同一批 booking 被其他 pending/executed 快照占用 |
| 10023 | SNAPSHOT_BOOKING_CHANGED | 预约已变化 | 执行前发现 booking 的 date/time/status 与快照创建时不一致；回退时发现目标状态不等于执行后期望状态 |
| 10024 | SNAPSHOT_OPERATION_NOT_ALLOWED | 无执行/回退权限 | resident 角色尝试调用 /execute、/rollback、/cancel |