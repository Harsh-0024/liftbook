"""Golden fixtures for the Supabase Edge Functions (supabase/functions/): what the Python app's AI
coach and note-text cleaning give, so `node --test supabase/functions/test/` can check the
JavaScript gives the same.

- coach tools (services/coach_tools.py) over the generated training histories of
  make_core_fixtures.py, at two "todays": just after the last workout, and months later;
- the coach's prompt, message clean-up, request bodies and reply parsing (services/ai_coach.py);
- note text from Apple Notes and other apps (utils/rich_text.py).

Run from the repo root:

    .venv/bin/python scripts/make_function_fixtures.py
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_core_fixtures as core  # noqa: E402  (sets up a throwaway environment first)

from services import ai_coach, coach_tools  # noqa: E402
from utils.rich_text import to_plain_text  # noqa: E402

OUT = core.ROOT / "supabase" / "functions" / "test" / "fixtures"

SCENARIOS = [
    dict(seed=11, n_workouts=30, bodyweight=78.0),
    dict(seed=12, n_workouts=14, bodyweight=None, own_plan="", own_reps=""),
    dict(seed=13, n_workouts=36, bodyweight=65.5, prefs=[{"exercise_key": "dip", "exercise_name": "Dips",
                                                          "is_bodyweight": False, "source": "manual"},
                                                         {"exercise_key": "plank", "is_timed": False}]),
    dict(seed=14, n_workouts=24, bodyweight=72.0,
         renames=[{"old_key": "barbell row", "old_name": "Barbell Row", "new_name": "Bent Over Row"}],
         prefs=[{"exercise_key": "farmer walk", "is_timed": True}]),
]

ASKED_NAMES = ["bench press", "Bench", "squat", "SQUAT", "benchpress", "pull up", "Plank", "curl", "deadlift",
               "Farmer Walk", "row", "Nothing Like This", "", "lat pulldown", "dips", "Leg Press"]


def tool_calls(names):
    calls = [("list_exercises", {}), ("list_exercises", {"query": "back"}), ("list_exercises", {"query": "squat", "limit": 2}),
             ("list_exercises", {"limit": "3"}), ("list_exercises", {"limit": "lots"}),
             ("get_personal_records", {}), ("get_personal_records", {"limit": 3}),
             ("get_workouts", {}), ("get_workouts", {"limit": 2}), ("get_workouts", {"start_date": "2025-07-01", "end_date": "2025-07-31"}),
             ("get_workouts", {"start_date": "July"}), ("get_workouts", {"end_date": "2025-06-15", "limit": 20}),
             ("get_training_summary", {}), ("get_training_summary", {"days": 7}), ("get_training_summary", {"days": 1000}),
             ("review_lifts", {}), ("review_lifts", {"days": 30, "limit": 3}), ("review_lifts", {"days": 2000}),
             ("compare_periods", {}), ("compare_periods", {"period_days": 90}), ("compare_periods", {"exercise": "squat"}),
             ("get_plan", {}), ("no_such_tool", {}), ("get_exercise_history", {"exercise": "squat", "bogus": 1})]
    for n in names + ASKED_NAMES:
        calls += [("get_exercise_history", {"exercise": n}), ("get_exercise_history", {"exercise": n, "limit": 3, "since_days": 60}),
                  ("get_personal_records", {"exercise": n}), ("get_progress_trend", {"exercise": n}),
                  ("get_progress_trend", {"exercise": n, "days": 3650}), ("suggest_next_session", {"exercise": n}),
                  ("compare_periods", {"exercise": n, "period_days": 14})]
    return calls


def tool_cases(final):
    cases = []
    last = max(datetime.fromisoformat(l["date"]).date() for l in final["logs"])
    names = sorted({l["exercise"] for l in final["logs"]})
    for today in (last + timedelta(days=2), last + timedelta(days=150)):
        with core.State(final) as s:
            saved = (coach_tools._today, coach_tools.get_effective_plan_text, coach_tools.get_effective_rep_ranges_text)
            coach_tools._today = lambda: today
            coach_tools.get_effective_plan_text = lambda db, user: final["effective_plan"]
            coach_tools.get_effective_rep_ranges_text = lambda db, user: final["effective_rep_ranges"]
            try:
                for name, args in tool_calls(names):
                    try:
                        out = coach_tools.run_tool(s.db, s.user, name, args)
                    except TypeError:
                        # A required argument left out: the old app failed the whole answer here.
                        out = {"python_raised": "TypeError"}
                    cases.append({"input": {"tool": name, "args": args, "today": today.isoformat(), "state": final},
                                  "output": core.plain(out)})
            finally:
                coach_tools._today, coach_tools.get_effective_plan_text, coach_tools.get_effective_rep_ranges_text = saved
    return cases


class FixedClock:
    def __init__(self, day):
        self.day = day

    def __call__(self):
        return datetime.combine(self.day, datetime.min.time())


def prompt_cases():
    users = [dict(full_name="Harsh Kumar", username="harsh", bodyweight=78.5), dict(full_name="", username="lifter9", bodyweight=None),
             dict(full_name=None, username=None, bodyweight=80.0)]
    contexts = [{}, {"page": "stats", "exercise": "Squat", "metric": "e1rm", "date": "2026-10-30"}, {"date": "2026-01-01"}]
    cases = []
    saved = ai_coach.utc_now
    try:
        for day in (date(2026, 11, 1), date(2027, 2, 28)):
            ai_coach.utc_now = FixedClock(day)
            for u in users:
                for ctx in contexts:
                    user = type("U", (), u)()
                    cases.append({"input": {"profile": u, "context": ctx, "today": day.isoformat()},
                                  "output": ai_coach.system_prompt(user, ctx)})
    finally:
        ai_coach.utc_now = saved
    return cases


HISTORIES = [
    [{"role": "user", "text": "How is my squat?"}],
    [{"role": "assistant", "text": "Hi!"}, {"role": "user", "text": " a "}, {"role": "user", "text": "b"}],
    [{"role": "model", "text": "x"}, {"role": "assistant", "text": "y"}],
    [{"role": "user", "text": "q" * 2000}, {"role": "assistant", "text": ""}, {"role": "assistant", "text": "answer"},
     {"role": "user", "text": None}, {"role": "user", "text": 42}, "junk", None, {"text": "no role"}],
    [{"role": "user", "text": f"turn {i}"} if i % 2 == 0 else {"role": "assistant", "text": f"reply {i}"} for i in range(20)],
    "not a list",
]

TURNS = [
    {"role": "user", "text": "How is my squat?"},
    {"role": "model", "text": "", "gemini_parts": None,
     "calls": [{"id": "call_a", "native_id": True, "name": "get_progress_trend", "args": {"exercise": "Squat"}},
               {"id": "call_b", "native_id": True, "name": "list_exercises", "args": {}}]},
    {"role": "tool", "results": [{"id": "call_a", "native_id": True, "name": "get_progress_trend", "response": {"trend": 1.5}},
                                 {"id": "call_b", "native_id": True, "name": "list_exercises", "response": {"exercises": []}}]},
    {"role": "model", "text": "Looking", "calls": [{"id": "call_1_0", "native_id": False, "name": "get_plan", "args": {}}],
     "gemini_parts": [{"text": "Looking"}, {"functionCall": {"name": "get_plan", "args": {}}, "thoughtSignature": "sig"}]},
    {"role": "tool", "results": [{"id": "call_1_0", "native_id": False, "name": "get_plan", "response": {"plan_text": "Day 1"}}]},
    {"role": "user", "text": "And bench?"},
]

REPLIES_GEMINI = [
    {"candidates": [{"content": {"parts": [{"text": "Your squat is up **5 kg**."}]}, "finishReason": "STOP"}],
     "usageMetadata": {"totalTokenCount": 321}},
    {"candidates": [{"content": {"parts": [{"text": "0"}, {"text": "oon"}, {"text": "Your bench is stuck."}]}}]},
    {"candidates": [{"content": {"parts": [{"thought": True, "text": "thinking..."}, {"text": "Fine answer here."}]}}]},
    {"candidates": [{"content": {"parts": [{"functionCall": {"name": "get_plan"}},
                                           {"functionCall": {"name": "get_progress_trend", "args": {"exercise": "Squat"}, "id": "g1"}}]}}]},
    {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "MAX_TOKENS"}]},
    {"candidates": []},
    {},
    {"candidates": [{"content": {"parts": [{"functionCall": {"name": "x", "args": [1, 2]}}]}}]},
]

REPLIES_OPENAI = [
    {"choices": [{"message": {"content": "Your squat is up 5 kg."}, "finish_reason": "stop"}], "usage": {"total_tokens": 99}},
    {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "t1", "function": {"name": "get_plan", "arguments": "{}"}},
        {"function": {"name": "get_progress_trend", "arguments": "{\"exercise\": \"Squat\", \"days\": 90}"}},
        {"id": "t3", "function": {"name": "list_exercises", "arguments": "not json"}},
        {"id": "t4", "function": {"name": "list_exercises", "arguments": "[1]"}}]}, "finish_reason": "tool_calls"}]},
    {"choices": []},
    {},
]

TEXTS = ["Your squat is up. Use `suggest_next_session` next, or get_progress_trend.",
         "Ranked by ranking_e1rm_kg and Ranking E1RM; see review_lifts.",
         "On 2026-10-01 and 2026-10-03 (and 2026-10-01 again), 2026-13-99, 1999-01-01, 2026-10-04 2026-10-05 2026-10-06 2026-10-07 2026-10-08",
         "list_exercisesX is not a tool name; get_plan is."]


def coach_cases():
    out = {"prompt": prompt_cases()}
    out["history"] = [{"input": h, "output": ai_coach._clean_history(h)} for h in HISTORIES]
    out["key_provider"] = [{"input": k, "output": ai_coach.key_provider(k)} for k in
                           ["gsk_abc", " gsk_x", "AIzaSy", "", None, "GSK_upper"]]
    orders = []
    for order, preferred in [("", ""), ("groq:a, gemini:b ,c,, bad:d, groq:a", ""), ("", "gemini-x"), ("x:y", "groq:z")]:
        core_cfg = ai_coach.Config
        saved = (getattr(core_cfg, "AI_MODEL_ORDER", ""), getattr(core_cfg, "GEMINI_COACH_MODEL", ""))
        core_cfg.AI_MODEL_ORDER, core_cfg.GEMINI_COACH_MODEL = order, preferred
        try:
            orders.append({"input": {"order": order, "preferred": preferred}, "output": [list(p) for p in ai_coach._model_order()]})
        finally:
            core_cfg.AI_MODEL_ORDER, core_cfg.GEMINI_COACH_MODEL = saved
    out["model_order"] = orders
    out["payload"] = []
    for final in (False, True):
        out["payload"].append({"input": {"kind": "gemini", "final": final, "turns": TURNS},
                               "output": ai_coach._gemini_payload("SYSTEM", TURNS, final)})
        for model in ("openai/gpt-oss-120b", "qwen/qwen3.8-27b"):
            out["payload"].append({"input": {"kind": "openai", "model": model, "final": final, "turns": TURNS},
                                   "output": ai_coach._openai_payload("SYSTEM", TURNS, model, final)})
    out["parse"] = [{"input": {"kind": "gemini", "data": d, "round": 2}, "output": ai_coach._parse_gemini(d, 2)} for d in REPLIES_GEMINI]
    out["parse"] += [{"input": {"kind": "openai", "data": d, "round": 3}, "output": ai_coach._parse_openai(d, 3)} for d in REPLIES_OPENAI]
    out["plain_words"] = [{"input": t, "output": ai_coach._plain_words(t)} for t in TEXTS]
    out["links"] = [{"input": t, "output": [{"label": l["label"], "url": "#" + l["url"]} for l in ai_coach._links_for(t)]} for t in TEXTS]
    return out


RICH_TEXTS = [
    "1/11 Push\nBench Press\n100x5x3",
    "Bench Press 100x5 Squat\r\n120x5\rDeadlift",
    "• Bench Press\n◦ 100x5\n- Squat\n☐ Rows\n✔︎ Curl 20x10",
    "- [ ] Squat 100x5\n- [x] Bench 80x5\n[x] Rows 60x8\n* [ ] Curl",
    "Bench Press   100 x 5\tx3​﻿",
    "<html><head><title>x</title><style>p{}</style></head><body><div>Bench Press</div><div>100x5<br>100x5</div>"
    "<p>Squat &amp; Lunge &nbsp;</p><ul><li>Row</li></ul><script>alert(1)</script></body></html>",
    "<div>Curl</div><!-- comment --><span>20 x 10</span>",
    "Squat &amp; Lunge &#8211; 100x5 &lt;3",
    "No tags here &unknown; just text",
    "{\\rtf1\\ansi\\ansicpg1252\\cocoartf2761\n{\\fonttbl\\f0\\fswiss\\fcharset0 Helvetica;}\n{\\colortbl;\\red255\\green255\\blue255;}\n"
    "\\pard\\tx560\\pardirnatural\\partightenfactor0\n\n\\f0\\fs24 \\cf0 Bench Press\\\n100x5\\par Squat \\'e9t\\'e9\\tab 120x5\\line Curl \\u8211\\'96 20x10\\par\n"
    "{\\*\\expandedcolortbl;;}\\{brace\\} back\\\\slash non\\~break}",
    "   \n\n  Leading and trailing  \n\n",
    "",
    "<b>Bold</b> only",
    "Line one\n\n\nLine  two",
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    finals = []
    for sc in SCENARIOS:
        _, final = core.run_scenario(**sc)
        final["effective_plan"] = sc.get("own_plan", core.SCENARIO_PLAN) or core.DEFAULT_PLAN
        final["effective_rep_ranges"] = sc.get("own_reps", core.SCENARIO_REPS) or core.retrieve._build_default_rep_text()
        finals.append(final)
    states = []
    tools = []
    for final in finals:
        states.append(core.js_state(final))
        for case in tool_cases(final):
            case["input"]["state"] = len(states) - 1
            tools.append(case)
    fixtures = {"coach_states": states, "coach_tools": tools, "rich_text": [{"input": t, "output": to_plain_text(t)} for t in RICH_TEXTS]}
    fixtures["rich_text"].append({"input": {"bytes": list("Curl – 20x10".encode("cp1252"))},
                                  "output": to_plain_text("Curl – 20x10".encode("cp1252"))})
    fixtures["rich_text"].append({"input": {"bytes": list("Curl – 20x10".encode("utf-8"))},
                                  "output": to_plain_text("Curl – 20x10".encode("utf-8"))})
    fixtures.update({f"coach_{k}": v for k, v in coach_cases().items()})
    for name, cases in fixtures.items():
        path = OUT / f"{name}.json"
        path.write_text(json.dumps({"cases": cases}, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
                                   default=str) + "\n", encoding="utf-8")
        print(f"  {name}: {len(cases)} cases ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
