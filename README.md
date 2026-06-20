# 社区活动室预约系统

基于 FastAPI + SQLite 的社区活动室预约后端服务，支持房间配置、时段管理、预约审批与审计日志。

## 快速启动

```bash
pip install -r requirements.txt
python -m uvicorn booking.main:app --host 127.0.0.1 --port 8000
```

启动后访问 http://127.0.0.1:8000/docs 查看 Swagger 交互式文档。

## 运行验收测试

```bash
python test_sample.py
```

脚本覆盖：主链路（配置→预约→审批→锁定）、重叠审批失败、居民取消他人预约失败、不在开放时段申请失败、持久性验证。

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
| GET | `/api/bookings` | 预约列表（按 status/room_id/user_id/date/batch_id 过滤） |
| GET | `/api/bookings/{id}` | 预约详情 |
| GET | `/api/bookings/batches` | 批次列表（可按 user_id 过滤） |
| GET | `/api/bookings/batches/{id}` | 批次详情（含关联预约） |
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

所有业务错误返回 HTTP 422，响应体为：

```json
{"error_code": 10004, "message": "Overlaps with approved booking #1"}
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

### 4. 审批通过

```bash
curl -X POST http://127.0.0.1:8000/api/bookings/1/approve \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin1", "operator_role": "admin", "reason": "同意"}'
```

### 5. 查询已锁定时段

```bash
curl "http://127.0.0.1:8000/api/bookings?status=approved&room_id=1"
```

### 6. 居民取消自己的预约

```bash
curl -X POST http://127.0.0.1:8000/api/bookings/1/cancel \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "zhangsan", "operator_role": "resident", "reason": "临时有事"}'
```

### 7. 查询审计日志

```bash
curl "http://127.0.0.1:8000/api/audit?booking_id=1"
```

### 8. 导出审计日志

```bash
curl "http://127.0.0.1:8000/api/audit/export" -o audit_logs.json
```

---

## 数据存储

使用 SQLite 文件 `booking.db`（项目根目录），服务重启后数据完整保留。

## 项目结构

```
booking/
  __init__.py
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
