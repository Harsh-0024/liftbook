"""
Workout logging service for processing and saving workout data.
"""
from collections import Counter, defaultdict
from typing import Any, List, Dict, Optional, Tuple
from datetime import datetime, date, timedelta
from utils.dates import local_now
from sqlalchemy import func, or_
import math
import re

from list_of_exercise import get_workout_days
from models import Lift, RepRange, TimedExercisePreference, WorkoutLog
from parsers.workout import (
    TIME_TOKEN,
    is_time_only_exercise,
    align_sets,
    extract_numbers,
    _extract_declared_sets,
    _extract_sets_from_bracket,
    _parse_plan_exercise_line,
)
from services.best_scoring import (
    compare_strength_workouts,
    compare_timed_workouts,
)
from services.helpers import get_set_stats, get_timed_set_stats
from services.rep_ranges import rep_range_names
from services.exercise_rename import apply_renames_to_parsed
from services.bodyweight import (
    effective_sets_for_current,
    effective_sets_for_log,
    has_bodyweight_token,
    is_bodyweight_enabled,
    set_bodyweight_preference,
)
from services.exercise_matching import (
    build_name_index,
    normalize_exercise_name,
    resolve_equivalent_names,
)
from utils.logger import logger


_PERFORMANCE_LABELS: Dict[str, Dict[str, str]] = {
    # Medal tier = which set (strongest / 2nd / 3rd) decided the new best.
    # Load tiers = strength tied, won on weight; shown with the same medals.
    "gold_strength": {"label": "🥇 New best", "short": "New best"},
    "silver_strength": {"label": "🥈 New best", "short": "New best"},
    "bronze_strength": {"label": "🥉 New best", "short": "New best"},
    "gold_load": {"label": "🥇 New best", "short": "New best"},
    "silver_load": {"label": "🥈 New best", "short": "New best"},
    "bronze_load": {"label": "🥉 New best", "short": "New best"},
    "consistent": {"label": "= Matches best", "short": "Matches best"},
    # Below best is the normal state, so the three "off" tiers share one calm label.
    "slightly_off": {"label": "Below best", "short": "Below best"},
    "moderately_off": {"label": "Below best", "short": "Below best"},
    "significantly_off": {"label": "Below best", "short": "Below best"},
    "first_log": {"label": "✦ First log", "short": "First log"},
}

_KNOWN_TIMED_EXERCISES = {
    "plank",
    "dead hang",
    "farmer's walk",
    "trap bar farmer's walk",
    "dumbbell farmer's walk",
    "wall sit",
    "hanging",
}


def _timed_lookup_key(exercise_name: str) -> str:
    normalized = normalize_exercise_name(exercise_name or "")
    return (normalized or "").replace("'", "").strip()


_KNOWN_TIMED_EXERCISE_KEYS = {
    _timed_lookup_key(name) for name in _KNOWN_TIMED_EXERCISES if _timed_lookup_key(name)
}


def _performance_payload(key: str, *, summary_mode: bool = False) -> Dict[str, str]:
    normalized = str(key or "consistent").strip().lower()
    if normalized not in _PERFORMANCE_LABELS:
        normalized = "consistent"

    # Session summary intentionally collapses load tie-break tiers into "Consistent".
    display_key = normalized
    if summary_mode and normalized in {"gold_load", "silver_load", "bronze_load"}:
        display_key = "consistent"

    meta = _PERFORMANCE_LABELS.get(display_key, _PERFORMANCE_LABELS["consistent"])
    return {
        "key": display_key,
        "label": meta["label"],
        "short": meta["short"],
    }


def _rank_vectors_for_sets(sets_json: Dict, *, top_n: int = 3, is_timed: bool = False) -> Dict[str, List[float]]:
    if is_timed:
        result = compare_timed_workouts(sets_json or {}, sets_json or {}, top_n=top_n)
    else:
        result = compare_strength_workouts(sets_json or {}, sets_json or {}, top_n=top_n)
    vectors = result.get("current") or {}
    return {
        "scores": [float(v) for v in (vectors.get("scores") or [])],
        "weights": [float(v) for v in (vectors.get("weights") or [])],
    }


def _lex_compare_desc(left: List[float], right: List[float], *, eps: float = 1e-6) -> int:
    limit = max(len(left), len(right))
    for idx in range(limit):
        lv = float(left[idx]) if idx < len(left) else None
        rv = float(right[idx]) if idx < len(right) else None
        if lv is None and rv is None:
            return 0
        if lv is None:
            return -1
        if rv is None:
            return 1
        if abs(lv - rv) <= eps:
            continue
        return 1 if lv > rv else -1
    return 0


def _first_drop_index(best_scores: List[float], current_scores: List[float], *, top_n: int = 3, eps: float = 1e-6) -> Optional[int]:
    for idx in range(max(1, int(top_n))):
        b = float(best_scores[idx]) if idx < len(best_scores) else 0.0
        c = float(current_scores[idx]) if idx < len(current_scores) else 0.0
        if c + eps < b:
            return idx
        if c > b + eps:
            return None
    return None


def _first_score_diff_index(left_scores: List[float], right_scores: List[float], *, top_n: int = 3, eps: float = 1e-6) -> tuple[Optional[int], int]:
    """
    Compare top-N score vectors and return (first_diff_index, cmp).

    cmp semantics:
    - 1: left wins
    - -1: right wins
    - 0: tied
    """
    n = max(1, int(top_n) if isinstance(top_n, int) and top_n > 0 else 3)
    for idx in range(n):
        lv = float(left_scores[idx]) if idx < len(left_scores) else 0.0
        rv = float(right_scores[idx]) if idx < len(right_scores) else 0.0
        if abs(lv - rv) <= eps:
            continue
        return (idx, 1) if lv > rv else (idx, -1)
    return None, 0


def _set_count_from_sets_json(sets_json: Optional[Dict]) -> int:
    normalized = _normalize_sets(sets_json)
    if not normalized:
        return 0
    return max(len(normalized.get("weights") or []), len(normalized.get("reps") or []))


def _align_sets_to_count(sets_json: Optional[Dict], target_count: int) -> Optional[Dict]:
    normalized = _normalize_sets(sets_json)
    if not normalized:
        return None
    target = int(target_count) if isinstance(target_count, int) and target_count > 0 else 3
    weights, reps = align_sets(
        list(normalized.get("weights") or []),
        list(normalized.get("reps") or []),
        target,
    )
    return {"weights": weights, "reps": reps}


