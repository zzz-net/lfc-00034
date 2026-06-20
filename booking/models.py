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


class AuditLogOut(BaseModel):
    id: int
    booking_id: Optional[int]
    batch_id: Optional[int]
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
    bookings: list[BookingOut]


class RecurringConfigOut(BaseModel):
    max_recurring_weeks: int
    min_recurring_weeks: int
    absolute_max_recurring_weeks: int
    default_max_recurring_weeks: int
    env_var_name: str


class ErrorResponse(BaseModel):
    error_code: int
    message: str
