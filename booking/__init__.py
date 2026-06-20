import os

DEFAULT_MAX_RECURRING_WEEKS = 4
MIN_RECURRING_WEEKS = 1
ABSOLUTE_MAX_RECURRING_WEEKS = 52
ENV_VAR_NAME = "BOOKING_MAX_RECURRING_WEEKS"


def _get_max_recurring_weeks() -> int:
    raw = os.environ.get(ENV_VAR_NAME, str(DEFAULT_MAX_RECURRING_WEEKS))
    try:
        val = int(raw)
        if val < MIN_RECURRING_WEEKS:
            return DEFAULT_MAX_RECURRING_WEEKS
        if val > ABSOLUTE_MAX_RECURRING_WEEKS:
            return ABSOLUTE_MAX_RECURRING_WEEKS
        return val
    except (ValueError, TypeError):
        return DEFAULT_MAX_RECURRING_WEEKS


MAX_RECURRING_WEEKS = _get_max_recurring_weeks()