def _raw_set_count_from_exercise_string(exercise_string: str) -> int:
    text = str(exercise_string or "")
    if not text:
        return 0

    lines = [line.strip() for line in text.splitlines() if line and line.strip()]
    if not lines:
        return 0

    max_count = 0
    numeric_lines: List[str] = []
    for line in lines:
        if " - [" in line:
            tail = line.split("]", 1)[1].strip() if "]" in line else ""
            tail = tail.lstrip("-:").strip()
            if tail:
                numeric_lines.append(tail)
            continue
        if re.match(r'^(?:bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|,|-?\d)', line, flags=re.IGNORECASE):
            numeric_lines.append(line)

    for line in numeric_lines:
        x_matches = re.findall(
            r'(?:bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)\s*[x×]\s*(?:\d+)',
            line,
            flags=re.IGNORECASE,
        )
        if x_matches:
            max_count = max(max_count, len(x_matches))
            continue

        if "," in line:
            left, right = line.split(",", 1)
            left_tokens = re.findall(r'(?:bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)', left, flags=re.IGNORECASE)
            right_tokens = re.findall(r'-?\d+(?:\.\d+)?', right)
            max_count = max(max_count, max(len(left_tokens), len(right_tokens)))
            continue

        tokens = re.findall(r'(?:bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)', line, flags=re.IGNORECASE)
        if tokens:
            max_count = max(max_count, len(tokens))

    if max_count <= 0 and len(numeric_lines) >= 2:
        left_tokens = re.findall(r'(?:bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)', numeric_lines[-2], flags=re.IGNORECASE)
        right_tokens = re.findall(r'-?\d+(?:\.\d+)?', numeric_lines[-1])
        max_count = max(max_count, max(len(left_tokens), len(right_tokens)))

    return int(max_count or 0)


def comparison_set_count(sets_json: Optional[Dict], exercise_string: str = "") -> int:
    json_count = _set_count_from_sets_json(sets_json)
    explicit_sets = _extract_explicit_target_sets(exercise_string)
    if isinstance(explicit_sets, int) and explicit_sets > 0:
        return max(explicit_sets, json_count)
    return json_count if json_count > 3 else 3


def _extract_explicit_target_sets(exercise_string: str) -> Optional[int]:
    text = str(exercise_string or "").strip()
    if not text:
        return None
    for raw_line in text.splitlines():
        line = (raw_line or "").strip()
        if not line:
            continue
        bracket_sets = _extract_sets_from_bracket(line)
        if isinstance(bracket_sets, int) and bracket_sets > 0:
            return int(bracket_sets)
        declared_sets, _cleaned = _extract_declared_sets(line)
        if isinstance(declared_sets, int) and declared_sets > 0:
            return int(declared_sets)
    return None


def _parse_plan_target_sets(plan_text: str) -> Dict[str, int]:
    target_counters: Dict[str, Counter] = defaultdict(Counter)
    try:
        plan_data = get_workout_days(plan_text or "")
        workout_map = plan_data.get("workout", {}) if isinstance(plan_data, dict) else {}
    except Exception:
        workout_map = {}

    for category_days in (workout_map or {}).values():
        if not isinstance(category_days, dict):
            continue
        for exercises in category_days.values():
            if not isinstance(exercises, list):
                continue
            for raw_exercise in exercises:
                line = str(raw_exercise or "").strip()
                if not line:
                    continue
                if _extract_sets_from_bracket(line) is None:
                    continue
                parsed = _parse_plan_exercise_line(line)
                declared_sets = parsed.get("declared_sets")
                key = normalize_exercise_name(parsed.get("name") or "")
                if not key or not declared_sets:
                    continue
                target_counters[key][int(declared_sets)] += 1

    resolved: Dict[str, int] = {}
    for key, counter in target_counters.items():
        if not counter:
            continue
        # Pick most-common declared count; if tied, prefer the larger count.
        count = max(counter.items(), key=lambda item: (item[1], item[0]))[0]
        if count > 0:
            resolved[key] = int(count)
    return resolved


def _get_plan_target_sets(db_session, user) -> Dict[str, int]:
    try:
        from services.retrieve import get_effective_plan_text

        plan_text = get_effective_plan_text(db_session, user)
    except Exception:
        return {}
    return _parse_plan_target_sets(plan_text or "")


def resolve_target_sets_for_exercise(
    *,
    exercise_name: str,
    exercise_string: str,
    rep_target_sets: Optional[Dict[str, int]] = None,
    plan_target_sets: Optional[Dict[str, int]] = None,
    inferred_set_count: int = 0,
    default_sets: int = 3,
) -> Tuple[int, bool]:
    """
    Resolve comparison set-target and whether the target is strict.

    Priority:
    1) Explicit declaration in exercise text ([n] / [n, a-b] / "n sets")
    2) Rep-range config set prefix (n, a-b)
    3) Workout-plan declaration ([n])
    4) Inferred set count when > default
    5) Default

    Returns:
        (target_sets, strict_target_sets)
    """
    explicit_sets = _extract_explicit_target_sets(exercise_string)
    inferred = int(inferred_set_count) if isinstance(inferred_set_count, int) else 0
    if isinstance(explicit_sets, int) and explicit_sets > 0:
        return max(int(explicit_sets), inferred), True

    key = normalize_exercise_name(exercise_name or "")
    if key and rep_target_sets:
        # A tagged name ("Preacher Curl (Wellness)") takes its base's rep range set count.
        for name in rep_range_names(exercise_name):
            mapped = rep_target_sets.get(normalize_exercise_name(name))
            if isinstance(mapped, int) and mapped > 0:
                return int(mapped), True

    if key and plan_target_sets:
        mapped = plan_target_sets.get(key)
        if isinstance(mapped, int) and mapped > 0:
            return int(mapped), True

    default_n = int(default_sets) if isinstance(default_sets, int) and default_sets > 0 else 3
    if inferred > default_n:
        return inferred, False
    return default_n, False


def get_plan_target_sets_for_user(db_session, user) -> Dict[str, int]:
    return _get_plan_target_sets(db_session, user)


def parse_rep_target_sets_text(rep_text: str) -> Dict[str, int]:
    return _parse_rep_target_sets(rep_text)


def get_best_log_for_exercise(
    db_session,
    user_id: int,
    exercise_name: str,
    *,
    target_sets: int = 3,
    strict_target_sets: bool = False,
    log_ex_index=None,
    is_timed: bool = False,
) -> Optional[WorkoutLog]:
    """
    Public wrapper so route/UI code can select "best log" using the same
    top-N/strict-set logic as backend comparison flows.
    """
    return _get_best_log(
        db_session,
        user_id,
        exercise_name,
        target_sets=target_sets,
        strict_target_sets=strict_target_sets,
        log_ex_index=log_ex_index,
        is_timed=is_timed,
    )


