import os

def _get_max_recurring_weeks() -> int:
    raw = os.environ.get("BOOKING_MAX_RECURRING_WEEKS", "4")
    try:
        val = int(raw)
        if val < 1:
            return 4
        return val
    except (ValueError, TypeError):
        return 4

MAX_RECURRING_WEEKS = _get_max_recurring_weeks()
