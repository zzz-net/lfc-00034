import json
from datetime import date

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from booking.database import get_db_readonly
from booking.models import AuditLogOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _log_to_out(row) -> dict:
    return {
        "id": row["id"],
        "booking_id": row["booking_id"],
        "batch_id": row["batch_id"],
        "action": row["action"],
        "old_status": row["old_status"],
        "new_status": row["new_status"],
        "operator_id": row["operator_id"],
        "operator_role": row["operator_role"],
        "detail": row["detail"],
        "created_at": row["created_at"],
    }


@router.get("", response_model=list[AuditLogOut])
def query_audit(
    booking_id: int | None = None,
    batch_id: int | None = None,
    action: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    operator_id: str | None = None,
):
    conn = get_db_readonly()
    conditions = []
    params = []
    if booking_id:
        conditions.append("booking_id = ?")
        params.append(booking_id)
    if batch_id:
        conditions.append("batch_id = ?")
        params.append(batch_id)
    if action:
        conditions.append("action = ?")
        params.append(action)
    if start_date:
        conditions.append("date(created_at) >= ?")
        params.append(start_date.isoformat())
    if end_date:
        conditions.append("date(created_at) <= ?")
        params.append(end_date.isoformat())
    if operator_id:
        conditions.append("operator_id = ?")
        params.append(operator_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM audit_logs {where} ORDER BY id DESC",
        params,
    ).fetchall()
    return [_log_to_out(r) for r in rows]


@router.get("/export")
def export_audit(
    booking_id: int | None = None,
    batch_id: int | None = None,
    action: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    operator_id: str | None = None,
):
    conn = get_db_readonly()
    conditions = []
    params = []
    if booking_id:
        conditions.append("booking_id = ?")
        params.append(booking_id)
    if batch_id:
        conditions.append("batch_id = ?")
        params.append(batch_id)
    if action:
        conditions.append("action = ?")
        params.append(action)
    if start_date:
        conditions.append("date(created_at) >= ?")
        params.append(start_date.isoformat())
    if end_date:
        conditions.append("date(created_at) <= ?")
        params.append(end_date.isoformat())
    if operator_id:
        conditions.append("operator_id = ?")
        params.append(operator_id)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM audit_logs {where} ORDER BY id",
        params,
    ).fetchall()
    data = [_log_to_out(r) for r in rows]
    return JSONResponse(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=audit_logs.json"},
    )
