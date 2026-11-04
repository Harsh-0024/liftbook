"""The app's clock: what "now" and "today" mean.

Workout dates are saved as the lifter's local wall-clock time (Config.APP_TIMEZONE,
India by default) without a time zone attached. A workout with a written date is that
day at midnight; one without is the local time it was saved. Everything that asks
"what day is it?" about workouts uses local_now() / local_today(), so a workout saved
at 1 am lands on the day the lifter is living in, not on the server's (UTC) day.
"""

from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import Config


def app_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(Config.APP_TIMEZONE or "Asia/Kolkata")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Asia/Kolkata")


def _aware_now() -> datetime:
    """The real current moment (tests replace this one function to pick a time)."""
    return datetime.now(timezone.utc)


def local_now() -> datetime:
    """The current local time (app time zone), without a timezone attached."""
    return _aware_now().astimezone(app_timezone()).replace(tzinfo=None)


def local_today() -> date:
    return local_now().date()


def local_from_epoch_ms(value) -> Optional[datetime]:
    """Milliseconds since 1970 (as phones send them) as local time; None if unusable."""
    try:
        moment = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return moment.astimezone(app_timezone()).replace(tzinfo=None)


def utc_now() -> datetime:
    """The current UTC time without a timezone, as datetime.utcnow() gave (now deprecated).
    For machine timestamps only; workout days use local_now()."""
    return _aware_now().replace(tzinfo=None)
