"""
Statistics and data export services for workout tracking.
"""
import csv
import io
import json
import math
import re
from statistics import median
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date, time
from sqlalchemy import func, desc
from models import WorkoutLog, RepRange, StatsExerciseView, StatsPreference
from services.bodyweight import effective_sets_for_log, infer_log_uses_bodyweight
from services.helpers import get_set_stats, timed_set_score
from services.workout_quality import WorkoutQualityScorer
from services.logging import _has_time_hint_in_exercise_string, resolve_timed_exercise_status
from services.exercise_matching import compound_vocabulary, token_signature


STATS_SORT_MODES = {
    "most_viewed",
    "most_trained",
    "recently_trained",
    "alpha_asc",
    "alpha_desc",
}
DEFAULT_STATS_SORT_MODE = "most_viewed"
STATS_RANGES = {"30", "90", "180", "365", "all"}
DEFAULT_STATS_RANGE = "all"
# Re-opening the same exercise within this window counts as one view.
STATS_VIEW_DEDUPE_MINUTES = 30


def get_stats_preferences(db_session, user) -> Dict[str, str]:
    preference = (
        db_session.query(StatsPreference)
        .filter(StatsPreference.user_id == user.id)
        .first()
    )
    mode = str(getattr(preference, "sort_mode", "") or "")
    time_range = str(getattr(preference, "time_range", "") or "")
    return {
        "sort_mode": mode if mode in STATS_SORT_MODES else DEFAULT_STATS_SORT_MODE,
        "range": time_range if time_range in STATS_RANGES else DEFAULT_STATS_RANGE,
    }


def set_stats_preferences(db_session, user, sort_mode: Optional[str] = None, time_range: Optional[str] = None) -> Dict[str, str]:
    """Save whichever of sort mode / time range is given; the other keeps its value."""
    if sort_mode is not None and sort_mode not in STATS_SORT_MODES:
        raise ValueError("Invalid stats sort mode.")
    if time_range is not None and time_range not in STATS_RANGES:
        raise ValueError("Invalid stats time range.")

    preference = (
        db_session.query(StatsPreference)
        .filter(StatsPreference.user_id == user.id)
        .first()
    )
    if preference is None:
        preference = StatsPreference(
            user_id=user.id,
            sort_mode=sort_mode or DEFAULT_STATS_SORT_MODE,
            time_range=time_range or DEFAULT_STATS_RANGE,
        )
        db_session.add(preference)
    else:
        if sort_mode is not None:
            preference.sort_mode = sort_mode
        if time_range is not None:
            preference.time_range = time_range
        preference.updated_at = datetime.now()
    db_session.commit()
    return get_stats_preferences(db_session, user)


def record_stats_exercise_view(db_session, user, exercise_name: str, now: Optional[datetime] = None) -> None:
    key = _normalize_exercise_name(exercise_name, _user_stats_vocabulary(db_session, user))
    if not key:
        return
    now = now or datetime.now()
    view = (
        db_session.query(StatsExerciseView)
        .filter(StatsExerciseView.user_id == user.id, StatsExerciseView.exercise_key == key)
        .first()
    )
    if view is None:
        db_session.add(StatsExerciseView(user_id=user.id, exercise_key=key, view_count=1, last_viewed_at=now))
    else:
        if not view.last_viewed_at or now - view.last_viewed_at >= timedelta(minutes=STATS_VIEW_DEDUPE_MINUTES):
            view.view_count = int(view.view_count or 0) + 1
        view.last_viewed_at = now
    db_session.commit()


def get_stats_exercise_view_counts(db_session, user) -> Dict[str, int]:
    rows = (
        db_session.query(StatsExerciseView.exercise_key, StatsExerciseView.view_count)
        .filter(StatsExerciseView.user_id == user.id)
        .all()
    )
    return {str(key): int(count or 0) for key, count in rows}


def _serialize_sets_json(sets_json) -> str:
    if not sets_json:
        return ""
    if isinstance(sets_json, str):
        return sets_json
    try:
        return json.dumps(sets_json, ensure_ascii=False)
    except Exception:
        return str(sets_json)


def _format_list(values) -> str:
    if not values:
        return ""
    return ",".join(str(v) for v in values if v is not None)


def backfill_log_bodyweight(db_session, user) -> int:
    if not getattr(user, 'bodyweight', None):
        return 0
    return (
        db_session.query(WorkoutLog)
        .filter(
            WorkoutLog.user_id == user.id,
            WorkoutLog.bodyweight.is_(None),
        )
        .update({WorkoutLog.bodyweight: user.bodyweight}, synchronize_session=False)
    )


