"""One-time fix for workouts saved with the server's (UTC) clock.

Before the app had one clock, a workout without a written date was stamped with the
server's time, which is UTC on Railway/Render, while a dated one was saved as local
midnight. Stats added 5h30 to every date to make up for it; History and the
"already a workout today" check didn't, so a workout saved between midnight and 5:30 am
(India) sat on the previous day.

Now every saved date is local time. This moves the old UTC-stamped ones to local time.
They are told apart by their time of day: a written date is exactly midnight
(00:00:00.000000), a clock stamp practically never is.

Used by migration 0014 (which runs it once) and scripts/preview_workout_time_fix.py
(which only reports).
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from zoneinfo import ZoneInfo

import sqlalchemy as sa


def _is_written_date(value: datetime) -> bool:
    return (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0)


def utc_to_local(value: datetime, zone: ZoneInfo) -> datetime:
    return value.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)


def _as_datetime(value) -> datetime:
    # SQLite hands back text; Postgres a datetime.
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def plan_shift(connection, zone: ZoneInfo) -> List[Tuple[int, int, datetime, datetime]]:
    """(id, user_id, old date, new date) for every workout row stamped by the server clock."""
    rows = connection.execute(sa.text("SELECT id, user_id, date FROM workout_logs")).fetchall()
    changes = []
    for row_id, user_id, value in rows:
        if value is None:
            continue
        old = _as_datetime(value)
        if _is_written_date(old):
            continue
        changes.append((row_id, user_id, old, utc_to_local(old, zone)))
    return changes


def summarize(connection, changes, zone: ZoneInfo) -> Dict:
    """What the shift does, in numbers a person can check before running it."""
    moved_day = [c for c in changes if c[2].date() != c[3].date()]
    # Workouts (one per user and day) whose day changes, and how many of them land on a
    # day that already has another workout of that user's.
    changed_workouts = {(c[1], c[2].date(), c[3].date()) for c in moved_day}
    existing_days = set()
    if changed_workouts:
        for user_id, value in connection.execute(sa.text("SELECT user_id, date FROM workout_logs")).fetchall():
            existing_days.add((user_id, _as_datetime(value).date()))
    moving_from = {(u, old) for u, old, _ in changed_workouts}
    joins = sorted(
        (u, old, new) for u, old, new in changed_workouts
        if (u, new) in existing_days and (u, new) not in moving_from
    )
    return {
        "time_zone": str(zone),
        "rows_to_shift": len(changes),
        "rows_changing_day": len(moved_day),
        "workouts_changing_day": sorted(changed_workouts),
        "workouts_joining_another_on_new_day": joins,
        # Hours (as stored, UTC) the stamps were made at: gym hours in India show up as
        # roughly 00-17 UTC. A cluster at local gym hours instead would mean the stamps
        # were already local and the shift should not run.
        "stored_hour_counts": dict(sorted(Counter(c[2].hour for c in changes).items())),
    }


def apply_shift(connection, changes) -> int:
    statement = sa.text("UPDATE workout_logs SET date = :new WHERE id = :id").bindparams(
        sa.bindparam("new", type_=sa.DateTime())
    )
    for row_id, _user_id, _old, new in changes:
        connection.execute(statement, {"id": row_id, "new": new})
    return len(changes)
