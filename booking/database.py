import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

_DB_PATH_ENV = os.environ.get("BOOKING_DB_PATH")
DB_PATH = Path(_DB_PATH_ENV) if _DB_PATH_ENV else (Path(__file__).parent.parent / "booking.db")

_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


@contextmanager
def get_db():
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_db_readonly():
    conn = _get_connection()
    return conn


def init_db():
    conn = _get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS time_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            batch_id INTEGER,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')),
            purpose TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (room_id) REFERENCES rooms(id),
            FOREIGN KEY (batch_id) REFERENCES booking_batches(id)
        );

        CREATE TABLE IF NOT EXISTS booking_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            total_count INTEGER NOT NULL,
            success_count INTEGER NOT NULL DEFAULT 0,
            skip_count INTEGER NOT NULL DEFAULT 0,
            denied_count INTEGER NOT NULL DEFAULT 0,
            exceeded_count INTEGER NOT NULL DEFAULT 0,
            max_recurring_weeks_at_creation INTEGER NOT NULL DEFAULT 4,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER,
            batch_id INTEGER,
            snapshot_id INTEGER,
            action TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT,
            operator_id TEXT NOT NULL,
            operator_role TEXT NOT NULL DEFAULT 'admin',
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (booking_id) REFERENCES bookings(id),
            FOREIGN KEY (batch_id) REFERENCES booking_batches(id),
            FOREIGN KEY (snapshot_id) REFERENCES batch_snapshots(id)
        );

        CREATE INDEX IF NOT EXISTS idx_bookings_room_date
            ON bookings(room_id, date, start_time, end_time);

        CREATE INDEX IF NOT EXISTS idx_bookings_status
            ON bookings(status);

        CREATE INDEX IF NOT EXISTS idx_bookings_user
            ON bookings(user_id);

        CREATE INDEX IF NOT EXISTS idx_bookings_batch
            ON bookings(batch_id);

        CREATE INDEX IF NOT EXISTS idx_audit_booking
            ON audit_logs(booking_id);

        CREATE INDEX IF NOT EXISTS idx_audit_batch
            ON audit_logs(batch_id);

        CREATE INDEX IF NOT EXISTS idx_audit_created
            ON audit_logs(created_at);

        CREATE INDEX IF NOT EXISTS idx_audit_snapshot
            ON audit_logs(snapshot_id);

        CREATE TABLE IF NOT EXISTS batch_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            batch_user_id TEXT NOT NULL,
            operation_type TEXT NOT NULL
                CHECK (operation_type IN ('reschedule', 'cancel', 'export')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'executed', 'rolled_back', 'cancelled')),
            description TEXT NOT NULL DEFAULT '',
            operator_id TEXT NOT NULL,
            operator_role TEXT NOT NULL DEFAULT 'admin',
            total_bookings INTEGER NOT NULL DEFAULT 0,
            affected_bookings INTEGER NOT NULL DEFAULT 0,
            preserved_bookings INTEGER NOT NULL DEFAULT 0,
            config_snapshot TEXT NOT NULL,
            operation_params TEXT,
            operation_result TEXT,
            rollback_result TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            executed_at TEXT,
            rolled_back_at TEXT,
            FOREIGN KEY (batch_id) REFERENCES booking_batches(id)
        );

        CREATE TABLE IF NOT EXISTS snapshot_bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            booking_id INTEGER NOT NULL,
            room_id INTEGER NOT NULL,
            room_name TEXT NOT NULL,
            user_id TEXT NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT '',
            old_date TEXT,
            rescheduled_from_booking_id INTEGER,
            week_phase TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (snapshot_id) REFERENCES batch_snapshots(id) ON DELETE CASCADE,
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_batch
            ON batch_snapshots(batch_id);

        CREATE INDEX IF NOT EXISTS idx_snapshots_status
            ON batch_snapshots(status);

        CREATE INDEX IF NOT EXISTS idx_snapshots_operator
            ON batch_snapshots(operator_id);

        CREATE INDEX IF NOT EXISTS idx_snapshot_bookings_snapshot
            ON snapshot_bookings(snapshot_id);

        CREATE INDEX IF NOT EXISTS idx_snapshot_bookings_booking
            ON snapshot_bookings(booking_id);
    """)
    conn.commit()

    try:
        conn.execute("ALTER TABLE bookings ADD COLUMN batch_id INTEGER REFERENCES booking_batches(id)")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE audit_logs ADD COLUMN batch_id INTEGER REFERENCES booking_batches(id)")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE booking_batches ADD COLUMN max_recurring_weeks_at_creation INTEGER NOT NULL DEFAULT 4")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE bookings ADD COLUMN old_date TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE bookings ADD COLUMN rescheduled_from_booking_id INTEGER REFERENCES bookings(id)")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE audit_logs ADD COLUMN snapshot_id INTEGER REFERENCES batch_snapshots(id)")
        conn.commit()
    except sqlite3.OperationalError:
        pass


def close_db():
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None