def _resolve_pointer_target_context(
    db_session,
    user,
    exercise_name: str,
    *,
    exercise_string: str = "",
    sets_json: Optional[Dict] = None,
    rep_target_sets: Optional[Dict[str, int]] = None,
    plan_target_sets: Optional[Dict[str, int]] = None,
    log_ex_index=None,
    is_timed: Optional[bool] = None,
) -> Tuple[int, bool, bool]:
    rep_targets = rep_target_sets
    if rep_targets is None:
        rep_row = db_session.query(RepRange).filter_by(user_id=user.id).first()
        rep_targets = _parse_rep_target_sets(rep_row.text_content if rep_row else "")

    plan_targets = plan_target_sets if plan_target_sets is not None else _get_plan_target_sets(db_session, user)
    inferred_set_count = _set_count_from_sets_json(sets_json) if sets_json else 0
    target_sets, strict_target_sets = resolve_target_sets_for_exercise(
        exercise_name=exercise_name,
        exercise_string=exercise_string,
        rep_target_sets=rep_targets,
        plan_target_sets=plan_targets,
        inferred_set_count=inferred_set_count,
        default_sets=3,
    )
    if is_timed is None:
        is_timed = bool(resolve_timed_exercise_status(
            db_session,
            user.id,
            exercise_name,
            exercise_string,
            log_ex_index=log_ex_index,
        ).get("is_timed"))
    return target_sets, strict_target_sets, is_timed


def refresh_best_lift_pointer(
    db_session,
    user,
    exercise_name: str,
    *,
    exercise_string: str = "",
    sets_json: Optional[Dict] = None,
    rep_target_sets: Optional[Dict[str, int]] = None,
    plan_target_sets: Optional[Dict[str, int]] = None,
    log_ex_index=None,
    lift_ex_index=None,
    is_timed: Optional[bool] = None,
) -> Optional[Lift]:
    # is_timed: pass it when already worked out for this exercise, to skip looking it up again.
    target_sets, strict_target_sets, is_timed = _resolve_pointer_target_context(
        db_session,
        user,
        exercise_name,
        exercise_string=exercise_string,
        sets_json=sets_json,
        rep_target_sets=rep_target_sets,
        plan_target_sets=plan_target_sets,
        log_ex_index=log_ex_index,
        is_timed=is_timed,
    )
    best_log = _get_best_log(
        db_session,
        user.id,
        exercise_name,
        target_sets=target_sets,
        strict_target_sets=strict_target_sets,
        log_ex_index=log_ex_index,
        is_timed=is_timed,
    )
    lift_record = _get_lift_record(db_session, user.id, exercise_name, lift_ex_index=lift_ex_index)
    if lift_record is None:
        lift_record = Lift(user_id=user.id, exercise=exercise_name)
        db_session.add(lift_record)
    lift_record.best_log_id = getattr(best_log, "id", None)
    return lift_record


def refresh_best_lift_pointers(
    db_session,
    user,
    exercise_names,
    *,
    rep_target_sets: Optional[Dict[str, int]] = None,
    plan_target_sets: Optional[Dict[str, int]] = None,
) -> None:
    names = [str(name or "").strip() for name in exercise_names or [] if str(name or "").strip()]
    if not names:
        return

    distinct_logs = (
        db_session.query(WorkoutLog.exercise)
        .filter(WorkoutLog.user_id == user.id)
        .distinct()
        .all()
    )
    log_ex_index = build_name_index([row[0] for row in distinct_logs or []])
    distinct_lifts = (
        db_session.query(Lift.exercise)
        .filter(Lift.user_id == user.id)
        .distinct()
        .all()
    )
    lift_ex_index = build_name_index([row[0] for row in distinct_lifts or []])
    rep_targets = rep_target_sets
    if rep_targets is None:
        rep_row = db_session.query(RepRange).filter_by(user_id=user.id).first()
        rep_targets = _parse_rep_target_sets(rep_row.text_content if rep_row else "")
    plan_targets = plan_target_sets if plan_target_sets is not None else _get_plan_target_sets(db_session, user)

    seen = set()
    for name in names:
        key = normalize_exercise_name(name)
        if key in seen:
            continue
        seen.add(key)
        refresh_best_lift_pointer(
            db_session,
            user,
            name,
            rep_target_sets=rep_targets,
            plan_target_sets=plan_targets,
            log_ex_index=log_ex_index,
            lift_ex_index=lift_ex_index,
        )


def get_best_log_for_exercise_before_date(
    db_session,
    user_id: int,
    exercise_name: str,
    *,
    target_sets: int = 3,
    strict_target_sets: bool = False,
    log_ex_index=None,
    is_timed: bool = False,
    workout_day_start_dt: Optional[datetime] = None,
) -> Optional[WorkoutLog]:
    """
    Public wrapper for selecting "best log before the viewed day" using
    the same top-N/strict-set logic as backend comparison flows.
    """
    return _get_best_log_before_date(
        db_session,
        user_id,
        exercise_name,
        target_sets=target_sets,
        strict_target_sets=strict_target_sets,
        log_ex_index=log_ex_index,
        is_timed=is_timed,
        workout_day_start_dt=workout_day_start_dt,
    )


