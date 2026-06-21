from datetime import date, time, datetime, timedelta

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from booking import MAX_RECURRING_WEEKS, ENV_VAR_NAME
from booking.database import get_db, get_db_readonly
from booking.errors import BookingError, ErrorCode
from booking.models import (
    BookingCreate,
    BookingAction,
    BookingOut,
    BookingDetailOut,
    BookingStatus,
    BookingWeekPhase,
    RecurringBookingCreate,
    RecurringBookingOut,
    RecurringResultItem,
    BatchOut,
    BatchDetailOut,
    VALID_TRANSITIONS,
    RecurringConfigOut,
    BatchRescheduleCreate,
    BatchCancelCreate,
    BatchOperationItem,
    BatchOperationOut,
)

from booking import DEFAULT_MAX_RECURRING_WEEKS, MIN_RECURRING_WEEKS, ABSOLUTE_MAX_RECURRING_WEEKS

router = APIRouter(prefix="/api/bookings", tags=["bookings"])

APPROVAL_ROLES = {"admin", "staff"}
ADMIN_ROLES = {"admin", "staff"}


def _booking_to_out(row) -> dict:
    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "room_name": row["room_name"] if "room_name" in row.keys() else "",
        "user_id": row["user_id"],
        "batch_id": row["batch_id"] if "batch_id" in row.keys() else None,
        "date": row["date"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "status": row["status"],
        "purpose": row["purpose"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _booking_to_detail_out(row, phase: BookingWeekPhase) -> dict:
    out = _booking_to_out(row)
    out["week_phase"] = phase.value
    out["old_date"] = row["old_date"] if "old_date" in row.keys() else None
    out["rescheduled_from_booking_id"] = (
        row["rescheduled_from_booking_id"]
        if "rescheduled_from_booking_id" in row.keys()
        else None
    )
    return out


def _classify_week_phase(booking_row) -> BookingWeekPhase:
    today = date.today()
    now = datetime.now()
    booking_date = date.fromisoformat(booking_row["date"])
    start_t = time.fromisoformat(booking_row["start_time"])
    status = BookingStatus(booking_row["status"])

    is_in_effect = (
        booking_date < today
        or (booking_date == today and start_t <= now.time())
        or status == BookingStatus.EXPIRED
    )
    if is_in_effect:
        return BookingWeekPhase.PRESERVED_IN_EFFECT
    if status == BookingStatus.APPROVED:
        return BookingWeekPhase.PRESERVED_APPROVED
    if status in (BookingStatus.CANCELLED, BookingStatus.REJECTED, BookingStatus.EXPIRED):
        return BookingWeekPhase.FINISHED
    return BookingWeekPhase.ADJUSTABLE


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


def _write_audit(conn, booking_id: int | None, action: str, old_status: str | None,
                 new_status: str | None, operator_id: str, operator_role: str, detail: str,
                 batch_id: int | None = None, snapshot_id: int | None = None):
    conn.execute(
        """INSERT INTO audit_logs (booking_id, batch_id, snapshot_id, action, old_status, new_status, operator_id, operator_role, detail)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (booking_id, batch_id, snapshot_id, action, old_status, new_status, operator_id, operator_role, detail),
    )


def _create_single_booking(conn, room_id: int, user_id: str, booking_date: str,
                           start_time: str, end_time: str, purpose: str,
                           batch_id: int | None = None) -> dict:
    room = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        raise BookingError(ErrorCode.ROOM_NOT_FOUND)
    if not room["is_active"]:
        raise BookingError(ErrorCode.ROOM_INACTIVE)

    _check_slot_open(conn, room_id, booking_date, start_time, end_time)
    _check_overlap(conn, room_id, booking_date, start_time, end_time)

    cur = conn.execute(
        """INSERT INTO bookings (room_id, user_id, batch_id, date, start_time, end_time, purpose)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (room_id, user_id, batch_id, booking_date, start_time, end_time, purpose),
    )
    booking_id = cur.lastrowid

    _write_audit(conn, booking_id, "create", None, "pending",
                 user_id, "resident", purpose, batch_id=batch_id)

    row = conn.execute(
        """SELECT b.*, r.name as room_name FROM bookings b
           JOIN rooms r ON b.room_id = r.id WHERE b.id = ?""",
        (booking_id,),
    ).fetchone()
    return _booking_to_out(row)


@router.post("", response_model=BookingOut, status_code=201)
def create_booking(body: BookingCreate):
    date_str = body.date.isoformat()
    start_str = body.start_time.isoformat()
    end_str = body.end_time.isoformat()

    if body.start_time >= body.end_time:
        raise BookingError(ErrorCode.INVALID_TIME_RANGE)

    with get_db() as conn:
        result = _create_single_booking(
            conn, body.room_id, body.user_id, date_str, start_str, end_str, body.purpose
        )
    return result


@router.get("/recurring/config", response_model=RecurringConfigOut)
def get_recurring_config():
    return RecurringConfigOut(
        max_recurring_weeks=MAX_RECURRING_WEEKS,
        min_recurring_weeks=MIN_RECURRING_WEEKS,
        absolute_max_recurring_weeks=ABSOLUTE_MAX_RECURRING_WEEKS,
        default_max_recurring_weeks=DEFAULT_MAX_RECURRING_WEEKS,
        env_var_name=ENV_VAR_NAME,
    )


@router.post("/recurring", response_model=RecurringBookingOut, status_code=201)
def create_recurring_booking(body: RecurringBookingCreate):
    if body.start_time >= body.end_time:
        raise BookingError(ErrorCode.INVALID_TIME_RANGE)

    if body.weeks > MAX_RECURRING_WEEKS:
        raise BookingError(
            ErrorCode.BATCH_LIMIT_EXCEEDED,
            f"Maximum {MAX_RECURRING_WEEKS} weeks allowed, requested {body.weeks}. "
            f"Current limit set by {ENV_VAR_NAME}={MAX_RECURRING_WEEKS} "
            f"(range: {MIN_RECURRING_WEEKS}-{ABSOLUTE_MAX_RECURRING_WEEKS})"
        )

    start_str = body.start_time.isoformat()
    end_str = body.end_time.isoformat()

    items: list[RecurringResultItem] = []
    success_count = 0
    skip_count = 0
    denied_count = 0
    exceeded_count = 0

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO booking_batches (user_id, total_count, max_recurring_weeks_at_creation)
               VALUES (?, ?, ?)""",
            (body.user_id, body.weeks, MAX_RECURRING_WEEKS),
        )
        batch_id = cur.lastrowid

        _write_audit(
            conn, None, "batch_create", None, None,
            body.user_id, "resident",
            f"Recurring booking batch: {body.weeks} weeks starting {body.start_date.isoformat()}, "
            f"max_recurring_weeks={MAX_RECURRING_WEEKS}",
            batch_id=batch_id
        )

        for i in range(body.weeks):
            current_date = body.start_date + timedelta(weeks=i)
            date_str = current_date.isoformat()

            try:
                result = _create_single_booking(
                    conn, body.room_id, body.user_id, date_str,
                    start_str, end_str, body.purpose, batch_id=batch_id
                )
                items.append(RecurringResultItem(
                    date=date_str,
                    status="success",
                    booking_id=result["id"]
                ))
                success_count += 1
            except BookingError as e:
                if e.code == ErrorCode.BOOKING_OVERLAP:
                    items.append(RecurringResultItem(
                        date=date_str,
                        status="skipped",
                        error_code=e.code,
                        message=e.message
                    ))
                    skip_count += 1
                elif e.code in (ErrorCode.SLOT_NOT_OPEN, ErrorCode.ROOM_INACTIVE):
                    items.append(RecurringResultItem(
                        date=date_str,
                        status="denied",
                        error_code=e.code,
                        message=e.message
                    ))
                    denied_count += 1
                else:
                    items.append(RecurringResultItem(
                        date=date_str,
                        status="denied",
                        error_code=e.code,
                        message=e.message
                    ))
                    denied_count += 1

        conn.execute(
            """UPDATE booking_batches
               SET success_count = ?, skip_count = ?, denied_count = ?, exceeded_count = ?
               WHERE id = ?""",
            (success_count, skip_count, denied_count, exceeded_count, batch_id)
        )

        batch_row = conn.execute(
            "SELECT * FROM booking_batches WHERE id = ?", (batch_id,)
        ).fetchone()

    return RecurringBookingOut(
        batch_id=batch_id,
        user_id=body.user_id,
        total=body.weeks,
        success=success_count,
        skipped=skip_count,
        denied=denied_count,
        exceeded=exceeded_count,
        items=items,
        created_at=batch_row["created_at"]
    )


@router.get("", response_model=list[BookingOut])
def list_bookings(
    status: BookingStatus | None = None,
    room_id: int | None = None,
    user_id: str | None = None,
    date: date | None = None,
    batch_id: int | None = None,
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
    if batch_id:
        conditions.append("b.batch_id = ?")
        params.append(batch_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""SELECT b.*, r.name as room_name FROM bookings b
            JOIN rooms r ON b.room_id = r.id {where}
            ORDER BY b.date DESC, b.start_time""",
        params,
    ).fetchall()
    return [_booking_to_out(r) for r in rows]


def _batch_to_out(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "total_count": row["total_count"],
        "success_count": row["success_count"],
        "skip_count": row["skip_count"],
        "denied_count": row["denied_count"],
        "exceeded_count": row["exceeded_count"],
        "max_recurring_weeks_at_creation": row["max_recurring_weeks_at_creation"],
        "created_at": row["created_at"],
    }


def _check_batch_access(conn, batch_id: int, operator_id: str, operator_role: str) -> dict:
    row = conn.execute(
        "SELECT * FROM booking_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    if not row:
        raise BookingError(ErrorCode.BATCH_NOT_FOUND)
    if operator_role == "resident" and row["user_id"] != operator_id:
        raise BookingError(
            ErrorCode.PERMISSION_DENIED,
            "Residents can only operate on their own batches"
        )
    return row


@router.get("/batches", response_model=list[BatchOut])
def list_batches(
    user_id: str | None = None,
    operator_id: str | None = None,
    operator_role: str = "resident",
):
    conn = get_db_readonly()
    conditions = []
    params = []

    if operator_role == "resident":
        if user_id is not None and user_id != operator_id:
            raise BookingError(
                ErrorCode.PERMISSION_DENIED,
                "Residents can only list their own batches"
            )
        conditions.append("user_id = ?")
        params.append(operator_id)
    elif user_id:
        conditions.append("user_id = ?")
        params.append(user_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM booking_batches {where} ORDER BY id DESC",
        params,
    ).fetchall()
    return [_batch_to_out(r) for r in rows]


@router.get("/batches/{batch_id}", response_model=BatchDetailOut)
def get_batch(batch_id: int, operator_id: str | None = None, operator_role: str = "resident"):
    conn = get_db_readonly()
    row = conn.execute(
        "SELECT * FROM booking_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    if not row:
        raise BookingError(ErrorCode.BATCH_NOT_FOUND)

    if operator_role == "resident" and row["user_id"] != operator_id:
        raise BookingError(
            ErrorCode.PERMISSION_DENIED,
            "Residents can only view their own batches"
        )

    bookings = conn.execute(
        """SELECT b.*, r.name as room_name FROM bookings b
           JOIN rooms r ON b.room_id = r.id
           WHERE b.batch_id = ?
           ORDER BY b.date, b.start_time""",
        (batch_id,),
    ).fetchall()

    result = _batch_to_out(row)
    result["bookings"] = [
        _booking_to_detail_out(b, _classify_week_phase(b)) for b in bookings
    ]
    return result


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
                     body.operator_id, body.operator_role, body.reason,
                     batch_id=row["batch_id"])

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
                     body.operator_id, body.operator_role, body.reason,
                     batch_id=row["batch_id"])

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
                     body.operator_id, body.operator_role, body.reason,
                     batch_id=row["batch_id"])

        result = conn.execute(
            """SELECT b.*, r.name as room_name FROM bookings b
               JOIN rooms r ON b.room_id = r.id WHERE b.id = ?""",
            (booking_id,),
        ).fetchone()
    return _booking_to_out(result)


