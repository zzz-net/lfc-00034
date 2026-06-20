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
}


class BookingError(Exception):
    def __init__(self, code: ErrorCode, detail: str | None = None):
        self.code = code
        self.message = detail or ERROR_MESSAGES.get(code, "Unknown error")
        super().__init__(self.message)
