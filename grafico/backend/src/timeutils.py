from datetime import datetime, timedelta

# The operating day runs 04:00 -> 04:00 rather than midnight -> midnight, matching the
# frontend chart's START_HOUR. Roughly 10 of the 251 real trips cross midnight, so any
# ordering comparison on raw time-of-day minutes ("00:02 is earlier than 23:59") is wrong.
SERVICE_DAY_START_HOUR = 4

# The daily reset job runs at 03:00, i.e. the last hour before a new service day begins.
DAILY_RESET_HOUR = 3


def time_str_to_minutes(time_str: str) -> float:
    hours, minutes, seconds = (int(part) for part in time_str.split(":"))
    return hours * 60 + minutes + seconds / 60


def time_str_to_service_minutes(time_str: str) -> float:
    """Minutes elapsed since the service day started at 04:00, wrapping at 24h.

    Use this (never `time_str_to_minutes`) whenever two times are compared for
    ordering or elapsed distance, so midnight-crossing trips stay monotonic.
    """
    raw = time_str_to_minutes(time_str)
    return (raw - SERVICE_DAY_START_HOUR * 60) % (24 * 60)


def datetime_to_service_minutes(moment: datetime) -> float:
    """Service-day minutes for a wall-clock `datetime`'s time-of-day component."""
    return time_str_to_service_minutes(moment.strftime("%H:%M:%S"))


def minutes_to_time_str(total_minutes: float) -> str:
    total_seconds = round(total_minutes * 60)
    total_seconds %= 24 * 60 * 60
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def effective_reset_date(now: datetime) -> str:
    """The calendar date of the reset cycle `now` belongs to.

    Anything before the 03:00 reset still belongs to the previous day's cycle. Both
    the startup catch-up check and the `last_reset_date` write go through this, so a
    restart at 02:00 does not see "yesterday" and fire a reset an hour early, wiping
    live edits on still-running overnight trips.
    """
    effective = now if now.hour >= DAILY_RESET_HOUR else now - timedelta(days=1)
    return effective.strftime("%Y-%m-%d")