def _normalize_sets(sets_json) -> List[List[float]]:
    if not sets_json or not isinstance(sets_json, dict):
        return [], []
    weights = sets_json.get('weights') or []
    reps = sets_json.get('reps') or []
    pairs = []
    for w, r in zip(weights, reps):
        if w is None or r is None:
            continue
        try:
            pairs.append((float(w), int(r)))
        except (TypeError, ValueError):
            continue
    if not pairs:
        return [], []
    return [p[0] for p in pairs], [p[1] for p in pairs]


def _log_uses_bw(log) -> bool:
    return bool(getattr(log, "uses_bodyweight", None))


def _apply_bodyweight(weights, reps, bodyweight):
    if bodyweight is None or not reps:
        return weights, reps

    def is_placeholder(weight):
        try:
            return weight is None or float(weight) <= 1
        except (TypeError, ValueError):
            return True

    if not weights:
        return [float(bodyweight)] * len(reps), reps

    if all(is_placeholder(w) for w in weights):
        return [float(bodyweight)] * len(weights), reps

    return weights, reps


def _build_rep_range_map(rep_text: str) -> Dict[str, Tuple[int, int]]:
    mapping: Dict[str, Tuple[int, int]] = {}
    for line in (rep_text or "").splitlines():
        if ':' not in line:
            continue
        k, v = line.split(':', 1)
        key = (k or '').strip().lower()
        value = (v or '').strip()
        if not key or not value:
            continue
        if ',' in value:
            value = value.split(',', 1)[1].strip()
        nums = re.findall(r'\d+', value)
        if len(nums) >= 2:
            mapping[key] = (int(nums[0]), int(nums[1]))
        elif len(nums) == 1:
            n = int(nums[0])
            mapping[key] = (n, n)
    return mapping


def _get_target_rep_range(db_session, user, exercise_name: str) -> Optional[Tuple[int, int]]:
    rep_row = db_session.query(RepRange).filter_by(user_id=user.id).first()
    rep_text = rep_row.text_content if rep_row else ""
    rep_map = _build_rep_range_map(rep_text)
    return rep_map.get((exercise_name or '').strip().lower())


def _normalize_sets_for_log(db_session, log):
    weights, reps = _normalize_sets(effective_sets_for_log(db_session, log))
    if weights and reps:
        return {"weights": weights, "reps": reps}
    return {}


def _get_top_weight(weights, reps):
    if not weights or not reps:
        return 0, 0
    top_weight = max(weights)
    try:
        idx = weights.index(top_weight)
        top_reps = reps[idx] if idx < len(reps) else reps[0]
    except Exception:
        top_reps = reps[0] if reps else 0
    return top_weight, top_reps


def _get_log_metrics(db_session, log):
    weights, reps = _normalize_sets(effective_sets_for_log(db_session, log))

    if (not weights or not reps) and log.top_weight is not None and log.top_reps is not None:
        weights = [float(log.top_weight)]
        reps = [int(log.top_reps)]

    if weights and reps:
        peak, _, _ = get_set_stats({'weights': weights, 'reps': reps})
        top_weight, top_reps = _get_top_weight(weights, reps)
        if not peak and log.estimated_1rm:
            peak = float(log.estimated_1rm)
        return peak, top_weight, top_reps

    return (
        float(log.estimated_1rm) if log.estimated_1rm else 0,
        float(log.top_weight) if log.top_weight else 0,
        int(log.top_reps) if log.top_reps else 0,
    )


def _is_timed_log(log) -> bool:
    """
    Check if a log is for a seconds/time-based exercise.

    Historically we relied on a narrow `[N-Ns]` pattern inside `exercise_string`.
    Some logs may contain non-standard dash encodings, so we also:
    - detect any bracket that contains a trailing `s` after digits
    - fall back to keyword matching on `log.exercise` for known timed movements
    """
    exercise_string = str(getattr(log, 'exercise_string', '') or '')
    exercise_name = str(getattr(log, 'exercise', '') or '')

    bracket_parts = re.findall(r"\[([^\]]*)\]", exercise_string)
    for part in bracket_parts:
        token = str(part or "").strip().lower()
        if not token:
            continue
        if re.search(r"(?:\b(?:s|sec|secs|second|seconds)\b|\d+\s*s(?:ec(?:onds?)?)?\b)", token):
            return True

    name = exercise_name.lower()
    # Keyword fallback for common seconds-based movements.
    timed_name_patterns = [
        r"\bdead\s*hang\b",
        r"\bplank\b",
        r"\bforearm\s*roller\b",
        # farmer's walk variants (including trap bar)
        r"\b(?:trap\s*bar\s*)?farmer(?:[’']\s*s)?\s*walk\b",
        r"\b(?:trap\s*bar\s*)?farmers?\s*walk\b",
    ]
    return bool(re.search("|".join(timed_name_patterns), name, flags=re.IGNORECASE))