def classify_exercise_performance(
    db_session,
    user_id: int,
    exercise_name: str,
    current_sets: Optional[Dict],
    *,
    target_sets: int = 3,
    strict_target_sets: bool = False,
    log_ex_index=None,
    is_timed: bool = False,
    current_log_id: Optional[int] = None,
    current_exercise_string: str = "",
    summary_mode: bool = False,
    historical_before_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Classify today's exercise performance against all historical logs of the exercise.

    Ranking uses top-N performance vectors (e1RM for strength, timed score for timed logs)
    and tie-breaks by top-set loads.
    """
    normalized_current = _normalize_sets(current_sets)
    if not normalized_current:
        return _performance_payload("consistent", summary_mode=summary_mode)

    candidates = resolve_equivalent_names(exercise_name, log_ex_index) if log_ex_index else []
    if not candidates:
        candidates = _exercise_candidates(exercise_name)
    if not candidates:
        return _performance_payload("first_log", summary_mode=summary_mode)

    top_n = max(1, int(target_sets) if isinstance(target_sets, int) and target_sets > 0 else 3)
    current_set_count = comparison_set_count(normalized_current, current_exercise_string or "")
    compare_n = top_n
    min_required_sets = top_n
    if strict_target_sets and current_set_count > 0 and current_set_count < top_n:
        # In strict mode, incomplete current sessions should still receive a normal
        # badge by comparing completed sets against historical logs with at least as
        # many sets completed.
        compare_n = current_set_count
        min_required_sets = current_set_count
    logs_query = (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user_id)
        .filter(WorkoutLog.exercise.in_(candidates))
    )
    if historical_before_dt is not None:
        if current_log_id is not None:
            logs_query = logs_query.filter(
                (WorkoutLog.date < historical_before_dt) | (WorkoutLog.id == current_log_id)
            )
        else:
            logs_query = logs_query.filter(WorkoutLog.date < historical_before_dt)
    logs = logs_query.order_by(WorkoutLog.date.asc(), WorkoutLog.id.asc()).all()

    rows: List[Dict[str, Any]] = []
    had_historical_with_sets = False
    for log in logs:
        log_sets = _normalize_sets(effective_sets_for_log(db_session, log))
        if not log_sets:
            continue
        if current_log_id is None or getattr(log, "id", None) != current_log_id:
            had_historical_with_sets = True
        log_set_count = comparison_set_count(log_sets, getattr(log, "exercise_string", "") or "")
        if strict_target_sets and log_set_count < min_required_sets:
            continue
        # Align to the log's own set count (as the best-log lookup does); padding up to
        # compare_n would invent sets the user never did and skew the medal.
        aligned_log_sets = _align_sets_to_count(log_sets, log_set_count) or log_sets
        vectors = _rank_vectors_for_sets(aligned_log_sets, top_n=compare_n, is_timed=is_timed)
        if not vectors.get("scores"):
            continue
        rows.append(
            {
                "id": getattr(log, "id", None),
                "scores": vectors["scores"],
                "weights": vectors["weights"],
                "set_count": log_set_count,
                "date": getattr(log, "date", datetime.min),
                "is_current": False,
            }
        )

    current_row: Optional[Dict[str, Any]] = None
    if current_log_id is not None:
        for row in rows:
            if row.get("id") == current_log_id:
                row["is_current"] = True
                current_row = row
                break

    if current_row is None:
        aligned_current = _align_sets_to_count(normalized_current, max(current_set_count, compare_n)) or normalized_current
        vectors = _rank_vectors_for_sets(aligned_current, top_n=compare_n, is_timed=is_timed)
        if not vectors.get("scores"):
            return _performance_payload("consistent", summary_mode=summary_mode)
        current_row = {
            "id": current_log_id,
            "scores": vectors["scores"],
            "weights": vectors["weights"],
            "date": local_now(),
            "is_current": True,
        }
        rows.append(current_row)

    competitors = [row for row in rows if not row.get("is_current")]
    if not competitors:
        if (
            strict_target_sets
            and current_set_count > 0
            and current_set_count < top_n
            and had_historical_with_sets
        ):
            return {
                "key": "first_log",
                "label": "No Comparable Baseline",
                "short": "No Comparable Baseline",
            }
        return _performance_payload("first_log", summary_mode=summary_mode)

    # Pick the reference workout with the same "best log" rule used everywhere else
    # (_get_best_log / _get_best_log_before_date): outside strict mode, logs that
    # reached the target set count win over shorter logs, so a padded short day
    # never becomes the medal baseline while the "Vs Best" link points elsewhere.
    if not strict_target_sets:
        full_competitors = [row for row in competitors if (row.get("set_count") or 0) >= top_n]
        if full_competitors:
            competitors = full_competitors
    reference_row = max(
        competitors,
        key=lambda row: (
            tuple(row.get("scores") or []),
            tuple(row.get("weights") or []),
            row.get("set_count") or 0,
            row.get("date") or datetime.min,
        ),
    )

    def _result(key: str, diff_idx: Optional[int] = None, vector: str = "scores") -> Dict[str, Any]:
        payload = _performance_payload(key, summary_mode=summary_mode)
        payload["reference_log_id"] = reference_row.get("id")
        # Size of the win/loss on the deciding set, so the UI can say "+4%" / "6% below".
        payload["diff_index"] = diff_idx
        payload["diff_pct"] = None
        if diff_idx is not None:
            cur_vals = current_row.get(vector) or []
            ref_vals = reference_row.get(vector) or []
            cur_val = float(cur_vals[diff_idx]) if diff_idx < len(cur_vals) else 0.0
            ref_val = float(ref_vals[diff_idx]) if diff_idx < len(ref_vals) else 0.0
            if ref_val > 0:
                payload["diff_pct"] = (cur_val - ref_val) / ref_val * 100.0
        return payload

    diff_idx, cmp_to_reference = _first_score_diff_index(
        current_row.get("scores") or [],
        reference_row.get("scores") or [],
        top_n=min(compare_n, 3),
    )

    if cmp_to_reference > 0:
        if diff_idx == 0:
            return _result("gold_strength", diff_idx)
        if diff_idx == 1:
            return _result("silver_strength", diff_idx)
        return _result("bronze_strength", diff_idx)

    if cmp_to_reference < 0:
        if diff_idx == 0:
            return _result("significantly_off", diff_idx)
        if diff_idx == 1:
            return _result("moderately_off", diff_idx)
        return _result("slightly_off", diff_idx)

    current_weights = current_row.get("weights") or []
    reference_weights = reference_row.get("weights") or []
    for idx in range(min(compare_n, 3)):
        current_weight = float(current_weights[idx]) if idx < len(current_weights) else 0.0
        reference_weight = float(reference_weights[idx]) if idx < len(reference_weights) else 0.0
        if current_weight > reference_weight:
            if idx == 0:
                return _result("gold_load", idx, "weights")
            if idx == 1:
                return _result("silver_load", idx, "weights")
            return _result("bronze_load", idx, "weights")

    return _result("consistent")


def _format_sets_display(sets_json):
    """Format sets JSON into display string like '26 x 7, 22.5 x 15'."""
    if not sets_json or not isinstance(sets_json, dict):
        return ""
    
    weights = sets_json.get('weights') or []
    reps = sets_json.get('reps') or []
    
    if not weights and not reps:
        return ""
    
    pairs = []
    for w, r in zip(weights, reps):
        if w is not None and r is not None:
            w_str = f"{w:g}" if isinstance(w, (int, float)) else str(w)
            pairs.append(f"{w_str} x {int(r)}")
    
    return ", ".join(pairs) if pairs else ""


def _format_best_string(record):
    """Format best_string from a record to match the display format."""
    if not record:
        return '-'
    sets_json = getattr(record, 'sets_json', None)
    if sets_json:
        formatted = _format_sets_display(sets_json)
        if formatted:
            return formatted
    best_string = getattr(record, 'best_string', None)
    if best_string:
        return best_string
    exercise_string = getattr(record, 'exercise_string', None)
    if exercise_string:
        return exercise_string
    return '-'


def _exercise_candidates(exercise_name: str) -> List[str]:
    if not exercise_name:
        return []
    name = exercise_name.strip()
    candidates = [
        name,
        name.title(),
        name.replace("'", "’"),
        name.replace("'", "’").title(),
        name.replace("’", "'"),
        name.replace("’", "'").title(),
        name.replace("-", "–"),
        name.replace("–", "-"),
        name.replace("-", " "),
        name.replace("–", " "),
    ]
    return list(dict.fromkeys(candidates))


def _normalize_sets(sets_json: Optional[Dict]) -> Optional[Dict]:
    if not sets_json or not isinstance(sets_json, dict):
        return None
    weights = sets_json.get('weights') or []
    reps = sets_json.get('reps') or []
    try:
        weights = [float(w) for w in weights]
        reps = [int(r) for r in reps]
    except Exception:
        return None
    if not weights and not reps:
        return None
    return {'weights': weights, 'reps': reps}


def _has_time_hint_in_exercise_string(exercise_string: str) -> bool:
    text = str(exercise_string or "")
    if not text:
        return False
    bracket_parts = re.findall(r"\[([^\]]*)\]", text)
    for part in bracket_parts:
        token = str(part or "").strip().lower()
        if not token:
            continue
        if re.search(r"(?:\b(?:s|sec|secs|second|seconds)\b|\d+\s*s(?:ec(?:onds?)?)?\b)", token):
            return True
    # Sets written as times ("60s, 45s", "1:00"), on the lines under the name (a name like
    # "21s Curl" isn't a time).
    return any(TIME_TOKEN.search(line) for line in text.splitlines()[1:])


def _has_time_history(db_session, user_id: int, exercise_name: str, *, log_ex_index=None) -> bool:
    candidates = resolve_equivalent_names(exercise_name, log_ex_index) if log_ex_index else []
    if not candidates:
        candidates = _exercise_candidates(exercise_name)
    if not candidates:
        return False

    # A time hint is a bracket, a digit followed by "s" (60s, 45 sec) or a colon (1:00), so the
    # database skips every log without one (this runs for each exercise on every page and save).
    maybe_timed = [WorkoutLog.exercise_string.like('%[%'), WorkoutLog.exercise_string.like('%:%')]
    maybe_timed += [WorkoutLog.exercise_string.ilike(f'%{digit}s%') for digit in range(10)]
    maybe_timed += [WorkoutLog.exercise_string.ilike(f'%{digit} s%') for digit in range(10)]
    logs = (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user_id)
        .filter(WorkoutLog.exercise.in_(candidates))
        .filter(or_(*maybe_timed))
        .all()
    )
    return any(_has_time_hint_in_exercise_string(getattr(log, 'exercise_string', '')) for log in logs)


def get_timed_exercise_preference(db_session, user_id: int, exercise_name: str) -> Optional[bool]:
    key = _timed_lookup_key(exercise_name)
    if not key:
        return None
    row = (
        db_session.query(TimedExercisePreference)
        .filter(TimedExercisePreference.user_id == user_id)
        .filter(TimedExercisePreference.exercise_key == key)
        .first()
    )
    if not row:
        return None
    return bool(row.is_timed)


def set_timed_exercise_preference(db_session, user_id: int, exercise_name: str, is_timed: bool) -> bool:
    key = _timed_lookup_key(exercise_name)
    if not key:
        return False
    row = (
        db_session.query(TimedExercisePreference)
        .filter(TimedExercisePreference.user_id == user_id)
        .filter(TimedExercisePreference.exercise_key == key)
        .first()
    )
    if row:
        row.is_timed = bool(is_timed)
    else:
        row = TimedExercisePreference(
            user_id=user_id,
            exercise_key=key,
            is_timed=bool(is_timed),
        )
        db_session.add(row)
    return True


def resolve_timed_exercise_status(
    db_session,
    user_id: int,
    exercise_name: str,
    exercise_string: str,
    *,
    log_ex_index=None,
) -> Dict[str, Any]:
    """
    Determine whether an exercise should be treated as timed.

    Priority:
    1) Explicit string hint (e.g. [1, 30-90s])
    2) Stored user preference for this exercise (permanent)
    3) Known timed fallback list (prompts once when first encountered without hint)
    4) Historical timed hint presence
    """
    has_explicit_hint = _has_time_hint_in_exercise_string(exercise_string or "")
    if has_explicit_hint:
        return {"is_timed": True, "prompt_needed": False, "reason": "explicit_hint"}

    pref = get_timed_exercise_preference(db_session, user_id, exercise_name)
    if pref is not None:
        return {"is_timed": bool(pref), "prompt_needed": False, "reason": "stored_preference"}

    key = _timed_lookup_key(exercise_name)
    if key and key in _KNOWN_TIMED_EXERCISE_KEYS:
        return {"is_timed": True, "prompt_needed": True, "reason": "known_timed_fallback"}

    is_timed_from_history = _has_time_history(
        db_session,
        user_id,
        exercise_name,
        log_ex_index=log_ex_index,
    )
    return {
        "is_timed": bool(is_timed_from_history),
        "prompt_needed": False,
        "reason": "time_history" if is_timed_from_history else "default_strength",
    }


def _extract_time_seconds(exercise_string: str, expected_sets: int) -> List[int]:
    text = str(exercise_string or "")
    if not text:
        return []

    lines = [ln.strip() for ln in text.splitlines() if ln and ln.strip()]
    if not lines:
        return []

    for line in lines:
        if ',' in line:
            rhs = line.split(',', 1)[1].strip()
            values = extract_numbers(rhs)
            if values:
                return [max(1, int(round(v))) for v in values]

    numeric_lines = [ln for ln in lines if re.search(r'\d', ln)]
    if len(numeric_lines) >= 2:
        values = extract_numbers(numeric_lines[-1])
        if values:
            return [max(1, int(round(v))) for v in values]

    values = extract_numbers(text)
    if expected_sets > 0 and len(values) == expected_sets * 2:
        latter = values[expected_sets:]
        return [max(1, int(round(v))) for v in latter]

    return []


def _parse_rep_target_sets(rep_text: str) -> Dict[str, int]:
    """Parse 'Exercise: 2, 8-15' style lines into lowercased exercise->set_count."""
    out: Dict[str, int] = {}
    if not rep_text:
        return out
    for raw in (rep_text or "").splitlines():
        line = (raw or "").strip()
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        key = normalize_exercise_name(name or "")
        if not key:
            continue
        value = (value or "").strip()
        m = re.match(r'^(\d+)\s*,', value)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except Exception:
            continue
        if n > 0:
            out[key] = n
    return out


def _get_best_log(
    db_session,
    user_id: int,
    exercise_name: str,
    *,
    target_sets: int = 3,
    strict_target_sets: bool = False,
    log_ex_index=None,
    is_timed: bool = False,
) -> Optional[WorkoutLog]:
    candidates = resolve_equivalent_names(exercise_name, log_ex_index) if log_ex_index else []
    if not candidates:
        candidates = _exercise_candidates(exercise_name)
    if not candidates:
        return None
    logs = (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user_id)
        .filter(WorkoutLog.exercise.in_(candidates))
        .all()
    )
    if not logs:
        return None

    required_sets = int(target_sets) if isinstance(target_sets, int) and target_sets > 0 else 3
    preferred = []
    fallback = []
    for log in logs:
        normalized_sets = _normalize_sets(effective_sets_for_log(db_session, log))
        if not normalized_sets:
            continue
        set_count = comparison_set_count(normalized_sets, getattr(log, "exercise_string", "") or "")
        scoring_sets = _align_sets_to_count(normalized_sets, set_count) or normalized_sets
        vectors = _rank_vectors_for_sets(scoring_sets, top_n=required_sets, is_timed=is_timed)
        scores = vectors.get("scores") or []
        if not scores:
            continue
        rank_key = (tuple(scores), tuple(vectors.get("weights") or []))
        row = (log, rank_key, set_count)
        if set_count >= required_sets:
            preferred.append(row)
        else:
            fallback.append(row)

    pool = preferred if strict_target_sets else (preferred if preferred else fallback)
    if not pool:
        return None

    best_log, _, _ = max(
        pool,
        key=lambda row: (
            row[1],
            row[2],
            getattr(row[0], "date", datetime.min),
        ),
    )
    return best_log


def _get_lift_record(db_session, user_id: int, exercise_name: str, *, lift_ex_index=None) -> Optional[Lift]:
    candidates = resolve_equivalent_names(exercise_name, lift_ex_index) if lift_ex_index else []
    if not candidates:
        candidates = _exercise_candidates(exercise_name)
    if not candidates:
        return None
    matches = db_session.query(Lift).filter(
        Lift.user_id == user_id,
        Lift.exercise.in_(candidates)
    ).all()
    if not matches:
        return None
    for match in matches:
        if match.best_log_id:
            return match
    return matches[0]


def handle_workout_log(db_session, user, parsed_data: Dict) -> List[Dict]:
    """
    Process and save a workout log.
    
    Args:
        db_session: Database session
        user: User object
        parsed_data: Parsed workout data dictionary
        
    Returns:
        List of summary dictionaries for each exercise
    """
    summary = []
    workout_date = parsed_data.get('date') or local_now()
    workout_name = parsed_data.get('workout_name')
    # A "Body Weight - 73 kg" line is that workout's bodyweight; without one, an edited workout
    # keeps the bodyweight it was logged with. The line becomes the current bodyweight only when
    # this is the newest workout: pasting or editing an old one used to reset today's setting.
    workout_bodyweight = parsed_data.get('logged_bodyweight') or getattr(user, "bodyweight", None)
    parsed_bodyweight = parsed_data.get('bodyweight')
    if parsed_bodyweight is not None:
        try:
            parsed_bodyweight = float(parsed_bodyweight)
            if not (math.isfinite(parsed_bodyweight) and 1 <= parsed_bodyweight <= 500):
                raise ValueError("not a bodyweight")
            workout_bodyweight = parsed_bodyweight
            latest = (
                db_session.query(func.max(WorkoutLog.date))
                .filter(WorkoutLog.user_id == user.id)
                .scalar()
            )
            if latest is None or workout_date >= latest:
                user.bodyweight = parsed_bodyweight
                db_session.flush()
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring invalid parsed bodyweight for user %s: %r",
                getattr(user, "username", user.id),
                parsed_data.get('bodyweight'),
            )
    rep_row = db_session.query(RepRange).filter_by(user_id=user.id).first()
    rep_target_sets = _parse_rep_target_sets(rep_row.text_content if rep_row else "")
    plan_target_sets = _get_plan_target_sets(db_session, user)

    # Build indices once per log submission so minimal normalization like hyphen/space
    # and safe word-order swaps can match existing history/Lift rows.
    distinct_logs = (
        db_session.query(WorkoutLog.exercise)
        .filter(WorkoutLog.user_id == user.id)
        .distinct()
        .all()
    )
    log_ex_index = build_name_index([row[0] for row in distinct_logs or []])
    distinct_lifts = (
        db_session.query(Lift.exercise)
        .filter(Lift.user_id == user.id)
        .distinct()
        .all()
    )
    lift_ex_index = build_name_index([row[0] for row in distinct_lifts or []])
    
    if 'exercises' not in parsed_data or not parsed_data['exercises']:
        logger.warning(f"No exercises found in workout data for user {user.username}")
        return summary

    # An exercise the user renamed is saved under its new name, whatever name it came in with.
    apply_renames_to_parsed(db_session, user, parsed_data)

    for item in parsed_data["exercises"]:
        ex_name = item['name']
        new_sets = {"weights": item["weights"], "reps": item["reps"]}
        new_str = item['exercise_string']
        is_valid = item.get('valid', True)
        time_based = False

        timed_status = {"is_timed": False, "prompt_needed": False}
        if is_valid:
            timed_status = resolve_timed_exercise_status(
                db_session,
                user.id,
                ex_name,
                new_str,
                log_ex_index=log_ex_index,
            )
            time_based = bool(timed_status.get("is_timed"))
            current_reps = [int(r) for r in (new_sets.get('reps') or []) if r is not None]
            if time_based and current_reps and all(r <= 1 for r in current_reps):
                seconds = _extract_time_seconds(new_str, expected_sets=len(new_sets.get('weights') or []))
                if seconds:
                    weights, reps = align_sets(
                        list(new_sets.get('weights') or []),
                        [int(v) for v in seconds],
                        len(new_sets.get('weights') or []) or None,
                    )
                    new_sets = {'weights': weights, 'reps': reps}

        inferred_set_count = _set_count_from_sets_json(new_sets)
        target_sets, strict_target_sets = resolve_target_sets_for_exercise(
            exercise_name=ex_name,
            exercise_string=new_str,
            rep_target_sets=rep_target_sets,
            plan_target_sets=plan_target_sets,
            inferred_set_count=inferred_set_count,
            default_sets=3,
        )
        if is_valid and _set_count_from_sets_json(new_sets) > 0:
            aligned_new_sets = _align_sets_to_count(new_sets, target_sets)
            if aligned_new_sets:
                new_sets = aligned_new_sets
        
        uses_bodyweight = bool(
            is_bodyweight_enabled(db_session, user.id, ex_name, exercise_text=new_str)
            or is_time_only_exercise(new_str, item.get('source_name') or ex_name)
        ) if is_valid else False
        if is_valid and has_bodyweight_token(new_str):
            set_bodyweight_preference(
                db_session,
                user.id,
                ex_name,
                True,
                source="auto",
            )
        effective_new_sets = effective_sets_for_current(
            new_sets,
            workout_bodyweight,
            uses_bodyweight,
        )

        # Format display string from sets data
        formatted_display = _format_sets_display(new_sets) if is_valid else new_str

        # 1. Calculate Stats for Today
        p_peak, p_sum, p_vol = get_set_stats(effective_new_sets)

        # Find the heaviest weight used today (for history)
        daily_max_weight = 0
        daily_max_reps = 0
        effective_weights = list((effective_new_sets or {}).get("weights") or [])
        effective_reps = list((effective_new_sets or {}).get("reps") or [])
        if is_valid and effective_weights:
            daily_max_weight = max(effective_weights)
            # Find reps corresponding to that max weight
            idx = effective_weights.index(daily_max_weight)
            daily_max_reps = effective_reps[idx] if idx < len(effective_reps) else 0

        best_log = _get_best_log(
            db_session,
            user.id,
            ex_name,
            target_sets=target_sets,
            strict_target_sets=strict_target_sets,
            log_ex_index=log_ex_index,
            is_timed=time_based,
        )
        best_log_sets = _normalize_sets(effective_sets_for_log(db_session, best_log)) if best_log else None

        row = {
            'name': ex_name, 'old': '-', 'new': formatted_display,
            'status': '-', 'class': 'neutral', 'valid': is_valid,
            'is_timed': time_based if is_valid else False,
            'timed_prompt_needed': bool(timed_status.get("prompt_needed")) if is_valid else False,
            'timed_prompt_exercise': ex_name,
            'performance_key': None,
            'performance_label': None,
        }

        if is_valid:
            if time_based:
                p_peak, p_sum, p_vol = get_timed_set_stats(effective_new_sets)
            # --- SAVE TO HISTORY ---
            history_log = None
            try:
                history_log = WorkoutLog(
                    user_id=user.id,
                    date=workout_date,
                    workout_name=workout_name,
                    exercise=ex_name,
                    exercise_string=new_str,
                    sets_json=new_sets,
                    bodyweight=workout_bodyweight,
                    uses_bodyweight=uses_bodyweight,
                    top_weight=daily_max_weight if daily_max_weight > 0 else None,
                    top_reps=daily_max_reps if daily_max_reps > 0 else None,
                    estimated_1rm=p_peak if p_peak > 0 else None
                )
                db_session.add(history_log)
                db_session.flush()
            except Exception as e:
                logger.error(f"Error creating workout log for {ex_name}: {e}", exc_info=True)
                # Continue processing other exercises even if one fails

            perf = classify_exercise_performance(
                db_session,
                user.id,
                ex_name,
                effective_new_sets,
                target_sets=target_sets,
                strict_target_sets=strict_target_sets,
                log_ex_index=log_ex_index,
                is_timed=time_based,
                current_log_id=(getattr(history_log, 'id', None) if history_log else None),
                current_exercise_string=new_str,
                summary_mode=True,
            )
            row['performance_key'] = perf.get('key')
            row['performance_label'] = perf.get('label')

            improvement = None
            is_new_best = False

            current_count = comparison_set_count(new_sets, new_str)
            can_compare = (not strict_target_sets) or (current_count >= target_sets)

            if best_log_sets and can_compare:
                row['old'] = _format_best_string(best_log)
                if time_based:
                    comparison = compare_timed_workouts(best_log_sets, effective_new_sets, top_n=target_sets)
                else:
                    comparison = compare_strength_workouts(best_log_sets, effective_new_sets, top_n=target_sets)

                # Peak-first, then lexicographic set comparison, then lexicographic weight comparison.
                if comparison.get("cmp", 0) > 0:
                    is_new_best = True
                    if comparison.get("reason") == "peak":
                        diff = float(comparison.get("diff") or 0.0)
                        improvement = f"PEAK (+{diff:.1f})"
                    else:
                        improvement = "CONSISTENCY"
            else:
                if best_log_sets:
                    row['old'] = _format_best_string(best_log)
                    row['status'] = "-"
                    row['class'] = 'neutral'
                    is_new_best = False
                else:
                    row['old'] = 'First Log'
                    row['status'] = "NEW"
                    row['class'] = 'new'
                    is_new_best = True

            if improvement:
                row['status'] = improvement
                row['class'] = 'improved'

            refresh_best_lift_pointer(
                db_session,
                user,
                ex_name,
                exercise_string=new_str,
                sets_json=new_sets,
                rep_target_sets=rep_target_sets,
                plan_target_sets=plan_target_sets,
                log_ex_index=log_ex_index,
                lift_ex_index=lift_ex_index,
                is_timed=time_based,
            )
        else:
            row['status'] = "ERROR"

        summary.append(row)

    return summary


def _get_best_log_before_date(
    db_session,
    user_id: int,
    exercise_name: str,
    *,
    target_sets: int = 3,
    strict_target_sets: bool = False,
    log_ex_index=None,
    is_timed: bool = False,
    workout_day_start_dt: Optional[datetime] = None,
) -> Optional[WorkoutLog]:
    """
    Like `_get_best_log`, but only considers logs strictly before `workout_day_start_dt`.
    Used to recreate "previous best" for the session summary page.
    """
    if workout_day_start_dt is None:
        return None

    candidates = resolve_equivalent_names(exercise_name, log_ex_index) if log_ex_index else []
    if not candidates:
        candidates = _exercise_candidates(exercise_name)
    if not candidates:
        return None

    required_sets = int(target_sets) if isinstance(target_sets, int) and target_sets > 0 else 3

    logs = (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user_id)
        .filter(WorkoutLog.exercise.in_(candidates))
        .filter(WorkoutLog.date < workout_day_start_dt)
        .all()
    )
    if not logs:
        return None

    preferred = []
    fallback = []

    for log in logs:
        normalized_sets = _normalize_sets(effective_sets_for_log(db_session, log))
        if not normalized_sets:
            continue
        set_count = comparison_set_count(normalized_sets, getattr(log, "exercise_string", "") or "")
        scoring_sets = _align_sets_to_count(normalized_sets, set_count) or normalized_sets

        vectors = _rank_vectors_for_sets(scoring_sets, top_n=required_sets, is_timed=is_timed)
        scores = vectors.get("scores") or []
        if not scores:
            continue

        rank_key = (tuple(scores), tuple(vectors.get("weights") or []))
        row = (log, rank_key, set_count)
        if set_count >= required_sets:
            preferred.append(row)
        else:
            fallback.append(row)

    pool = preferred if strict_target_sets else (preferred if preferred else fallback)
    if not pool:
        return None

    best_log, _, _ = max(
        pool,
        key=lambda row: (
            row[1],
            row[2],
            getattr(row[0], "date", datetime.min),
        ),
    )
    return best_log


def compute_workout_summary_for_date(db_session, user, workout_date: date | datetime) -> tuple[list[Dict], int, int]:
    """
    Build per-exercise summary rows (previous best, today, medal) for an already-logged day.
    This recreates the "previous best vs today's performance" session summary without mutating history.
    """
    workout_day = workout_date.date() if isinstance(workout_date, datetime) else workout_date
    workout_day_start_dt = datetime.combine(workout_day, datetime.min.time())
    workout_day_end_dt = workout_day_start_dt + timedelta(days=1)

    logs = (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user.id)
        .filter(WorkoutLog.date >= workout_day_start_dt)
        .filter(WorkoutLog.date < workout_day_end_dt)
        .order_by(WorkoutLog.id)
        .all()
    )
    if not logs:
        return [], 0, 0

    rep_row = db_session.query(RepRange).filter_by(user_id=user.id).first()
    rep_target_sets = _parse_rep_target_sets(rep_row.text_content if rep_row else "")
    plan_target_sets = _get_plan_target_sets(db_session, user)

    distinct_exercises: list[str] = []
    seen: set[str] = set()
    unique_logs: list[WorkoutLog] = []
    for log in logs:
        if log.exercise in seen:
            continue
        seen.add(log.exercise)
        unique_logs.append(log)
        distinct_exercises.append(log.exercise)

    # Use the full user's distinct exercise list for conservative aliasing,
    # matching the behavior of `handle_workout_log`.
    distinct_logs = (
        db_session.query(WorkoutLog.exercise)
        .filter(WorkoutLog.user_id == user.id)
        .distinct()
        .all()
    )
    log_ex_index = build_name_index([row[0] for row in distinct_logs or []])

    summary: list[Dict] = []
    exercise_count = len(unique_logs)
    set_count = 0

    for log in unique_logs:
        ex_name = log.exercise
        raw_new_sets = _normalize_sets(log.sets_json)
        new_sets = _normalize_sets(effective_sets_for_log(db_session, log))
        valid = bool(new_sets)
        timed_status = resolve_timed_exercise_status(
            db_session,
            user.id,
            ex_name,
            getattr(log, "exercise_string", "") or "",
            log_ex_index=log_ex_index,
        )
        time_based = bool(timed_status.get("is_timed"))
        inferred_set_count = _set_count_from_sets_json(new_sets)
        target_sets, strict_target_sets = resolve_target_sets_for_exercise(
            exercise_name=ex_name,
            exercise_string=getattr(log, "exercise_string", "") or "",
            rep_target_sets=rep_target_sets,
            plan_target_sets=plan_target_sets,
            inferred_set_count=inferred_set_count,
            default_sets=3,
        )

        formatted_display = _format_sets_display(raw_new_sets) if raw_new_sets else (getattr(log, "exercise_string", "") or "")

        row = {
            "name": ex_name,
            "old": "-",
            "new": formatted_display,
            "status": "-",
            "class": "neutral",
            "valid": valid,
            "is_timed": time_based if valid else False,
            "timed_prompt_needed": bool(timed_status.get("prompt_needed")) if valid else False,
            "timed_prompt_exercise": ex_name,
            "performance_key": None,
            "performance_label": None,
        }

        if valid:
            perf = classify_exercise_performance(
                db_session,
                user.id,
                ex_name,
                new_sets,
                target_sets=target_sets,
                strict_target_sets=strict_target_sets,
                log_ex_index=log_ex_index,
                is_timed=time_based,
                current_log_id=getattr(log, "id", None),
                current_exercise_string=getattr(log, "exercise_string", "") or "",
                summary_mode=True,
            )
            row["performance_key"] = perf.get("key")
            row["performance_label"] = perf.get("label")

            if time_based:
                p_peak, p_sum, p_vol = get_timed_set_stats(new_sets)
            else:
                p_peak, p_sum, p_vol = get_set_stats(new_sets)

            best_log = _get_best_log_before_date(
                db_session,
                user.id,
                ex_name,
                target_sets=target_sets,
                strict_target_sets=strict_target_sets,
                log_ex_index=log_ex_index,
                is_timed=time_based,
                workout_day_start_dt=workout_day_start_dt,
            )
            best_log_sets = _normalize_sets(effective_sets_for_log(db_session, best_log)) if best_log else None

            current_count = comparison_set_count(new_sets, getattr(log, "exercise_string", "") or "")
            can_compare = (not strict_target_sets) or (current_count >= target_sets)

            if best_log_sets and can_compare:
                row["old"] = _format_best_string(best_log)

                if time_based:
                    comparison = compare_timed_workouts(best_log_sets, new_sets, top_n=target_sets)
                else:
                    comparison = compare_strength_workouts(best_log_sets, new_sets, top_n=target_sets)

                if comparison.get("cmp", 0) > 0:
                    if comparison.get("reason") == "peak":
                        diff = float(comparison.get("diff") or 0.0)
                        row["status"] = f"PEAK (+{diff:.1f})"
                    else:
                        row["status"] = "CONSISTENCY"
                    row["class"] = "improved"
            else:
                if best_log_sets:
                    row["old"] = _format_best_string(best_log)
                    row["status"] = "-"
                    row["class"] = "neutral"
                else:
                    row["old"] = "First Log"
                    row["status"] = "NEW"
                    row["class"] = "new"

            if isinstance(log.sets_json, dict):
                weights = log.sets_json.get("weights") or []
                reps = log.sets_json.get("reps") or []
                try:
                    set_count += max(len(weights), len(reps))
                except Exception:
                    pass

        summary.append(row)

    return summary, exercise_count, set_count
