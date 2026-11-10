"""scripts/import_to_supabase.py: old workout times become the person's own clock time."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from import_to_supabase import local_workout_time  # noqa: E402


def test_a_written_date_stays_on_its_day():
    assert local_workout_time(datetime(2026, 11, 4)) == datetime(2026, 11, 4)


def test_an_undated_workout_after_midnight_moves_to_its_india_day():
    # Saved at 1:30 am in India: the old server (UTC) stamped 20:00 the day before.
    assert local_workout_time(datetime(2026, 11, 4, 20, 0, 0, 123456)) == datetime(2026, 11, 5, 1, 30, 0, 123456)


def test_an_undated_daytime_workout_keeps_its_day():
    assert local_workout_time(datetime(2026, 11, 3, 12, 15, 30, 500000)) == datetime(2026, 11, 3, 17, 45, 30, 500000)


def test_nothing_or_a_zoned_time_is_left_alone():
    assert local_workout_time(None) is None
    zoned = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)
    assert local_workout_time(zoned) is zoned
