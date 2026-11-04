"""The admin AI coach: its data tools on a real database, and the agent loop with Gemini faked."""
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from config import Config
from models import Base, CoachAnswer, RepRange, User, UserApiKey, UserRole, WorkoutLog
from services import ai_coach, coach_tools
from utils.dates import local_now
from liftbook import create_app


def _log(user, day, exercise, weight, reps, e1rm, name="Workout", sets=3):
    return WorkoutLog(
        user_id=user.id, date=day, workout_name=name, exercise=exercise,
        sets_json={"weights": [weight] * sets, "reps": [reps] * sets},
        top_weight=weight, top_reps=reps, estimated_1rm=e1rm,
    )


class _CoachDb(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = scoped_session(sessionmaker(bind=self.engine))
        self.user = User(username="coachee", full_name="Sam Lifter", role=UserRole.ADMIN, is_verified=True)
        self.other = User(username="someone", role=UserRole.USER, is_verified=True)
        self.db.add_all([self.user, self.other])
        self.db.commit()
        # The tools count days in UTC; a local "today" breaks these tests after local midnight.
        self.today = local_now().replace(hour=12, minute=0, second=0, microsecond=0)
        days = lambda n: self.today - timedelta(days=n)
        rows = [
            _log(self.user, days(1), "Back Squat", 120, 5, 140, "Legs"),
            _log(self.user, days(1), "Leg Press", 250, 10, 330, "Legs"),
            _log(self.user, days(3), "Flat Barbell Press", 85, 5, 99, "Push"),
            _log(self.user, days(8), "Back Squat", 115, 5, 134, "Legs"),
            _log(self.user, days(15), "Back Squat", 110, 5, 128, "Legs"),
            _log(self.user, days(40), "Back Squat", 100, 5, 117, "Legs"),
            # Bench stuck for months: best was long ago.
            _log(self.user, days(120), "Flat Barbell Press", 90, 5, 105, "Push"),
            _log(self.user, days(60), "Flat Barbell Press", 85, 5, 99, "Push"),
            _log(self.user, days(30), "Flat Barbell Press", 85, 5, 99, "Push"),
            # Another user's heavier squat must never show up.
            _log(self.other, days(2), "Back Squat", 200, 5, 233, "Legs"),
        ]
        self.db.add_all(rows)
        self.db.commit()
        self.user_id, self.other_id = self.user.id, self.other.id
        ai_coach._rate_hits.clear()
        ai_coach._bad_models.clear()

    def tearDown(self):
        self.db.remove()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def iso(self, n):
        return (self.today - timedelta(days=n)).date().isoformat()


class TestCoachTools(_CoachDb):
    def test_exercise_names_resolve_by_word_order_and_spelling(self):
        self.assertEqual(coach_tools.resolve_exercise(self.db, self.user, "squat back"), ["Back Squat"])
        self.assertEqual(coach_tools.resolve_exercise(self.db, self.user, "bak squat"), ["Back Squat"])
        with self.assertRaises(coach_tools.ToolError):
            coach_tools.resolve_exercise(self.db, self.user, "zercher carry")
        with self.assertRaisesRegex(coach_tools.ToolError, "Flat Barbell Press"):
            coach_tools.resolve_exercise(self.db, self.user, "bench press")

    def test_history_and_records_are_only_this_users(self):
        history = coach_tools.get_exercise_history(self.db, self.user, "Back Squat", limit=2)
        self.assertEqual(history["total_sessions"], 4)
        self.assertEqual([s["date"] for s in history["sessions_newest_first"]], [self.iso(1), self.iso(8)])
        self.assertEqual(history["sessions_newest_first"][0]["sets"], "120 x 5, 120 x 5, 120 x 5")

        pr = coach_tools.get_personal_records(self.db, self.user, "back squat")
        self.assertEqual(pr["best_estimated_1rm"]["e1rm_kg"], 140)
        ranked = coach_tools.get_personal_records(self.db, self.user)["records_by_estimated_1rm"]
        self.assertEqual(ranked[0]["exercise"], "Leg Press")
        self.assertNotIn(233, [r["e1rm_kg"] for r in ranked])

    def test_timed_holds_are_not_ranked_as_lifts(self):
        # 20 kg x 90 s scores like a huge "e1RM"; it is a hold, not a lift.
        self.db.add(_log(self.user, self.today - timedelta(days=2), "Plank", 20, 90, 190, "Core"))
        self.db.commit()
        ranked = coach_tools.get_personal_records(self.db, self.user)["records_by_estimated_1rm"]
        self.assertNotIn("Plank", [r["exercise"] for r in ranked])

        history = coach_tools.get_exercise_history(self.db, self.user, "plank")
        self.assertTrue(history["timed_hold"])
        self.assertEqual(history["sessions_newest_first"][0]["top_seconds"], 90)
        self.assertNotIn("e1rm_kg", history["sessions_newest_first"][0])

    def test_long_sets_count_only_twelve_reps_when_ranking(self):
        # 60 kg x 20 "estimates" 100 kg; counted as 12 reps it's 84, below the real 5-rep bench (99).
        self.db.add(_log(self.user, self.today - timedelta(days=2), "Cable Row", 60, 20, 100, "Pull"))
        # Heavier and more reps is still better: 140 x 15 beats 130 x 10 even though 15 > 12.
        self.db.add(_log(self.user, self.today - timedelta(days=4), "Lat Pulldown", 130, 10, 173, "Pull"))
        self.db.add(_log(self.user, self.today - timedelta(days=5), "Lat Pulldown", 140, 15, 210, "Pull"))
        self.db.commit()
        ranked = coach_tools.get_personal_records(self.db, self.user)["records_by_estimated_1rm"]
        names = [r["exercise"] for r in ranked]
        self.assertLess(names.index("Flat Barbell Press"), names.index("Cable Row"))
        pulldown = ranked[names.index("Lat Pulldown")]
        self.assertEqual((pulldown["top_weight_kg"], pulldown["ranking_e1rm_kg"]), (140, 196.0))
        row = coach_tools.get_exercise_history(self.db, self.user, "cable row")["sessions_newest_first"][0]
        self.assertTrue(row["e1rm_unreliable"])

        dips = _log(self.user, self.today - timedelta(days=6), "Dips", 135, 8, 171, "Push")
        dips.uses_bodyweight, dips.bodyweight = True, 73
        self.db.add(dips)
        self.db.commit()
        row = coach_tools.get_exercise_history(self.db, self.user, "dips")["sessions_newest_first"][0]
        self.assertEqual(row["load"], "135 kg total = 73 kg bodyweight + 62 kg added")

    def test_trend_spots_progress_and_a_stall(self):
        squat = coach_tools.get_progress_trend(self.db, self.user, "Back Squat", days=90)
        self.assertGreater(squat["trend_kg_per_week"], 0)
        self.assertEqual(squat["all_time_best"]["date"], self.iso(1))
        self.assertFalse(squat["looks_stalled"])

        bench = coach_tools.get_progress_trend(self.db, self.user, "Flat Barbell Press", days=180)
        self.assertEqual(bench["all_time_best"]["date"], self.iso(120))
        self.assertTrue(bench["looks_stalled"])

    def test_review_lifts_puts_stalls_first(self):
        review = coach_tools.review_lifts(self.db, self.user, days=180)
        names = [l["exercise"] for l in review["lifts_stalled_first"]]
        # Bench's best is months old (stalled); squat is climbing; leg press has too few sessions.
        self.assertEqual(names, ["Flat Barbell Press", "Back Squat"])
        self.assertTrue(review["lifts_stalled_first"][0]["looks_stalled"])
        self.assertIn("weight_kg", review["lifts_stalled_first"][0]["next_session_target"]["target"])
        self.assertNotIn("next_session_target", review["lifts_stalled_first"][1])  # squat is progressing
        self.assertGreater(review["lifts_stalled_first"][1]["trend_kg_per_week"], 0)
        self.assertIn("note", coach_tools.review_lifts(self.db, self.other, days=28))
        self.assertEqual(coach_tools.review_lifts(self.db, self.user, days=28)["window_days"], 90)

    def test_summary_workouts_and_comparison(self):
        summary = coach_tools.get_training_summary(self.db, self.user, days=28)
        self.assertEqual(summary["workout_days"], 4)
        self.assertEqual(summary["days_since_last_workout"], 1)
        self.assertIn("Legs", summary["weekly_sets_by_muscle_group"])
        self.assertIn("Back", summary["muscle_groups_not_trained"])

        workouts = coach_tools.get_workouts(self.db, self.user, start_date=self.iso(1), end_date=self.iso(1))
        day = workouts["workouts_newest_first"]
        self.assertEqual(len(day), 1)
        self.assertEqual(day[0]["title"], "Legs")
        self.assertEqual({e["exercise"] for e in day[0]["exercises"]}, {"Back Squat", "Leg Press"})

        cmp = coach_tools.compare_periods(self.db, self.user, period_days=14, exercise="back squat")
        self.assertEqual(cmp["current"]["workout_days"], 2)
        self.assertEqual(cmp["previous"]["workout_days"], 1)

    def test_next_session_uses_double_progression(self):
        self.user.follow_admin_exercises = False
        self.db.add(RepRange(user_id=self.user.id, text_content="Back Squat: 3, 3-5\nFlat Barbell Press: 3, 6-8"))
        self.db.commit()
        days = lambda n: self.today - timedelta(days=n)

        # Squat: 120 x 5 on every set = top of 3-5 -> add weight, restart at 3.
        squat = coach_tools.suggest_next_session(self.db, self.user, "back squat")
        self.assertEqual(squat["target"], {"weight_kg": 122.5, "reps": [3, 3, 3]})
        self.assertEqual(squat["rep_range"]["source"], "your rep ranges")

        # Bench: 85 x 5 twice in a row, under 6 -> back off ~10%.
        bench = coach_tools.suggest_next_session(self.db, self.user, "flat barbell press")
        self.assertEqual(bench["target"]["weight_kg"], 77.5)

        # Inside the range: same weight, one more rep where there's room.
        self.db.add(WorkoutLog(user_id=self.user.id, date=days(0), exercise="Flat Barbell Press",
                               sets_json={"weights": [80, 80, 80], "reps": [8, 7, 6]}, top_weight=80, top_reps=8,
                               estimated_1rm=99))
        self.db.commit()
        bench = coach_tools.suggest_next_session(self.db, self.user, "flat barbell press")
        self.assertEqual(bench["target"], {"weight_kg": 80.0, "reps": [8, 8, 7]})

        # No range set -> the default, said so.
        press = coach_tools.suggest_next_session(self.db, self.user, "leg press")
        self.assertIn("default", press["rep_range"]["source"])
        self.assertEqual(press["target"], {"weight_kg": 252.5, "reps": [6, 6, 6]})

    def test_run_tool_reports_problems_to_the_model(self):
        self.assertIn("error", coach_tools.run_tool(self.db, self.user, "drop_tables", {}))
        self.assertIn("error", coach_tools.run_tool(self.db, self.user, "get_workouts", {"start_date": "yesterday"}))
        # Unknown arguments are dropped rather than crashing the tool.
        out = coach_tools.run_tool(self.db, self.user, "list_exercises", {"query": "squat", "user_id": self.other.id})
        self.assertEqual([e["exercise"] for e in out["exercises"]], ["Back Squat"])
        names = {d["name"] for d in coach_tools.function_declarations()}
        self.assertEqual(names, set(coach_tools.TOOLS))


def _reply(*parts):
    return {"candidates": [{"content": {"role": "model", "parts": list(parts)}, "finishReason": "STOP"}]}


def _groq_reply(content=None, tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": {"total_tokens": 100}}


def _gemini_models():
    """The Gemini part of the model order; the tests' keys are all Gemini keys."""
    return [model for provider, model in ai_coach._model_order() if provider == "gemini"]


def _http_error(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(response=resp)


class TestCoachLoop(_CoachDb):
    def ask(self, text, **kwargs):
        kwargs.setdefault("api_keys", [{"id": 7, "api_key": "k"}])
        return ai_coach.run_coach(self.db, self.user, messages=[{"role": "user", "text": text}], **kwargs)

    def test_model_calls_tools_then_answers(self):
        sent = []

        def fake_post(api_key, model, payload):
            sent.append(payload)
            if len(sent) == 1:
                return _reply({"functionCall": {"name": "get_progress_trend", "args": {"exercise": "squat back"}, "id": "call_1"},
                               "thoughtSignature": "sig"})
            return _reply({"text": f"Your squat is up. Best **140 kg** on {self.iso(1)}."})

        with patch.object(ai_coach, "_post", side_effect=fake_post):
            out = self.ask("How's my squat?", context={"page": "stats"})

        self.assertTrue(out["ok"])
        self.assertEqual(out["source"], "ai")
        self.assertEqual(out["key_id"], 7)
        self.assertEqual([s["tool"] for s in out["steps"]], ["get_progress_trend"])
        self.assertEqual(out["links"], [{"label": self.iso(1), "url": f"/workout/{self.iso(1)}"}])
        second = sent[1]["contents"]
        # The model's own turn goes back untouched (thought signature included), then the tool result.
        self.assertEqual(second[1]["parts"][0]["thoughtSignature"], "sig")
        result = second[2]["parts"][0]["functionResponse"]
        self.assertEqual(result["name"], "get_progress_trend")
        self.assertEqual(result["id"], "call_1")
        self.assertEqual(result["response"]["exercise"], "Back Squat")
        self.assertIn("Sam", sent[0]["systemInstruction"]["parts"][0]["text"])
        self.assertIn("page 'stats'", sent[0]["systemInstruction"]["parts"][0]["text"])

    def test_retired_model_is_skipped_for_the_next(self):
        models = []

        def fake_post(api_key, model, payload):
            models.append(model)
            if model == _gemini_models()[0]:
                raise _http_error(404)
            return _reply({"text": "Fine."})

        with patch.object(ai_coach, "_post", side_effect=fake_post):
            self.assertTrue(self.ask("hi")["ok"])
            self.assertTrue(self.ask("hi again")["ok"])
        self.assertEqual(models, [_gemini_models()[0], _gemini_models()[1], _gemini_models()[1]])

    def test_rate_limit_mid_answer_moves_to_another_model(self):
        first, second = _gemini_models()[:2]
        models = []

        def fake_post(api_key, model, payload):
            models.append(model)
            if len(models) == 1:
                return _reply({"functionCall": {"name": "list_exercises", "args": {}}})
            if model == first:
                raise _http_error(429)
            return _reply({"text": "You log squats most."})

        with patch.object(ai_coach, "_post", side_effect=fake_post):
            out = self.ask("What do I train most?")
        self.assertEqual(out["source"], "ai")
        self.assertEqual(out["model"], second)
        self.assertEqual(models, [first, first, second])

    def test_stray_fragments_are_dropped_or_asked_again(self):
        self.assertEqual(ai_coach._answer_text([{"text": "oon\n"}, {"text": "Your squat is up."}]), "Your squat is up.")
        self.assertEqual(ai_coach._answer_text([{"text": "Your squat is "}, {"text": "up."}]), "Your squat is up.")
        self.assertEqual(ai_coach._answer_text([{"text": "oz"}]), "")
        self.assertEqual(ai_coach._answer_text([{"text": "Fine."}]), "Fine.")
        replies = iter([_reply({"text": "0"}), _reply({"text": "Squats, mostly."})])
        with patch.object(ai_coach, "_post", side_effect=lambda *a: next(replies)):
            self.assertEqual(self.ask("What do I train most?")["answer"], "Squats, mostly.")

    def test_each_question_logs_its_cost(self):
        first = _gemini_models()[0]

        def fake_post(api_key, model, payload):
            if model == first:
                raise _http_error(429)
            return {**_reply({"text": "Fine."}), "usageMetadata": {"totalTokenCount": 321}}

        with patch.object(ai_coach, "_post", side_effect=fake_post), \
                self.assertLogs("liftbook", level="INFO") as logs:
            self.ask("hi")
        line = [l for l in logs.output if "AI coach user=" in l][-1]
        self.assertIn(f"outcome=ai:{_gemini_models()[1]}", line)
        self.assertIn("calls=2 tokens=321", line)
        self.assertIn(f"failed={first}:429", line)

    def test_an_empty_answer_is_asked_again_on_another_model(self):
        models = []

        def fake_post(api_key, model, payload):
            models.append(model)
            if len(models) == 1:
                return _reply()
            return _reply({"text": "Squats, mostly."})

        with patch.object(ai_coach, "_post", side_effect=fake_post):
            out = self.ask("What do I train most?")
        self.assertEqual(out["answer"], "Squats, mostly.")
        self.assertEqual(models, list(_gemini_models()[:2]))

    def test_falls_back_to_rules_when_gemini_is_down_or_missing(self):
        with patch.object(ai_coach, "_post", side_effect=_http_error(503)):
            out = self.ask("when did I last hit 120kg back squat")
        self.assertTrue(out["ok"])
        self.assertEqual(out["source"], "rules")
        self.assertIn(self.iso(1), out["answer"])

        with patch.object(ai_coach, "_post") as never:
            out = self.ask("when did I last hit 120kg back squat", api_keys=[])
            never.assert_not_called()
        self.assertEqual(out["source"], "rules")
        self.assertIn("No AI key", out["note"])

        out = self.ask("Write me a poem", api_keys=[])
        self.assertFalse(out["ok"])
        self.assertIn("No AI key", out["error"])

    GROQ_KEY = {"id": 8, "api_key": "gsk_test"}
    GEMINI_KEY = {"id": 7, "api_key": "AIza-test"}

    def test_groq_goes_first_in_openai_format(self):
        sent = []

        def fake_groq(api_key, model, payload):
            sent.append(payload)
            if len(sent) == 1:
                return _groq_reply(tool_calls=[{"id": "t1", "type": "function", "function": {
                    "name": "get_progress_trend", "arguments": '{"exercise": "squat back"}'}}])
            return _groq_reply(content="Your squat is up.")

        with patch.object(ai_coach, "_post_groq", side_effect=fake_groq), patch.object(ai_coach, "_post") as gemini:
            out = self.ask("How's my squat?", api_keys=[self.GEMINI_KEY, self.GROQ_KEY])
            gemini.assert_not_called()
        self.assertEqual((out["answer"], out["model"], out["key_id"]), ("Your squat is up.", "openai/gpt-oss-120b", 8))
        first, second = sent
        self.assertEqual(first["messages"][0]["role"], "system")
        self.assertEqual(first["reasoning_effort"], ai_coach.GROQ_REASONING_EFFORT)
        plan = next(t for t in first["tools"] if t["function"]["name"] == "get_plan")
        self.assertEqual(plan["function"]["parameters"], {"type": "object", "properties": {}})
        call, result = second["messages"][2], second["messages"][3]
        self.assertEqual(call["tool_calls"][0]["id"], "t1")
        self.assertEqual((result["role"], result["tool_call_id"]), ("tool", "t1"))
        self.assertEqual(json.loads(result["content"])["exercise"], "Back Squat")

    def test_groq_hands_a_question_to_gemini_mid_way(self):
        groq_calls = []

        def fake_groq(api_key, model, payload):
            groq_calls.append(model)
            if len(groq_calls) == 1:
                return _groq_reply(tool_calls=[{"id": "t1", "type": "function",
                                                "function": {"name": "list_exercises", "arguments": "{}"}}])
            raise _http_error(429)

        sent = []

        def fake_gemini(api_key, model, payload):
            sent.append(payload)
            return _reply({"text": "You log squats most."})

        with patch.object(ai_coach, "_post_groq", side_effect=fake_groq), \
                patch.object(ai_coach, "_post", side_effect=fake_gemini):
            out = self.ask("What do I train most?", api_keys=[self.GEMINI_KEY, self.GROQ_KEY])
        self.assertEqual(out["model"], _gemini_models()[0])
        model_turn, tool_turn = sent[0]["contents"][1], sent[0]["contents"][2]
        # Gemini 3 needs a signature on calls it didn't write, and the result pairs with the call by id.
        self.assertEqual(model_turn["parts"][0]["thoughtSignature"], ai_coach.SKIP_SIGNATURE)
        self.assertEqual(model_turn["parts"][0]["functionCall"]["id"], "t1")
        self.assertEqual(tool_turn["parts"][0]["functionResponse"]["id"], "t1")

    def test_gemini_hands_a_question_to_groq_mid_way(self):
        def fake_gemini(api_key, model, payload):
            if len(payload["contents"]) == 1:
                return _reply({"functionCall": {"name": "list_exercises", "args": {}}})  # 2.5: no call id
            raise _http_error(503)

        sent = []

        def fake_groq(api_key, model, payload):
            sent.append(payload)
            return _groq_reply(content="Squats, mostly.")

        with patch.object(ai_coach.Config, "AI_MODEL_ORDER", "gemini-2.5-flash,groq:openai/gpt-oss-120b"), \
                patch.object(ai_coach, "_post", side_effect=fake_gemini), \
                patch.object(ai_coach, "_post_groq", side_effect=fake_groq):
            out = self.ask("What do I train most?", api_keys=[self.GEMINI_KEY, self.GROQ_KEY])
        self.assertEqual(out["answer"], "Squats, mostly.")
        call, result = sent[0]["messages"][2], sent[0]["messages"][3]
        self.assertEqual(result["tool_call_id"], call["tool_calls"][0]["id"])

    def test_a_rejected_groq_key_falls_through_to_gemini(self):
        with patch.object(ai_coach, "_post_groq", side_effect=_http_error(401)) as groq, \
                patch.object(ai_coach, "_post", return_value=_reply({"text": "Fine."})):
            out = self.ask("hi", api_keys=[self.GEMINI_KEY, self.GROQ_KEY])
        self.assertEqual(out["source"], "ai")
        self.assertEqual(groq.call_count, 1)  # a 401 key isn't retried on its other models

    def test_the_last_round_must_answer_from_what_it_found(self):
        sent = []

        def fake_post(api_key, model, payload):
            sent.append(payload["toolConfig"]["functionCallingConfig"]["mode"])
            if payload["toolConfig"]["functionCallingConfig"]["mode"] == "NONE":
                return _reply({"text": "From everything I looked up: squats lead."})
            return _reply({"functionCall": {"name": "list_exercises", "args": {"limit": len(sent)}}})

        with patch.object(ai_coach, "_post", side_effect=fake_post):
            out = self.ask("What do I train most?")
        self.assertEqual(out["source"], "ai")
        self.assertEqual(out["answer"], "From everything I looked up: squats lead.")
        self.assertEqual(sent, ["AUTO"] * ai_coach.MAX_TOOL_ROUNDS + ["NONE"])
        self.assertEqual(len(out["steps"]), ai_coach.MAX_TOOL_ROUNDS)

    def test_answers_read_as_words_not_code(self):
        self.assertEqual(ai_coach._plain_words("Use `suggest_next_session` before your back day."),
                         "Use next-session target before your back day.")
        self.assertEqual(ai_coach._plain_words("**179.9 kg** ranking e1rm"), "**179.9 kg** e1RM")
        self.assertEqual(ai_coach._plain_words("Your plan says push."), "Your plan says push.")

    def test_an_empty_summary_points_at_the_last_block(self):
        away = User(username="away", role=UserRole.USER, is_verified=True)
        self.db.add(away)
        self.db.commit()
        self.db.add(_log(away, self.today - timedelta(days=40), "Back Squat", 100, 5, 117))
        self.db.commit()
        summary = coach_tools.get_training_summary(self.db, away, days=28)
        self.assertEqual(summary["workout_days"], 0)
        self.assertIn(f"latest workout was {self.iso(40)}", summary["note"])
        self.assertIn("days=128", summary["note"])  # 28 + 40 days away + 60

    def test_keys_and_model_order(self):
        self.assertEqual(ai_coach.key_provider("gsk_abc"), "groq")
        self.assertEqual(ai_coach.key_provider("AIzaSy"), "gemini")
        with patch.object(ai_coach.Config, "AI_MODEL_ORDER", "gemini-2.5-flash, groq:qwen/qwen3.8-27b, nope:x"), \
                patch.object(ai_coach.Config, "GEMINI_COACH_MODEL", ""):
            self.assertEqual(ai_coach._model_order(), [("gemini", "gemini-2.5-flash"), ("groq", "qwen/qwen3.8-27b")])

    def test_history_is_cleaned(self):
        contents = ai_coach._clean_history([
            {"role": "assistant", "text": "hello"},  # can't lead
            {"role": "user", "text": "a"}, {"role": "user", "text": "b"},
            {"role": "assistant", "text": "c"}, {"role": "user", "text": "x" * 5000}, "junk",
        ])
        self.assertEqual([c["role"] for c in contents], ["user", "model", "user"])
        self.assertEqual(contents[0]["text"], "a\n\nb")
        self.assertEqual(len(contents[-1]["text"]), ai_coach.MAX_MESSAGE_CHARS)

    def test_rate_limit(self):
        for i in range(ai_coach.RATE_LIMIT):
            self.assertTrue(ai_coach.allow_request(1, now=1000 + i))
        self.assertFalse(ai_coach.allow_request(1, now=1100))
        self.assertTrue(ai_coach.allow_request(1, now=1000 + ai_coach.RATE_WINDOW_S + 50))

    def test_suggestions_use_the_users_lifts(self):
        tips = ai_coach.suggestions(self.db, self.user)
        self.assertIn("How is my Back Squat progressing?", tips)


class _TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    ENABLE_CSRF = False
    WTF_CSRF_ENABLED = False


class TestCoachRoutes(_CoachDb):
    def setUp(self):
        super().setUp()
        self._patchers = [
            patch("models.Session", self.db),
            patch("liftbook.Session", self.db),
            patch("liftbook.routes.auth.Session", self.db),
            patch("liftbook.routes.workouts.Session", self.db),
            patch("liftbook.routes.stats.Session", self.db),
            patch("liftbook.routes.plans.Session", self.db),
        ]
        for p in self._patchers:
            p.start()
        self.client = create_app(config_object=_TestConfig, init_db=False).test_client()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        super().tearDown()

    def login(self, user_id):
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(user_id)

    def test_only_admins_can_use_the_coach(self):
        self.login(self.other_id)
        self.assertEqual(self.client.post("/api/ai-coach", json={"messages": []}).status_code, 403)
        self.assertEqual(self.client.get("/api/ai-coach/suggestions").status_code, 403)
        page = self.client.get("/", follow_redirects=True).get_data(as_text=True)
        self.assertNotIn("aiAssistantModal", page)

    def test_streamed_answer_is_recorded_and_can_be_rated(self):
        self.login(self.user_id)
        replies = iter([
            _reply({"functionCall": {"name": "list_exercises", "args": {}, "id": "c1"}, "thoughtSignature": "s"}),
            _reply({"text": "You train squats most."}),
        ])
        with patch.object(ai_coach, "_keys", return_value=[{"id": None, "api_key": "k", "source": "env", "provider": "gemini"}]), \
                patch.object(ai_coach, "_post", side_effect=lambda *a: next(replies)):
            res = self.client.post("/api/ai-coach", json={"stream": True, "messages": [{"role": "user", "text": "What do I train most?"}]})
            events = [json.loads(line) for line in res.get_data(as_text=True).splitlines() if line.strip()]
        self.assertEqual(res.mimetype, "application/x-ndjson")
        self.assertEqual([e["type"] for e in events], ["step", "done"])
        self.assertEqual(events[0]["label"], "Exercise list")
        done = events[-1]
        self.assertEqual(done["answer"], "You train squats most.")
        self.assertNotIn("usage", done)

        fresh = lambda: self.db.query(CoachAnswer).filter_by(id=done["answer_id"]).one()
        row = fresh()
        self.assertEqual((row.question, row.model, row.source), ("What do I train most?", _gemini_models()[0], "ai"))
        self.assertEqual([s["tool"] for s in row.steps], ["list_exercises"])
        self.assertEqual(row.calls, 2)

        ok = self.client.post("/api/ai-coach/rate", json={"answer_id": row.id, "rating": -1, "comment": "Too vague"})
        self.assertEqual(ok.status_code, 200)
        row = fresh()
        self.assertEqual((row.rating, row.comment), (-1, "Too vague"))
        self.client.post("/api/ai-coach/rate", json={"answer_id": row.id, "rating": 0})
        row = fresh()
        self.assertEqual((row.rating, row.comment), (None, None))
        self.assertEqual(self.client.post("/api/ai-coach/rate", json={"answer_id": row.id, "rating": 5}).status_code, 400)

        page = self.client.get("/admin/coach").get_data(as_text=True)
        self.assertIn("What do I train most?", page)
        self.assertIn(_gemini_models()[0], page)

        # Someone else can't rate it (and non-admins can't rate at all).
        self.login(self.other_id)
        self.assertEqual(self.client.post("/api/ai-coach/rate", json={"answer_id": row.id, "rating": 1}).status_code, 403)

    def test_model_summary_ranks_by_helpfulness(self):
        from services import coach_answers
        for model, rating, ms in [("a", 1, 4000), ("a", -1, 6000), ("b", 1, 9000), ("b", 1, 11000), ("b", None, 10000)]:
            self.db.add(CoachAnswer(user_id=self.user_id, question="q", answer="x", model=model, rating=rating, ms=ms))
        self.db.add(CoachAnswer(user_id=self.user_id, question="q", answer="x", source="rules"))
        self.db.commit()
        summary = coach_answers.model_summary(self.db)
        self.assertEqual([r["model"] for r in summary], ["b", "a", "Built-in answer"])
        self.assertEqual((summary[0]["helpful_pct"], summary[0]["answers"], summary[0]["median_s"]), (100, 3, 10.0))
        self.assertEqual(summary[1]["helpful_pct"], 50)

    def test_integrations_label_each_keys_provider(self):
        self.db.add_all([UserApiKey(user_id=self.user_id, api_key="gsk_groq1234", account_label="Fast"),
                         UserApiKey(user_id=self.user_id, api_key="AIza-gem5678")])
        self.db.commit()
        self.login(self.user_id)
        page = self.client.get("/settings/integrations").get_data(as_text=True)
        self.assertIn("Groq · •••• 1234", page)
        self.assertIn("Gemini · •••• 5678", page)

    def test_admin_chat_round_trip(self):
        self.login(self.user_id)
        with patch.object(ai_coach, "_post", return_value=_reply({"text": "Train legs."})):
            res = self.client.post("/api/ai-coach", json={
                "messages": [{"role": "user", "text": "What now?"}],
                "context": {"page": "/", "exercise": "Back Squat", "evil": "x"},
            })
        # No key configured anywhere → the rules engine, which can't answer this one.
        self.assertEqual(res.status_code, 400)
        self.assertIn("No AI key", res.get_json()["error"])

        with patch.object(ai_coach, "_keys", return_value=[{"id": None, "api_key": "k", "source": "env", "provider": "gemini"}]), \
                patch.object(ai_coach, "_post", return_value=_reply({"text": "Train legs."})):
            res = self.client.post("/api/ai-coach", json={"messages": [{"role": "user", "text": "What now?"}]})
        body = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body["answer"], "Train legs.")
        self.assertNotIn("key_id", body)

        tips = self.client.get("/api/ai-coach/suggestions").get_json()
        self.assertTrue(tips["ok"])
        self.assertFalse(tips["ai_enabled"])
        self.assertIn("aiAssistantModal", self.client.get("/", follow_redirects=True).get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