@router.post("/{booking_id}/expire", response_model=dict)
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
                         "system", "system", "Auto-expired past booking",
                         batch_id=row["batch_id"])
            count += 1

    return {"expired_count": count}


# ============================================================
# 新增：批量改期
# ============================================================
@router.post("/batches/{batch_id}/reschedule", response_model=BatchOperationOut, status_code=200)
def reschedule_batch(batch_id: int, body: BatchRescheduleCreate):
    if body.new_start_time is not None and body.new_end_time is not None:
        if body.new_start_time >= body.new_end_time:
            raise BookingError(ErrorCode.INVALID_TIME_RANGE)
    if (body.new_start_time is None) != (body.new_end_time is None):
        raise BookingError(
            ErrorCode.INVALID_TIME_RANGE,
            "new_start_time and new_end_time must be provided together or both omitted"
        )

    with get_db() as conn:
        batch_row = _check_batch_access(conn, batch_id, body.operator_id, body.operator_role)

        bookings = conn.execute(
            """SELECT b.*, r.name as room_name FROM bookings b
               JOIN rooms r ON b.room_id = r.id
               WHERE b.batch_id = ?
               ORDER BY b.date, b.start_time""",
            (batch_id,),
        ).fetchall()

        if not bookings:
            raise BookingError(
                ErrorCode.BATCH_NOTHING_TO_OPERATE,
                "This batch has no associated bookings"
            )

        room_id = bookings[0]["room_id"]
        original_start_time = bookings[0]["start_time"]
        original_end_time = bookings[0]["end_time"]
        user_id = batch_row["user_id"]
        purpose = bookings[0]["purpose"]

        adjustable_items = []
        preserved_items_info = []

        for b in bookings:
            phase = _classify_week_phase(b)
            if phase == BookingWeekPhase.ADJUSTABLE:
                adjustable_items.append(b)
            else:
                preserved_items_info.append((b, phase))

        if not adjustable_items:
            raise BookingError(
                ErrorCode.BATCH_NOTHING_TO_OPERATE,
                "No adjustable bookings in this batch (all in effect, approved, or finished)"
            )

        new_start_time_str = (
            body.new_start_time.isoformat()
            if body.new_start_time is not None
            else original_start_time
        )
        new_end_time_str = (
            body.new_end_time.isoformat()
            if body.new_end_time is not None
            else original_end_time
        )

        items: list[BatchOperationItem] = []
        success_count = 0
        preserved_count = len(preserved_items_info)
        skipped_count = 0
        denied_count = 0

        _write_audit(
            conn, None, "batch_reschedule_start", None, None,
            body.operator_id, body.operator_role,
            f"Start rescheduling batch #{batch_id}: "
            f"new_start_date={body.new_start_date.isoformat()}, "
            f"time={new_start_time_str}-{new_end_time_str}, "
            f"reason={body.reason}, "
            f"max_recurring_weeks_at_operation={MAX_RECURRING_WEEKS}",
            batch_id=batch_id
        )

        for b, phase in preserved_items_info:
            items.append(BatchOperationItem(
                booking_id=b["id"],
                old_date=b["date"],
                new_date=b["date"],
                old_status=b["status"],
                new_status=b["status"],
                result="preserved",
                week_phase_before=phase.value,
                message=f"Preserved ({phase.value.replace('_', ' ')})",
            ))

        new_dates = []
        for i in range(len(adjustable_items)):
            nd = body.new_start_date + timedelta(weeks=i)
            new_dates.append(nd.isoformat())

        exclude_ids_for_overlap_check = set()

        for idx, b in enumerate(adjustable_items):
            old_date = b["date"]
            old_status = b["status"]
            new_date = new_dates[idx]
            booking_id = b["id"]

            phase_before = _classify_week_phase(b)

            try:
                room = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
                if not room:
                    raise BookingError(ErrorCode.ROOM_NOT_FOUND)
                if not room["is_active"]:
                    raise BookingError(ErrorCode.ROOM_INACTIVE)

                dt = date.fromisoformat(new_date)
                weekday = dt.weekday()
                slots = conn.execute(
                    "SELECT start_time, end_time FROM time_slots WHERE room_id = ? AND weekday = ?",
                    (room_id, weekday),
                ).fetchall()
                if not slots:
                    raise BookingError(
                        ErrorCode.NEW_SLOT_NOT_OPEN,
                        f"No open time slots for new date {new_date} (weekday {weekday})"
                    )
                t_start = time.fromisoformat(new_start_time_str)
                t_end = time.fromisoformat(new_end_time_str)
                slot_ok = False
                for slot in slots:
                    s = time.fromisoformat(slot["start_time"])
                    e = time.fromisoformat(slot["end_time"])
                    if t_start >= s and t_end <= e:
                        slot_ok = True
                        break
                if not slot_ok:
                    raise BookingError(
                        ErrorCode.NEW_SLOT_NOT_OPEN,
                        f"Time {new_start_time_str}-{new_end_time_str} is not within any open slot on {new_date}"
                    )

                query = """
                    SELECT id FROM bookings
                    WHERE room_id = ? AND date = ? AND status = 'approved'
                      AND start_time < ? AND end_time > ?
                      AND id != ?
                """
                params = [room_id, new_date, new_end_time_str, new_start_time_str, booking_id]
                overlap = conn.execute(query, params).fetchone()
                if overlap:
                    raise BookingError(
                        ErrorCode.NEW_BOOKING_OVERLAP,
                        f"New date {new_date} overlaps with approved booking #{overlap['id']}"
                    )

                conn.execute(
                    """UPDATE bookings
                       SET date = ?, start_time = ?, end_time = ?,
                           old_date = ?, rescheduled_from_booking_id = ?,
                           updated_at = datetime('now','localtime')
                       WHERE id = ?""",
                    (new_date, new_start_time_str, new_end_time_str,
                     old_date, booking_id, booking_id),
                )

                _write_audit(
                    conn, booking_id, "reschedule",
                    old_status, old_status,
                    body.operator_id, body.operator_role,
                    f"Rescheduled: {old_date} {original_start_time}-{original_end_time} "
                    f"-> {new_date} {new_start_time_str}-{new_end_time_str}. "
                    f"Reason: {body.reason}. "
                    f"max_recurring_weeks_at_operation={MAX_RECURRING_WEEKS}",
                    batch_id=batch_id
                )

                items.append(BatchOperationItem(
                    booking_id=booking_id,
                    old_date=old_date,
                    new_date=new_date,
                    old_status=old_status,
                    new_status=old_status,
                    result="success",
                    week_phase_before=phase_before.value,
                ))
                success_count += 1
                exclude_ids_for_overlap_check.add(booking_id)

            except BookingError as e:
                if e.code in (ErrorCode.NEW_SLOT_NOT_OPEN, ErrorCode.NEW_BOOKING_OVERLAP,
                              ErrorCode.ROOM_INACTIVE, ErrorCode.ROOM_NOT_FOUND):
                    items.append(BatchOperationItem(
                        booking_id=booking_id,
                        old_date=old_date,
                        new_date=new_date,
                        old_status=old_status,
                        new_status=old_status,
                        result="denied",
                        error_code=e.code,
                        message=e.message,
                        week_phase_before=phase_before.value,
                    ))
                    denied_count += 1
                else:
                    items.append(BatchOperationItem(
                        booking_id=booking_id,
                        old_date=old_date,
                        new_date=new_date,
                        old_status=old_status,
                        new_status=old_status,
                        result="skipped",
                        error_code=e.code,
                        message=e.message,
                        week_phase_before=phase_before.value,
                    ))
                    skipped_count += 1

        _write_audit(
            conn, None, "batch_reschedule_end", None, None,
            body.operator_id, body.operator_role,
            f"Finish rescheduling batch #{batch_id}: "
            f"success={success_count}, preserved={preserved_count}, "
            f"skipped={skipped_count}, denied={denied_count}",
            batch_id=batch_id
        )

        operated_at = conn.execute("SELECT datetime('now','localtime') as ts").fetchone()["ts"]

    return BatchOperationOut(
        batch_id=batch_id,
        user_id=user_id,
        operation="reschedule",
        total=len(items),
        success=success_count,
        preserved=preserved_count,
        skipped=skipped_count,
        denied=denied_count,
        max_recurring_weeks_at_creation=batch_row["max_recurring_weeks_at_creation"],
        max_recurring_weeks_at_operation=MAX_RECURRING_WEEKS,
        items=items,
        operated_at=operated_at,
    )


