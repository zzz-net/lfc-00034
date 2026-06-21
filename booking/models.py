from datetime import date, time, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BookingStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


VALID_TRANSITIONS = {
    BookingStatus.PENDING: {BookingStatus.APPROVED, BookingStatus.REJECTED, BookingStatus.CANCELLED},
    BookingStatus.APPROVED: {BookingStatus.CANCELLED, BookingStatus.EXPIRED},
    BookingStatus.REJECTED: set(),
    BookingStatus.CANCELLED: set(),
    BookingStatus.EXPIRED: set(),
}


class BookingWeekPhase(str, Enum):
    PRESERVED_IN_EFFECT = "preserved_in_effect"
    PRESERVED_APPROVED = "preserved_approved"
    ADJUSTABLE = "adjustable"
    FINISHED = "finished"


class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None


class RoomOut(BaseModel):
    id: int
    name: str
    description: str
    is_active: bool
    created_at: str


class TimeSlotCreate(BaseModel):
    weekday: int = Field(..., ge=0, le=6)
    start_time: time
    end_time: time


class TimeSlotBatch(BaseModel):
    slots: list[TimeSlotCreate]


class TimeSlotOut(BaseModel):
    id: int
    room_id: int
    weekday: int
    start_time: str
    end_time: str


class BookingCreate(BaseModel):
    room_id: int
    user_id: str = Field(..., min_length=1, max_length=50)
    date: date
    start_time: time
    end_time: time
    purpose: str = Field(default="", max_length=500)


class RecurringBookingCreate(BaseModel):
    room_id: int
    user_id: str = Field(..., min_length=1, max_length=50)
    start_date: date
    start_time: time
    end_time: time
    purpose: str = Field(default="", max_length=500)
    weeks: int = Field(..., ge=1, le=52)


class BookingAction(BaseModel):
    operator_id: str = Field(..., min_length=1, max_length=50)
    operator_role: str = Field(default="admin", pattern="^(admin|staff|resident)$")
    reason: str = Field(default="", max_length=500)


class BookingOut(BaseModel):
    id: int
    room_id: int
    room_name: str
    user_id: str
    batch_id: Optional[int]
    date: str
    start_time: str
    end_time: str
    status: BookingStatus
    purpose: str
    created_at: str
    updated_at: str


class BookingDetailOut(BookingOut):
    week_phase: BookingWeekPhase
    old_date: Optional[str] = None
    rescheduled_from_booking_id: Optional[int] = None


class AuditLogOut(BaseModel):
    id: int
    booking_id: Optional[int]
    batch_id: Optional[int]
    snapshot_id: Optional[int]
    action: str
    old_status: Optional[str]
    new_status: Optional[str]
    operator_id: str
    operator_role: str
    detail: str
    created_at: str


class RecurringResultItem(BaseModel):
    date: str
    status: str
    booking_id: Optional[int] = None
    error_code: Optional[int] = None
    message: Optional[str] = None


class RecurringBookingOut(BaseModel):
    batch_id: int
    user_id: str
    total: int
    success: int
    skipped: int
    denied: int
    exceeded: int
    items: list[RecurringResultItem]
    created_at: str


class BatchOut(BaseModel):
    id: int
    user_id: str
    total_count: int
    success_count: int
    skip_count: int
    denied_count: int
    exceeded_count: int
    max_recurring_weeks_at_creation: int
    created_at: str


class BatchDetailOut(BatchOut):
    bookings: list[BookingDetailOut]


class RecurringConfigOut(BaseModel):
    max_recurring_weeks: int
    min_recurring_weeks: int
    absolute_max_recurring_weeks: int
    default_max_recurring_weeks: int
    env_var_name: str


class ErrorResponse(BaseModel):
    error_code: int
    message: str


# ============================================================
# 批次接管与回滚中心模型
# ============================================================

