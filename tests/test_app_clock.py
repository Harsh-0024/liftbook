"""One app clock: a workout saved at 1:30 am in India belongs to that day, everywhere."""
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import sqlalchemy as sa

import tests.test_route_regressions as base
from models import WorkoutLog
from services.workout_time_fix import apply_shift, plan_shift, summarize
from utils import dates

# 20:00 UTC on 4 Nov is 01:30 on 5 Nov in India: the window where the old code
# put an undated workout on the previous day.
LATE_NIGHT_UTC = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)
INDIA = ZoneInfo("Asia/Kolkata")


def at(moment):
    return patch.object(dates, "_aware_now", return_value=moment)


class TestClock(unittest.TestCase):
    def test_today_is_the_local_day_not_the_server_day(self):
        with at(LATE_NIGHT_UTC):
            self.assertEqual(dates.local_now(), datetime(2026, 11, 5, 1, 30))
            self.assertEqual(dates.local_today(), date(2026, 11, 5))
            self.assertEqual(dates.utc_now(), datetime(2026, 11, 4, 20, 0))

    def test_phone_timestamps_become_local_time(self):
        ms = int(LATE_NIGHT_UTC.timestamp() * 1000)
        self.assertEqual(dates.local_from_epoch_ms(ms), datetime(2026, 11, 5, 1, 30))
        self.assertIsNone(dates.local_from_epoch_ms("not a time"))

    def test_time_zone_is_a_setting(self):
        with patch.object(dates.Config, "APP_TIMEZONE", "Europe/London"), at(LATE_NIGHT_UTC):
            self.assertEqual(dates.local_today(), date(2026, 11, 4))
        with patch.object(dates.Config, "APP_TIMEZONE", "Not/AZone"):
            self.assertEqual(str(dates.app_timezone()), "Asia/Kolkata")


class TestLateNightWorkout(unittest.TestCase):
    setUp = base.TestRouteRegressions.setUp
    tearDown = base.TestRouteRegressions.tearDown
    _create_logged_in_user = base.TestRouteRegressions._create_logged_in_user

    def test_undated_workout_after_midnight_is_saved_on_the_new_day(self):
        user = self._create_logged_in_user(username="night_owl")
        # Yesterday's workout, written with its date (saved as midnight).
        self.client.post("/log", data={"workout_text": "4/11/26 Push\nBench Press 80x5"})
        with at(LATE_NIGHT_UTC):
            preview = self.client.post("/log/preview", data={"workout_text": "Pull\nBarbell Row 60x8"}).get_json()
            self.assertEqual(preview["date_str"], "2026-11-05")
            self.assertEqual(preview["date_label"], "Today")
            self.assertFalse(preview.get("existing"))  # not mistaken for yesterday's workout
            response = self.client.post("/log", data={"workout_text": "Pull\nBarbell Row 60x8"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("2026-11-05", response.headers["Location"])

        logs = {log.exercise: log.date for log in self.session.query(WorkoutLog).filter_by(user_id=user.id)}
        self.assertEqual(logs["Bench Press"], datetime(2026, 11, 4))
        self.assertEqual(logs["Barbell Row"], datetime(2026, 11, 5, 1, 30))
        self.assertEqual(self.client.get("/workout/2026-11-05").status_code, 200)
        self.assertIn("Barbell Row", self.client.get("/workout/2026-11-05").get_data(as_text=True))
        self.assertNotIn("Barbell Row", self.client.get("/workout/2026-11-04").get_data(as_text=True))


class TestOldDataFix(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine("sqlite://")
        with self.engine.begin() as c:
            c.execute(sa.text("CREATE TABLE workout_logs (id INTEGER PRIMARY KEY, user_id INTEGER, date DATETIME)"))
            c.execute(sa.text("INSERT INTO workout_logs VALUES "
                              "(1, 7, '2026-11-04 00:00:00.000000'),"   # written date: stays
                              "(2, 7, '2026-11-04 20:00:00.123456'),"   # 1:30 am on the 5th in India
                              "(3, 7, '2026-11-04 20:00:00.123456'),"   # same workout, 2nd exercise
                              "(4, 7, '2026-11-05 00:00:00.000000'),"   # a dated workout on the 5th
                              "(5, 8, '2026-11-03 12:15:30.500000')"))  # 5:45 pm, same day

    def _dates(self, c):
        return {i: datetime.fromisoformat(str(d)) for i, d in c.execute(sa.text("SELECT id, date FROM workout_logs"))}

    def test_server_clock_rows_move_to_local_time_and_dated_rows_stay(self):
        with self.engine.begin() as c:
            changes = plan_shift(c, INDIA)
            report = summarize(c, changes, INDIA)
            self.assertEqual(report["rows_to_shift"], 3)
            self.assertEqual(report["rows_changing_day"], 2)
            self.assertEqual(report["workouts_joining_another_on_new_day"],
                             [(7, date(2026, 11, 4), date(2026, 11, 5))])
            apply_shift(c, changes)
            got = self._dates(c)
        self.assertEqual(got[1], datetime(2026, 11, 4))
        self.assertEqual(got[2], datetime(2026, 11, 5, 1, 30, 0, 123456))
        self.assertEqual(got[3], got[2])
        self.assertEqual(got[4], datetime(2026, 11, 5))
        self.assertEqual(got[5], datetime(2026, 11, 3, 17, 45, 30, 500000))


if __name__ == "__main__":
    unittest.main()
