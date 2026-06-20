from datetime import date, time, datetime

from fastapi import APIRouter

from booking.database import get_db, get_db_readonly
from booking.errors import BookingError, ErrorCode
from booking.models import (
    BookingCreate,
    BookingAction,
    BookingOut,
    BookingStatus,
    VALID_TRANSITIONS,
)

router = APIRouter(prefix="/api/bookings", tags=["bookings"])

APPROVAL_ROLES = {"admin", "staff"}


def _booking_to_out(row) -> dict:
    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "room_name": row["room_name"] if "room_name" in row.keys() else "",
        "user_id": row["user_id"],
        "date": row["date"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "status": row["status"],
        "purpose": row["purpose"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _check_slot_open(conn, room_id: int, booking_date: str, start_time: str, end_time: str):
    dt = date.fromisoformat(booking_date)
    weekday = dt.weekday()
    slots = conn.execute(
        "SELECT start_time, end_time FROM time_slots WHERE room_id = ? AND weekday = ?",
        (room_id, weekday),
    ).fetchall()
    if not slots:
        raise BookingError(ErrorCode.SLOT_NOT_OPEN,
                           f"No open time slots for weekday {weekday} ({dt.strftime('%A')})")
    t_start = time.fromisoformat(start_time)
    t_end = time.fromisoformat(end_time)
    for slot in slots:
        s = time.fromisoformat(slot["start_time"])
        e = time.fromisoformat(slot["end_time"])
        if t_start >= s and t_end <= e:
            return
    raise BookingError(ErrorCode.SLOT_NOT_OPEN,
                       f"Time {start_time}-{end_time} is not within any open slot on {dt.strftime('%A')}")


def _check_overlap(conn, room_id: int, booking_date: str, start_time: str, end_time: str,
                   exclude_id: int | None = None):
    query = """
        SELECT id FROM bookings
        WHERE room_id = ? AND date = ? AND status = 'approved'
          AND start_time < ? AND end_time > ?
    """
    params = [room_id, booking_date, end_time, start_time]
    if exclude_id:
        query += " AND id != ?"
        params.append(exclude_id)
    overlap = conn.execute(query, params).fetchone()
    if overlap:
        raise BookingError(ErrorCode.BOOKING_OVERLAP,
                           f"Overlaps with approved booking #{overlap['id']}")


def _check_approval_permission(operator_role: str):
    if operator_role not in APPROVAL_ROLES:
        raise BookingError(ErrorCode.PERMISSION_DENIED,
                           f"Only {sorted(APPROVAL_ROLES)} can approve or reject bookings")


def _write_audit(conn, booking_id: int, action: str, old_status: str | None,
                 new_status: str | None, operator_id: str, operator_role: str, detail: str):
    conn.execute(
        """INSERT INTO audit_logs (booking_id, action, old_status, new_status, operator_id, operator_role, detail)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (booking_id, action, old_status, new_status, operator_id, operator_role, detail),
    )


@router.post("", response_model=BookingOut, status_code=201)
def create_booking(body: BookingCreate):
    date_str = body.date.isoformat()
    start_str = body.start_time.isoformat()
    end_str = body.end_time.isoformat()

    if body.start_time >= body.end_time:
        raise BookingError(ErrorCode.INVALID_TIME_RANGE)

    with get_db() as conn:
        room = conn.execute("SELECT * FROM rooms WHERE id = ?", (body.room_id,)).fetchone()
        if not room:
            raise BookingError(ErrorCode.ROOM_NOT_FOUND)
        if not room["is_active"]:
            raise BookingError(ErrorCode.ROOM_INACTIVE)

        _check_slot_open(conn, body.room_id, date_str, start_str, end_str)
        _check_overlap(conn, body.room_id, date_str, start_str, end_str)

        cur = conn.execute(
            """INSERT INTO bookings (room_id, user_id, date, start_time, end_time, purpose)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (body.room_id, body.user_id, date_str, start_str, end_str, body.purpose),
        )
        booking_id = cur.lastrowid

        _write_audit(conn, booking_id, "create", None, "pending",
                     body.user_id, "resident", body.purpose)

        row = conn.execute(
            """SELECT b.*, r.name as room_name FROM bookings b
               JOIN rooms r ON b.room_id = r.id WHERE b.id = ?""",
            (booking_id,),
        ).fetchone()
    return _booking_to_out(row)


@router.get("", response_model=list[BookingOut])
def list_bookings(
    status: BookingStatus | None = None,
    room_id: int | None = None,
    user_id: str | None = None,
    date: date | None = None,
):
    conn = get_db_readonly()
    conditions = []
    params = []
    if status:
        conditions.append("b.status = ?")
        params.append(status.value)
    if room_id:
        conditions.append("b.room_id = ?")
        params.append(room_id)
    if user_id:
        conditions.append("b.user_id = ?")
        params.append(user_id)
    if date:
        conditions.append("b.date = ?")
        params.append(date.isoformat())

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""SELECT b.*, r.name as room_name FROM bookings b
            JOIN rooms r ON b.room_id = r.id {where}
            ORDER BY b.date DESC, b.start_time""",
        params,
    ).fetchall()
    return [_booking_to_out(r) for r in rows]


@router.get("/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int):
    conn = get_db_readonly()
    row = conn.execute(
        """SELECT b.*, r.name as room_name FROM bookings b
           JOIN rooms r ON b.room_id = r.id WHERE b.id = ?""",
        (booking_id,),
    ).fetchone()
    if not row:
        raise BookingError(ErrorCode.BOOKING_NOT_FOUND)
    return _booking_to_out(row)


@router.post("/{booking_id}/approve", response_model=BookingOut)
def approve_booking(booking_id: int, body: BookingAction):
    _check_approval_permission(body.operator_role)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not row:
            raise BookingError(ErrorCode.BOOKING_NOT_FOUND)
        current = BookingStatus(row["status"])
        if current != BookingStatus.PENDING:
            if current == BookingStatus.APPROVED:
                raise BookingError(ErrorCode.BOOKING_ALREADY_PROCESSED,
                                   "Booking is already approved")
            raise BookingError(ErrorCode.INVALID_STATUS_TRANSITION,
                               f"Cannot approve a booking with status '{current.value}'")

        _check_overlap(conn, row["room_id"], row["date"], row["start_time"], row["end_time"],
                       exclude_id=booking_id)

        conn.execute(
            "UPDATE bookings SET status = 'approved', updated_at = datetime('now','localtime') WHERE id = ?",
            (booking_id,),
        )
        _write_audit(conn, booking_id, "approve", "pending", "approved",
                     body.operator_id, body.operator_role, body.reason)

        result = conn.execute(
            """SELECT b.*, r.name as room_name FROM bookings b
               JOIN rooms r ON b.room_id = r.id WHERE b.id = ?""",
            (booking_id,),
        ).fetchone()
    return _booking_to_out(result)


@router.post("/{booking_id}/reject", response_model=BookingOut)
def reject_booking(booking_id: int, body: BookingAction):
    _check_approval_permission(body.operator_role)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not row:
            raise BookingError(ErrorCode.BOOKING_NOT_FOUND)
        current = BookingStatus(row["status"])
        if current != BookingStatus.PENDING:
            raise BookingError(ErrorCode.INVALID_STATUS_TRANSITION,
                               f"Cannot reject a booking with status '{current.value}'")

        conn.execute(
            "UPDATE bookings SET status = 'rejected', updated_at = datetime('now','localtime') WHERE id = ?",
            (booking_id,),
        )
        _write_audit(conn, booking_id, "reject", "pending", "rejected",
                     body.operator_id, body.operator_role, body.reason)

        result = conn.execute(
            """SELECT b.*, r.name as room_name FROM bookings b
               JOIN rooms r ON b.room_id = r.id WHERE b.id = ?""",
            (booking_id,),
        ).fetchone()
    return _booking_to_out(result)


@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: int, body: BookingAction):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not row:
            raise BookingError(ErrorCode.BOOKING_NOT_FOUND)
        current = BookingStatus(row["status"])
        target = BookingStatus.CANCELLED

        if target not in VALID_TRANSITIONS.get(current, set()):
            raise BookingError(ErrorCode.INVALID_STATUS_TRANSITION,
                               f"Cannot cancel a booking with status '{current.value}'")

        if body.operator_role == "resident" and row["user_id"] != body.operator_id:
            raise BookingError(ErrorCode.PERMISSION_DENIED,
                               "Residents can only cancel their own bookings")

        conn.execute(
            "UPDATE bookings SET status = 'cancelled', updated_at = datetime('now','localtime') WHERE id = ?",
            (booking_id,),
        )
        _write_audit(conn, booking_id, "cancel", current.value, "cancelled",
                     body.operator_id, body.operator_role, body.reason)

        result = conn.execute(
            """SELECT b.*, r.name as room_name FROM bookings b
               JOIN rooms r ON b.room_id = r.id WHERE b.id = ?""",
            (booking_id,),
        ).fetchone()
    return _booking_to_out(result)


@router.post("/expire", response_model=dict)
def expire_bookings():
    with get_db() as conn:
        now = datetime.now()
        today = now.date().isoformat()
        now_time = now.time().isoformat()[:5]

        rows = conn.execute(
            """SELECT * FROM bookings
               WHERE status = 'approved'
                 AND (date < ? OR (date = ? AND end_time <= ?))""",
            (today, today, now_time),
        ).fetchall()

        count = 0
        for row in rows:
            conn.execute(
                "UPDATE bookings SET status = 'expired', updated_at = datetime('now','localtime') WHERE id = ?",
                (row["id"],),
            )
            _write_audit(conn, row["id"], "expire", "approved", "expired",
                         "system", "system", "Auto-expired past booking")
            count += 1

    return {"expired_count": count}