def _get_timed_target_range(db_session, user, exercise_name: str) -> Optional[Tuple[int, int]]:
    """Like _get_target_rep_range but treats the values as seconds."""
    return _get_target_rep_range(db_session, user, exercise_name)


def _clean_exercise_text(exercise: str) -> str:
    value = str(exercise or '').strip().lower()
    value = re.sub(r'^\s*\d+\s*[\.)\-:]\s*', '', value)
    value = re.sub(r'[-–—]+', ' ', value)
    value = re.sub(r'[^a-z0-9\s]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def stats_vocabulary(names) -> frozenset:
    """The words in a user's exercise names, so "Push Down" groups with a logged "Pushdown"."""
    return compound_vocabulary(_clean_exercise_text(n) for n in names or [])


def _normalize_exercise_name(exercise: str, vocabulary=None) -> str:
    """The key an exercise is grouped under: its words in any order. Pass the user's
    stats_vocabulary to also count a word written as one or two alike."""
    value = _clean_exercise_text(exercise)
    signature = token_signature(value, vocabulary)
    return ' '.join(signature) if signature else value


def _user_stats_vocabulary(db_session, user) -> frozenset:
    rows = db_session.query(WorkoutLog.exercise).filter(WorkoutLog.user_id == user.id).distinct().all()
    return stats_vocabulary(r[0] for r in rows)


def _clean_workout_title(title: str) -> str:
    cleaned = str(title or "").strip()
    return cleaned or "Workout"


def _resolve_exercise_aliases(db_session, user, exercise_name: str) -> List[str]:
    exercises = (
        db_session.query(WorkoutLog.exercise)
        .filter(WorkoutLog.user_id == user.id)
        .distinct()
        .all()
    )
    vocabulary = stats_vocabulary([ex[0] for ex in exercises] + [exercise_name])
    key = _normalize_exercise_name(exercise_name, vocabulary)
    if not key:
        return []
    aliases = [ex[0] for ex in exercises if _normalize_exercise_name(ex[0], vocabulary) == key]
    return aliases or [exercise_name]


def _get_peak_1rm_for_log(db_session, log=None) -> float:
    if log is None:
        log = db_session
        db_session = None
    weights, reps = _normalize_sets(effective_sets_for_log(db_session, log))

    if (not weights or not reps) and log.top_weight is not None and log.top_reps is not None:
        weights = [float(log.top_weight)]
        reps = [int(log.top_reps)]

    if not weights or not reps:
        return float(log.estimated_1rm) if getattr(log, 'estimated_1rm', None) else 0.0

    if _is_timed_log(log):
        return max(
            (timed_set_score(w, r) for w, r in zip(weights, reps) if w > 0 and r > 0),
            default=0.0,
        )

    quality = WorkoutQualityScorer.calculate_workout_score({'weights': weights, 'reps': reps}, None)
    return float(quality.get('peak_1rm') or 0.0)


def _export_query(db_session, user, start_date: Optional[date] = None, end_date: Optional[date] = None):
    query = db_session.query(WorkoutLog).filter_by(user_id=user.id)

    if start_date is not None:
        start_dt = datetime.combine(start_date, time.min)
        query = query.filter(WorkoutLog.date >= start_dt)

    if end_date is not None:
        end_dt_exclusive = datetime.combine(end_date + timedelta(days=1), time.min)
        query = query.filter(WorkoutLog.date < end_dt_exclusive)

    return query


def _query_logs_for_export(db_session, user, start_date: Optional[date] = None, end_date: Optional[date] = None):
    return _export_query(db_session, user, start_date, end_date).order_by(desc(WorkoutLog.date)).all()


def get_export_log_count(db_session, user, start_date: Optional[date] = None, end_date: Optional[date] = None) -> int:
    # Counted by the database: loading the whole history just to count it doubled an export's work.
    return _export_query(db_session, user, start_date, end_date).count()


def timed_checker(db_session, user):
    """Whether a log's reps are seconds (Plank, Dead Hang, a "[30-60s]" target), asking the
    database once per exercise name."""
    by_name: Dict[str, bool] = {}

    def is_timed(log) -> bool:
        if _has_time_hint_in_exercise_string(log.exercise_string or ''):
            return True
        name = log.exercise or ''
        if name not in by_name:
            by_name[name] = bool(resolve_timed_exercise_status(db_session, user.id, name, '').get('is_timed'))
        return by_name[name]

    return is_timed


def get_csv_export(db_session, user, start_date: Optional[date] = None, end_date: Optional[date] = None, is_timed=None):
    """Generates a CSV string of all workout history."""
    logs = _query_logs_for_export(db_session, user, start_date=start_date, end_date=end_date)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        'Date',
        'Workout Name',
        'Exercise',
        'Exercise String',
        'Weights',
        'Reps',
        'Sets JSON',
        'Top Weight (kg)',
        'Top Reps',
        'Estimated 1RM (kg)',
        # For bodyweight exercises the weights above are added to (or taken off) bodyweight.
        'Uses Bodyweight',
        'Bodyweight (kg)',
        # For timed exercises the reps are seconds.
        'Timed',
    ])
    is_timed = is_timed or timed_checker(db_session, user)

    for log in logs:
        sets_json = log.sets_json if isinstance(log.sets_json, dict) else {}
        weights = sets_json.get('weights') if isinstance(sets_json, dict) else None
        reps = sets_json.get('reps') if isinstance(sets_json, dict) else None
        writer.writerow([
            log.date.isoformat() if log.date else "",
            log.workout_name or "",
            log.exercise or "",
            log.exercise_string or "",
            _format_list(weights),
            _format_list(reps),
            _serialize_sets_json(log.sets_json),
            log.top_weight if log.top_weight is not None else "",
            log.top_reps if log.top_reps is not None else "",
            f"{log.estimated_1rm:.2f}" if log.estimated_1rm is not None else "",
            "yes" if log.uses_bodyweight else ("no" if log.uses_bodyweight is not None else ""),
            log.bodyweight if log.bodyweight is not None else "",
            "yes" if is_timed(log) else "no",
        ])

    return output.getvalue()