class SnapshotStatus(str, Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class SnapshotOperationType(str, Enum):
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    EXPORT = "export"


class SnapshotCreate(BaseModel):
    batch_id: int
    operation_type: SnapshotOperationType
    operator_id: str = Field(..., min_length=1, max_length=50)
    operator_role: str = Field(default="admin", pattern="^(admin|staff|resident)$")
    description: str = Field(default="", max_length=500)
    operation_params: dict | None = None


class SnapshotExecute(BaseModel):
    operator_id: str = Field(..., min_length=1, max_length=50)
    operator_role: str = Field(default="admin", pattern="^(admin|staff|resident)$")
    reason: str = Field(default="", max_length=500)


class SnapshotRollback(BaseModel):
    operator_id: str = Field(..., min_length=1, max_length=50)
    operator_role: str = Field(default="admin", pattern="^(admin|staff|resident)$")
    reason: str = Field(default="", max_length=500)


class SnapshotBookingOut(BaseModel):
    booking_id: int
    room_id: int
    room_name: str
    user_id: str
    date: str
    start_time: str
    end_time: str
    status: BookingStatus
    purpose: str
    old_date: str | None = None
    rescheduled_from_booking_id: int | None = None
    week_phase: BookingWeekPhase


class SnapshotConfigOut(BaseModel):
    max_recurring_weeks_at_snapshot: int
    min_recurring_weeks: int
    absolute_max_recurring_weeks: int
    default_max_recurring_weeks: int
    env_var_name: str
    snapshot_created_at: str


class SnapshotConflictFieldDiff(BaseModel):
    field: str
    expected_value: str | None
    actual_value: str | None


class SnapshotConflictItem(BaseModel):
    booking_id: int
    conflict_type: str
    message: str
    current_snapshot_id: int | None = None
    current_status: str | None = None
    field_diffs: list[SnapshotConflictFieldDiff] = []


class SnapshotConflictCheck(BaseModel):
    has_conflict: bool
    conflicts: list[SnapshotConflictItem]


class SnapshotOperationResultItem(BaseModel):
    booking_id: int | None = None
    old_date: str | None = None
    new_date: str | None = None
    old_status: str | None = None
    new_status: str | None = None
    result: str
    error_code: int | None = None
    message: str | None = None
    week_phase_before: str | None = None
    expected_new_date: str | None = None
    expected_new_start_time: str | None = None
    expected_new_end_time: str | None = None
    expected_new_status: str | None = None


class SnapshotOperationResult(BaseModel):
    snapshot_id: int
    batch_id: int
    operation: str
    total: int
    success: int
    preserved: int
    skipped: int
    denied: int
    items: list[SnapshotOperationResultItem]
    executed_at: str | None = None


class SnapshotOut(BaseModel):
    id: int
    batch_id: int
    batch_user_id: str
    operation_type: SnapshotOperationType
    status: SnapshotStatus
    description: str
    operator_id: str
    operator_role: str
    total_bookings: int
    affected_bookings: int
    preserved_bookings: int
    created_at: str
    executed_at: str | None = None
    rolled_back_at: str | None = None
    config_snapshot: SnapshotConfigOut
    operation_params: dict | None = None
    booking_snapshots: list[SnapshotBookingOut]
    conflict_check: SnapshotConflictCheck | None = None
    operation_result: SnapshotOperationResult | None = None
    rollback_result: SnapshotOperationResult | None = None
    audit_logs: list[AuditLogOut] = []


class SnapshotListItem(BaseModel):
    id: int
    batch_id: int
    batch_user_id: str
    operation_type: SnapshotOperationType
    status: SnapshotStatus
    description: str
    operator_id: str
    operator_role: str
    total_bookings: int
    affected_bookings: int
    preserved_bookings: int
    created_at: str
    executed_at: str | None = None
    rolled_back_at: str | None = None


class BatchRescheduleCreate(BaseModel):
    new_start_date: date
    operator_id: str = Field(..., min_length=1, max_length=50)
    operator_role: str = Field(default="admin", pattern="^(admin|staff|resident)$")
    reason: str = Field(default="", max_length=500)
    new_start_time: Optional[time] = None
    new_end_time: Optional[time] = None


class BatchCancelCreate(BaseModel):
    operator_id: str = Field(..., min_length=1, max_length=50)
    operator_role: str = Field(default="admin", pattern="^(admin|staff|resident)$")
    reason: str = Field(default="", max_length=500)


class BatchOperationItem(BaseModel):
    booking_id: Optional[int] = None
    old_date: Optional[str] = None
    new_date: Optional[str] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    result: str
    error_code: Optional[int] = None
    message: Optional[str] = None
    week_phase_before: Optional[str] = None


class BatchOperationOut(BaseModel):
    batch_id: int
    user_id: str
    operation: str
    total: int
    success: int
    preserved: int
    skipped: int
    denied: int
    max_recurring_weeks_at_creation: int
    max_recurring_weeks_at_operation: int
    items: list[BatchOperationItem]
    operated_at: str
