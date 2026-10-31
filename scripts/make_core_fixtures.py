"""Golden fixtures for the JavaScript core (web/core/): inputs, and what the Python app gives for
them, so `node --test` can check the JavaScript gives exactly the same.

Inputs come from three places:
1. every input the existing pytest suite gives the ported functions (recorded while it runs,
   see scripts/core_fixture_recorder.py),
2. hand-written realistic and odd inputs below,
3. seeded random workouts and training histories (the same every run).

Every expected output is then computed again here by the real Python functions, on a fresh
in-memory database built from the recorded state, so the fixtures don't depend on how a test
set things up. Run from the repo root:

    .venv/bin/python scripts/make_core_fixtures.py
"""
import copy
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "core" / "test" / "fixtures"
sys.path.insert(0, str(ROOT))

# Never the real environment (as tests/conftest.py): no .env, a throwaway database.
sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: False, find_dotenv=lambda *a, **k: "")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="core-fixtures-"), "unused.db")
for _key in ("MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_DEFAULT_SENDER", "BREVO_API_KEY", "BREVO_SENDER_EMAIL",
             "GEMINI_API_KEY", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "ADMIN_PASSWORD", "ADMIN_EMAILS"):
    os.environ[_key] = ""

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import list_of_exercise  # noqa: E402
from list_of_exercise import DEFAULT_PLAN, get_workout_days, list_of_exercises  # noqa: E402
from models import (  # noqa: E402
    Base, BodyweightExercisePreference, ExerciseRename, Plan, RepRange, TimedExercisePreference, User, WorkoutLog,
)
from parsers import workout as workout_module  # noqa: E402
from parsers.workout import workout_parser  # noqa: E402
from services import exercise_matching, exercise_rename, rep_ranges, retrieve, stats  # noqa: E402
from services import logging as logging_service  # noqa: E402

FIXED_NOW = datetime(2026, 10, 31, 9, 15)
TODAY = "31/10/26"
SEED = 20261031