# ============================================================
# 新增：整批取消
# ============================================================
@router.post("/batches/{batch_id}/cancel", response_model=BatchOperationOut, status_code=200)
def cancel_batch(batch_id: int, body: BatchCancelCreate):
    with get_db() as conn:
        batch_row = _check_batch_access(conn, batch_id, body.operator_id, body.operator_role)

        bookings = conn.execute(
            """SELECT b.*, r.name as room_name FROM bookings b
               JOIN rooms r ON b.room_id = r.id
               WHERE b.batch_id = ?
               ORDER BY b.date, b.start_time""",
            (batch_id,),
        ).fetchall()

        if not bookings:
            raise BookingError(
                ErrorCode.BATCH_NOTHING_TO_OPERATE,
                "This batch has no associated bookings"
            )

        user_id = batch_row["user_id"]

        items: list[BatchOperationItem] = []
        success_count = 0
        preserved_count = 0
        skipped_count = 0
        denied_count = 0

        _write_audit(
            conn, None, "batch_cancel_start", None, None,
            body.operator_id, body.operator_role,
            f"Start canceling batch #{batch_id}: reason={body.reason}, "
            f"operator_role={body.operator_role}",
            batch_id=batch_id
        )

        for b in bookings:
            booking_id = b["id"]
            old_date = b["date"]
            old_status = b["status"]
            phase = _classify_week_phase(b)

            target = BookingStatus.CANCELLED
            current = BookingStatus(old_status)

            if phase == BookingWeekPhase.PRESERVED_IN_EFFECT:
                items.append(BatchOperationItem(
                    booking_id=booking_id,
                    old_date=old_date,
                    new_date=old_date,
                    old_status=old_status,
                    new_status=old_status,
                    result="preserved",
                    week_phase_before=phase.value,
                    message="Preserved (booking already in effect / passed)",
                ))
                preserved_count += 1
                continue

            if current == BookingStatus.APPROVED and phase == BookingWeekPhase.PRESERVED_APPROVED:
                if body.operator_role in ADMIN_ROLES:
                    try:
                        conn.execute(
                            "UPDATE bookings SET status = 'cancelled', "
                            "updated_at = datetime('now','localtime') WHERE id = ?",
                            (booking_id,),
                        )
                        _write_audit(
                            conn, booking_id, "cancel", old_status, "cancelled",
                            body.operator_id, body.operator_role,
                            f"Admin/staff batch cancel approved booking. Reason: {body.reason}",
                            batch_id=batch_id
                        )
                        items.append(BatchOperationItem(
                            booking_id=booking_id,
                            old_date=old_date,
                            new_date=old_date,
                            old_status=old_status,
                            new_status="cancelled",
                            result="success",
                            week_phase_before=phase.value,
                            message="Admin/staff cancelled approved booking",
                        ))
                        success_count += 1
                        continue
                    except Exception as e:
                        items.append(BatchOperationItem(
                            booking_id=booking_id,
                            old_date=old_date,
                            new_date=old_date,
                            old_status=old_status,
                            new_status=old_status,
                            result="denied",
                            error_code=ErrorCode.INVALID_STATUS_TRANSITION,
                            message=f"Unexpected error: {e}",
                            week_phase_before=phase.value,
                        ))
                        denied_count += 1
                        continue
                else:
                    items.append(BatchOperationItem(
                        booking_id=booking_id,
                        old_date=old_date,
                        new_date=old_date,
                        old_status=old_status,
                        new_status=old_status,
                        result="preserved",
                        week_phase_before=phase.value,
                        message="Preserved (approved booking, only admin/staff can batch cancel)",
                    ))
                    preserved_count += 1
                    continue

            if target not in VALID_TRANSITIONS.get(current, set()):
                items.append(BatchOperationItem(
                    booking_id=booking_id,
                    old_date=old_date,
                    new_date=old_date,
                    old_status=old_status,
                    new_status=old_status,
                    result="skipped",
                    error_code=ErrorCode.INVALID_STATUS_TRANSITION,
                    message=f"Cannot cancel booking with status '{old_status}'",
                    week_phase_before=phase.value,
                ))
                skipped_count += 1
                continue

            try:
                conn.execute(
                    "UPDATE bookings SET status = 'cancelled', "
                    "updated_at = datetime('now','localtime') WHERE id = ?",
                    (booking_id,),
                )
                _write_audit(
                    conn, booking_id, "cancel", old_status, "cancelled",
                    body.operator_id, body.operator_role,
                    f"Batch cancel. Reason: {body.reason}",
                    batch_id=batch_id
                )
                items.append(BatchOperationItem(
                    booking_id=booking_id,
                    old_date=old_date,
                    new_date=old_date,
                    old_status=old_status,
                    new_status="cancelled",
                    result="success",
                    week_phase_before=phase.value,
                ))
                success_count += 1
            except Exception as e:
                items.append(BatchOperationItem(
                    booking_id=booking_id,
                    old_date=old_date,
                    new_date=old_date,
                    old_status=old_status,
                    new_status=old_status,
                    result="denied",
                    message=f"Unexpected error: {e}",
                    week_phase_before=phase.value,
                ))
                denied_count += 1

        _write_audit(
            conn, None, "batch_cancel_end", None, None,
            body.operator_id, body.operator_role,
            f"Finish canceling batch #{batch_id}: "
            f"success={success_count}, preserved={preserved_count}, "
            f"skipped={skipped_count}, denied={denied_count}",
            batch_id=batch_id
        )

        operated_at = conn.execute("SELECT datetime('now','localtime') as ts").fetchone()["ts"]

    return BatchOperationOut(
        batch_id=batch_id,
        user_id=user_id,
        operation="cancel",
        total=len(items),
        success=success_count,
        preserved=preserved_count,
        skipped=skipped_count,
        denied=denied_count,
        max_recurring_weeks_at_creation=batch_row["max_recurring_weeks_at_creation"],
        max_recurring_weeks_at_operation=MAX_RECURRING_WEEKS,
        items=items,
        operated_at=operated_at,
    )


