from enum import IntEnum


class ErrorCode(IntEnum):
    ROOM_NOT_FOUND = 10001
    ROOM_INACTIVE = 10002
    SLOT_NOT_OPEN = 10003
    BOOKING_OVERLAP = 10004
    BOOKING_NOT_FOUND = 10005
    INVALID_STATUS_TRANSITION = 10006
    PERMISSION_DENIED = 10007
    BOOKING_ALREADY_PROCESSED = 10008
    INVALID_TIME_RANGE = 10009
    BATCH_LIMIT_EXCEEDED = 10010
    BATCH_NOT_FOUND = 10011
    BOOKING_ALREADY_IN_EFFECT = 10012
    BOOKING_APPROVED_PROTECTED = 10013
    BATCH_NOTHING_TO_OPERATE = 10014
    NEW_SLOT_NOT_OPEN = 10015
    NEW_BOOKING_OVERLAP = 10016
    SNAPSHOT_NOT_FOUND = 10017
    SNAPSHOT_INVALID_STATUS = 10018
    SNAPSHOT_ALREADY_EXECUTED = 10019
    SNAPSHOT_NOT_EXECUTED = 10020
    SNAPSHOT_ALREADY_ROLLED_BACK = 10021
    SNAPSHOT_CONFLICT = 10022
    SNAPSHOT_BOOKING_CHANGED = 10023
    SNAPSHOT_OPERATION_NOT_ALLOWED = 10024


ERROR_MESSAGES = {
    ErrorCode.ROOM_NOT_FOUND: "Room not found",
    ErrorCode.ROOM_INACTIVE: "Room is not active",
    ErrorCode.SLOT_NOT_OPEN: "Requested time is not within any open time slot",
    ErrorCode.BOOKING_OVERLAP: "Booking time overlaps with an existing approved booking",
    ErrorCode.BOOKING_NOT_FOUND: "Booking not found",
    ErrorCode.INVALID_STATUS_TRANSITION: "Invalid status transition for this booking",
    ErrorCode.PERMISSION_DENIED: "You do not have permission to perform this action",
    ErrorCode.BOOKING_ALREADY_PROCESSED: "Booking has already been processed",
    ErrorCode.INVALID_TIME_RANGE: "start_time must be before end_time",
    ErrorCode.BATCH_LIMIT_EXCEEDED: "Recurring booking weeks exceed the allowed limit",
    ErrorCode.BATCH_NOT_FOUND: "Batch not found",
    ErrorCode.BOOKING_ALREADY_IN_EFFECT: "Booking is already in effect (date passed or started)",
    ErrorCode.BOOKING_APPROVED_PROTECTED: "Approved booking cannot be rescheduled, cancel individually instead",
    ErrorCode.BATCH_NOTHING_TO_OPERATE: "No eligible items in this batch to operate on (all in effect, approved, or already cancelled/rejected/expired)",
    ErrorCode.NEW_SLOT_NOT_OPEN: "New rescheduled time is not within any open time slot",
    ErrorCode.NEW_BOOKING_OVERLAP: "New rescheduled time overlaps with an existing approved booking",
    ErrorCode.SNAPSHOT_NOT_FOUND: "Snapshot not found",
    ErrorCode.SNAPSHOT_INVALID_STATUS: "Invalid snapshot status for this operation",
    ErrorCode.SNAPSHOT_ALREADY_EXECUTED: "Snapshot has already been executed",
    ErrorCode.SNAPSHOT_NOT_EXECUTED: "Snapshot has not been executed yet",
    ErrorCode.SNAPSHOT_ALREADY_ROLLED_BACK: "Snapshot has already been rolled back",
    ErrorCode.SNAPSHOT_CONFLICT: "One or more bookings are already occupied by another snapshot",
    ErrorCode.SNAPSHOT_BOOKING_CHANGED: "One or more bookings have changed since snapshot was created",
    ErrorCode.SNAPSHOT_OPERATION_NOT_ALLOWED: "You do not have permission to perform this snapshot operation",
}


class BookingError(Exception):
    def __init__(self, code: ErrorCode, detail: str | None = None):
        self.code = code
        self.message = detail or ERROR_MESSAGES.get(code, "Unknown error")
        super().__init__(self.message)