def get_json_export(db_session, user, start_date: Optional[date] = None, end_date: Optional[date] = None, is_timed=None) -> Dict:
    """Generate full JSON export payload for workout history."""
    logs = _query_logs_for_export(db_session, user, start_date=start_date, end_date=end_date)

    workouts_by_date: Dict[str, Dict] = {}
    is_timed = is_timed or timed_checker(db_session, user)
    for log in logs:
        date_key = log.date.strftime('%Y-%m-%d') if log.date else ""
        entry = {
            'id': log.id,
            'date': log.date.isoformat() if log.date else None,
            'workout_name': log.workout_name,
            'exercise': log.exercise,
            'exercise_string': log.exercise_string,
            'sets_json': log.sets_json,
            'top_weight': log.top_weight,
            'top_reps': log.top_reps,
            'estimated_1rm': log.estimated_1rm,
            # For bodyweight exercises the weights are added to (or taken off) bodyweight.
            'uses_bodyweight': log.uses_bodyweight,
            'bodyweight': log.bodyweight,
            # For timed exercises the reps are seconds.
            'timed': is_timed(log),
        }
        workouts_by_date.setdefault(date_key, {'date': date_key, 'entries': []})['entries'].append(entry)

    return {
        'user': user.username,
        'export_date': datetime.now().isoformat(),
        'workouts': list(workouts_by_date.values()),
    }


def _any_log_is_timed(db_session, user, logs) -> bool:
    """Whether any of these logs is a timed exercise. Apart from a time written in a log's own
    text, the answer only depends on the exercise name, so the database is asked once per name
    instead of once per session (a long history made the chart slow to load)."""
    if any(_has_time_hint_in_exercise_string(getattr(log, 'exercise_string', '') or '') for log in logs):
        return True
    names = dict.fromkeys(getattr(log, 'exercise', '') or '' for log in logs)
    return any(
        resolve_timed_exercise_status(db_session, user.id, name, '').get("is_timed")
        for name in names
    )


