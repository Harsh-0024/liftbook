"""Read-only views of one user's training that the AI coach can call as tools.

Every tool takes (db_session, user, **args) and returns a small JSON-able dict. They only ever
query the asking user's rows, never write, and cap what they return so a long history can't
blow up the model's context.
"""
from __future__ import annotations

import difflib
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func

from models import WorkoutLog
from services.bodyweight import effective_sets_for_log
from services.logging import resolve_timed_exercise_status
from services.retrieve import get_effective_plan_text, get_effective_rep_ranges_text
from services.stats import _build_rep_range_map, _resolve_exercise_aliases
from services.workout_title import classify_by_name
from utils.dates import local_today

MAX_ROWS = 40
PLAN_TEXT_LIMIT = 4000
MAX_E1RM_REPS = 12  # rep-max formulas overshoot past this, so ranking counts at most this many


class ToolError(Exception):
    """A tool was called with arguments it can't answer; the message goes back to the model."""


def _iso(value) -> Optional[str]:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def _num(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ToolError(f"Dates must be YYYY-MM-DD, got {value!r}.")


def _clamp(value, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _today() -> date:
    return local_today()


def _sets_text(log: WorkoutLog) -> str:
    try:
        return log.sets_display or ""
    except Exception:
        return ""


def _set_count(log: WorkoutLog) -> int:
    sets = log.sets_json if isinstance(log.sets_json, dict) else {}
    reps = [r for r in (sets.get("reps") or []) if r is not None]
    return len(reps) or (1 if log.top_reps else 0)


def _volume(log: WorkoutLog) -> float:
    """Weight x reps over the logged sets (bodyweight-only sets count as 0)."""
    sets = log.sets_json if isinstance(log.sets_json, dict) else {}
    total = 0.0
    for w, r in zip(sets.get("weights") or [], sets.get("reps") or []):
        try:
            total += float(w or 0) * float(r or 0)
        except (TypeError, ValueError):
            continue
    if not total and log.top_weight and log.top_reps:
        total = float(log.top_weight) * float(log.top_reps)
    return total


def _muscle_group(name: str) -> str:
    groups = classify_by_name(name or "")
    for group in ("Chest", "Back", "Shoulders", "Biceps", "Triceps", "Forearms", "Legs", "Abs"):
        if group in groups:
            return group
    return "Other"


def _logged_names(db_session, user) -> List[str]:
    rows = db_session.query(WorkoutLog.exercise).filter(WorkoutLog.user_id == user.id).distinct().all()
    return [r[0] for r in rows if r and r[0]]


def resolve_exercise(db_session, user, exercise: str) -> List[str]:
    """The logged names that mean this exercise: same words in any order, else the closest spelling."""
    exercise = str(exercise or "").strip()
    if not exercise:
        raise ToolError("Name an exercise.")
    names = _logged_names(db_session, user)
    aliases = [a for a in _resolve_exercise_aliases(db_session, user, exercise) if a in names]
    if aliases:
        return aliases
    lowered = {n.lower(): n for n in names}
    contains = [n for low, n in lowered.items() if exercise.lower() in low]
    if len(contains) == 1:
        return contains
    close = difflib.get_close_matches(exercise.lower(), list(lowered), n=3, cutoff=0.8)  # 0.6 took "bench press" for "Leg Press"
    if close:
        return [lowered[close[0]]]
    words = set(exercise.lower().split())
    sharing = sorted((n for low, n in lowered.items() if words & set(low.split())), key=len)
    hint = contains[:5] or sharing[:5] or [lowered[c] for c in difflib.get_close_matches(exercise.lower(), list(lowered), n=5, cutoff=0.3)]
    suffix = f" Did you mean one of: {', '.join(hint)}?" if hint else " Call list_exercises to see what's logged."
    raise ToolError(f"No logged exercise matches {exercise!r}.{suffix}")


def _logs_query(db_session, user):
    return db_session.query(WorkoutLog).filter(WorkoutLog.user_id == user.id)


def _ranking_e1rm(db_session, log: WorkoutLog) -> float:
    """Best Epley e1RM over the log's sets with reps capped at MAX_E1RM_REPS.

    More weight or more reps never lowers it, but a 20-rep set can't outrank a heavy 5.
    """
    sets = effective_sets_for_log(db_session, log) or {}
    best = 0.0
    for w, r in zip(sets.get("weights") or [], sets.get("reps") or []):
        try:
            best = max(best, float(w) * (1 + min(int(r), MAX_E1RM_REPS) / 30))
        except (TypeError, ValueError):
            continue
    return best or float(log.estimated_1rm or 0)


def _is_timed(db_session, user, name: str) -> bool:
    """Holds like planks log seconds as reps, and their 'e1RM' column is a weight*sqrt(seconds) score."""
    try:
        return bool(resolve_timed_exercise_status(db_session, user.id, name or "", "").get("is_timed"))
    except Exception:
        return False


def _log_row(log: WorkoutLog, timed: bool = False) -> Dict[str, Any]:
    row = {"date": _iso(log.date), "sets": _sets_text(log), "top_weight_kg": _num(log.top_weight)}
    if timed:
        row.update(top_seconds=log.top_reps, hold_score=_num(log.estimated_1rm))
    else:
        row.update(top_reps=log.top_reps, e1rm_kg=_num(log.estimated_1rm))
        if (log.top_reps or 0) > MAX_E1RM_REPS:
            row["e1rm_unreliable"] = True
    if log.uses_bodyweight:
        row["includes_bodyweight"] = True  # top_weight_kg is bodyweight + added load
        if log.bodyweight and log.top_weight:
            # Spelled out: models read a bare flag as "plus bodyweight" on top of the total.
            added = float(log.top_weight) - float(log.bodyweight)
            row["load"] = f"{float(log.top_weight):g} kg total = {float(log.bodyweight):g} kg bodyweight + {added:g} kg added"
    return row


# --- tools ---------------------------------------------------------------------------------

def list_exercises(db_session, user, query: str = "", limit: int = 30) -> Dict[str, Any]:
    limit = _clamp(limit, 1, 80, 30)
    rows = (
        db_session.query(WorkoutLog.exercise, func.count(WorkoutLog.id), func.max(WorkoutLog.date))
        .filter(WorkoutLog.user_id == user.id)
        .group_by(WorkoutLog.exercise)
        .all()
    )
    q = str(query or "").strip().lower()
    items = [
        {"exercise": name, "sessions": count, "last_logged": _iso(last), "muscle_group": _muscle_group(name)}
        for name, count, last in rows
        if name and (not q or q in name.lower() or q == _muscle_group(name).lower())
    ]
    items.sort(key=lambda x: (-x["sessions"], x["exercise"]))
    return {"total_matching": len(items), "exercises": items[:limit]}


def get_exercise_history(db_session, user, exercise: str, limit: int = 12, since_days: int = 0) -> Dict[str, Any]:
    names = resolve_exercise(db_session, user, exercise)
    limit = _clamp(limit, 1, MAX_ROWS, 12)
    q = _logs_query(db_session, user).filter(WorkoutLog.exercise.in_(names))
    since = _clamp(since_days, 0, 3650, 0)
    if since:
        q = q.filter(WorkoutLog.date >= datetime.combine(_today() - timedelta(days=since), datetime.min.time()))
    total = q.count()
    logs = q.order_by(WorkoutLog.date.desc(), WorkoutLog.id.desc()).limit(limit).all()
    timed = _is_timed(db_session, user, names[0])
    return {
        "exercise": names[0],
        "also_logged_as": names[1:],
        "timed_hold": timed,
        "total_sessions": total,
        "sessions_newest_first": [_log_row(l, timed) for l in logs],
    }


def get_personal_records(db_session, user, exercise: str = "", limit: int = 10) -> Dict[str, Any]:
    if exercise:
        names = resolve_exercise(db_session, user, exercise)
        logs = _logs_query(db_session, user).filter(WorkoutLog.exercise.in_(names)).all()
        if not logs:
            raise ToolError(f"Nothing logged for {exercise!r}.")
        best_e1rm = max(logs, key=lambda l: (_ranking_e1rm(db_session, l), l.date))
        heaviest = max(logs, key=lambda l: (float(l.top_weight or 0), int(l.top_reps or 0)))
        most_volume = max(logs, key=_volume)
        timed = _is_timed(db_session, user, names[0])
        return {
            "exercise": names[0],
            "timed_hold": timed,
            ("best_hold_score" if timed else "best_estimated_1rm"): _log_row(best_e1rm, timed),
            "heaviest_top_set": _log_row(heaviest, timed),
            "most_volume_session": {"date": _iso(most_volume.date), "volume_kg": round(_volume(most_volume)), "sets": _sets_text(most_volume)},
            "sessions_logged": len(logs),
        }

    limit = _clamp(limit, 1, 30, 10)
    best: Dict[str, tuple] = {}
    for log in _logs_query(db_session, user).filter(WorkoutLog.estimated_1rm.isnot(None)).all():
        score = _ranking_e1rm(db_session, log)
        cur = best.get(log.exercise)
        if cur is None or score > cur[0]:
            best[log.exercise] = (score, log)
    # Timed holds have no e1RM, so they'd rank on a score in different units.
    ranked = sorted(
        (pair for pair in best.values() if not _is_timed(db_session, user, pair[1].exercise)),
        key=lambda pair: pair[0],
        reverse=True,
    )[:limit]
    return {
        "records_by_estimated_1rm": [
            {"exercise": l.exercise, **_log_row(l), "ranking_e1rm_kg": round(score, 1)} for score, l in ranked
        ],
        "note": f"Ranked by e1RM counting at most {MAX_E1RM_REPS} reps a set; timed holds are left out. "
                "On includes_bodyweight rows top_weight_kg is bodyweight + added load.",
    }


def get_workouts(db_session, user, start_date: str = "", end_date: str = "", limit: int = 5) -> Dict[str, Any]:
    limit = _clamp(limit, 1, 14, 5)
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    q = _logs_query(db_session, user)
    if start:
        q = q.filter(WorkoutLog.date >= datetime.combine(start, datetime.min.time()))
    if end:
        q = q.filter(WorkoutLog.date < datetime.combine(end + timedelta(days=1), datetime.min.time()))

    day_rows = (
        q.with_entities(func.date(WorkoutLog.date)).distinct()
        .order_by(func.date(WorkoutLog.date).desc()).limit(limit).all()
    )
    days = sorted({_parse_date(str(r[0])) for r in day_rows if r and r[0]}, reverse=True)
    out = []
    for d in days:
        logs = (
            _logs_query(db_session, user)
            .filter(WorkoutLog.date >= datetime.combine(d, datetime.min.time()))
            .filter(WorkoutLog.date < datetime.combine(d + timedelta(days=1), datetime.min.time()))
            .order_by(WorkoutLog.id.asc()).all()
        )
        out.append({
            "date": d.isoformat(),
            "title": next((l.workout_name for l in logs if l.workout_name), None),
            "exercises": [{"exercise": l.exercise, "sets": _sets_text(l), "e1rm_kg": _num(l.estimated_1rm)} for l in logs],
        })
    return {"workouts_newest_first": out}


def get_training_summary(db_session, user, days: int = 28) -> Dict[str, Any]:
    days = _clamp(days, 7, 365, 28)
    today = _today()
    start = today - timedelta(days=days - 1)
    logs = (
        _logs_query(db_session, user)
        .filter(WorkoutLog.date >= datetime.combine(start, datetime.min.time()))
        .all()
    )
    trained_days = sorted({l.date.date() for l in logs if isinstance(l.date, datetime)})

    sets_by_group: Counter = Counter()
    sessions_by_exercise: Counter = Counter()
    volume = 0.0
    for log in logs:
        sets_by_group[_muscle_group(log.exercise)] += _set_count(log)
        sessions_by_exercise[log.exercise] += 1
        volume += _volume(log)

    gaps = [(b - a).days for a, b in zip(trained_days, trained_days[1:])]
    last_any = _logs_query(db_session, user).with_entities(func.max(WorkoutLog.date)).scalar()
    weeks = days / 7.0
    out = {
        "window": {"from": start.isoformat(), "to": today.isoformat(), "days": days},
        "workout_days": len(trained_days),
        "workouts_per_week": round(len(trained_days) / weeks, 1),
        "longest_gap_days": max(gaps) if gaps else None,
        "days_since_last_workout": (today - last_any.date()).days if isinstance(last_any, datetime) else None,
        "total_volume_kg": round(volume),
        "weekly_sets_by_muscle_group": {g: round(n / weeks, 1) for g, n in sets_by_group.most_common()},
        "most_trained_exercises": [{"exercise": e, "sessions": n} for e, n in sessions_by_exercise.most_common(10)],
        "muscle_groups_not_trained": [
            g for g in ("Chest", "Back", "Shoulders", "Biceps", "Triceps", "Legs", "Abs") if not sets_by_group.get(g)
        ],
    }
    if not trained_days and isinstance(last_any, datetime):
        # An empty window says nothing about balance or habits; point at the last block instead.
        out["note"] = (f"Nothing logged in this window; the latest workout was {_iso(last_any)}. Call again with "
                       f"days={min(365, days + (today - last_any.date()).days + 60)} to describe their recent training.")
    return out


def get_progress_trend(db_session, user, exercise: str, days: int = 90) -> Dict[str, Any]:
    names = resolve_exercise(db_session, user, exercise)
    days = _clamp(days, 14, 3650, 90)
    start = _today() - timedelta(days=days)
    logs = (
        _logs_query(db_session, user)
        .filter(WorkoutLog.exercise.in_(names))
        .filter(WorkoutLog.estimated_1rm.isnot(None))
        .order_by(WorkoutLog.date.asc())
        .all()
    )
    if not logs:
        raise ToolError(f"No strength data logged for {names[0]}.")
    metric = "hold_score" if _is_timed(db_session, user, names[0]) else "e1rm_kg"

    # One point per day: the day's best e1RM (or hold score).
    per_day: Dict[date, float] = {}
    for log in logs:
        d = log.date.date()
        per_day[d] = max(per_day.get(d, 0.0), float(log.estimated_1rm or 0))
    all_points = sorted(per_day.items())
    points = [(d, v) for d, v in all_points if d >= start]
    if len(points) < 2:
        return {
            "exercise": names[0],
            "note": f"Fewer than two sessions in the last {days} days.",
            "last_session": {"date": all_points[-1][0].isoformat(), metric: round(all_points[-1][1], 1)},
        }

    xs = [(d - points[0][0]).days for d, _ in points]
    ys = [v for _, v in points]
    n = len(points)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs) or 1.0
    slope_per_day = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom

    running_best, last_pr = 0.0, None
    for d, v in all_points:
        if v > running_best:
            running_best, last_pr = v, d
    first, last = points[0], points[-1]
    change_pct = ((last[1] - first[1]) / first[1] * 100.0) if first[1] else None
    # Counted to the latest session, not today, so a break from training doesn't read as a stall.
    weeks_since_pr = (all_points[-1][0] - last_pr).days // 7 if last_pr else None
    return {
        "exercise": names[0],
        "metric": metric,
        "window_days": days,
        "sessions_in_window": n,
        "first": {"date": first[0].isoformat(), metric: round(first[1], 1)},
        "latest": {"date": last[0].isoformat(), metric: round(last[1], 1)},
        "change_pct": round(change_pct, 1) if change_pct is not None else None,
        "trend_kg_per_week": round(slope_per_day * 7, 2),
        "all_time_best": {"date": last_pr.isoformat() if last_pr else None, metric: round(running_best, 1)},
        "weeks_from_best_to_latest_session": weeks_since_pr,
        "days_since_latest_session": (_today() - all_points[-1][0]).days,
        "looks_stalled": bool(weeks_since_pr is not None and weeks_since_pr >= 6 and n >= 4),
        "recent_points": [{"date": d.isoformat(), metric: round(v, 1)} for d, v in points[-12:]],
    }


def review_lifts(db_session, user, days: int = 180, limit: int = 8) -> Dict[str, Any]:
    """Trend for each lift trained regularly in the window, so 'what's stalling?' takes one call.

    At least 90 days: a stall means 6+ weeks without a new best over 4+ sessions, which a shorter
    window can't show, so a model asking about "the last 4 weeks" still gets a real answer.
    """
    days = _clamp(days, 90, 3650, 180)
    limit = _clamp(limit, 1, 15, 8)
    since = datetime.combine(_today() - timedelta(days=days), datetime.min.time())
    rows = (
        db_session.query(WorkoutLog.exercise, func.count(func.distinct(func.date(WorkoutLog.date))))
        .filter(WorkoutLog.user_id == user.id, WorkoutLog.date >= since, WorkoutLog.estimated_1rm.isnot(None))
        .group_by(WorkoutLog.exercise)
        .order_by(func.count(func.distinct(func.date(WorkoutLog.date))).desc())
        .all()
    )
    lifts = []
    for name, sessions in rows:
        if len(lifts) >= limit:
            break
        if sessions < 3 or _is_timed(db_session, user, name):
            continue
        trend = get_progress_trend(db_session, user, name, days=days)
        if "trend_kg_per_week" not in trend:
            continue
        lifts.append({
            "exercise": name,
            "sessions": trend["sessions_in_window"],
            "first": trend["first"],
            "latest": trend["latest"],
            "change_pct": trend["change_pct"],
            "trend_kg_per_week": trend["trend_kg_per_week"],
            "all_time_best": trend["all_time_best"],
            "weeks_from_best_to_latest_session": trend["weeks_from_best_to_latest_session"],
            "looks_stalled": trend["looks_stalled"],
        })
    lifts.sort(key=lambda l: (not l["looks_stalled"], l["trend_kg_per_week"]))
    # A stall comes with what to do about it, so the answer can give targets instead of offering to.
    for lift in [l for l in lifts if l["looks_stalled"]][:4]:
        try:
            nxt = suggest_next_session(db_session, user, lift["exercise"])
            lift["next_session_target"] = {"target": nxt["target"], "rule": nxt["rule"],
                                           "last_session": nxt["last_session"]}
        except ToolError:
            pass
    out = {"window_days": days, "lifts_stalled_first": lifts}
    if not lifts:
        out["note"] = f"No lift was logged 3+ times with weights in the last {days} days; try a longer window."
    return out


def compare_periods(db_session, user, period_days: int = 28, exercise: str = "") -> Dict[str, Any]:
    period_days = _clamp(period_days, 7, 180, 28)
    today = _today()
    cur_start = today - timedelta(days=period_days - 1)
    prev_start = cur_start - timedelta(days=period_days)
    q = _logs_query(db_session, user)
    label = "all exercises"
    if exercise:
        names = resolve_exercise(db_session, user, exercise)
        q = q.filter(WorkoutLog.exercise.in_(names))
        label = names[0]
    logs = q.filter(WorkoutLog.date >= datetime.combine(prev_start, datetime.min.time())).all()

    def summarize(lo: date, hi: date) -> Dict[str, Any]:
        sel = [l for l in logs if lo <= l.date.date() <= hi]
        return {
            "from": lo.isoformat(),
            "to": hi.isoformat(),
            "workout_days": len({l.date.date() for l in sel}),
            "sets": sum(_set_count(l) for l in sel),
            "volume_kg": round(sum(_volume(l) for l in sel)),
            "best_e1rm_kg": _num(max((float(l.estimated_1rm or 0) for l in sel), default=0)) or None,
        }

    out = {
        "scope": label,
        "current": summarize(cur_start, today),
        "previous": summarize(prev_start, cur_start - timedelta(days=1)),
    }
    if not out["current"]["workout_days"]:
        last = q.order_by(WorkoutLog.date.desc()).first()
        if last:
            # Coming back from a break: point the model at their last block rather than an empty window.
            out["note"] = (f"Nothing logged in the current period; the latest workout was {_iso(last.date)}. "
                           "For stalls or progress, use review_lifts (or get_progress_trend) over a longer window, e.g. days=180.")
    return out


def get_plan(db_session, user) -> Dict[str, Any]:
    text = (get_effective_plan_text(db_session, user) or "").strip()
    last_by_title: Dict[str, str] = {}
    rows = (
        _logs_query(db_session, user)
        .with_entities(WorkoutLog.workout_name, func.max(WorkoutLog.date))
        .filter(WorkoutLog.workout_name.isnot(None))
        .group_by(WorkoutLog.workout_name)
        .all()
    )
    for title, last in sorted(rows, key=lambda r: r[1] or datetime.min, reverse=True)[:15]:
        last_by_title[title] = _iso(last)
    return {
        "plan_text": text[:PLAN_TEXT_LIMIT] + ("\n…(truncated)" if len(text) > PLAN_TEXT_LIMIT else ""),
        "last_done_by_workout_title": last_by_title,
    }


DEFAULT_REP_RANGE = (6, 10)


def _session_sets(log: WorkoutLog) -> List[tuple]:
    sets = log.sets_json if isinstance(log.sets_json, dict) else {}
    out = []
    for w, r in zip(sets.get("weights") or [], sets.get("reps") or []):
        try:
            out.append((float(w or 0), int(r)))
        except (TypeError, ValueError):
            continue
    if not out and log.top_reps:
        out.append((float(log.top_weight or 0), int(log.top_reps)))
    return out


def _round_to(value: float, step: float) -> float:
    return round(round(value / step) * step, 2)


def suggest_next_session(db_session, user, exercise: str) -> Dict[str, Any]:
    """Double progression: fill the rep range at a weight, then add weight and start at the bottom.
    Two sessions in a row under the range at the same weight -> a ~10% back-off."""
    names = resolve_exercise(db_session, user, exercise)
    logs = (
        _logs_query(db_session, user).filter(WorkoutLog.exercise.in_(names))
        .order_by(WorkoutLog.date.desc(), WorkoutLog.id.desc()).limit(4).all()
    )
    if not logs:
        raise ToolError(f"Nothing logged for {names[0]}.")

    ranges = _build_rep_range_map(get_effective_rep_ranges_text(db_session, user) or "")
    rep_range = next((ranges[n.lower()] for n in names if n.lower() in ranges), None)
    range_source = "your rep ranges"
    if not rep_range:
        rep_range, range_source = DEFAULT_REP_RANGE, "a default (no rep range set for this exercise)"
    lo, hi = rep_range

    last = _session_sets(logs[0])
    if not last:
        raise ToolError(f"The last {names[0]} session has no sets to work from.")
    top_weight = max(w for w, _ in last)
    working = [r for w, r in last if w == top_weight]
    bodyweight_only = top_weight <= 0

    if bodyweight_only:
        target = {"weight_kg": None, "reps": [r + 1 for r in working]}
        rule = "Bodyweight movement: add a rep to each set."
    elif min(working) >= hi:
        step = 1.0 if top_weight < 20 else 2.5
        target = {"weight_kg": _round_to(top_weight + step, 0.5), "reps": [lo] * len(working)}
        rule = f"Every working set reached the top of the range ({hi}), so add {step:g} kg and restart at {lo} reps."
    else:
        prev = _session_sets(logs[1]) if len(logs) > 1 else []
        prev_top = max((w for w, _ in prev), default=None)
        prev_working = [r for w, r in prev if w == prev_top]
        if max(working) < lo and prev_top == top_weight and prev_working and max(prev_working) < lo:
            target = {"weight_kg": _round_to(top_weight * 0.9, 2.5), "reps": [lo] * len(working)}
            rule = f"Two sessions in a row below {lo} reps at {top_weight:g} kg: back off ~10% and build up again."
        else:
            target = {"weight_kg": top_weight, "reps": [min(r + 1, hi) if r < hi else r for r in working]}
            rule = f"Stay at {top_weight:g} kg and add a rep to sets below {hi}."

    return {
        "exercise": names[0],
        "rep_range": {"low": lo, "high": hi, "source": range_source},
        "last_session": {"date": _iso(logs[0].date), "sets": _sets_text(logs[0])},
        "target": target,
        "rule": rule,
        "recent_sessions": [{"date": _iso(l.date), "sets": _sets_text(l)} for l in logs[1:]],
    }


# --- registry ------------------------------------------------------------------------------

_STR = {"type": "string"}
_INT = {"type": "integer"}

TOOLS: Dict[str, Dict[str, Any]] = {
    "list_exercises": {
        "fn": list_exercises,
        "description": "List the exercises the user has logged, with session counts, last date and muscle group. "
                       "Optional query filters by name substring or muscle group (e.g. 'Back').",
        "parameters": {"type": "object", "properties": {"query": _STR, "limit": _INT}},
    },
    "get_exercise_history": {
        "fn": get_exercise_history,
        "description": "Recent sessions for one exercise (newest first): date, every set, top set and estimated 1RM.",
        "parameters": {"type": "object", "properties": {
            "exercise": _STR, "limit": _INT, "since_days": _INT}, "required": ["exercise"]},
    },
    "get_personal_records": {
        "fn": get_personal_records,
        "description": "Personal records. With an exercise: best e1RM, heaviest top set and biggest-volume session. "
                       "Without: the user's strongest lifts ranked by e1RM.",
        "parameters": {"type": "object", "properties": {"exercise": _STR, "limit": _INT}},
    },
    "get_workouts": {
        "fn": get_workouts,
        "description": "Full workouts (all exercises and sets) grouped by day, newest first, optionally within a "
                       "YYYY-MM-DD date range. Use for 'what did I do on/last ...' questions.",
        "parameters": {"type": "object", "properties": {"start_date": _STR, "end_date": _STR, "limit": _INT}},
    },
    "get_training_summary": {
        "fn": get_training_summary,
        "description": "Training overview for the last N days: workouts per week, gaps, volume, weekly sets per "
                       "muscle group, most trained exercises and neglected muscle groups.",
        "parameters": {"type": "object", "properties": {"days": _INT}},
    },
    "get_progress_trend": {
        "fn": get_progress_trend,
        "description": "Strength trend for one exercise over N days: first vs latest e1RM, % change, kg/week trend "
                       "line, all-time best and whether progress looks stalled.",
        "parameters": {"type": "object", "properties": {"exercise": _STR, "days": _INT}, "required": ["exercise"]},
    },
    "review_lifts": {
        "fn": review_lifts,
        "description": "Progress check on every lift trained regularly in the last N days (default 180, at least 90) in one "
                       "call: per lift first/latest e1RM, % change, kg/week trend, all-time best and looks_stalled. "
                       "Stalled lifts come first, each with its next-session target (weight and reps). Use it for "
                       "'what's stalling / progressing / how are my lifts'.",
        "parameters": {"type": "object", "properties": {"days": _INT, "limit": _INT}},
    },
    "compare_periods": {
        "fn": compare_periods,
        "description": "Compare the last N days with the N days before: workout days, sets, volume, best e1RM. "
                       "Optionally for one exercise.",
        "parameters": {"type": "object", "properties": {"period_days": _INT, "exercise": _STR}},
    },
    "suggest_next_session": {
        "fn": suggest_next_session,
        "description": "Concrete target for the next session of one exercise (weight and reps per set) using double "
                       "progression against the user's rep range. Use for 'what should I aim for/lift next time'.",
        "parameters": {"type": "object", "properties": {"exercise": _STR}, "required": ["exercise"]},
    },
    "get_plan": {
        "fn": get_plan,
        "description": "The user's workout plan text and when each workout title was last done. Use for "
                       "'what should I train today' and programming questions.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def function_declarations() -> List[Dict[str, Any]]:
    out = []
    for name, spec in TOOLS.items():
        decl = {"name": name, "description": spec["description"]}
        if spec["parameters"].get("properties"):
            decl["parameters"] = spec["parameters"]
        out.append(decl)
    return out


def run_tool(db_session, user, name: str, args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    spec = TOOLS.get(name)
    if not spec:
        return {"error": f"Unknown tool {name!r}."}
    fn: Callable[..., Dict[str, Any]] = spec["fn"]
    allowed = set(spec["parameters"].get("properties", {}))
    kwargs = {k: v for k, v in (args or {}).items() if k in allowed and v not in (None, "")}
    try:
        return fn(db_session, user, **kwargs)
    except ToolError as e:
        return {"error": str(e)}
