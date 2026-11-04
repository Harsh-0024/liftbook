"""Shows what migration 0014 (workout dates in local time) would change. Changes nothing.

    DATABASE_URL=... python scripts/preview_workout_time_fix.py

Then, to apply it once:  DATABASE_URL=... alembic upgrade head
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlalchemy as sa  # noqa: E402

from config import Config  # noqa: E402
from services.workout_time_fix import plan_shift, summarize  # noqa: E402
from utils.dates import app_timezone  # noqa: E402


def main() -> None:
    engine = sa.create_engine(Config.get_database_url())
    zone = app_timezone()
    with engine.connect() as connection:
        changes = plan_shift(connection, zone)
        report = summarize(connection, changes, zone)
    print(f"Time zone: {report['time_zone']}")
    print(f"Workout rows saved with the server clock (will move): {report['rows_to_shift']}")
    print(f"  ...of which land on a different day: {report['rows_changing_day']}")
    for user_id, old, new in report["workouts_changing_day"]:
        print(f"    user {user_id}: {old} -> {new}")
    if report["workouts_joining_another_on_new_day"]:
        print("  These land on a day that already has a workout (they'll show as one day):")
        for user_id, old, new in report["workouts_joining_another_on_new_day"]:
            print(f"    user {user_id}: {old} -> {new}")
    print("Hour of day the stamps were saved at (as stored):")
    for hour, count in report["stored_hour_counts"].items():
        print(f"  {hour:02d}:00  {'#' * min(count, 60)} {count}")


if __name__ == "__main__":
    main()
