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


class BookingAction(BaseModel):
    operator_id: str = Field(..., min_length=1, max_length=50)
    operator_role: str = Field(default="admin", pattern="^(admin|staff|resident)$")
    reason: str = Field(default="", max_length=500)


class BookingOut(BaseModel):
    id: int
    room_id: int
    room_name: str
    user_id: str
    date: str
    start_time: str
    end_time: str
    status: BookingStatus
    purpose: str
    created_at: str
    updated_at: str


class AuditLogOut(BaseModel):
    id: int
    booking_id: int
    action: str
    old_status: Optional[str]
    new_status: Optional[str]
    operator_id: str
    operator_role: str
    detail: str
    created_at: str


class ErrorResponse(BaseModel):
    error_code: int
    message: str
