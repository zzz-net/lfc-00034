import json
import sqlite3
from datetime import date, time, datetime, timedelta

from booking import (
    MAX_RECURRING_WEEKS,
    MIN_RECURRING_WEEKS,
    ABSOLUTE_MAX_RECURRING_WEEKS,
    DEFAULT_MAX_RECURRING_WEEKS,
    ENV_VAR_NAME,
)
from booking.database import get_db, get_db_readonly
from booking.errors import BookingError, ErrorCode
from booking.models import (
    BookingStatus,
    BookingWeekPhase,
    SnapshotStatus,
    SnapshotOperationType,
    SnapshotCreate,
    SnapshotExecute,
    SnapshotRollback,
    SnapshotOut,
    SnapshotListItem,
    SnapshotBookingOut,
    SnapshotConfigOut,
    SnapshotConflictCheck,
    SnapshotConflictItem,
    SnapshotOperationResult,
    SnapshotOperationResultItem,
    AuditLogOut,
    BatchOperationOut,
    BatchOperationItem,
    BatchRescheduleCreate,
    BatchCancelCreate,
    VALID_TRANSITIONS,
)

APPROVAL_ROLES = {"admin", "staff"}
ADMIN_ROLES = {"admin", "staff"}


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


def _write_audit(conn, booking_id: int | None, action: str, old_status: str | None,
                 new_status: str | None, operator_id: str, operator_role: str, detail: str,
                 batch_id: int | None = None, snapshot_id: int | None = None):
    conn.execute(
        """INSERT INTO audit_logs (booking_id, batch_id, snapshot_id, action, old_status, new_status, operator_id, operator_role, detail)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (booking_id, batch_id, snapshot_id, action, old_status, new_status, operator_id, operator_role, detail),
    )


def _audit_log_to_out(row) -> dict:
    def _g(key, default=None):
        try:
            return row[key]
        except (KeyError, IndexError):
            return default
    return {
        "id": row["id"],
        "booking_id": row["booking_id"],
        "batch_id": row["batch_id"],
        "snapshot_id": _g("snapshot_id"),
        "action": row["action"],
        "old_status": row["old_status"],
        "new_status": row["new_status"],
        "operator_id": row["operator_id"],
        "operator_role": row["operator_role"],
        "detail": row["detail"],
        "created_at": row["created_at"],
    }


def _snapshot_booking_to_out(row) -> dict:
    return {
        "booking_id": row["booking_id"],
        "room_id": row["room_id"],
        "room_name": row["room_name"],
        "user_id": row["user_id"],
        "date": row["date"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "status": row["status"],
        "purpose": row["purpose"],
        "old_date": row["old_date"] if "old_date" in row.keys() else None,
        "rescheduled_from_booking_id": (
            row["rescheduled_from_booking_id"]
            if "rescheduled_from_booking_id" in row.keys()
            else None
        ),
        "week_phase": row["week_phase"],
    }


def _snapshot_row_to_out(conn, row) -> dict:
    config_snapshot = json.loads(row["config_snapshot"])
    operation_params = json.loads(row["operation_params"]) if row["operation_params"] else None
    operation_result = json.loads(row["operation_result"]) if row["operation_result"] else None
    rollback_result = json.loads(row["rollback_result"]) if row["rollback_result"] else None

    booking_rows = conn.execute(
        "SELECT * FROM snapshot_bookings WHERE snapshot_id = ? ORDER BY date, start_time",
        (row["id"],)
    ).fetchall()

    audit_rows = conn.execute(
        """SELECT * FROM audit_logs
           WHERE snapshot_id = ?
           ORDER BY id""",
        (row["id"],)
    ).fetchall()

    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "batch_user_id": row["batch_user_id"],
        "operation_type": row["operation_type"],
        "status": row["status"],
        "description": row["description"],
        "operator_id": row["operator_id"],
        "operator_role": row["operator_role"],
        "total_bookings": row["total_bookings"],
        "affected_bookings": row["affected_bookings"],
        "preserved_bookings": row["preserved_bookings"],
        "created_at": row["created_at"],
        "executed_at": row["executed_at"],
        "rolled_back_at": row["rolled_back_at"],
        "config_snapshot": config_snapshot,
        "operation_params": operation_params,
        "booking_snapshots": [_snapshot_booking_to_out(b) for b in booking_rows],
        "conflict_check": None,
        "operation_result": operation_result,
        "rollback_result": rollback_result,
        "audit_logs": [_audit_log_to_out(a) for a in audit_rows],
    }


def _check_operation_permission(operator_role: str):
    if operator_role not in ADMIN_ROLES:
        raise BookingError(
            ErrorCode.SNAPSHOT_OPERATION_NOT_ALLOWED,
            f"Only {sorted(ADMIN_ROLES)} can execute or rollback snapshots"
        )


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


def _get_config_snapshot() -> dict:
    return {
        "max_recurring_weeks_at_snapshot": MAX_RECURRING_WEEKS,
        "min_recurring_weeks": MIN_RECURRING_WEEKS,
        "absolute_max_recurring_weeks": ABSOLUTE_MAX_RECURRING_WEEKS,
        "default_max_recurring_weeks": DEFAULT_MAX_RECURRING_WEEKS,
        "env_var_name": ENV_VAR_NAME,
        "snapshot_created_at": datetime.now().isoformat(),
    }


def _check_conflicts(conn, batch_id: int, booking_ids: list[int], current_snapshot_id: int | None = None) -> SnapshotConflictCheck:
    conflicts: list[SnapshotConflictItem] = []

    for booking_id in booking_ids:
        booking_row = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()

        if not booking_row:
            conflicts.append(SnapshotConflictItem(
                booking_id=booking_id,
                conflict_type="booking_not_found",
                message=f"Booking #{booking_id} no longer exists"
            ))
            continue

        active_snapshot = conn.execute(
            """SELECT s.id, s.status, s.operation_type
               FROM batch_snapshots s
               JOIN snapshot_bookings sb ON s.id = sb.snapshot_id
               WHERE sb.booking_id = ?
                 AND s.status IN ('pending', 'executed')
                 AND s.id != COALESCE(?, 0)
               ORDER BY s.id DESC
               LIMIT 1""",
            (booking_id, current_snapshot_id)
        ).fetchone()

        if active_snapshot:
            conflicts.append(SnapshotConflictItem(
                booking_id=booking_id,
                conflict_type="occupied_by_another_snapshot",
                message=f"Booking #{booking_id} is occupied by snapshot #{active_snapshot['id']} (status: {active_snapshot['status']})",
                current_snapshot_id=active_snapshot["id"],
                current_status=active_snapshot["status"]
            ))

    return SnapshotConflictCheck(
        has_conflict=len(conflicts) > 0,
        conflicts=conflicts
    )


def _verify_booking_unchanged(conn, snapshot_booking_rows) -> tuple[bool, list[SnapshotConflictItem]]:
    from booking.models import SnapshotConflictFieldDiff

    conflicts: list[SnapshotConflictItem] = []

    for sb in snapshot_booking_rows:
        current = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (sb["booking_id"],)
        ).fetchone()

        if not current:
            conflicts.append(SnapshotConflictItem(
                booking_id=sb["booking_id"],
                conflict_type="booking_deleted",
                message=f"Booking #{sb['booking_id']} has been deleted since snapshot was created. Expected booking to exist with status={sb['status']}, date={sb['date']}",
            ))
            continue

        field_diffs: list[SnapshotConflictFieldDiff] = []
        changed_desc = []
        for field in ["date", "start_time", "end_time", "status"]:
            expected = str(sb[field])
            actual = str(current[field])
            if actual != expected:
                field_diffs.append(SnapshotConflictFieldDiff(
                    field=field,
                    expected_value=expected,
                    actual_value=actual,
                ))
                changed_desc.append(f"{field}: expected={expected}, actual={actual}")

        if field_diffs:
            conflicts.append(SnapshotConflictItem(
                booking_id=sb["booking_id"],
                conflict_type="booking_changed",
                message=(
                    f"Booking #{sb['booking_id']} has been modified externally since snapshot was created. "
                    f"Cannot proceed without risk of overwriting. Conflicting fields: {'; '.join(changed_desc)}. "
                    f"Either revert the external changes first, or create a fresh snapshot."
                ),
                current_status=current["status"],
                field_diffs=field_diffs,
            ))

    return len(conflicts) == 0, conflicts


def create_snapshot(body: SnapshotCreate) -> SnapshotOut:
    with get_db() as conn:
        batch_row = _check_batch_access(conn, body.batch_id, body.operator_id, body.operator_role)

        bookings = conn.execute(
            """SELECT b.*, r.name as room_name FROM bookings b
               JOIN rooms r ON b.room_id = r.id
               WHERE b.batch_id = ?
               ORDER BY b.date, b.start_time""",
            (body.batch_id,)
        ).fetchall()

        if not bookings:
            raise BookingError(
                ErrorCode.BATCH_NOTHING_TO_OPERATE,
                "This batch has no associated bookings"
            )

        booking_ids = [b["id"] for b in bookings]
        conflict_check = _check_conflicts(conn, body.batch_id, booking_ids)

        if conflict_check.has_conflict:
            conflict_details = "; ".join([f"#{c.booking_id}: {c.message}" for c in conflict_check.conflicts])
            raise BookingError(
                ErrorCode.SNAPSHOT_CONFLICT,
                f"Cannot create snapshot: {conflict_details}",
                extra={
                    "conflict_check": {
                        "has_conflict": True,
                        "conflicts": [c.model_dump() for c in conflict_check.conflicts],
                    },
                },
            )

        preserved_count = 0
        affected_count = 0

        for b in bookings:
            phase = _classify_week_phase(b)
            if phase in (BookingWeekPhase.ADJUSTABLE,):
                affected_count += 1
            else:
                preserved_count += 1

        config_snapshot = _get_config_snapshot()

        cur = conn.execute(
            """INSERT INTO batch_snapshots
               (batch_id, batch_user_id, operation_type, description,
                operator_id, operator_role, total_bookings, affected_bookings,
                preserved_bookings, config_snapshot, operation_params)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                body.batch_id,
                batch_row["user_id"],
                body.operation_type.value,
                body.description,
                body.operator_id,
                body.operator_role,
                len(bookings),
                affected_count,
                preserved_count,
                json.dumps(config_snapshot),
                json.dumps(body.operation_params) if body.operation_params else None,
            )
        )
        snapshot_id = cur.lastrowid

        for b in bookings:
            phase = _classify_week_phase(b)
            conn.execute(
                """INSERT INTO snapshot_bookings
                   (snapshot_id, booking_id, room_id, room_name, user_id,
                    date, start_time, end_time, status, purpose,
                    old_date, rescheduled_from_booking_id, week_phase)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    b["id"],
                    b["room_id"],
                    b["room_name"],
                    b["user_id"],
                    b["date"],
                    b["start_time"],
                    b["end_time"],
                    b["status"],
                    b["purpose"],
                    b["old_date"] if "old_date" in b.keys() else None,
                    b["rescheduled_from_booking_id"] if "rescheduled_from_booking_id" in b.keys() else None,
                    phase.value,
                )
            )

        _write_audit(
            conn, None, "snapshot_create", None, None,
            body.operator_id, body.operator_role,
            f"Created snapshot #{snapshot_id} for batch #{body.batch_id}, "
            f"operation={body.operation_type.value}, affected={affected_count}, "
            f"preserved={preserved_count}. Description: {body.description}",
            batch_id=body.batch_id,
            snapshot_id=snapshot_id
        )

        snapshot_row = conn.execute(
            "SELECT * FROM batch_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()

        result = _snapshot_row_to_out(conn, snapshot_row)
        result["conflict_check"] = conflict_check.model_dump()

    return result


def get_snapshot(snapshot_id: int, operator_id: str | None = None, operator_role: str = "resident") -> SnapshotOut:
    conn = get_db_readonly()
    row = conn.execute(
        "SELECT * FROM batch_snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()

    if not row:
        raise BookingError(ErrorCode.SNAPSHOT_NOT_FOUND)

    if operator_role == "resident" and row["batch_user_id"] != operator_id:
        raise BookingError(
            ErrorCode.PERMISSION_DENIED,
            "Residents can only view their own snapshots"
        )

    result = _snapshot_row_to_out(conn, row)

    snapshot_bookings = conn.execute(
        "SELECT * FROM snapshot_bookings WHERE snapshot_id = ?", (snapshot_id,)
    ).fetchall()
    booking_ids = [sb["booking_id"] for sb in snapshot_bookings]

    conflict_check = _check_conflicts(conn, row["batch_id"], booking_ids, snapshot_id)
    result["conflict_check"] = conflict_check.model_dump()

    return result


def list_snapshots(batch_id: int | None = None, operator_id: str | None = None,
                   operator_role: str = "resident", status: SnapshotStatus | None = None) -> list[SnapshotListItem]:
    conn = get_db_readonly()
    conditions = []
    params = []

    if operator_role == "resident":
        if operator_id is None:
            raise BookingError(
                ErrorCode.PERMISSION_DENIED,
                "Residents must provide operator_id to list snapshots"
            )
        conditions.append("batch_user_id = ?")
        params.append(operator_id)

    if batch_id:
        conditions.append("batch_id = ?")
        params.append(batch_id)

    if status:
        conditions.append("status = ?")
        params.append(status.value)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM batch_snapshots {where} ORDER BY id DESC",
        params,
    ).fetchall()

    return [
        {
            "id": r["id"],
            "batch_id": r["batch_id"],
            "batch_user_id": r["batch_user_id"],
            "operation_type": r["operation_type"],
            "status": r["status"],
            "description": r["description"],
            "operator_id": r["operator_id"],
            "operator_role": r["operator_role"],
            "total_bookings": r["total_bookings"],
            "affected_bookings": r["affected_bookings"],
            "preserved_bookings": r["preserved_bookings"],
            "created_at": r["created_at"],
            "executed_at": r["executed_at"],
            "rolled_back_at": r["rolled_back_at"],
        }
        for r in rows
    ]


def execute_snapshot(snapshot_id: int, body: SnapshotExecute) -> SnapshotOut:
    _check_operation_permission(body.operator_role)

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM batch_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()

        if not row:
            raise BookingError(ErrorCode.SNAPSHOT_NOT_FOUND)

        if row["status"] == SnapshotStatus.EXECUTED.value:
            raise BookingError(
                ErrorCode.SNAPSHOT_ALREADY_EXECUTED,
                f"Snapshot #{snapshot_id} has already been executed"
            )

        if row["status"] == SnapshotStatus.ROLLED_BACK.value:
            raise BookingError(
                ErrorCode.SNAPSHOT_INVALID_STATUS,
                f"Snapshot #{snapshot_id} has been rolled back and cannot be executed"
            )

        if row["status"] == SnapshotStatus.CANCELLED.value:
            raise BookingError(
                ErrorCode.SNAPSHOT_INVALID_STATUS,
                f"Snapshot #{snapshot_id} has been cancelled"
            )

        if row["status"] != SnapshotStatus.PENDING.value:
            raise BookingError(
                ErrorCode.SNAPSHOT_INVALID_STATUS,
                f"Snapshot #{snapshot_id} is not in pending status (current: {row['status']})"
            )

        snapshot_bookings = conn.execute(
            "SELECT * FROM snapshot_bookings WHERE snapshot_id = ? ORDER BY date, start_time",
            (snapshot_id,)
        ).fetchall()

        unchanged, conflicts = _verify_booking_unchanged(conn, snapshot_bookings)
        if not unchanged:
            conflict_details = "; ".join([f"#{c.booking_id}: {c.message}" for c in conflicts])
            raise BookingError(
                ErrorCode.SNAPSHOT_BOOKING_CHANGED,
                f"Cannot execute snapshot: {conflict_details}",
                extra={
                    "conflict_check": {
                        "has_conflict": True,
                        "conflicts": [c.model_dump() for c in conflicts],
                    },
                },
            )

        booking_ids = [sb["booking_id"] for sb in snapshot_bookings]
        conflict_check = _check_conflicts(conn, row["batch_id"], booking_ids, snapshot_id)
        if conflict_check.has_conflict:
            conflict_details = "; ".join([f"#{c.booking_id}: {c.message}" for c in conflict_check.conflicts])
            raise BookingError(
                ErrorCode.SNAPSHOT_CONFLICT,
                f"Cannot execute snapshot: {conflict_details}",
                extra={
                    "conflict_check": {
                        "has_conflict": True,
                        "conflicts": [c.model_dump() for c in conflict_check.conflicts],
                    },
                },
            )

        operation_type = row["operation_type"]
        operation_params = json.loads(row["operation_params"]) if row["operation_params"] else {}

        _write_audit(
            conn, None, "snapshot_execute_start", None, None,
            body.operator_id, body.operator_role,
            f"Starting execution of snapshot #{snapshot_id}, operation={operation_type}, "
            f"reason={body.reason}",
            batch_id=row["batch_id"],
            snapshot_id=snapshot_id
        )

        operation_result: SnapshotOperationResult | None = None

        if operation_type == SnapshotOperationType.RESCHEDULE.value:
            operation_result = _execute_reschedule(conn, row, snapshot_bookings, operation_params, body)
        elif operation_type == SnapshotOperationType.CANCEL.value:
            operation_result = _execute_cancel(conn, row, snapshot_bookings, body)
        elif operation_type == SnapshotOperationType.EXPORT.value:
            operation_result = _execute_export(conn, row, snapshot_bookings, body)

        conn.execute(
            """UPDATE batch_snapshots
               SET status = 'executed', executed_at = datetime('now','localtime'),
                   operation_result = ?
               WHERE id = ?""",
            (json.dumps(operation_result.model_dump()), snapshot_id)
        )

        _write_audit(
            conn, None, "snapshot_execute_end", None, None,
            body.operator_id, body.operator_role,
            f"Finished execution of snapshot #{snapshot_id}: "
            f"success={operation_result.success}, preserved={operation_result.preserved}, "
            f"skipped={operation_result.skipped}, denied={operation_result.denied}",
            batch_id=row["batch_id"],
            snapshot_id=snapshot_id
        )

        snapshot_row = conn.execute(
            "SELECT * FROM batch_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()

        result = _snapshot_row_to_out(conn, snapshot_row)
        result["conflict_check"] = conflict_check.model_dump()

    return result


def _build_reschedule_execution_baseline(
    snapshot_bookings: list, operation_params: dict
) -> tuple[list, list]:
    original_start_time = snapshot_bookings[0]["start_time"]
    original_end_time = snapshot_bookings[0]["end_time"]

    adjustable_items = []
    preserved_items_info = []

    for sb in snapshot_bookings:
        phase = BookingWeekPhase(sb["week_phase"])
        if phase == BookingWeekPhase.ADJUSTABLE:
            adjustable_items.append(sb)
        else:
            preserved_items_info.append((sb, phase))

    new_start_date_str = operation_params.get("new_start_date")
    new_start_time_str = operation_params.get("new_start_time", original_start_time)
    new_end_time_str = operation_params.get("new_end_time", original_end_time)

    new_start_date = date.fromisoformat(new_start_date_str)

    baseline = []
    for idx, sb in enumerate(adjustable_items):
        expected_new_date = (new_start_date + timedelta(weeks=idx)).isoformat()
        baseline.append({
            "booking_id": sb["booking_id"],
            "old_date": sb["date"],
            "old_start_time": sb["start_time"],
            "old_end_time": sb["end_time"],
            "old_status": sb["status"],
            "expected_new_date": expected_new_date,
            "expected_new_start_time": new_start_time_str,
            "expected_new_end_time": new_end_time_str,
            "week_phase_before": BookingWeekPhase(sb["week_phase"]).value,
        })

    return baseline, preserved_items_info


def _execute_reschedule(conn, snapshot_row, snapshot_bookings, operation_params: dict, body: SnapshotExecute) -> SnapshotOperationResult:
    batch_id = snapshot_row["batch_id"]
    snapshot_id = snapshot_row["id"]

    room_id = snapshot_bookings[0]["room_id"]
    original_start_time = snapshot_bookings[0]["start_time"]
    original_end_time = snapshot_bookings[0]["end_time"]

    baseline, preserved_items_info = _build_reschedule_execution_baseline(
        snapshot_bookings, operation_params
    )

    if not baseline:
        raise BookingError(
            ErrorCode.BATCH_NOTHING_TO_OPERATE,
            "No adjustable bookings in this snapshot (all in effect, approved, or finished)"
        )

    items: list[SnapshotOperationResultItem] = []
    success_count = 0
    preserved_count = len(preserved_items_info)
    skipped_count = 0
    denied_count = 0

    for sb, phase in preserved_items_info:
        items.append(SnapshotOperationResultItem(
            booking_id=sb["booking_id"],
            old_date=sb["date"],
            new_date=sb["date"],
            old_status=sb["status"],
            new_status=sb["status"],
            result="preserved",
            week_phase_before=phase.value,
            message=f"Preserved ({phase.value.replace('_', ' ')})",
            expected_new_date=sb["date"],
            expected_new_start_time=sb["start_time"],
            expected_new_end_time=sb["end_time"],
            expected_new_status=sb["status"],
        ))

    for item_baseline in baseline:
        booking_id = item_baseline["booking_id"]
        old_date = item_baseline["old_date"]
        old_start_time = item_baseline["old_start_time"]
        old_end_time = item_baseline["old_end_time"]
        old_status = item_baseline["old_status"]
        new_date = item_baseline["expected_new_date"]
        new_start_time_str = item_baseline["expected_new_start_time"]
        new_end_time_str = item_baseline["expected_new_end_time"]
        phase_before = item_baseline["week_phase_before"]

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
                f"Snapshot #{snapshot_id} reschedule: "
                f"{old_date} {original_start_time}-{original_end_time} "
                f"-> {new_date} {new_start_time_str}-{new_end_time_str}. "
                f"Reason: {body.reason}. "
                f"max_recurring_weeks_at_operation={MAX_RECURRING_WEEKS}",
                batch_id=batch_id,
                snapshot_id=snapshot_id
            )

            items.append(SnapshotOperationResultItem(
                booking_id=booking_id,
                old_date=old_date,
                new_date=new_date,
                old_status=old_status,
                new_status=old_status,
                result="success",
                week_phase_before=phase_before,
                expected_new_date=new_date,
                expected_new_start_time=new_start_time_str,
                expected_new_end_time=new_end_time_str,
                expected_new_status=old_status,
            ))
            success_count += 1

        except BookingError as e:
            if e.code in (ErrorCode.NEW_SLOT_NOT_OPEN, ErrorCode.NEW_BOOKING_OVERLAP,
                          ErrorCode.ROOM_INACTIVE, ErrorCode.ROOM_NOT_FOUND):
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=old_date,
                    new_date=new_date,
                    old_status=old_status,
                    new_status=old_status,
                    result="denied",
                    error_code=e.code,
                    message=e.message,
                    week_phase_before=phase_before,
                    expected_new_date=new_date,
                    expected_new_start_time=new_start_time_str,
                    expected_new_end_time=new_end_time_str,
                    expected_new_status=old_status,
                ))
                denied_count += 1
            else:
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=old_date,
                    new_date=new_date,
                    old_status=old_status,
                    new_status=old_status,
                    result="skipped",
                    error_code=e.code,
                    message=e.message,
                    week_phase_before=phase_before,
                    expected_new_date=new_date,
                    expected_new_start_time=new_start_time_str,
                    expected_new_end_time=new_end_time_str,
                    expected_new_status=old_status,
                ))
                skipped_count += 1

    executed_at = conn.execute("SELECT datetime('now','localtime') as ts").fetchone()["ts"]

    return SnapshotOperationResult(
        snapshot_id=snapshot_id,
        batch_id=batch_id,
        operation="reschedule",
        total=len(items),
        success=success_count,
        preserved=preserved_count,
        skipped=skipped_count,
        denied=denied_count,
        items=items,
        executed_at=executed_at,
    )


def _execute_cancel(conn, snapshot_row, snapshot_bookings, body: SnapshotExecute) -> SnapshotOperationResult:
    batch_id = snapshot_row["batch_id"]
    snapshot_id = snapshot_row["id"]

    items: list[SnapshotOperationResultItem] = []
    success_count = 0
    preserved_count = 0
    skipped_count = 0
    denied_count = 0

    for sb in snapshot_bookings:
        booking_id = sb["booking_id"]
        old_date = sb["date"]
        old_status = sb["status"]
        phase = BookingWeekPhase(sb["week_phase"])

        target = BookingStatus.CANCELLED
        current = BookingStatus(old_status)

        if phase == BookingWeekPhase.PRESERVED_IN_EFFECT:
            items.append(SnapshotOperationResultItem(
                booking_id=booking_id,
                old_date=old_date,
                new_date=old_date,
                old_status=old_status,
                new_status=old_status,
                result="preserved",
                week_phase_before=phase.value,
                message="Preserved (booking already in effect / passed)",
                expected_new_date=old_date,
                expected_new_status=old_status,
            ))
            preserved_count += 1
            continue

        if current == BookingStatus.APPROVED and phase == BookingWeekPhase.PRESERVED_APPROVED:
            try:
                conn.execute(
                    "UPDATE bookings SET status = 'cancelled', "
                    "updated_at = datetime('now','localtime') WHERE id = ?",
                    (booking_id,),
                )
                _write_audit(
                    conn, booking_id, "cancel", old_status, "cancelled",
                    body.operator_id, body.operator_role,
                    f"Snapshot #{snapshot_id} admin/staff batch cancel approved booking. "
                    f"Reason: {body.reason}",
                    batch_id=batch_id,
                    snapshot_id=snapshot_id
                )
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=old_date,
                    new_date=old_date,
                    old_status=old_status,
                    new_status="cancelled",
                    result="success",
                    week_phase_before=phase.value,
                    message="Admin/staff cancelled approved booking",
                    expected_new_date=old_date,
                    expected_new_status="cancelled",
                ))
                success_count += 1
                continue
            except Exception as e:
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=old_date,
                    new_date=old_date,
                    old_status=old_status,
                    new_status=old_status,
                    result="denied",
                    error_code=ErrorCode.INVALID_STATUS_TRANSITION,
                    message=f"Unexpected error: {e}",
                    week_phase_before=phase.value,
                    expected_new_date=old_date,
                    expected_new_status=old_status,
                ))
                denied_count += 1
                continue

        if target not in VALID_TRANSITIONS.get(current, set()):
            items.append(SnapshotOperationResultItem(
                booking_id=booking_id,
                old_date=old_date,
                new_date=old_date,
                old_status=old_status,
                new_status=old_status,
                result="skipped",
                error_code=ErrorCode.INVALID_STATUS_TRANSITION,
                message=f"Cannot cancel booking with status '{old_status}'",
                week_phase_before=phase.value,
                expected_new_date=old_date,
                expected_new_status=old_status,
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
                    f"Snapshot #{snapshot_id} batch cancel. Reason: {body.reason}",
                    batch_id=batch_id,
                    snapshot_id=snapshot_id
                )
            items.append(SnapshotOperationResultItem(
                booking_id=booking_id,
                old_date=old_date,
                new_date=old_date,
                old_status=old_status,
                new_status="cancelled",
                result="success",
                week_phase_before=phase.value,
                expected_new_date=old_date,
                expected_new_status="cancelled",
            ))
            success_count += 1
        except Exception as e:
            items.append(SnapshotOperationResultItem(
                booking_id=booking_id,
                old_date=old_date,
                new_date=old_date,
                old_status=old_status,
                new_status=old_status,
                result="denied",
                message=f"Unexpected error: {e}",
                week_phase_before=phase.value,
                expected_new_date=old_date,
                expected_new_status=old_status,
            ))
            denied_count += 1

    executed_at = conn.execute("SELECT datetime('now','localtime') as ts").fetchone()["ts"]

    return SnapshotOperationResult(
        snapshot_id=snapshot_id,
        batch_id=batch_id,
        operation="cancel",
        total=len(items),
        success=success_count,
        preserved=preserved_count,
        skipped=skipped_count,
        denied=denied_count,
        items=items,
        executed_at=executed_at,
    )


def _execute_export(conn, snapshot_row, snapshot_bookings, body: SnapshotExecute) -> SnapshotOperationResult:
    batch_id = snapshot_row["batch_id"]
    snapshot_id = snapshot_row["id"]

    items: list[SnapshotOperationResultItem] = []
    success_count = 0
    preserved_count = 0
    skipped_count = 0
    denied_count = 0

    for sb in snapshot_bookings:
        items.append(SnapshotOperationResultItem(
            booking_id=sb["booking_id"],
            old_date=sb["date"],
            new_date=sb["date"],
            old_status=sb["status"],
            new_status=sb["status"],
            result="success",
            week_phase_before=sb["week_phase"],
            message="Exported in snapshot",
            expected_new_date=sb["date"],
            expected_new_start_time=sb["start_time"],
            expected_new_end_time=sb["end_time"],
            expected_new_status=sb["status"],
        ))
        success_count += 1

    _write_audit(
        conn, None, "snapshot_export", None, None,
        body.operator_id, body.operator_role,
        f"Snapshot #{snapshot_id} export executed for batch #{batch_id}. "
        f"Reason: {body.reason}",
        batch_id=batch_id,
        snapshot_id=snapshot_id
    )

    executed_at = conn.execute("SELECT datetime('now','localtime') as ts").fetchone()["ts"]

    return SnapshotOperationResult(
        snapshot_id=snapshot_id,
        batch_id=batch_id,
        operation="export",
        total=len(items),
        success=success_count,
        preserved=preserved_count,
        skipped=skipped_count,
        denied=denied_count,
        items=items,
        executed_at=executed_at,
    )


def rollback_snapshot(snapshot_id: int, body: SnapshotRollback) -> SnapshotOut:
    _check_operation_permission(body.operator_role)

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM batch_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()

        if not row:
            raise BookingError(ErrorCode.SNAPSHOT_NOT_FOUND)

        if row["status"] == SnapshotStatus.PENDING.value:
            raise BookingError(
                ErrorCode.SNAPSHOT_NOT_EXECUTED,
                f"Snapshot #{snapshot_id} has not been executed yet"
            )

        if row["status"] == SnapshotStatus.ROLLED_BACK.value:
            raise BookingError(
                ErrorCode.SNAPSHOT_ALREADY_ROLLED_BACK,
                f"Snapshot #{snapshot_id} has already been rolled back"
            )

        if row["status"] == SnapshotStatus.CANCELLED.value:
            raise BookingError(
                ErrorCode.SNAPSHOT_INVALID_STATUS,
                f"Snapshot #{snapshot_id} has been cancelled"
            )

        if row["status"] != SnapshotStatus.EXECUTED.value:
            raise BookingError(
                ErrorCode.SNAPSHOT_INVALID_STATUS,
                f"Snapshot #{snapshot_id} is not in executed status (current: {row['status']})"
            )

        snapshot_bookings = conn.execute(
            "SELECT * FROM snapshot_bookings WHERE snapshot_id = ? ORDER BY date, start_time",
            (snapshot_id,)
        ).fetchall()

        _write_audit(
            conn, None, "snapshot_rollback_start", None, None,
            body.operator_id, body.operator_role,
            f"Starting rollback of snapshot #{snapshot_id}, "
            f"operation={row['operation_type']}, reason={body.reason}",
            batch_id=row["batch_id"],
            snapshot_id=snapshot_id
        )

        rollback_result = _execute_rollback(conn, row, snapshot_bookings, body)

        conn.execute(
            """UPDATE batch_snapshots
               SET status = 'rolled_back', rolled_back_at = datetime('now','localtime'),
                   rollback_result = ?
               WHERE id = ?""",
            (json.dumps(rollback_result.model_dump()), snapshot_id)
        )

        _write_audit(
            conn, None, "snapshot_rollback_end", None, None,
            body.operator_id, body.operator_role,
            f"Finished rollback of snapshot #{snapshot_id}: "
            f"success={rollback_result.success}, preserved={rollback_result.preserved}, "
            f"skipped={rollback_result.skipped}, denied={rollback_result.denied}",
            batch_id=row["batch_id"],
            snapshot_id=snapshot_id
        )

        snapshot_row = conn.execute(
            "SELECT * FROM batch_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()

        result = _snapshot_row_to_out(conn, snapshot_row)

        booking_ids = [sb["booking_id"] for sb in snapshot_bookings]
        conflict_check = _check_conflicts(conn, row["batch_id"], booking_ids, snapshot_id)
        result["conflict_check"] = conflict_check.model_dump()

    return result


def _build_rollback_baseline_from_execution_result(
    operation_result: dict, snapshot_bookings: list
) -> dict:
    baseline_map = {}
    result_items = operation_result.get("items", [])

    for item in result_items:
        booking_id = item.get("booking_id")
        if booking_id is None:
            continue

        sb = next((b for b in snapshot_bookings if b["booking_id"] == booking_id), None)
        if sb is None:
            continue

        expected_new_date = item.get("expected_new_date")
        expected_new_start_time = item.get("expected_new_start_time") or sb["start_time"]
        expected_new_end_time = item.get("expected_new_end_time") or sb["end_time"]
        expected_new_status = item.get("expected_new_status") or sb["status"]

        result = item.get("result")

        baseline_map[booking_id] = {
            "booking_id": booking_id,
            "old_date": sb["date"],
            "old_start_time": sb["start_time"],
            "old_end_time": sb["end_time"],
            "old_status": sb["status"],
            "expected_new_date": expected_new_date,
            "expected_new_start_time": expected_new_start_time,
            "expected_new_end_time": expected_new_end_time,
            "expected_new_status": expected_new_status,
            "week_phase": sb["week_phase"],
            "execution_result": result,
        }

    return baseline_map


def _check_rollback_conflict_for_item(
    baseline: dict, current_booking: sqlite3.Row, operation_type: str
) -> tuple[bool, str]:
    booking_id = baseline["booking_id"]

    if operation_type == SnapshotOperationType.RESCHEDULE.value:
        if baseline["execution_result"] != "success":
            return False, ""

        current_dt = str(current_booking["date"])
        current_st = str(current_booking["start_time"])
        current_et = str(current_booking["end_time"])
        current_status = str(current_booking["status"])

        exp_dt = str(baseline["expected_new_date"])
        exp_st = str(baseline["expected_new_start_time"])
        exp_et = str(baseline["expected_new_end_time"])
        exp_status = str(baseline["expected_new_status"])

        date_match = current_dt == exp_dt
        start_match = current_st.startswith(exp_st)
        end_match = current_et.startswith(exp_et)
        date_time_match = date_match and start_match and end_match
        status_match = current_status == exp_status
        current_matches_expected = date_time_match and status_match

        if not current_matches_expected:
            mismatch_parts = []
            if not date_time_match:
                mismatch_parts.append(
                    f"Expected: date={exp_dt}, time={exp_st}-{exp_et}. "
                    f"Actual: date={current_dt}, time={current_st}-{current_et}."
                )
            if not status_match:
                mismatch_parts.append(
                    f"Expected: status={exp_status}. Actual: status={current_status}."
                )
            message = (
                f"Cannot rollback: booking #{booking_id} state does not match expected state after snapshot execution. "
                f"{' '.join(mismatch_parts)} "
                f"The booking may have been modified after the snapshot was executed."
            )
            return True, message

    elif operation_type == SnapshotOperationType.CANCEL.value:
        if baseline["execution_result"] != "success":
            return False, ""

        current_status = str(current_booking["status"])
        exp_status = str(baseline["expected_new_status"])

        if current_status != exp_status:
            message = (
                f"Cannot rollback: booking #{booking_id} status does not match expected state after snapshot execution. "
                f"Expected: status={exp_status}. Actual: status={current_status}. "
                f"The booking may have been modified after the snapshot was executed."
            )
            return True, message

    return False, ""


def _execute_rollback(conn, snapshot_row, snapshot_bookings, body: SnapshotRollback) -> SnapshotOperationResult:
    batch_id = snapshot_row["batch_id"]
    snapshot_id = snapshot_row["id"]
    operation_type = snapshot_row["operation_type"]

    operation_result_json = snapshot_row["operation_result"]
    if not operation_result_json:
        raise BookingError(
            ErrorCode.SNAPSHOT_INVALID_STATUS,
            f"Snapshot #{snapshot_id} has no execution result, cannot rollback"
        )

    operation_result = json.loads(operation_result_json)
    rollback_baseline = _build_rollback_baseline_from_execution_result(
        operation_result, snapshot_bookings
    )

    items: list[SnapshotOperationResultItem] = []
    success_count = 0
    preserved_count = 0
    skipped_count = 0
    denied_count = 0

    for sb in snapshot_bookings:
        booking_id = sb["booking_id"]
        old_date = sb["date"]
        old_start_time = sb["start_time"]
        old_end_time = sb["end_time"]
        old_status = sb["status"]
        phase = BookingWeekPhase(sb["week_phase"])

        baseline = rollback_baseline.get(booking_id)
        if baseline is None:
            baseline = {
                "booking_id": booking_id,
                "old_date": old_date,
                "old_start_time": old_start_time,
                "old_end_time": old_end_time,
                "old_status": old_status,
                "expected_new_date": old_date,
                "expected_new_start_time": old_start_time,
                "expected_new_end_time": old_end_time,
                "expected_new_status": old_status,
                "week_phase": sb["week_phase"],
                "execution_result": "preserved",
            }

        current = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()

        if not current:
            items.append(SnapshotOperationResultItem(
                booking_id=booking_id,
                old_date=None,
                new_date=None,
                old_status=None,
                new_status=None,
                result="denied",
                error_code=ErrorCode.BOOKING_NOT_FOUND,
                message=f"Booking #{booking_id} no longer exists, cannot rollback",
                week_phase_before=phase.value,
            ))
            denied_count += 1
            continue

        if operation_type == SnapshotOperationType.EXPORT.value:
            items.append(SnapshotOperationResultItem(
                booking_id=booking_id,
                old_date=current["date"],
                new_date=current["date"],
                old_status=current["status"],
                new_status=current["status"],
                result="preserved",
                week_phase_before=phase.value,
                message="Export snapshot: no changes to rollback",
            ))
            preserved_count += 1
            continue

        if operation_type == SnapshotOperationType.RESCHEDULE.value:
            if phase != BookingWeekPhase.ADJUSTABLE:
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=current["date"],
                    new_date=old_date,
                    old_status=current["status"],
                    new_status=old_status,
                    result="preserved",
                    week_phase_before=phase.value,
                    message=f"Preserved ({phase.value.replace('_', ' ')}): was not modified by snapshot",
                ))
                preserved_count += 1
                continue

            if current["date"] == old_date and current["start_time"] == old_start_time and current["end_time"] == old_end_time:
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=current["date"],
                    new_date=old_date,
                    old_status=current["status"],
                    new_status=old_status,
                    result="skipped",
                    week_phase_before=phase.value,
                    message="Booking already matches snapshot state, no rollback needed",
                ))
                skipped_count += 1
                continue

            has_conflict, conflict_msg = _check_rollback_conflict_for_item(
                baseline, current, operation_type
            )
            if has_conflict:
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=current["date"],
                    new_date=old_date,
                    old_status=current["status"],
                    new_status=old_status,
                    result="denied",
                    error_code=ErrorCode.SNAPSHOT_BOOKING_CHANGED,
                    message=conflict_msg,
                    week_phase_before=phase.value,
                ))
                denied_count += 1
                continue

            try:
                room = conn.execute("SELECT * FROM rooms WHERE id = ?", (sb["room_id"],)).fetchone()
                if room and room["is_active"]:
                    dt = date.fromisoformat(old_date)
                    weekday = dt.weekday()
                    slots = conn.execute(
                        "SELECT start_time, end_time FROM time_slots WHERE room_id = ? AND weekday = ?",
                        (sb["room_id"], weekday),
                    ).fetchall()
                    t_start = time.fromisoformat(old_start_time)
                    t_end = time.fromisoformat(old_end_time)
                    slot_ok = False
                    for slot in slots:
                        s = time.fromisoformat(slot["start_time"])
                        e = time.fromisoformat(slot["end_time"])
                        if t_start >= s and t_end <= e:
                            slot_ok = True
                            break
                    if not slot_ok:
                        items.append(SnapshotOperationResultItem(
                            booking_id=booking_id,
                            old_date=current["date"],
                            new_date=old_date,
                            old_status=current["status"],
                            new_status=old_status,
                            result="denied",
                            error_code=ErrorCode.NEW_SLOT_NOT_OPEN,
                            message=f"Cannot rollback: original slot on {old_date} is no longer open",
                            week_phase_before=phase.value,
                        ))
                        denied_count += 1
                        continue

                    query = """
                        SELECT id FROM bookings
                        WHERE room_id = ? AND date = ? AND status = 'approved'
                          AND start_time < ? AND end_time > ?
                          AND id != ?
                    """
                    params = [sb["room_id"], old_date, old_end_time, old_start_time, booking_id]
                    overlap = conn.execute(query, params).fetchone()
                    if overlap:
                        items.append(SnapshotOperationResultItem(
                            booking_id=booking_id,
                            old_date=current["date"],
                            new_date=old_date,
                            old_status=current["status"],
                            new_status=old_status,
                            result="denied",
                            error_code=ErrorCode.NEW_BOOKING_OVERLAP,
                            message=f"Cannot rollback: original slot on {old_date} overlaps with approved booking #{overlap['id']}",
                            week_phase_before=phase.value,
                        ))
                        denied_count += 1
                        continue

                conn.execute(
                    """UPDATE bookings
                       SET date = ?, start_time = ?, end_time = ?,
                           old_date = NULL, rescheduled_from_booking_id = NULL,
                           updated_at = datetime('now','localtime')
                       WHERE id = ?""",
                    (old_date, old_start_time, old_end_time, booking_id),
                )

                _write_audit(
                    conn, booking_id, "rollback_reschedule",
                    current["status"], old_status,
                    body.operator_id, body.operator_role,
                    f"Snapshot #{snapshot_id} rollback reschedule: "
                    f"{current['date']} {current['start_time']}-{current['end_time']} "
                    f"-> {old_date} {old_start_time}-{old_end_time}. "
                    f"Reason: {body.reason}",
                    batch_id=batch_id,
                    snapshot_id=snapshot_id
                )

                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=current["date"],
                    new_date=old_date,
                    old_status=current["status"],
                    new_status=old_status,
                    result="success",
                    week_phase_before=phase.value,
                ))
                success_count += 1

            except BookingError as e:
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=current["date"],
                    new_date=old_date,
                    old_status=current["status"],
                    new_status=old_status,
                    result="denied",
                    error_code=e.code,
                    message=e.message,
                    week_phase_before=phase.value,
                ))
                denied_count += 1

        elif operation_type == SnapshotOperationType.CANCEL.value:
            if current["status"] == old_status:
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=current["date"],
                    new_date=old_date,
                    old_status=current["status"],
                    new_status=old_status,
                    result="skipped",
                    week_phase_before=phase.value,
                    message="Booking status already matches snapshot state",
                ))
                skipped_count += 1
                continue

            has_conflict, conflict_msg = _check_rollback_conflict_for_item(
                baseline, current, operation_type
            )
            if has_conflict:
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=current["date"],
                    new_date=old_date,
                    old_status=current["status"],
                    new_status=old_status,
                    result="denied",
                    error_code=ErrorCode.SNAPSHOT_BOOKING_CHANGED,
                    message=conflict_msg,
                    week_phase_before=phase.value,
                ))
                denied_count += 1
                continue

            target = BookingStatus(old_status)
            current_status = BookingStatus(current["status"])

            valid_rollback = (
                (current_status == BookingStatus.CANCELLED and target in (BookingStatus.PENDING, BookingStatus.APPROVED))
            )

            if not valid_rollback:
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=current["date"],
                    new_date=old_date,
                    old_status=current["status"],
                    new_status=old_status,
                    result="denied",
                    error_code=ErrorCode.INVALID_STATUS_TRANSITION,
                    message=f"Cannot rollback from '{current['status']}' to '{old_status}'",
                    week_phase_before=phase.value,
                ))
                denied_count += 1
                continue

            try:
                conn.execute(
                    "UPDATE bookings SET status = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                    (old_status, booking_id),
                )

                _write_audit(
                    conn, booking_id, "rollback_cancel",
                    current["status"], old_status,
                    body.operator_id, body.operator_role,
                    f"Snapshot #{snapshot_id} rollback cancel: "
                    f"{current['status']} -> {old_status}. Reason: {body.reason}",
                    batch_id=batch_id,
                    snapshot_id=snapshot_id
                )

                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=current["date"],
                    new_date=old_date,
                    old_status=current["status"],
                    new_status=old_status,
                    result="success",
                    week_phase_before=phase.value,
                ))
                success_count += 1

            except Exception as e:
                items.append(SnapshotOperationResultItem(
                    booking_id=booking_id,
                    old_date=current["date"],
                    new_date=old_date,
                    old_status=current["status"],
                    new_status=old_status,
                    result="denied",
                    message=f"Unexpected error: {e}",
                    week_phase_before=phase.value,
                ))
                denied_count += 1

    executed_at = conn.execute("SELECT datetime('now','localtime') as ts").fetchone()["ts"]

    return SnapshotOperationResult(
        snapshot_id=snapshot_id,
        batch_id=batch_id,
        operation=f"rollback_{operation_type}",
        total=len(items),
        success=success_count,
        preserved=preserved_count,
        skipped=skipped_count,
        denied=denied_count,
        items=items,
        executed_at=executed_at,
    )


def export_snapshot(snapshot_id: int, operator_id: str | None = None, operator_role: str = "resident") -> dict:
    conn = get_db_readonly()
    row = conn.execute(
        "SELECT * FROM batch_snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()

    if not row:
        raise BookingError(ErrorCode.SNAPSHOT_NOT_FOUND)

    if operator_role == "resident" and row["batch_user_id"] != operator_id:
        raise BookingError(
            ErrorCode.PERMISSION_DENIED,
            "Residents can only export their own snapshots"
        )

    snapshot_bookings = conn.execute(
        "SELECT * FROM snapshot_bookings WHERE snapshot_id = ? ORDER BY date, start_time",
        (snapshot_id,)
    ).fetchall()

    audit_rows = conn.execute(
        """SELECT * FROM audit_logs
           WHERE snapshot_id = ?
           ORDER BY id""",
        (snapshot_id,)
    ).fetchall()

    batch_audit_rows = conn.execute(
        "SELECT * FROM audit_logs WHERE batch_id = ? ORDER BY id",
        (row["batch_id"],)
    ).fetchall()

    export_data = {
        "snapshot": {
            "id": row["id"],
            "batch_id": row["batch_id"],
            "batch_user_id": row["batch_user_id"],
            "operation_type": row["operation_type"],
            "status": row["status"],
            "description": row["description"],
            "operator_id": row["operator_id"],
            "operator_role": row["operator_role"],
            "total_bookings": row["total_bookings"],
            "affected_bookings": row["affected_bookings"],
            "preserved_bookings": row["preserved_bookings"],
            "created_at": row["created_at"],
            "executed_at": row["executed_at"],
            "rolled_back_at": row["rolled_back_at"],
            "exported_at": conn.execute("SELECT datetime('now','localtime') as ts").fetchone()["ts"],
        },
        "config_snapshot": json.loads(row["config_snapshot"]),
        "operation_params": json.loads(row["operation_params"]) if row["operation_params"] else None,
        "operation_result": json.loads(row["operation_result"]) if row["operation_result"] else None,
        "rollback_result": json.loads(row["rollback_result"]) if row["rollback_result"] else None,
        "booking_snapshots": [_snapshot_booking_to_out(b) for b in snapshot_bookings],
        "snapshot_audit_logs": [_audit_log_to_out(a) for a in audit_rows],
        "batch_audit_logs": [_audit_log_to_out(a) for a in batch_audit_rows],
        "summary": {
            "total_bookings": len(snapshot_bookings),
            "preserved_in_effect": sum(
                1 for b in snapshot_bookings
                if b["week_phase"] == BookingWeekPhase.PRESERVED_IN_EFFECT.value
            ),
            "preserved_approved": sum(
                1 for b in snapshot_bookings
                if b["week_phase"] == BookingWeekPhase.PRESERVED_APPROVED.value
            ),
            "adjustable": sum(
                1 for b in snapshot_bookings
                if b["week_phase"] == BookingWeekPhase.ADJUSTABLE.value
            ),
            "finished": sum(
                1 for b in snapshot_bookings
                if b["week_phase"] == BookingWeekPhase.FINISHED.value
            ),
        },
    }

    return export_data


def cancel_snapshot(snapshot_id: int, operator_id: str, operator_role: str, reason: str = "") -> SnapshotOut:
    _check_operation_permission(operator_role)

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM batch_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()

        if not row:
            raise BookingError(ErrorCode.SNAPSHOT_NOT_FOUND)

        if row["status"] != SnapshotStatus.PENDING.value:
            raise BookingError(
                ErrorCode.SNAPSHOT_INVALID_STATUS,
                f"Only pending snapshots can be cancelled (current: {row['status']})"
            )

        conn.execute(
            "UPDATE batch_snapshots SET status = 'cancelled' WHERE id = ?",
            (snapshot_id,)
        )

        _write_audit(
            conn, None, "snapshot_cancel", None, None,
            operator_id, operator_role,
            f"Cancelled snapshot #{snapshot_id} for batch #{row['batch_id']}. "
            f"Reason: {reason}",
            batch_id=row["batch_id"],
            snapshot_id=snapshot_id
        )

        snapshot_row = conn.execute(
            "SELECT * FROM batch_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()

        result = _snapshot_row_to_out(conn, snapshot_row)

    return result


def compare_snapshot_execution_result(snapshot_id: int, operator_id: str | None = None, operator_role: str = "resident") -> dict:
    conn = get_db_readonly()
    row = conn.execute(
        "SELECT * FROM batch_snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()

    if not row:
        raise BookingError(ErrorCode.SNAPSHOT_NOT_FOUND)

    if operator_role == "resident" and row["batch_user_id"] != operator_id:
        raise BookingError(
            ErrorCode.PERMISSION_DENIED,
            "Residents can only compare their own snapshots"
        )

    snapshot_bookings = conn.execute(
        "SELECT * FROM snapshot_bookings WHERE snapshot_id = ? ORDER BY date, start_time",
        (snapshot_id,)
    ).fetchall()

    operation_result_json = row["operation_result"]
    if not operation_result_json:
        return {
            "snapshot_id": snapshot_id,
            "has_result": False,
            "comparison": None,
        }

    operation_result = json.loads(operation_result_json)
    operation_items = operation_result.get("items", [])

    comparison_items = []
    all_match = True
    changed_items = []
    unchanged_items = []

    for item in operation_items:
        booking_id = item.get("booking_id")
        if booking_id is None:
            continue

        sb = next((b for b in snapshot_bookings if b["booking_id"] == booking_id), None)
        if sb is None:
            continue

        current = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()

        result = item.get("result")
        expected_new_date = item.get("expected_new_date")
        expected_new_start_time = item.get("expected_new_start_time")
        expected_new_end_time = item.get("expected_new_end_time")
        expected_new_status = item.get("expected_new_status")

        comparison = {
            "booking_id": booking_id,
            "execution_result": result,
            "expected": {},
            "actual": {},
            "matches": False,
            "field_diffs": [],
        }

        if result == "success":
            if expected_new_date is not None:
                comparison["expected"]["date"] = expected_new_date
                comparison["expected"]["start_time"] = expected_new_start_time
                comparison["expected"]["end_time"] = expected_new_end_time
                comparison["expected"]["status"] = expected_new_status

            if current:
                    comparison["actual"]["date"] = str(current["date"])
                    comparison["actual"]["start_time"] = str(current["start_time"])
                    comparison["actual"]["end_time"] = str(current["end_time"])
                    comparison["actual"]["status"] = str(current["status"])

                    field_diffs = []
                    for field in ["date", "start_time", "end_time", "status"]:
                        exp = comparison["expected"].get(field)
                        act = comparison["actual"].get(field)
                        if exp is not None and str(exp) != str(act):
                            field_diffs.append({
                                "field": field,
                                "expected_value": exp,
                                "actual_value": act,
                            })

                    comparison["field_diffs"] = field_diffs
                    comparison["matches"] = len(field_diffs) == 0

                    if not comparison["matches"]:
                        all_match = False
                        changed_items.append(comparison)
                    else:
                        unchanged_items.append(comparison)

        comparison_items.append(comparison)

    return {
        "snapshot_id": snapshot_id,
        "has_result": True,
        "all_match": all_match,
        "total_items": len(comparison_items),
        "changed_count": len(changed_items),
        "unchanged_count": len(unchanged_items),
        "denied_or_preserved_count": len(comparison_items) - len(changed_items) - len(unchanged_items),
        "changed_items": changed_items,
        "unchanged_items": unchanged_items,
        "all_comparison_items": comparison_items,
    }
