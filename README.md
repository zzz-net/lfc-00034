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
