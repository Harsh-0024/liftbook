"""A pytest plugin for scripts/make_core_fixtures.py: while the normal test suite runs, it notes
every input the suite gives the logic ported to JavaScript, so the golden fixtures cover all of
them. It only records; the tests run exactly as usual (the database is read with autoflush off).

Used as: pytest -p core_fixture_recorder (with scripts/ on PYTHONPATH and
CORE_FIXTURE_RECORD set to the JSON file to write).
"""
import copy
import functools
import json
import os
import sys
import tempfile
import types

# The same isolation as tests/conftest.py, in case anything is imported before it loads.
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: False, find_dotenv=lambda *a, **k: ""))
os.environ.setdefault("DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="core-fixtures-"), "t.db"))

RECORDS = {}
_SEEN = set()


def _note(kind, payload):
    try:
        key = kind + json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        return
    if key in _SEEN:
        return
    _SEEN.add(key)
    RECORDS.setdefault(kind, []).append(payload)


def _plain(value):
    from datetime import date, datetime

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def snapshot(db_session, user):
    """Everything about this user the ported logic reads, as plain data."""
    from models import (
        BodyweightExercisePreference, ExerciseRename, Plan, RepRange, TimedExercisePreference, WorkoutLog,
    )
    from services import retrieve

    with db_session.no_autoflush:
        logs = db_session.query(WorkoutLog).filter(WorkoutLog.user_id == user.id).order_by(WorkoutLog.id).all()
        rep = db_session.query(RepRange).filter_by(user_id=user.id).first()
        plan = db_session.query(Plan).filter_by(user_id=user.id).first()
        return {
            "bodyweight": user.bodyweight,
            "logs": [{
                "id": log.id,
                "date": log.date.isoformat() if log.date else None,
                "workout_name": log.workout_name,
                "exercise": log.exercise,
                "exercise_string": log.exercise_string,
                "sets": _plain(log.sets_json),
                "bodyweight": log.bodyweight,
                "uses_bodyweight": log.uses_bodyweight,
                "top_weight": log.top_weight,
                "top_reps": log.top_reps,
                "estimated_1rm": log.estimated_1rm,
            } for log in logs],
            "bodyweight_prefs": [{
                "exercise_key": p.exercise_key, "exercise_name": p.exercise_name,
                "is_bodyweight": bool(p.is_bodyweight), "source": p.source,
            } for p in db_session.query(BodyweightExercisePreference).filter_by(user_id=user.id).order_by(BodyweightExercisePreference.id)],
            "timed_prefs": [{"exercise_key": p.exercise_key, "is_timed": bool(p.is_timed)}
                            for p in db_session.query(TimedExercisePreference).filter_by(user_id=user.id).order_by(TimedExercisePreference.id)],
            "renames": [{"old_key": r.old_key, "old_name": r.old_name, "new_name": r.new_name}
                        for r in db_session.query(ExerciseRename).filter_by(user_id=user.id).order_by(ExerciseRename.id)],
            "own_rep_ranges": (rep.text_content if rep else "") or "",
            "own_plan": (plan.text_content if plan else "") or "",
            "effective_plan": retrieve.get_effective_plan_text(db_session, user),
            "effective_rep_ranges": retrieve.get_effective_rep_ranges_text(db_session, user),
        }


def _wrap_pure(module, name, kind, to_payload):
    original = getattr(module, name)

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        try:
            payload = to_payload(*args, **kwargs)
            if payload is not None:
                _note(kind, _plain(payload))
        except Exception:
            pass
        return original(*args, **kwargs)

    setattr(module, name, wrapper)


def _wrap_db(module, name, kind, to_payload):
    original = getattr(module, name)

    @functools.wraps(original)
    def wrapper(db_session, user, *args, **kwargs):
        try:
            payload = to_payload(*args, **kwargs)
            if payload is not None and getattr(user, "id", None) is not None and hasattr(db_session, "no_autoflush"):
                payload = dict(_plain(payload), state=snapshot(db_session, user))
                _note(kind, payload)
        except Exception:
            pass
        return original(db_session, user, *args, **kwargs)

    setattr(module, name, wrapper)


def install():
    # Leaf modules first, so modules importing these names get the recording versions.
    import parsers.workout as workout

    def parser_payload(text, bodyweight=None, preserve_bodyweight_offsets=False, now=None):
        if not isinstance(text, str):
            return None
        return {"text": text, "bodyweight": bodyweight, "preserve": bool(preserve_bodyweight_offsets), "now": now}

    _wrap_pure(workout, "workout_parser", "parser", parser_payload)
    _wrap_pure(workout, "_parse_plan_exercise_line", "plan_line", lambda line: {"line": line} if isinstance(line, str) else None)

    import list_of_exercise
    _wrap_pure(list_of_exercise, "get_workout_days", "workout_days", lambda text: {"text": text} if isinstance(text, str) else None)

    from services import exercise_matching
    _wrap_pure(exercise_matching, "normalize_exercise_name", "normalize", lambda name: {"name": name} if isinstance(name, str) else None)
    _wrap_pure(exercise_matching, "same_exercise", "same_exercise",
               lambda a, b: {"a": a, "b": b} if isinstance(a, str) and isinstance(b, str) else None)

    from services import rep_ranges
    _wrap_pure(rep_ranges, "parse_rep_entries", "rep_entries", lambda text: {"text": text} if isinstance(text, str) else None)
    _wrap_pure(rep_ranges, "canonical_rep_text", "rep_canonical", lambda text: {"text": text} if isinstance(text, str) else None)

    from services import logging as logging_service
    _wrap_db(logging_service, "handle_workout_log", "log", lambda parsed: {"parsed": copy.deepcopy(parsed)})

    from services import retrieve
    _wrap_pure(retrieve, "describe_retrieve_output", "describe", lambda output: {"output": output} if isinstance(output, str) else None)
    _wrap_db(retrieve, "_generate_retrieve_output_for_exercises", "retrieve",
             lambda exercises, *, header_line, set_overrides=None: {
                 "exercises": list(exercises or []), "header_line": header_line, "set_overrides": set_overrides})

    from services import stats
    _wrap_db(stats, "get_chart_data", "chart", lambda exercise_name: {"exercise": exercise_name})
    _wrap_db(stats, "get_exercise_summary", "summary", lambda exercise_name: {"exercise": exercise_name})
    _wrap_db(stats, "get_average_growth_data", "growth", lambda: {})
    _wrap_db(stats, "get_overall_progress_data", "overall", lambda mode="index", **kw: {"mode": mode, **kw})


def pytest_configure(config):
    install()


def pytest_unconfigure(config):
    path = os.environ.get("CORE_FIXTURE_RECORD")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(RECORDS, fh, default=str)
