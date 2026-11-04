"""The assistant's history questions that are answered without AI: rules and a real database."""
import unittest
from datetime import date, datetime, timedelta

from utils.dates import local_now
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, User, UserRole, WorkoutLog
from services import history_qa
from services.history_qa import _heuristic_intent, _parse_day_month, answer_history_question


class TestQuestionRules(unittest.TestCase):
    def test_questions_map_to_answers(self):
        self.assertEqual(_heuristic_intent("When did I last hit 100kg squat?"),
                         ("last_hit", {"exercise": "squat", "weight_kg": 100.0}))
        self.assertEqual(_heuristic_intent("when did I last do Bench Press?"),
                         ("last_hit", {"exercise": "bench press", "weight_kg": None}))
        self.assertEqual(_heuristic_intent("What was my best push day in the last 30 days"),
                         ("best_day", {"day_type": "push", "since_days": 30}))
        self.assertEqual(_heuristic_intent("best legs day last 60 days"),
                         ("best_day", {"day_type": "legs", "since_days": 60}))
        self.assertEqual(_heuristic_intent("How am I doing in squat relative to previous?")[0], "best_relative")
        self.assertEqual(_heuristic_intent("Tell me a joke"), (None, {}))

    def test_day_month_dates_are_the_nearest_past_one(self):
        with patch.object(history_qa, "local_today", return_value=date(2026, 9, 30)):
            self.assertEqual(_parse_day_month("why is the graph down on 12 sep"), date(2026, 9, 12))
            self.assertEqual(_parse_day_month("what about 28 Dec"), date(2025, 12, 28))
            self.assertIsNone(_parse_day_month("no date here"))


class TestAnswers(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(username="asker", role=UserRole.ADMIN, is_verified=True)
        self.db.add(self.user)
        self.db.commit()
        today = local_now().replace(hour=18, minute=0, second=0, microsecond=0)
        self.push_day = today - timedelta(days=3)
        self.legs_day = today - timedelta(days=2)
        self.pull_day = today - timedelta(days=1)
        for day, name, exercises in (
            (self.push_day, "Push", [("Flat Barbell Press", 80, 100), ("Tricep Pushdown", 30, 40)]),
            (self.legs_day, "Legs", [("Back Squat", 140, 170), ("Leg Press", 250, 300)]),
            (self.pull_day, "Pull", [("Barbell Row", 70, 90), ("Lat Pulldown", 60, 75)]),
            (today - timedelta(days=40), "Legs", [("Back Squat", 100, 120)]),
        ):
            for exercise, weight, e1rm in exercises:
                self.db.add(WorkoutLog(user_id=self.user.id, date=day, workout_name=name, exercise=exercise,
                                       top_weight=weight, top_reps=5, estimated_1rm=e1rm))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def ask(self, question):
        return answer_history_question(self.db, self.user, question=question)

    def test_best_day_of_each_type_is_that_type(self):
        # The legs day scores highest overall, so without the type filter it won every question.
        expected = {"push": self.push_day, "pull": self.pull_day, "legs": self.legs_day, "upper": self.pull_day}
        for day_type, day in expected.items():
            answer = self.ask(f"best {day_type} day in the last 30 days")
            self.assertTrue(answer["ok"], day_type)
            self.assertEqual(answer["workout_url"], f"/workout/{day.date().isoformat()}", day_type)
        push = self.ask("best push day in the last 30 days")
        self.assertEqual({r["exercise"] for r in push["results"]}, {"Flat Barbell Press", "Tricep Pushdown"})

    def test_last_time_at_a_weight(self):
        answer = self.ask("when did I last hit 120kg back squat")
        self.assertTrue(answer["ok"])
        self.assertIn(self.legs_day.date().isoformat(), answer["answer"])
        answer = self.ask("when did I last hit 200kg back squat")
        self.assertEqual(answer["results"], [])
        self.assertIn("haven't logged", answer["answer"])
        self.assertFalse(self.ask("when did I last do zercher squat")["ok"])

    def test_questions_the_rules_cannot_answer_need_a_key(self):
        answer = self.ask("Tell me something interesting about my training")
        self.assertFalse(answer["ok"])
        self.assertIn("No AI API key", answer["error"])
        self.assertFalse(self.ask("   ")["ok"])


if __name__ == "__main__":
    unittest.main()