def get_chart_data(db_session, user, exercise_name):
    """Fetches date vs 1RM data for a specific exercise with additional metrics."""
    aliases = _resolve_exercise_aliases(db_session, user, exercise_name)
    if not aliases:
        logs = []
    else:
        logs = db_session.query(WorkoutLog).filter(
            WorkoutLog.user_id == user.id,
            WorkoutLog.exercise.in_(aliases)
        ).order_by(WorkoutLog.date).all()

    labels = []
    data_1rm = []
    data_weight = []
    data_reps = []
    data_volume = []
    data_effective_volume = []
    data_quality = []
    data_quality_adjusted_1rm = []
    # For bodyweight exercises, the top set as logged: 14 for "BW+14" (None for others).
    data_bodyweight_offset = []
    workout_titles = []

    target_rep_range = _get_target_rep_range(db_session, user, exercise_name)

    exercise_is_timed = _any_log_is_timed(db_session, user, logs)

    if exercise_is_timed:
        timed_target = _get_timed_target_range(db_session, user, exercise_name)
    else:
        timed_target = None

    for log in logs:
        label = log.date.date().isoformat() if log.date else ""
        title = _clean_workout_title(getattr(log, 'workout_name', None))

        sets_for_quality = _normalize_sets_for_log(db_session, log)

        if exercise_is_timed:
            quality = WorkoutQualityScorer.calculate_timed_workout_score(sets_for_quality, timed_target)
            e1rm = quality.get('peak_1rm') or 0
        else:
            one_rm, top_weight_m, top_reps_m = _get_log_metrics(db_session, log)
            quality = WorkoutQualityScorer.calculate_workout_score(sets_for_quality, target_rep_range)
            e1rm = quality.get('peak_1rm') or one_rm

        top_weight, top_reps = 0, 0
        weights_raw, reps_raw = _normalize_sets(effective_sets_for_log(db_session, log))
        if weights_raw and reps_raw:
            top_weight, top_reps = _get_top_weight(weights_raw, reps_raw)
        elif log.top_weight is not None:
            top_weight = float(log.top_weight)
            top_reps = int(log.top_reps or 0)

        total_vol = quality.get('total_volume') or 0
        eff_vol = quality.get('effective_volume') or 0
        q_index = quality.get('quality_index') or 0

        offset = None
        if getattr(log, 'uses_bodyweight', None) and log.bodyweight and top_weight:
            offset = round(float(top_weight) - float(log.bodyweight), 2)
        point = (float(e1rm or 0), float(top_weight or 0), int(top_reps or 0),
                 float(q_index) * 100.0, float(e1rm or 0) * float(q_index or 0), offset)
        if label and labels and labels[-1] == label:
            # The same exercise twice in a day (or under two of its names) is one point:
            # the stronger entry, with the day's volume added up.
            data_volume[-1] += float(total_vol or 0)
            data_effective_volume[-1] += float(eff_vol or 0)
            if point[0] <= data_1rm[-1]:
                continue
            for series in (data_1rm, data_weight, data_reps, data_quality, data_quality_adjusted_1rm,
                           data_bodyweight_offset):
                series.pop()
        else:
            labels.append(label)
            workout_titles.append(title)
            data_volume.append(float(total_vol or 0))
            data_effective_volume.append(float(eff_vol or 0))
        data_1rm.append(point[0])
        data_weight.append(point[1])
        data_reps.append(point[2])
        data_quality.append(point[3])
        data_quality_adjusted_1rm.append(point[4])
        data_bodyweight_offset.append(point[5])

    # Calculate statistics
    stats = {}
    if data_1rm:
        stats = {
            'current_1rm': data_1rm[-1] if data_1rm else 0,
            'max_1rm': max(data_1rm) if data_1rm else 0,
            'min_1rm': min(data_1rm) if data_1rm else 0,
            'improvement': data_1rm[-1] - data_1rm[0] if len(data_1rm) > 1 else 0,
            'improvement_pct': ((data_1rm[-1] - data_1rm[0]) / data_1rm[0] * 100) if len(data_1rm) > 1 and data_1rm[0] > 0 else 0
        }

    return {
        "labels": labels,
        "data": data_1rm,
        "workout_days": labels,
        "weight": data_weight,
        "reps": data_reps,
        "bodyweight_offset": data_bodyweight_offset,
        "volume": data_volume,
        "effective_volume": data_effective_volume,
        "quality": data_quality,
        "quality_adjusted_1rm": data_quality_adjusted_1rm,
        "workout_titles": workout_titles,
        "is_timed": exercise_is_timed,
        "series": {
            "e1rm": data_1rm,
            "top_weight": data_weight,
            "top_reps": data_reps,
            "tonnage": data_volume,
            "effective_tonnage": data_effective_volume,
            "quality": data_quality,
            "quality_adjusted_1rm": data_quality_adjusted_1rm,
        },
        "exercise": exercise_name,
        "stats": stats
    }


