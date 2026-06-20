from fastapi import APIRouter

from booking.database import get_db, get_db_readonly
from booking.errors import BookingError, ErrorCode
from booking.models import RoomCreate, RoomUpdate, RoomOut, TimeSlotBatch, TimeSlotOut

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def _room_to_out(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


def _slot_to_out(row) -> dict:
    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "weekday": row["weekday"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
    }


@router.post("", response_model=RoomOut, status_code=201)
def create_room(body: RoomCreate):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO rooms (name, description) VALUES (?, ?)",
            (body.name, body.description),
        )
        room_id = cur.lastrowid
        row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    return _room_to_out(row)


@router.get("", response_model=list[RoomOut])
def list_rooms(is_active: bool | None = None):
    conn = get_db_readonly()
    if is_active is not None:
        rows = conn.execute(
            "SELECT * FROM rooms WHERE is_active = ? ORDER BY id",
            (int(is_active),),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM rooms ORDER BY id").fetchall()
    return [_room_to_out(r) for r in rows]


@router.get("/{room_id}", response_model=RoomOut)
def get_room(room_id: int):
    conn = get_db_readonly()
    row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not row:
        raise BookingError(ErrorCode.ROOM_NOT_FOUND)
    return _room_to_out(row)


@router.patch("/{room_id}", response_model=RoomOut)
def update_room(room_id: int, body: RoomUpdate):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if not row:
            raise BookingError(ErrorCode.ROOM_NOT_FOUND)
        updates = []
        params = []
        if body.name is not None:
            updates.append("name = ?")
            params.append(body.name)
        if body.description is not None:
            updates.append("description = ?")
            params.append(body.description)
        if body.is_active is not None:
            updates.append("is_active = ?")
            params.append(int(body.is_active))
        if updates:
            params.append(room_id)
            conn.execute(f"UPDATE rooms SET {', '.join(updates)} WHERE id = ?", params)
        row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    return _room_to_out(row)


@router.post("/{room_id}/timeslots", response_model=list[TimeSlotOut], status_code=201)
def set_timeslots(room_id: int, body: TimeSlotBatch):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if not row:
            raise BookingError(ErrorCode.ROOM_NOT_FOUND)
        conn.execute("DELETE FROM time_slots WHERE room_id = ?", (room_id,))
        result = []
        for slot in body.slots:
            if slot.start_time >= slot.end_time:
                raise BookingError(ErrorCode.INVALID_TIME_RANGE,
                                   f"start_time must be before end_time (slot weekday={slot.weekday})")
            cur = conn.execute(
                "INSERT INTO time_slots (room_id, weekday, start_time, end_time) VALUES (?, ?, ?, ?)",
                (room_id, slot.weekday, slot.start_time.isoformat(), slot.end_time.isoformat()),
            )
            slot_row = conn.execute("SELECT * FROM time_slots WHERE id = ?", (cur.lastrowid,)).fetchone()
            result.append(_slot_to_out(slot_row))
    return result


@router.get("/{room_id}/timeslots", response_model=list[TimeSlotOut])
def get_timeslots(room_id: int):
    conn = get_db_readonly()
    row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not row:
        raise BookingError(ErrorCode.ROOM_NOT_FOUND)
    rows = conn.execute(
        "SELECT * FROM time_slots WHERE room_id = ? ORDER BY weekday, start_time",
        (room_id,),
    ).fetchall()
    return [_slot_to_out(r) for r in rows]
