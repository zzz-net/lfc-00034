from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from booking.batch_takeover import (
    create_snapshot,
    get_snapshot,
    list_snapshots,
    execute_snapshot,
    rollback_snapshot,
    export_snapshot,
    cancel_snapshot,
    compare_snapshot_execution_result,
)
from booking.models import (
    SnapshotCreate,
    SnapshotExecute,
    SnapshotRollback,
    SnapshotOut,
    SnapshotListItem,
    SnapshotStatus,
)

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])


@router.post("", response_model=SnapshotOut, status_code=201)
def api_create_snapshot(body: SnapshotCreate):
    return create_snapshot(body)


@router.get("", response_model=list[SnapshotListItem])
def api_list_snapshots(
    batch_id: int | None = None,
    operator_id: str | None = None,
    operator_role: str = Query(default="resident", pattern="^(admin|staff|resident)$"),
    status: SnapshotStatus | None = None,
):
    return list_snapshots(batch_id, operator_id, operator_role, status)


@router.get("/{snapshot_id}", response_model=SnapshotOut)
def api_get_snapshot(
    snapshot_id: int,
    operator_id: str | None = None,
    operator_role: str = Query(default="resident", pattern="^(admin|staff|resident)$"),
):
    return get_snapshot(snapshot_id, operator_id, operator_role)


@router.post("/{snapshot_id}/execute", response_model=SnapshotOut)
def api_execute_snapshot(snapshot_id: int, body: SnapshotExecute):
    return execute_snapshot(snapshot_id, body)


@router.post("/{snapshot_id}/rollback", response_model=SnapshotOut)
def api_rollback_snapshot(snapshot_id: int, body: SnapshotRollback):
    return rollback_snapshot(snapshot_id, body)


@router.get("/{snapshot_id}/export")
def api_export_snapshot(
    snapshot_id: int,
    operator_id: str | None = None,
    operator_role: str = Query(default="resident", pattern="^(admin|staff|resident)$"),
):
    export_data = export_snapshot(snapshot_id, operator_id, operator_role)
    return JSONResponse(
        content=export_data,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f"attachment; filename=snapshot_{snapshot_id}_export.json"
            ),
        },
    )


@router.get("/{snapshot_id}/compare")
def api_compare_snapshot_execution_result(
    snapshot_id: int,
    operator_id: str | None = None,
    operator_role: str = Query(default="resident", pattern="^(admin|staff|resident)$"),
):
    return compare_snapshot_execution_result(snapshot_id, operator_id, operator_role)


@router.post("/{snapshot_id}/cancel", response_model=SnapshotOut)
def api_cancel_snapshot(
    snapshot_id: int,
    operator_id: str = Query(..., min_length=1, max_length=50),
    operator_role: str = Query(default="admin", pattern="^(admin|staff|resident)$"),
    reason: str = Query(default="", max_length=500),
):
    return cancel_snapshot(snapshot_id, operator_id, operator_role, reason)