def get_exercise_summary(db_session, user, exercise_name: str) -> Dict:
    """Get summary statistics for a specific exercise."""
    logs = db_session.query(WorkoutLog).filter(
        WorkoutLog.user_id == user.id,
        WorkoutLog.exercise == exercise_name
    ).order_by(WorkoutLog.date).all()

    if not logs:
        return {}

    metrics = []
    for log in logs:
        one_rm, top_weight, top_reps = _get_log_metrics(db_session, log)
        metrics.append((log, one_rm, top_weight, top_reps))

    first_log, first_1rm, _, _ = metrics[0]
    latest_log, latest_1rm, _, _ = metrics[-1]

    # Calculate PRs
    max_1rm_log, max_1rm_value, _, _ = max(metrics, key=lambda x: x[1])
    max_weight_log, _, max_weight_value, max_weight_reps = max(metrics, key=lambda x: x[2])

    return {
        'total_sessions': len(logs),
        'first_date': first_log.date,
        'latest_date': latest_log.date,
        'current_1rm': latest_1rm or 0,
        'pr_1rm': max_1rm_value or 0,
        'pr_weight': max_weight_value or 0,
        'pr_reps': max_weight_reps or 0,
        'pr_date': max_1rm_log.date,
        'improvement': (latest_1rm or 0) - (first_1rm or 0),
        'improvement_pct': ((latest_1rm or 0) - (first_1rm or 0)) / (first_1rm or 1) * 100 if first_1rm else 0
    }


def get_average_growth_data(db_session, user) -> Dict:
    """Aggregate average percent change per exercise across dates (normalized)."""
    logs = db_session.query(WorkoutLog).filter(
        WorkoutLog.user_id == user.id,
    ).order_by(WorkoutLog.date).all()

    if not logs:
        return {
            "labels": [],
            "data": [],
            "workout_days": [],
            "weight": [],
            "reps": [],
            "exercise": "Overall Progress",
            "stats": {},
            "unit": "percent",
        }

    logs_by_exercise = {}
    title_by_date = {}
    vocabulary = stats_vocabulary({log.exercise for log in logs})
    for log in logs:
        key = _normalize_exercise_name(log.exercise, vocabulary)
        if not key:
            continue
        if log.date:
            date_key = log.date.date()
            title_by_date.setdefault(date_key, _clean_workout_title(getattr(log, 'workout_name', None)))
        logs_by_exercise.setdefault(key, []).append(log)

    by_date = {}
    for exercise_logs in logs_by_exercise.values():
        # A day's best for the exercise, so a lighter second entry that day doesn't pull it down.
        best_by_day = {}
        for log in exercise_logs:
            if not log.date:
                continue
            one_rm = _get_peak_1rm_for_log(db_session, log)
            if not one_rm or one_rm <= 0:
                continue
            date_key = log.date.date()
            best_by_day[date_key] = max(best_by_day.get(date_key, 0.0), float(one_rm))

        if not best_by_day:
            continue
        base = best_by_day[min(best_by_day)]

        for date_key, one_rm in best_by_day.items():
            pct_change = ((one_rm - base) / base) * 100.0
            pct_change = max(-300.0, min(300.0, pct_change))
            entry = by_date.setdefault(date_key, {'weighted_sum': 0.0, 'weight_sum': 0.0})
            entry['weighted_sum'] += pct_change * base
            entry['weight_sum'] += base

    if not by_date:
        return {
            "labels": [],
            "data": [],
            "workout_days": [],
            "weight": [],
            "reps": [],
            "exercise": "Overall Progress",
            "stats": {},
            "unit": "percent",
        }

    labels = []
    data_pct = []
    workout_titles = []

    for date_key in sorted(by_date.keys()):
        values = by_date[date_key]
        labels.append(date_key.isoformat())
        workout_titles.append(title_by_date.get(date_key, "Workout"))
        weight_sum = values.get('weight_sum', 0.0)
        if weight_sum:
            data_pct.append(values.get('weighted_sum', 0.0) / weight_sum)
        else:
            data_pct.append(0)

    stats = {}
    if any(value != 0 for value in data_pct):
        avg_pct = sum(data_pct) / len(data_pct) if data_pct else 0
        stats = {
            'current_1rm': data_pct[-1] if data_pct else 0,
            'max_1rm': max(data_pct) if data_pct else 0,
            'min_1rm': min(data_pct) if data_pct else 0,
            'improvement': data_pct[-1] - data_pct[0] if len(data_pct) > 1 else 0,
            'improvement_pct': avg_pct,
        }

    return {
        "labels": labels,
        "data": data_pct,
        "workout_days": labels,
        "weight": [],
        "reps": [],
        "exercise": "Overall Progress",
        "stats": stats,
        "unit": "percent",
        "workout_titles": workout_titles,
    }