# ============================================================
# 新增：批次导出（含处理结果、规则快照和审计信息）
# ============================================================
@router.get("/batches/{batch_id}/export")
def export_batch(
    batch_id: int,
    operator_id: str | None = None,
    operator_role: str = "resident",
):
    conn = get_db_readonly()
    batch_row = conn.execute(
        "SELECT * FROM booking_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    if not batch_row:
        raise BookingError(ErrorCode.BATCH_NOT_FOUND)

    if operator_role == "resident" and batch_row["user_id"] != operator_id:
        raise BookingError(
            ErrorCode.PERMISSION_DENIED,
            "Residents can only export their own batches"
        )

    bookings = conn.execute(
        """SELECT b.*, r.name as room_name FROM bookings b
           JOIN rooms r ON b.room_id = r.id
           WHERE b.batch_id = ?
           ORDER BY b.date, b.start_time""",
        (batch_id,),
    ).fetchall()

    audit_logs = conn.execute(
        "SELECT * FROM audit_logs WHERE batch_id = ? ORDER BY id",
        (batch_id,),
    ).fetchall()

    booking_details = []
    for b in bookings:
        phase = _classify_week_phase(b)
        bd = _booking_to_detail_out(b, phase)
        per_booking_logs = [
            {
                "id": log["id"],
                "booking_id": log["booking_id"],
                "action": log["action"],
                "old_status": log["old_status"],
                "new_status": log["new_status"],
                "operator_id": log["operator_id"],
                "operator_role": log["operator_role"],
                "detail": log["detail"],
                "created_at": log["created_at"],
            }
            for log in audit_logs if log["booking_id"] == b["id"]
        ]
        bd["audit_logs"] = per_booking_logs
        booking_details.append(bd)

    batch_level_logs = [
        {
            "id": log["id"],
            "action": log["action"],
            "old_status": log["old_status"],
            "new_status": log["new_status"],
            "operator_id": log["operator_id"],
            "operator_role": log["operator_role"],
            "detail": log["detail"],
            "created_at": log["created_at"],
        }
        for log in audit_logs if log["booking_id"] is None
    ]

    export_data = {
        "batch": {
            "id": batch_row["id"],
            "user_id": batch_row["user_id"],
            "total_count": batch_row["total_count"],
            "success_count": batch_row["success_count"],
            "skip_count": batch_row["skip_count"],
            "denied_count": batch_row["denied_count"],
            "exceeded_count": batch_row["exceeded_count"],
            "max_recurring_weeks_at_creation": batch_row["max_recurring_weeks_at_creation"],
            "current_max_recurring_weeks": MAX_RECURRING_WEEKS,
            "env_var_name": ENV_VAR_NAME,
            "created_at": batch_row["created_at"],
            "exported_at": conn.execute(
                "SELECT datetime('now','localtime') as ts"
            ).fetchone()["ts"],
        },
        "config_snapshot": {
            "max_recurring_weeks_at_creation": batch_row["max_recurring_weeks_at_creation"],
            "max_recurring_weeks_current": MAX_RECURRING_WEEKS,
            "min_recurring_weeks": MIN_RECURRING_WEEKS,
            "absolute_max_recurring_weeks": ABSOLUTE_MAX_RECURRING_WEEKS,
            "default_max_recurring_weeks": DEFAULT_MAX_RECURRING_WEEKS,
            "env_var_name": ENV_VAR_NAME,
        },
        "bookings": booking_details,
        "batch_level_audit_logs": batch_level_logs,
        "summary": {
            "total_bookings": len(booking_details),
            "preserved_in_effect": sum(
                1 for bd in booking_details
                if bd["week_phase"] == BookingWeekPhase.PRESERVED_IN_EFFECT.value
            ),
            "preserved_approved": sum(
                1 for bd in booking_details
                if bd["week_phase"] == BookingWeekPhase.PRESERVED_APPROVED.value
            ),
            "adjustable": sum(
                1 for bd in booking_details
                if bd["week_phase"] == BookingWeekPhase.ADJUSTABLE.value
            ),
            "finished": sum(
                1 for bd in booking_details
                if bd["week_phase"] == BookingWeekPhase.FINISHED.value
            ),
        },
    }

    return JSONResponse(
        content=export_data,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f"attachment; filename=batch_{batch_id}_export.json"
            ),
        },
    )