def plain(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("not JSON")
    return value


def parse_now(value):
    return datetime.fromisoformat(value) if value else FIXED_NOW


# --- A database built from a recorded state ---

class State:
    """A fresh in-memory database holding one user's recorded state, with the plan and rep
    ranges they train from fixed to the recorded ones."""

    def __init__(self, state):
        self.state = state
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(id=1, username="golden", bodyweight=state.get("bodyweight"),
                         follow_admin_plan=False, follow_admin_exercises=False)
        self.db.add(self.user)
        for log in state.get("logs") or []:
            self.db.add(WorkoutLog(
                id=log["id"], user_id=1, date=datetime.fromisoformat(log["date"]), workout_name=log["workout_name"],
                exercise=log["exercise"], exercise_string=log["exercise_string"], sets_json=log["sets"],
                bodyweight=log["bodyweight"], uses_bodyweight=log["uses_bodyweight"], top_weight=log["top_weight"],
                top_reps=log["top_reps"], estimated_1rm=log["estimated_1rm"]))
        for p in state.get("bodyweight_prefs") or []:
            self.db.add(BodyweightExercisePreference(user_id=1, **p))
        for p in state.get("timed_prefs") or []:
            self.db.add(TimedExercisePreference(user_id=1, **p))
        for r in state.get("renames") or []:
            self.db.add(ExerciseRename(user_id=1, log_ids=[], **r))
        if state.get("own_rep_ranges"):
            self.db.add(RepRange(user_id=1, text_content=state["own_rep_ranges"]))
        if state.get("own_plan"):
            self.db.add(Plan(user_id=1, text_content=state["own_plan"]))
        self.db.commit()

    def __enter__(self):
        self._saved = (retrieve.get_effective_plan_text, retrieve.get_effective_rep_ranges_text,
                       retrieve._retrieve_date_string)
        retrieve.get_effective_plan_text = lambda db, user: self.state["effective_plan"]
        retrieve.get_effective_rep_ranges_text = lambda db, user: self.state["effective_rep_ranges"]
        retrieve._retrieve_date_string = lambda: TODAY
        return self

    def __exit__(self, *exc):
        (retrieve.get_effective_plan_text, retrieve.get_effective_rep_ranges_text,
         retrieve._retrieve_date_string) = self._saved
        self.db.close()
        self.engine.dispose()


def js_state(state):
    """The recorded state as the JavaScript functions take it."""
    settings = {}
    for p in state.get("bodyweight_prefs") or []:
        settings.setdefault(p["exercise_key"], {"exercise_key": p["exercise_key"]})["is_bodyweight"] = p["is_bodyweight"]
    for p in state.get("timed_prefs") or []:
        settings.setdefault(p["exercise_key"], {"exercise_key": p["exercise_key"]})["is_timed"] = p["is_timed"]
    return {
        "history": state["logs"],
        "settings": list(settings.values()),
        "renames": [{"old_key": r["old_key"], "new_name": r["new_name"]} for r in state.get("renames") or []],
        "bodyweight": state.get("bodyweight"),
        "own_rep_ranges": state.get("own_rep_ranges") or "",
        "plan": state["effective_plan"],
        "rep_ranges": state["effective_rep_ranges"],
    }


def snapshot_of(db, user):
    from core_fixture_recorder import snapshot
    return plain(snapshot(db, user))


# --- Cases ---

def parser_case(text, bodyweight=None, preserve=False, now=None):
    out = workout_parser(text, bodyweight, preserve, parse_now(now))
    return {"input": {"text": text, "bodyweight": bodyweight, "preserve": preserve, "now": parse_now(now).isoformat()},
            "output": plain(out)}


def log_case(record):
    state = record["state"]
    parsed = copy.deepcopy(record["parsed"])
    if isinstance(parsed.get("date"), str):
        parsed["date"] = datetime.fromisoformat(parsed["date"])
    js_parsed = plain(copy.deepcopy(parsed))
    with State(state) as s:
        max_id = max([log["id"] for log in state["logs"]] or [0])
        summary = logging_service.handle_workout_log(s.db, s.user, parsed)
        s.db.flush()
        new_logs = (s.db.query(WorkoutLog).filter(WorkoutLog.id > max_id).order_by(WorkoutLog.id).all())
        prefs = s.db.query(BodyweightExercisePreference).order_by(BodyweightExercisePreference.id).all()
        before = {p["exercise_key"] for p in state.get("bodyweight_prefs") or []}
        output = {
            "summary": plain(summary),
            "logs": [{
                "id": log.id, "date": log.date.isoformat(), "workout_name": log.workout_name, "exercise": log.exercise,
                "exercise_string": log.exercise_string, "sets": plain(log.sets_json), "bodyweight": log.bodyweight,
                "uses_bodyweight": log.uses_bodyweight, "top_weight": log.top_weight, "top_reps": log.top_reps,
                "estimated_1rm": log.estimated_1rm,
            } for log in new_logs],
            "bodyweight": s.user.bodyweight,
            "bodyweight_keys": sorted({p.exercise_key for p in prefs if p.is_bodyweight} - {k for k in before}),
        }
    return {"input": {"parsed": js_parsed, "state": js_state(state), "logged_bodyweight": record["parsed"].get("logged_bodyweight")},
            "output": output}


def retrieve_case(record):
    state = record["state"]
    with State(state) as s:
        text, n_ex, n_sets = retrieve._generate_retrieve_output_for_exercises(
            s.db, s.user, record["exercises"], header_line=record["header_line"], set_overrides=record.get("set_overrides"))
    return {"input": {"exercises": record["exercises"], "header_line": record["header_line"],
                      "set_overrides": record.get("set_overrides"), "state": js_state(state)},
            "output": [text, n_ex, n_sets]}


def retrieve_day_case(state, category, day_id):
    with State(state) as s:
        out = retrieve.generate_retrieve_output(s.db, s.user, category, day_id)
    return {"input": {"category": category, "day_id": day_id, "today": TODAY, "state": js_state(state)}, "output": list(out)}


def stats_case(kind, record):
    state = record["state"]
    with State(state) as s:
        if kind == "chart":
            out = stats.get_chart_data(s.db, s.user, record["exercise"])
        elif kind == "summary":
            out = stats.get_exercise_summary(s.db, s.user, record["exercise"])
        elif kind == "all_summary":
            out = stats.get_all_exercises_summary(s.db, s.user)
        elif kind == "growth":
            out = stats.get_average_growth_data(s.db, s.user)
        else:
            args = {k: v for k, v in record.items() if k not in ("state",)}
            out = stats.get_overall_progress_data(s.db, s.user, **args)
    args = {k: v for k, v in record.items() if k != "state"}
    return {"input": {**args, "state": js_state(state)}, "output": plain(out)}


def pure_cases(kind, records):
    funcs = {
        "plan_line": lambda r: workout_module._parse_plan_exercise_line(r["line"]),
        "workout_days": lambda r: get_workout_days(r["text"]),
        "normalize": lambda r: exercise_matching.normalize_exercise_name(r["name"]),
        "same_exercise": lambda r: exercise_matching.same_exercise(r["a"], r["b"]),
        "rep_entries": lambda r: rep_ranges.parse_rep_entries(r["text"]),
        "rep_canonical": lambda r: rep_ranges.canonical_rep_text(r["text"]),
        "describe": lambda r: retrieve.describe_retrieve_output(r["output"]),
        "rename_plan": lambda r: exercise_rename._rename_in_plan_text(r["text"], r["old_key"], r["new_name"]),
        "rename_rep": lambda r: exercise_rename._rename_in_rep_text(r["text"], r["old_key"], r["new_name"]),
        "rename_string": lambda r: exercise_rename._rename_in_exercise_string(r["text"], r["old"], r["new"]),
        "validate_rename": lambda r: exercise_rename.validate_rename(r["old"], r["new"]),
        "plan_names": lambda r: exercise_rename.plan_exercise_names(r["text"]),
    }
    return [{"input": r, "output": plain(funcs[kind](r))} for r in records]


# --- Hand-written inputs ---

ODD_WORKOUTS = [
    "", "   ", "#Gym\n#Only comments", "Body Weight - 80 kg",
    "30/9 Push\nBench Press 100x5 x5 x4\nIncline Dumbbell Press 30 30 30, 10 10 8",
    "Monday 30/9 Push &amp; Pull\nBody Weight - 73 kg\n1. Bench Press 100x5\n2) Pull Ups bw+10 x 8, 8, 6",
    "2026-09-28 Legs\nSquat [3, 6-8]\n100kg 5 5 5\nLeg Press 3x10 @ 200",
    "1st Oct - Pull\nDeadlift 3x5 180kg\nRow 100kg 3x8",
    "Sep 30 Back\nLat Pulldown 60 x 12, 10, 8", "Tue, 29 Sep - Legs\nLunges 20 20, 12 12",
    "31/9 Bad date\nCurl 20x10", "29/2 Leap\nCurl 20x10", "29/2/24 Leap\nCurl 20x10", "15/3/25 Old\nCurl 20x10",
    "0/0 Zero\nCurl 20x10", "123/9 Odd\nCurl 20x10", "12/13 Bad month\nCurl 20x10", "31 Sept\nCurl 10x10",
    "Feb 30 Push\nDips bw x 10", "1/1\nSquat 100x5", "2026-02-30 Nope\nSquat 100x5", "0000-01-01 Zero\nSquat 1x1",
    "Push Day\nPlank\n60s, 45s\nDead Hang 1:00, 0:45\nWall Sit 3 x 60s\nFarmer's Walk 40 x 30 sec",
    "Abs\nPlank 60 sec x 3\nV Tucks 15 15 12\nCrunches A\n20, 20, 15",
    "Arms\n21s Curl 20x7\n1-Arm Row 30x10\n45 Degree Hyperextension 20, 12\n3/4 Squat 100x5",
    "Arms\nA1. Curl 20x10\nA2) Pushdown 30x12\nB1: Hammer Curl 18x10\nB2 - Dips bw x 8",
    "Chest\nBench Press - [3, 6-8]\n80 80 75, 8 7 8\nFly - [12-20]\n15 15, 15 12",
    "Chest\nBench Press-[8-12] 80x8\nPec Deck [3]\n50, 12\n45, 12\n40, 15",
    "Chest\nBench 💪 100x5\n• Fly 20x12\nSquat 🔥\n100x5\n90x8\n80x10",
    "Back\nPull Ups\nbw\n8 8 6\nChin Ups bw-10 x 8\nAssisted Dips -35x5",
    "Back\nPull Ups bw/2+10x5 x6\nRow bodyweight x 10\nRow Body Weight - 5 x 8",
    "Legs\nSquat 100x5x3\nSquat 3x5x100\nSquat 3 sets of 8 at 60\nSquat 3 sets x 8 reps @ 60\nSquat 3 sets of 8",
    "Legs\nLeg Press 2x10 @ 60, 1x8 @ 70\nLeg Curl 3x10 @ 40, 30x12\nHip Thrust 100kg: 10, 10, 8",
    "Legs\nCalf Raise 100 - 12 12 10\nCalf Raise 100 for 12, 12, 10\nCalf Raise 12 12 10 @ 100\nCalf 60kg 20, 12",
    "Misc\nCurl 20 10\nCurl 20 10 15 8\nCurl 20 15 10 8\nCurl 20 20\nCurl 10.5 10\nCurl 25. 4",
    "Misc\nCurl 3 sets\n20 20 15, 10 10 12\nRow\n3 sets\n50x10",
    "Misc\nCurl\n20 20 15\n10 10 12\nPress\n40\n8",
    "Misc\nCurl x5 x5\nCurl nan x 5\nCurl 1e5 x 5\nCurl inf\nCurl 20 , 10",
    "Misc\nPlank [1, 30-60s]\n60\nForearm Roller - [2, 30-60s] 20 20, 45 60",
    "Misc\nUnknown\n- 100x5\n: 100x5\n100x5",
    "Misc\nDips 3 sets\nDips 4 set\nDips - 3 sets\nDips: 2 sets",
    "Misc\nbody weight x 10\nBW x 10, 10, 8\n100x5, 5, 4",
    "Misc\nSquat 100 lbs x 5\nSquat 225lb 5 5 5\nSquat 100 kgs, 5",
    "Misc\r\nSquat 100x5\r\nBench 80x8\r\n",
    "Misc\n\tSquat\t100x5\n  Bench   80 x 8  ",
    "Misc\nÜbung 20x10\nCurl ١٠x5\nRow 20×10\nPress 20*10",
    "Session 2 – Shoulders\nOverhead Press 40x8\nLateral Raise 10x15",
    "10/10 Push\nBench Press 100x5\nBench Press 105x3",
    "Legs\nSquat 100 x 5 90 x 8",
    "Legs\nSquat 100x5 90x8 80x10\nSquat 100x5, 90x8, 80x10",
    "Legs\n1 Squat 100x5\n2 - Bench 80x8\n3 Leg Press 200x10\n4 Arm Curl 20x10",
    "Legs\nSquat 100 90 80 70, 5 6 7 8",
    "Legs\nSquat 100 x 5 x 5 x 5 x 5 x 5",
    "Legs\nSquat 15x100",
    "&lt;Push&gt; &copy; &#169; &#x41; &amp\nBench 100x5",
    "Push &notit; &unknown; &#0; &#128; &#xD800;\nBench 100x5",
    "१२/१० Push\nCurl १०x5\nRow ٣ ٤, ٥\nSquat ０１x5\nPress 𝟏𝟎x5\nPlank ६०s, ४५s",
    "٢٨/٩/٢٦ Legs\nSquat ١٠٠x٥",
]

RETRIEVE_TEXTS = [
    "31/10/26 - Session 1 - Chest & Biceps\n\nBody Weight - 73 kg\n\nBench Press - [3, 6–8]\n100, 5\n95, 6\n90, 8\n\nDips\nbw, 10\nbw, 8\n\nCurl\n1, 1\n1, 1\n",
    "31/10/26 - Push\n\nPlank - [1, 30-60s]\n60, 1\n\nFarmer's Walk - [20–60s]\n40 40, 30 45",
    "31/10/26 - Custom\n\nSquat - [3]\n100 x 5, 90 x 8\n\nRow - [AMRAP]\nbw/4, 1",
    "", "Header only", "31/10/26 - X\n\nBody Weight - 80 kg",
    "h\n\nSquat - [2, Max reps]\n100 90, 5 6\n\nPull Ups - [3, 6-10]\nbw+10 bw+5 bw, 8 8 6",
    "h\n\nSquat\n100\n\nLeg Press - [10–20]\n200 x 12\n\nBroken\n1 2 3",
]

REP_TEXTS = [
    "Bench Press: 6-10\nSquat = 3, 5-8\nDips\t3x6-12\nPlank 30-60 sec\nCurl\n8 to 12\nRow:\nFly: n/a\nPress: (blank)\n#comment\nAMRAP thing: AMRAP",
    "Bench Press: 10-6\nBench Press: 8-12\nbench press: 5\nDeadlift: 3,3-6\nFarmer's Walk: 20–60s",
    "Preacher Curl (Wellness): 3, 10-12\nPreacher Curl: 8-12\nHip Thrust - (wellness)\n12",
    "", "   \n\n", "Name only\nAnother name", "X²: 5", "1. Squat 5", "Squat 5 5",
]

PLAN_TEXTS = [
    DEFAULT_PLAN, list_of_exercise.PREVIOUS_DEFAULT_PLAN,
    "Push 1\nBench Press - [3, 6-8]\nDips - [3]\n\nPull 1\nPull Ups\nRow [2, 8-12]\n\nLegs 1\nSquat – [4, 5–8]\nLeg Press",
    "Cycle 1\nSession 1 - Chest\nBench\nSession 2: Back\nRow\nHeading 2\nSession 3\nSquat\nSession 1 – Chest again\nFly",
    "Exercises before any day\nPush 1\n• Bench\nPush 1\nIncline",
    "", "2026 5\nSquat", "Day 10\nA\nDay 2\nB",
]

NAMES = [
    "Pull-Ups", "Pull Ups", "pullups", "Tricep Rod Push-Down", "Rod Triceps Pushdown", "OH Press", "Overhead Press",
    "Farmer’s Walk", "Farmer's Walk", "Wrist Flexion – Dumbbell", "Wrist Flexion - Dumbbell", "Calf Raises Standing",
    "Standing Calf Raises", "Press", "Presses", "Glass", "  Leg   Press  ", "Leg_Press", "Abs", "Bus", "", "Ü-Bung",
]

# --- Seeded random inputs ---

FUZZ_NAMES = list_of_exercises + [
    "1-Arm Row", "45 Degree Hyperextension", "21s Curl", "Plank", "Dead Hang", "Farmer's Walk", "Pull-Ups",
    "Squat 💪", "• Leg Press", "EZ-bar curl", "oh press", "3/4 Squat", "Bench Press", "Squat", "Chin Ups",
    "Preacher Curl (Wellness)", "Wall Sit", "Rod Push Down", "Pushdown Rod",
]
TITLES = ["", "30/9 Push", "Monday 30/9 Push", "2026-09-28 Legs", "1st Oct - Pull", "Sep 30 Back", "31/9 Bad",
          "15/3/25 Old", "Push Day", "12/01 Chest Day", "29/2 Leap", "Tue, 29 Sep - Legs", "Session 2 – Shoulders",
          "4 Oct", "Oct 4 2025 Legs", "1/1/2026"]
PREFIXES = ["", "", "", "1. ", "2) ", "3 - ", "B1: ", "4 "]
TARGETS = ["", "", "", " - [3]", " - [3, 6-8]", " [2]", "-[8-12]", " - [1, 30-60s]", " 3 sets", " – [4, 5–8]", " [2, 10-15]"]


def _w(rng):
    return rng.choice(["20", "22.5", "30", "40", "60", "80", "100", "102.5", "7.25", "0", "-20", "bw", "bw+10", "bw-5", "bw/4", "bw/2+10"])


def _r(rng):
    return str(rng.choice([1, 3, 5, 6, 8, 10, 12, 15, 20, 30, 45, 60]))


def fuzz_data(rng):
    w, r = _w, _r
    forms = [
        lambda: f"{w(rng)}x{r(rng)}",
        lambda: f"{w(rng)} x {r(rng)}, {w(rng)} x {r(rng)}",
        lambda: f"{w(rng)}x{r(rng)} x{r(rng)} x{r(rng)}",
        lambda: f"{w(rng)} x {r(rng)}, {r(rng)}, {r(rng)}",
        lambda: f"{w(rng)} {w(rng)} {w(rng)}, {r(rng)} {r(rng)} {r(rng)}",
        lambda: f"{w(rng)} {w(rng)}, {r(rng)} {r(rng)}",
        lambda: f"{rng.randint(1, 5)}x{r(rng)} @ {w(rng)}",
        lambda: f"{rng.randint(1, 5)}x{r(rng)} {w(rng)}kg",
        lambda: f"{w(rng)}kg {rng.randint(1, 5)}x{r(rng)}",
        lambda: f"{w(rng)}x{r(rng)}x{rng.randint(1, 5)}",
        lambda: f"{w(rng)}kg {r(rng)} {r(rng)} {r(rng)}",
        lambda: f"{w(rng)}: {r(rng)}, {r(rng)}, {r(rng)}",
        lambda: f"{r(rng)} {r(rng)} {r(rng)} @ {w(rng)}",
        lambda: f"{rng.choice([30, 45, 60, 90])}s, {rng.choice([30, 45, 60])}s",
        lambda: f"1:{rng.randint(0, 59):02d}, 0:{rng.randint(10, 59)}",
        lambda: f"{rng.randint(1, 4)} x {rng.choice([30, 60])}s",
        lambda: f"{rng.randint(2, 4)} sets of {r(rng)} at {w(rng)}",
        lambda: f"{w(rng)} {r(rng)}",
        lambda: f"{w(rng)} {r(rng)} {w(rng)} {r(rng)}",
        lambda: f"{w(rng)}, {r(rng)}\n{w(rng)}, {r(rng)}\n{w(rng)}, {r(rng)}",
        lambda: f"{w(rng)}x{r(rng)}\n{w(rng)}x{r(rng)}",
        lambda: f"{w(rng)} {w(rng)}\n{r(rng)} {r(rng)}",
        lambda: f"{w(rng)}. {r(rng)}",
        lambda: f"{w(rng)} lbs x {r(rng)}",
        lambda: "",
    ]
    return rng.choice(forms)()


def fuzz_workout(rng):
    lines = [rng.choice(TITLES) or rng.choice(["Workout", "Push", "X"])]
    if rng.random() < 0.25:
        lines.append(rng.choice(["Body Weight - 73 kg", "Bodyweight: 81.5", "body weight - 160 lbs"]))
    for _ in range(rng.randint(1, 6)):
        name = rng.choice(PREFIXES) + rng.choice(FUZZ_NAMES) + rng.choice(TARGETS)
        data = fuzz_data(rng)
        if data and rng.random() < 0.5:
            lines.append(f"{name} {data}")
        else:
            lines.append(name)
            if data:
                lines.append(data)
        if rng.random() < 0.08:
            lines.append(rng.choice(["#note", "", "3 sets"]))
    return "\n".join(lines)


# --- Training histories, logged through the real Python app ---

SCENARIO_PLAN = """Push 1
Bench Press - [3, 6-8]
Incline Dumbbell Press [2]
Dips
Plank - [1, 30-60s]

Pull 1
Pull Ups - [3, 6-10]
Barbell Row
Hammer Curl - [2, 10-15]
Farmer's Walk

Legs 1
Squat – [4, 5–8]
Romanian Deadlift
Leg Press
Calf Raises Standing
"""

SCENARIO_REPS = """Bench Press: 3, 6-8
Barbell Row: 3, 8-12
Squat: 5-8
Leg Press: 2, 10-20
Hammer Curl: 10-15
Dips: 3, 6-12
Farmer's Walk: 20-60s
"""

SCENARIO_EXERCISES = {
    "Push 1": ["Bench Press", "Incline Dumbbell Press", "Dips", "Plank"],
    "Pull 1": ["Pull Ups", "Barbell Row", "Hammer Curl", "Farmer's Walk"],
    "Legs 1": ["Squat", "Romanian Deadlift", "Leg Press", "Calf Raises Standing"],
}
BASE = {"Bench Press": 60, "Incline Dumbbell Press": 20, "Barbell Row": 50, "Hammer Curl": 12, "Squat": 80,
        "Romanian Deadlift": 70, "Leg Press": 120, "Calf Raises Standing": 60, "Farmer's Walk": 30}


def scenario_workout(rng, day, session, progress, bodyweight_line):
    lines = [f"{day.date().isoformat()} {session}"]
    if bodyweight_line:
        lines.append(bodyweight_line)
    for name in SCENARIO_EXERCISES[session]:
        if rng.random() < 0.15:
            continue
        shown = rng.choice([name, name.lower(), name.replace(" ", "-"), name]) if rng.random() < 0.2 else name
        sets = rng.choice([2, 3, 3, 4])
        if name == "Plank":
            lines += [shown, ", ".join(f"{rng.choice([30, 45, 60, 75])}s" for _ in range(sets))]
        elif name in ("Dips", "Pull Ups"):
            add = rng.choice(["bw", "bw+5", "bw+10", "bw-10"])
            lines.append(f"{shown} {add} x {rng.randint(5, 10)}, {rng.randint(4, 9)}, {rng.randint(3, 8)}")
        elif name == "Farmer's Walk":
            lines.append(f"{shown} {BASE[name] + 2 * progress} x {rng.choice([30, 40, 60])} sec")
        else:
            top = BASE[name] + progress * rng.choice([0, 2.5, 2.5, 5]) - rng.choice([0, 0, 5])
            reps = [rng.randint(5, 12) for _ in range(sets)]
            style = rng.randint(0, 3)
            if style == 0:
                lines.append(f"{shown} " + ", ".join(f"{top - 5 * i:g} x {r}" for i, r in enumerate(reps)))
            elif style == 1:
                lines += [shown, f"{' '.join(f'{top - 2.5 * i:g}' for i in range(sets))}, {' '.join(map(str, reps))}"]
            elif style == 2:
                lines.append(f"{shown} {sets}x{reps[0]} @ {top:g}")
            else:
                lines += [shown] + [f"{top - 5 * i:g}, {r}" for i, r in enumerate(reps)]
    return "\n".join(lines)


def run_scenario(seed, n_workouts, *, bodyweight, prefs=(), renames=(), own_plan=SCENARIO_PLAN, own_reps=SCENARIO_REPS):
    """Log a random history through the real app, recording each save and the final state."""
    rng = random.Random(seed)
    state = {"bodyweight": bodyweight, "logs": [], "bodyweight_prefs": [p for p in prefs if "is_bodyweight" in p],
             "timed_prefs": [p for p in prefs if "is_timed" in p], "renames": list(renames),
             "own_rep_ranges": own_reps, "own_plan": own_plan, "effective_plan": own_plan or DEFAULT_PLAN,
             "effective_rep_ranges": own_reps or retrieve._build_default_rep_text()}
    log_records = []
    with State(state) as s:
        day = datetime(2025, 6, 2)
        sessions = list(SCENARIO_EXERCISES)
        for k in range(n_workouts):
            day += timedelta(days=rng.choice([1, 2, 2, 3, 4, 9, 30 if rng.random() < 0.05 else 2]))
            bw_line = f"Body Weight - {bodyweight + rng.choice([-1, 0, 1]):g} kg" if bodyweight and rng.random() < 0.2 else ""
            text = scenario_workout(rng, day, sessions[k % len(sessions)], k // 3, bw_line)
            parsed = workout_parser(text, s.user.bodyweight, False, day + timedelta(hours=20))
            if not parsed:
                continue
            if rng.random() < 0.1:
                parsed["date"] = parsed["date"] + timedelta(hours=rng.randint(1, 23), minutes=rng.randint(0, 59))
            log_records.append({"parsed": plain(copy.deepcopy(parsed)), "state": snapshot_of(s.db, s.user)})
            logging_service.handle_workout_log(s.db, s.user, parsed)
            s.db.commit()
        final = snapshot_of(s.db, s.user)
    final["effective_plan"] = state["effective_plan"]
    final["effective_rep_ranges"] = state["effective_rep_ranges"]
    for record in log_records:
        record["state"]["effective_plan"] = state["effective_plan"]
        record["state"]["effective_rep_ranges"] = state["effective_rep_ranges"]
    return log_records, final


def pin_clock(value, run_start):
    """Times the suite took from the clock ("now", "2 days ago") as the same offsets from
    FIXED_NOW, in whole days, so the fixtures are the same on every run. A time within a few
    minutes of the run's time of day came from the clock; dates a test wrote out are left alone."""
    if isinstance(value, dict):
        return {k: pin_clock(v, run_start) for k, v in value.items()}
    if isinstance(value, list):
        return [pin_clock(v, run_start) for v in value]
    if isinstance(value, str) and len(value) >= 19 and value[10:11] == "T":
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return value
        days = (moment - run_start).total_seconds() / 86400
        off_by = abs(days - round(days)) * 24 * 60
        if abs(days) < 400 and off_by < 15:
            return (FIXED_NOW + timedelta(days=round(days))).isoformat()
    return value


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    record_path = Path(tempfile.mkdtemp(prefix="core-record-")) / "records.json"
    env = dict(os.environ, CORE_FIXTURE_RECORD=str(record_path), PYTHONPATH=f"{ROOT}{os.pathsep}{ROOT / 'scripts'}")
    print("Recording the inputs the test suite uses...")
    run_start = datetime.now()
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "core_fixture_recorder", "-p", "no:cacheprovider"],
                   cwd=ROOT, env=env, stdout=subprocess.DEVNULL, check=False)
    recorded = pin_clock(json.loads(record_path.read_text(encoding="utf-8")), run_start)
    # The suite reaches some functions in an order that depends on Python's hash seed.
    recorded = {kind: sorted(records, key=lambda r: json.dumps(r, sort_keys=True)) for kind, records in recorded.items()}
    sys.path.insert(0, str(ROOT / "scripts"))
    rng = random.Random(SEED)
    fixtures = {}

    def keep(cases, case):
        try:
            json.dumps(case, allow_nan=False)
        except (TypeError, ValueError):
            return
        cases.append(case)

    # Parser
    cases = []
    seen = set()
    inputs = [(r["text"], r["bodyweight"], r["preserve"], r["now"]) for r in recorded.get("parser", [])]
    inputs += [(t, bw, pres, None) for t in ODD_WORKOUTS for bw, pres in ((None, False), (80.0, False), (80.0, True))]
    inputs += [(fuzz_workout(rng), rng.choice([None, 70.0, 82.5]), rng.random() < 0.1,
                rng.choice([None, "2026-01-15T08:00:00", "2026-12-31T23:59:59.500000"])) for _ in range(2500)]
    for text, bw, pres, now in inputs:
        key = json.dumps([text, bw, pres, now])
        if key in seen:
            continue
        seen.add(key)
        try:
            keep(cases, parser_case(text, bw, pres, now))
        except ValueError:
            continue
    fixtures["parser"] = cases

    # Pure helpers
    fixtures["plan_line"] = pure_cases("plan_line", recorded.get("plan_line", []) + [
        {"line": line} for text in PLAN_TEXTS for line in text.split("\n")] + [
        {"line": l} for l in ["Squat - [3]", "Squat [3, 6-8]", "Squat – [3, 6–8]", "Squat: [12]", "Squat - [8-12]",
                              "Squat - [AMRAP]", "Squat 3 sets", "Squat - [3] 4 sets", "[3]", "Squat [a]", " - [3]"]])
    fixtures["workout_days"] = pure_cases("workout_days", recorded.get("workout_days", []) + [{"text": t} for t in PLAN_TEXTS])
    names = [r["name"] for r in recorded.get("normalize", [])] + NAMES + FUZZ_NAMES
    fixtures["normalize"] = pure_cases("normalize", [{"name": n} for n in dict.fromkeys(names)])
    pairs = [(r["a"], r["b"]) for r in recorded.get("same_exercise", [])]
    pairs += [(rng.choice(NAMES + FUZZ_NAMES), rng.choice(NAMES + FUZZ_NAMES)) for _ in range(300)]
    pairs += [("Rod Push Down", "Rod Pushdown"), ("Tricep Rod Push-Down", "Rod Triceps Pushdown"), ("Squat", "Squats")]
    fixtures["same_exercise"] = pure_cases("same_exercise", [{"a": a, "b": b} for a, b in dict.fromkeys(pairs)])
    fixtures["rep_entries"] = pure_cases("rep_entries", recorded.get("rep_entries", []) + [{"text": t} for t in REP_TEXTS])
    fixtures["rep_canonical"] = pure_cases("rep_canonical", recorded.get("rep_canonical", []) + [{"text": t} for t in REP_TEXTS])

    # Renames
    rename_pairs = [("bench press", "Flat Bench"), ("squat", "Back Squat"), ("dips", "Chest Dips"),
                    ("preacher curl", "EZ Preacher Curl"), ("farmer walk", "Farmer Carry"), ("nothing", "X")]
    fixtures["rename_plan"] = pure_cases("rename_plan", [
        {"text": t, "old_key": k, "new_name": n} for t in PLAN_TEXTS + [SCENARIO_PLAN] for k, n in rename_pairs])
    fixtures["rename_rep"] = pure_cases("rename_rep", [
        {"text": t, "old_key": k, "new_name": n} for t in REP_TEXTS + [SCENARIO_REPS] for k, n in rename_pairs])
    fixtures["rename_string"] = pure_cases("rename_string", [
        {"text": t, "old": o, "new": n} for t, o, n in [
            ("Bench Press 100x5", "Bench Press", "Flat Bench"), ("  bench press\n100x5", "Bench Press", "Flat Bench"),
            ("Bench Pressing 100x5", "Bench Press", "X"), ("Squat", "Squat", "Back Squat"), ("Squat2 5", "Squat", "B"),
            ("Squat-[3] 100x5", "Squat", "Back Squat"), ("Row", "", "X"), ("Rowé 5", "Row", "X")]])
    fixtures["validate_rename"] = pure_cases("validate_rename", [
        {"old": o, "new": n} for o, n in [("Squat", "Back Squat"), ("Squat", "squat"), ("Squat", ""), ("", "X"),
                                         ("Squat", "x" * 101), ("Squat", "x" * 100), ("Squat", "  Squat  "),
                                         ("Squat", "Squats"), ("Bench Press", "Bench-Press"), ("Squat", "   ")]])
    fixtures["plan_names"] = pure_cases("plan_names", [{"text": t} for t in PLAN_TEXTS + [SCENARIO_PLAN]])

    # Logging, retrieve and stats: recorded from the suite, then generated histories.
    log_records = list(recorded.get("log", []))
    retrieve_records = list(recorded.get("retrieve", []))
    stat_records = {k: list(recorded.get(k, [])) for k in ("chart", "summary", "growth", "overall")}
    finals = []
    scenarios = [
        dict(seed=1, n_workouts=24, bodyweight=78.0),
        dict(seed=2, n_workouts=18, bodyweight=None),
        dict(seed=3, n_workouts=30, bodyweight=65.5, prefs=[{"exercise_key": "dip", "exercise_name": "Dips",
                                                             "is_bodyweight": False, "source": "manual"},
                                                            {"exercise_key": "plank", "is_timed": False}]),
        dict(seed=4, n_workouts=12, bodyweight=90.0, own_plan="", own_reps=""),
        dict(seed=5, n_workouts=20, bodyweight=72.0,
             renames=[{"old_key": "barbell row", "old_name": "Barbell Row", "new_name": "Bent Over Row"}],
             prefs=[{"exercise_key": "farmer walk", "is_timed": True}]),
        dict(seed=6, n_workouts=40, bodyweight=81.0),
    ]
    for sc in scenarios:
        logs, final = run_scenario(**sc)
        log_records += logs
        finals.append(final)
    fixtures["log"] = [log_case(r) for r in log_records]

    retrieve_cases = [retrieve_case(r) for r in retrieve_records]
    day_cases = []
    for final in finals:
        plan = get_workout_days(final["effective_plan"])
        for category, days in plan["workout"].items():
            for day_name in days:
                day_cases.append(retrieve_day_case(final, category, day_name.rsplit(" ", 1)[-1]))
        day_cases.append(retrieve_day_case(final, "Nope", 9))
        picks = sorted({log["exercise"] for log in final["logs"]})
        retrieve_cases.append(retrieve_case({"exercises": picks + ["Never Logged", "Dips - [2]", "squat"],
                                             "header_line": f"{TODAY} - Custom Workout",
                                             "set_overrides": {"Squat": 2, "bench press": "5", "x": "bad"}, "state": final}))
        names = sorted({log["exercise"] for log in final["logs"]}) + ["bench-press", "Pushdown", "Nothing"]
        stat_records["chart"] += [{"exercise": n, "state": final} for n in names]
        stat_records["summary"] += [{"exercise": n, "state": final} for n in names]
        stat_records["growth"].append({"state": final})
        stat_records["overall"] += [{"mode": "index", "state": final}, {"mode": "rate", "state": final},
                                    {"mode": "index", "baseline_sessions_target": 2, "min_sessions": 1,
                                     "fade_start_days": 5, "fade_end_days": 20, "state": final}]
    fixtures["retrieve"] = retrieve_cases
    fixtures["retrieve_day"] = day_cases

    describe = list(recorded.get("describe", [])) + [{"output": t} for t in RETRIEVE_TEXTS]
    describe += [{"output": c["output"][0]} for c in retrieve_cases + day_cases]
    fixtures["describe"] = pure_cases("describe", list({json.dumps(d): d for d in describe}.values()))

    fixtures["chart"] = [stats_case("chart", r) for r in stat_records["chart"]]
    fixtures["summary"] = [stats_case("summary", r) for r in stat_records["summary"]]
    fixtures["all_summary"] = [stats_case("all_summary", {"state": f}) for f in finals]
    fixtures["growth"] = [stats_case("growth", r) for r in stat_records["growth"]]
    fixtures["overall"] = [stats_case("overall", r) for r in stat_records["overall"]]

    # The same training history is shared by many cases: keep each one once, in states.json.
    states, state_ids = [], {}
    for cases in fixtures.values():
        for case in cases:
            state = case["input"].get("state")
            if state is None:
                continue
            key = json.dumps(state, sort_keys=True)
            if key not in state_ids:
                state_ids[key] = len(states)
                states.append(state)
            case["input"]["state"] = state_ids[key]
    fixtures["states"] = states

    for old in OUT.glob("*.json"):
        old.unlink()
    for name, cases in fixtures.items():
        path = OUT / f"{name}.json"
        path.write_text(json.dumps({"cases": cases}, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n",
                        encoding="utf-8")
        print(f"  {name}: {len(cases)} cases ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