def _date_range(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _fade_multiplier(days_since_last: int, fade_start_days: int, fade_end_days: int) -> float:
    if days_since_last <= fade_start_days:
        return 1.0
    if days_since_last >= fade_end_days:
        return 0.0
    span = float(fade_end_days - fade_start_days)
    return max(0.0, min(1.0, (fade_end_days - float(days_since_last)) / span))


def _logged_set_count(log) -> int:
    """How many sets a log holds (at least 1), for how full a day looks in Consistency."""
    data = getattr(log, 'sets_json', None)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            data = None
    if isinstance(data, dict):
        for key in ('reps', 'weights'):
            values = data.get(key)
            if isinstance(values, list) and values:
                return len(values)
    return 1


def get_overall_progress_data(
    db_session,
    user,
    mode: str = 'index',
    baseline_sessions_target: int = 5,
    min_sessions: int = 3,
    fade_start_days: int = 60,
    fade_end_days: int = 90,
) -> Dict:
    logs = (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user.id)
        .order_by(WorkoutLog.date)
        .all()
    )

    if not logs:
        return {
            'labels': [],
            'data': [],
            'log_data': [],
            'workout_days': [],
            'weight': [],
            'reps': [],
            'exercise': 'Overall',
            'stats': {},
            'unit': 'percent',
            'overall_mode': mode,
        }

    exercise_day_values: Dict[str, Dict] = {}
    workout_days = set()
    title_by_day: Dict = {}
    name_by_key: Dict[str, str] = {}
    sets_by_day: Dict = {}

    vocabulary = stats_vocabulary({log.exercise for log in logs})
    for log in logs:
        if not log.date:
            continue
        key = _normalize_exercise_name(log.exercise, vocabulary)
        if not key:
            continue
        day = log.date.date()
        workout_days.add(day)
        title_by_day.setdefault(day, _clean_workout_title(getattr(log, 'workout_name', None)))
        # The latest spelling names the exercise.
        name_by_key[key] = str(log.exercise or '').strip() or key
        sets_by_day[day] = sets_by_day.get(day, 0) + _logged_set_count(log)
        value = _get_peak_1rm_for_log(db_session, log)
        if not value or value <= 0:
            continue
        per_day = exercise_day_values.setdefault(key, {})
        per_day[day] = max(float(per_day.get(day, 0.0)), float(value))

    if not exercise_day_values or not workout_days:
        return {
            'labels': [],
            'data': [],
            'log_data': [],
            'workout_days': [],
            'weight': [],
            'reps': [],
            'exercise': 'Overall',
            'stats': {},
            'unit': 'percent',
            'overall_mode': mode,
        }

    workout_days_sorted = sorted(workout_days)
    start_day = workout_days_sorted[0]
    end_day = workout_days_sorted[-1]

    baseline_by_exercise: Dict[str, float] = {}
    sessions_by_exercise: Dict[str, int] = {}
    for key, day_map in exercise_day_values.items():
        session_items = sorted(day_map.items())
        sessions_by_exercise[key] = len(session_items)
        positive_values = [v for _, v in session_items if v and v > 0]
        baseline_session_count = min(
            int(baseline_sessions_target),
            len(positive_values),
        )
        samples = positive_values[:baseline_session_count]
        if not samples:
            continue
        if len(samples) >= 3:
            base = float(median(samples))
        else:
            base = float(sum(samples) / len(samples))
        if base > 0:
            baseline_by_exercise[key] = base

    universe = [
        key
        for key in baseline_by_exercise.keys()
        if sessions_by_exercise.get(key, 0) >= int(min_sessions)
    ]

    # Every day trained and what it was called, for the Consistency view.
    day_titles = {d.isoformat(): title_by_day.get(d, 'Workout') for d in workout_days_sorted}
    day_sets = {d.isoformat(): int(sets_by_day.get(d, 0)) for d in workout_days_sorted}

    if not universe:
        return {
            'labels': [],
            'data': [],
            'log_data': [],
            'workout_days': [d.isoformat() for d in workout_days_sorted],
            'day_titles': day_titles,
            'day_sets': day_sets,
            'exercises': [],
            'weight': [],
            'reps': [],
            'exercise': 'Overall',
            'stats': {},
            'unit': 'percent',
            'overall_mode': mode,
        }

    timelines = {}
    for key in universe:
        items = sorted(exercise_day_values.get(key, {}).items())
        timelines[key] = {
            'days': [d for d, _ in items],
            'values': [float(v) for _, v in items],
        }

    labels = []
    series = []
    log_series = []
    workout_titles = []
    pointers = {key: -1 for key in universe}
    last_values = {key: None for key in universe}
    last_session_days = {key: None for key in universe}
    rate_segment = {key: 0 for key in universe}

    for day in _date_range(start_day, end_day):
        labels.append(day.isoformat())
        workout_titles.append(title_by_day.get(day, "Workout"))
        weighted_sum = 0.0
        weight_sum = 0.0
        daily_log_sum = 0.0
        daily_log_weight_sum = 0.0

        for key in universe:
            timeline = timelines[key]
            days = timeline['days']
            values = timeline['values']

            idx = pointers[key]
            while idx + 1 < len(days) and days[idx + 1] <= day:
                idx += 1
                last_values[key] = values[idx]
                last_session_days[key] = days[idx]
            pointers[key] = idx

            last_val = last_values.get(key)
            last_session_day = last_session_days.get(key)
            if last_val is None or not last_session_day:
                continue

            days_since = (day - last_session_day).days
            fade = _fade_multiplier(days_since, int(fade_start_days), int(fade_end_days))
            if fade <= 0:
                continue

            base = baseline_by_exercise.get(key) or 0.0
            if base <= 0:
                continue

            weight = base * fade

            if mode == 'rate':
                seg = rate_segment[key]
                while seg + 1 < len(days) and day > days[seg + 1]:
                    seg += 1
                rate_segment[key] = seg

                daily_L = 0.0
                if seg + 1 < len(days):
                    d1 = days[seg]
                    d2 = days[seg + 1]
                    v1 = values[seg]
                    v2 = values[seg + 1]
                    day_span = (d2 - d1).days
                    if day_span > 0 and v1 > 0 and v2 > 0 and day > d1 and day <= d2:
                        ratio = v2 / v1
                        if ratio > 0:
                            daily_L = math.log(ratio) / float(day_span)

                daily_log_sum += daily_L * weight
                daily_log_weight_sum += weight
            else:
                index_value = (last_val / base) * 100.0
                weighted_sum += index_value * weight
                weight_sum += weight

        if mode == 'rate':
            overall_L = (daily_log_sum / daily_log_weight_sum) if daily_log_weight_sum else 0.0
            log_series.append(overall_L)
            series.append((math.exp(overall_L) - 1.0) * 100.0)
        else:
            log_series.append(0.0)
            series.append((weighted_sum / weight_sum) if weight_sum else 0.0)

    stats = {}
    if any(value != 0 for value in series):
        cleaned = [float(v) for v in series]
        avg_value = sum(cleaned) / len(cleaned) if cleaned else 0
        stats = {
            'current_1rm': cleaned[-1] if cleaned else 0,
            'max_1rm': max(cleaned) if cleaned else 0,
            'min_1rm': min(cleaned) if cleaned else 0,
            'improvement': cleaned[-1] - cleaned[0] if len(cleaned) > 1 else 0,
            'improvement_pct': avg_value,
        }

    title = 'Strength Index (vs baseline)' if mode != 'rate' else 'Improvement Rate (per day)'

    return {
        'labels': labels,
        'data': series,
        'log_data': log_series,
        'workout_days': [d.isoformat() for d in workout_days_sorted],
        'day_titles': day_titles,
        'day_sets': day_sets,
        # Each exercise's estimated max per session, for "New bests" and "Most improved".
        'exercises': [
            {
                'name': name_by_key.get(key, key),
                'baseline': round(baseline_by_exercise[key], 2),
                'days': [d.isoformat() for d in timelines[key]['days']],
                'values': [round(v, 2) for v in timelines[key]['values']],
            }
            for key in universe
        ],
        'weight': [],
        'reps': [],
        'workout_titles': workout_titles,
        'exercise': title,
        'stats': stats,
        'unit': 'percent',
        'overall_mode': mode,
        'baseline_sessions': int(baseline_sessions_target),
        'min_sessions': int(min_sessions),
    }


def get_all_exercises_summary(db_session, user) -> List[Dict]:
    """Get summary for all exercises."""
    exercises = db_session.query(WorkoutLog.exercise).filter_by(
        user_id=user.id
    ).distinct().all()
    
    summaries = []
    for ex in exercises:
        summary = get_exercise_summary(db_session, user, ex[0])
        summary['exercise'] = ex[0]
        summaries.append(summary)
    
    # Sort by latest date
    summaries.sort(key=lambda x: x.get('latest_date', datetime.min), reverse=True)
    return summaries
