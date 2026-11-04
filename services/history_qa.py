from __future__ import annotations

import re
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, func

from config import Config
from models import WorkoutLog
from services.stats import get_average_growth_data, get_chart_data
from utils.logger import logger
from utils.dates import local_now, local_today


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
    ]
    return list(dict.fromkeys([c for c in candidates if c and c.strip()]))


def _parse_iso_date(text: str) -> Optional[date]:
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_day_month(text: str) -> Optional[date]:
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip().lower()

    m = re.search(r"\b(\d{1,2})\s*(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
                  s, flags=re.IGNORECASE)
    if not m:
        return None

    day_num = int(m.group(1))
    mon = m.group(2).lower()
    month_map = {
        'jan': 1, 'january': 1,
        'feb': 2, 'february': 2,
        'mar': 3, 'march': 3,
        'apr': 4, 'april': 4,
        'may': 5,
        'jun': 6, 'june': 6,
        'jul': 7, 'july': 7,
        'aug': 8, 'august': 8,
        'sep': 9, 'sept': 9, 'september': 9,
        'oct': 10, 'october': 10,
        'nov': 11, 'november': 11,
        'dec': 12, 'december': 12,
    }
    month_num = month_map.get(mon)
    if not month_num:
        return None

    today = local_today()
    year = today.year
    candidate = None
    try:
        candidate = date(year, month_num, day_num)
    except Exception:
        candidate = None

    if candidate and candidate > today:
        try:
            prev = date(year - 1, month_num, day_num)
            candidate = prev
        except Exception:
            pass

    return candidate


def _parse_any_date(text: str) -> Optional[date]:
    return _parse_iso_date(text) or _parse_day_month(text)


def _parse_number(text: str) -> Optional[float]:
    if not isinstance(text, str) or not text.strip():
        return None
    m = re.search(r"(-?\d+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _get_logs_for_date(db_session, user, target: date) -> List[WorkoutLog]:
    start_dt = datetime.combine(target, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)
    return (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user.id)
        .filter(WorkoutLog.date >= start_dt)
        .filter(WorkoutLog.date < end_dt)
        .order_by(WorkoutLog.id.asc())
        .all()
    )


def _resolve_exercise_name(db_session, user, exercise: str) -> Optional[str]:
    candidates = _exercise_candidates(exercise)
    if not candidates:
        return None
    row = (
        db_session.query(WorkoutLog.exercise)
        .filter(WorkoutLog.user_id == user.id)
        .filter(WorkoutLog.exercise.in_(candidates))
        .order_by(WorkoutLog.exercise.asc())
        .first()
    )
    if row and isinstance(row[0], str) and row[0].strip():
        return row[0]
    return None


def _select_series(data: dict, metric: str) -> List[float]:
    if not isinstance(data, dict):
        return []
    if data.get('unit') == 'percent':
        return [float(x or 0) for x in (data.get('data') or [])]

    series = data.get('series') or {}
    if metric in series:
        return [float(x or 0) for x in (series.get(metric) or [])]
    if metric == 'e1rm':
        return [float(x or 0) for x in (data.get('data') or [])]
    return [float(x or 0) for x in (data.get('data') or [])]


def _index_for_date(labels: List[str], d: date) -> Optional[int]:
    if not labels or not d:
        return None
    key = d.isoformat()
    try:
        return labels.index(key)
    except ValueError:
        return None


def _match_exercise_from_options(question: str, exercise_options: Optional[List[str]]) -> Optional[str]:
    if not question or not exercise_options:
        return None
    q = str(question).lower()
    best = None
    best_len = 0
    for opt in exercise_options:
        if not isinstance(opt, str):
            continue
        cand = opt.strip()
        if not cand:
            continue
        cand_l = cand.lower()
        try:
            pat = r'(^|[^a-z0-9])' + re.escape(cand_l) + r'($|[^a-z0-9])'
            if re.search(pat, q) and len(cand_l) > best_len:
                best = cand
                best_len = len(cand_l)
        except Exception:
            continue
    return best


def _answer_last_hit(db_session, user, *, exercise: str, weight_kg: Optional[float]) -> Dict[str, Any]:
    candidates = _exercise_candidates(exercise)
    if not candidates:
        return {"ok": False, "error": "Please specify an exercise."}

    q = (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user.id)
        .filter(WorkoutLog.exercise.in_(candidates))
    )

    logs = q.order_by(desc(WorkoutLog.date)).all()
    if not logs:
        return {"ok": False, "error": f"No logs found for {exercise}."}

    picked = None
    if weight_kg is not None:
        for log in logs:
            try:
                if log.top_weight is not None and float(log.top_weight) >= float(weight_kg):
                    picked = log
                    break
            except Exception:
                continue
    else:
        picked = logs[0]

    if not picked:
        return {
            "ok": True,
            "answer": f"You haven't logged {exercise} at {weight_kg:g}kg yet.",
            "results": [],
        }

    d = picked.date.date() if isinstance(picked.date, datetime) else None
    if weight_kg is not None:
        answer = (
            f"Last time you hit {weight_kg:g}kg+ on {exercise} was {d.isoformat() if d else 'an unknown date'}. "
            f"(Top set: {picked.top_weight or ''} x {picked.top_reps or ''})"
        )
    else:
        answer = (
            f"Last time you logged {exercise} was {d.isoformat() if d else 'an unknown date'}. "
            f"(Top set: {picked.top_weight or ''} x {picked.top_reps or ''})"
        )

    return {
        "ok": True,
        "answer": answer,
        "results": [
            {
                "date": d.isoformat() if d else None,
                "workout_name": picked.workout_name,
                "exercise": picked.exercise,
                "top_weight": picked.top_weight,
                "top_reps": picked.top_reps,
                "estimated_1rm": picked.estimated_1rm,
            }
        ],
        "workout_url": f"/workout/{d.isoformat()}" if d else None,
    }


def _pull_like(exercise_name: str) -> bool:
    s = (exercise_name or '').strip().lower()
    if not s:
        return False
    keywords = (
        'pull', 'row', 'deadlift', 'lat', 'chin', 'curl', 'pulldown', 'face pull', 'rear delt', 'shrug'
    )
    return any(k in s for k in keywords)


def _push_like(exercise_name: str) -> bool:
    s = (exercise_name or '').strip().lower()
    keywords = ('press', 'bench', 'dip', 'fly', 'flye', 'push', 'lateral raise', 'front raise', 'tricep', 'skull')
    return any(k in s for k in keywords)


def _legs_like(exercise_name: str) -> bool:
    s = (exercise_name or '').strip().lower()
    keywords = ('squat', 'leg press', 'leg extension', 'leg curl', 'lunge', 'calf', 'hamstring', 'quad',
                'glute', 'hip thrust', 'romanian', 'rdl', 'step up', 'hack')
    return any(k in s for k in keywords)


# Which of a day's exercises count towards "best <type> day". Before, only "pull" was filtered,
# so "best push day" could name a legs day.
_DAY_TYPE_FILTERS = {
    'pull': _pull_like,
    'push': lambda name: _push_like(name) and not _legs_like(name),  # not "Leg Press"
    'legs': _legs_like,
    'lower': _legs_like,
    'upper': lambda name: (_pull_like(name) or _push_like(name)) and not _legs_like(name),
}


def _answer_best_day(db_session, user, *, day_type: str, since_days: int) -> Dict[str, Any]:
    day_type_norm = (day_type or '').strip().lower()
    since_days = int(since_days or 30)
    since_days = max(1, min(since_days, 365))

    cutoff_dt = local_now() - timedelta(days=since_days)

    logs = (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user.id)
        .filter(WorkoutLog.date >= cutoff_dt)
        .order_by(WorkoutLog.date.desc(), WorkoutLog.id.asc())
        .all()
    )
    if not logs:
        return {"ok": False, "error": f"No workouts found in the last {since_days} days."}

    by_day: Dict[date, List[WorkoutLog]] = {}
    for log in logs:
        d = log.date.date() if isinstance(log.date, datetime) else None
        if not d:
            continue
        by_day.setdefault(d, []).append(log)

    scored: List[Tuple[float, date, List[WorkoutLog]]] = []
    for d, day_logs in by_day.items():
        keep = _DAY_TYPE_FILTERS.get(day_type_norm)
        filtered = [l for l in day_logs if keep(l.exercise)] if keep else list(day_logs)

        if not filtered:
            continue

        score = 0.0
        for l in filtered:
            try:
                score += float(l.estimated_1rm or 0.0)
            except Exception:
                continue
        scored.append((score, d, filtered))

    if not scored:
        return {"ok": False, "error": f"No {day_type_norm or 'matching'} workouts found in the last {since_days} days."}

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best_score, best_date, best_logs = scored[0]

    best_logs_sorted = sorted(best_logs, key=lambda l: float(l.estimated_1rm or 0.0), reverse=True)
    top_entries = []
    for l in best_logs_sorted[:8]:
        top_entries.append({
            "exercise": l.exercise,
            "top_weight": l.top_weight,
            "top_reps": l.top_reps,
            "estimated_1rm": l.estimated_1rm,
        })

    label = day_type_norm.title() if day_type_norm else "Best"
    answer = f"Your best {label} day in the last {since_days} days was {best_date.isoformat()} (score {best_score:.1f})."

    return {
        "ok": True,
        "answer": answer,
        "results": top_entries,
        "workout_url": f"/workout/{best_date.isoformat()}",
    }


def _answer_explain_drop(
    db_session,
    user,
    *,
    target_date: date,
    exercise: Optional[str],
    metric: str,
) -> Dict[str, Any]:
    metric = (metric or 'e1rm').strip().lower()

    if not exercise:
        data = get_average_growth_data(db_session, user)
        labels = data.get('labels') or []
        series = _select_series(data, 'data')
        idx = _index_for_date(labels, target_date)
        if idx is None:
            return {
                "ok": True,
                "answer": f"I don't have a plotted point for {target_date.isoformat()} on Overall Progress (no logs that day).",
                "results": [],
            }
        prev_idx = idx - 1
        cur = float(series[idx] or 0.0) if idx < len(series) else 0.0
        prev = float(series[prev_idx] or 0.0) if prev_idx >= 0 and prev_idx < len(series) else None
        delta = (cur - prev) if prev is not None else None

        logs = _get_logs_for_date(db_session, user, target_date)
        top = sorted(logs, key=lambda l: float(l.estimated_1rm or 0.0), reverse=True)[:8]
        results = [
            {
                "exercise": l.exercise,
                "top_weight": l.top_weight,
                "top_reps": l.top_reps,
                "estimated_1rm": l.estimated_1rm,
            }
            for l in top
        ]

        if delta is None:
            answer = f"On {target_date.isoformat()}, Overall Progress was {cur:.1f}%."
        else:
            sign = '+' if delta >= 0 else ''
            answer = f"On {target_date.isoformat()}, Overall Progress was {cur:.1f}% ({sign}{delta:.1f}% vs previous point)."

        return {
            "ok": True,
            "answer": answer,
            "results": results,
            "workout_url": f"/workout/{target_date.isoformat()}" if logs else None,
        }

    resolved = _resolve_exercise_name(db_session, user, exercise)
    exercise_name = resolved or exercise
    data = get_chart_data(db_session, user, exercise_name)
    labels = data.get('labels') or []
    series = _select_series(data, metric)
    idx = _index_for_date(labels, target_date)
    if idx is None:
        return {
            "ok": True,
            "answer": f"I don't have a plotted point for {target_date.isoformat()} on {exercise_name} ({metric}).",
            "results": [],
        }
    prev_idx = idx - 1
    cur = float(series[idx] or 0.0) if idx < len(series) else 0.0
    prev = float(series[prev_idx] or 0.0) if prev_idx >= 0 and prev_idx < len(series) else None
    delta = (cur - prev) if prev is not None else None

    day_logs = _get_logs_for_date(db_session, user, target_date)
    candidates = set(_exercise_candidates(exercise))
    matching = [l for l in day_logs if (l.exercise or '').strip() in candidates]
    matching_sorted = sorted(matching, key=lambda l: float(l.estimated_1rm or 0.0), reverse=True)

    results = []
    for l in matching_sorted[:6]:
        results.append({
            "exercise": l.exercise,
            "top_weight": l.top_weight,
            "top_reps": l.top_reps,
            "estimated_1rm": l.estimated_1rm,
        })

    if delta is None:
        answer = f"On {target_date.isoformat()}, {exercise_name} ({metric}) was {cur:.1f}."
    else:
        sign = '+' if delta >= 0 else ''
        answer = f"On {target_date.isoformat()}, {exercise_name} ({metric}) was {cur:.1f} ({sign}{delta:.1f} vs previous point)."

    return {
        "ok": True,
        "answer": answer,
        "results": results,
        "workout_url": f"/workout/{target_date.isoformat()}" if day_logs else None,
    }


def _answer_best_relative(db_session, user, *, exercise: str, metric: str = 'e1rm') -> Dict[str, Any]:
    exercise = str(exercise or '').strip()
    if not exercise:
        return {"ok": False, "error": "Please specify an exercise."}

    resolved = _resolve_exercise_name(db_session, user, exercise)
    exercise_name = resolved or exercise
    data = get_chart_data(db_session, user, exercise_name)
    labels = data.get('labels') or []
    series = _select_series(data, metric)

    if not labels or not series or len(series) < 2:
        return {"ok": False, "error": f"Not enough data to compare days for {exercise_name}."}

    best_idx = None
    best_delta = None
    for i in range(1, min(len(labels), len(series))):
        try:
            prev = float(series[i - 1] or 0.0)
            cur = float(series[i] or 0.0)
        except Exception:
            continue
        delta = cur - prev
        if best_delta is None or delta > best_delta:
            best_delta = delta
            best_idx = i

    if best_idx is None or best_delta is None:
        return {"ok": False, "error": f"Unable to compute day-over-day improvements for {exercise_name}."}

    best_date = labels[best_idx]
    prev_val = float(series[best_idx - 1] or 0.0)
    cur_val = float(series[best_idx] or 0.0)
    sign = '+' if best_delta >= 0 else ''
    answer = (
        f"Your biggest day-to-day change on {exercise_name} was on {best_date}: "
        f"{cur_val:.1f} ({sign}{best_delta:.1f} vs previous logged day {prev_val:.1f})."
    )

    return {
        "ok": True,
        "answer": answer,
        "results": [
            {
                "date": best_date,
                "exercise": exercise_name,
                "estimated_1rm": cur_val,
            }
        ],
        "workout_url": f"/workout/{best_date}",
    }


def _heuristic_intent(question: str) -> Tuple[Optional[str], Dict[str, Any]]:
    q = (question or '').strip()
    q_lower = q.lower()

    m_last_hit = re.search(r"\blast\s+hit\s+(\d+(?:\.\d+)?)\s*(?:kg)?\s*(.+)$", q_lower)
    if m_last_hit:
        weight = None
        try:
            weight = float(m_last_hit.group(1))
        except Exception:
            weight = None
        ex = (m_last_hit.group(2) or '').strip()
        ex = re.sub(r"\?$", "", ex).strip()
        return "last_hit", {"exercise": ex, "weight_kg": weight}

    m_last_did = re.search(r"\bwhen\s+did\s+i\s+last\s+(?:do|train|log)\s+(.+?)\??$", q_lower)
    if m_last_did:
        ex = (m_last_did.group(1) or '').strip()
        return "last_hit", {"exercise": ex, "weight_kg": None}

    m_best_day = re.search(r"\bbest\s+(pull|push|legs|upper|lower)\s+day\s+in\s+the\s+last\s+(\d{1,3})\s+days\b", q_lower)
    if m_best_day:
        return "best_day", {"day_type": m_best_day.group(1), "since_days": int(m_best_day.group(2))}

    m_best_day_short = re.search(r"\bbest\s+(pull|push|legs)\s+day\s+last\s+(\d{1,3})\s+days\b", q_lower)
    if m_best_day_short:
        return "best_day", {"day_type": m_best_day_short.group(1), "since_days": int(m_best_day_short.group(2))}

    if ('relative to previous' in q_lower) or ('vs previous' in q_lower) or ('compared to previous' in q_lower):
        m_ex = re.search(r"\b(?:in|for)\s+(.+?)\s+(?:relative|vs|compared)\b", q_lower)
        if not m_ex:
            m_ex = re.search(r"\b(?:in|for)\s+(.+?)\??$", q_lower)
        if m_ex:
            ex = (m_ex.group(1) or '').strip()
            return "best_relative", {"exercise": ex, "metric": "e1rm"}

    if 'graph' in q_lower and ('down' in q_lower or 'drop' in q_lower):
        d = _parse_any_date(q)
        if d:
            return "explain_drop", {"date": d}

    return None, {}


def _gemini_plan_question(*, question: str, api_key: str, exercise_options: List[str]) -> Optional[Dict[str, Any]]:
    if not api_key:
        return None

    import requests

    options = [x for x in exercise_options if isinstance(x, str) and x.strip()]
    options = options[:120]

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "You are an assistant inside a workout logging app. "
                            "Your job is to map a user's question into a structured query plan.\n\n"
                            "Return ONLY valid JSON with this schema:\n"
                            "{\"intent\": \"last_hit\"|\"best_day\"|\"explain_drop\"|\"best_relative\", "
                            "\"exercise\": string|null, \"weight_kg\": number|null, \"since_days\": integer|null, \"date\": string|null, "
                            "\"day_type\": string|null, \"metric\": string|null}\n\n"
                            "Rules:\n"
                            "- intent must be one of the allowed values.\n"
                            "- exercise should match one of the provided exercises if possible, otherwise null.\n"
                            "- date must be YYYY-MM-DD if present.\n"
                            "- metric should be one of: e1rm, top_weight, tonnage, effective_tonnage, overall_progress.\n"
                            "- since_days must be between 1 and 365.\n\n"
                            f"Available exercises: {options}\n\n"
                            f"Question: {question}"
                        )
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "type": "object",
                "propertyOrdering": ["intent", "exercise", "weight_kg", "since_days", "date", "day_type", "metric"],
                "properties": {
                    "intent": {"type": "string", "enum": ["last_hit", "best_day", "explain_drop", "best_relative"]},
                    "exercise": {"type": ["string", "null"]},
                    "weight_kg": {"type": ["number", "null"]},
                    "since_days": {"type": ["integer", "null"], "minimum": 1, "maximum": 365},
                    "date": {"type": ["string", "null"]},
                    "day_type": {"type": ["string", "null"]},
                    "metric": {"type": ["string", "null"]},
                },
                "required": ["intent", "exercise", "weight_kg", "since_days", "date", "day_type", "metric"],
            },
        },
    }

    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    model_candidates = [
        "gemini-2.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-flash",
    ]

    data = None
    last_error = None
    for model in model_candidates:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            last_error = None
            break
        except Exception as e:
            last_error = e
            continue

    if data is None:
        raise last_error or RuntimeError("Gemini request failed")

    text = None
    try:
        candidates = data.get("candidates") if isinstance(data, dict) else None
        if isinstance(candidates, list) and candidates:
            content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list) and parts:
                part0 = parts[0]
                if isinstance(part0, dict) and isinstance(part0.get("text"), str):
                    text = part0.get("text")
    except Exception:
        text = None

    if not isinstance(text, str) or not text.strip():
        return None

    try:
        import json

        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def answer_history_question(
    db_session,
    user,
    *,
    question: str,
    context_exercise: Optional[str] = None,
    context_metric: Optional[str] = None,
    context_date: Optional[str] = None,
    api_keys: Optional[List[Dict[str, Any]]] = None,
    exercise_options: Optional[List[str]] = None,
    use_ai: bool = True,
) -> Dict[str, Any]:
    question = str(question or '').strip()
    if not question:
        return {"ok": False, "error": "Please enter a question."}
    if len(question) > 400:
        question = question[:400]

    intent, params = _heuristic_intent(question)

    if intent == 'last_hit':
        return _answer_last_hit(db_session, user, exercise=params.get('exercise') or '', weight_kg=params.get('weight_kg'))

    if intent == 'best_day':
        return _answer_best_day(
            db_session,
            user,
            day_type=params.get('day_type') or 'pull',
            since_days=int(params.get('since_days') or 30),
        )

    if intent == 'explain_drop':
        metric = (context_metric or 'e1rm').strip()
        d = params.get('date')
        if not isinstance(d, date):
            return {"ok": False, "error": "Please specify a date."}
        ex = (context_exercise or '').strip() or None
        return _answer_explain_drop(db_session, user, target_date=d, exercise=ex, metric=metric)

    if intent == 'best_relative':
        matched = _match_exercise_from_options(question, exercise_options)
        exercise = matched or params.get('exercise') or (context_exercise or '')
        return _answer_best_relative(
            db_session,
            user,
            exercise=exercise,
            metric=str(params.get('metric') or context_metric or 'e1rm'),
        )

    ctx_date = _parse_iso_date(str(context_date)) if context_date else None
    ql = question.lower()
    if ctx_date and (('down' in ql) or ('drop' in ql) or ('low' in ql) or ('dip' in ql)):
        ex = (context_exercise or '').strip() or None
        metric = (context_metric or 'e1rm').strip()
        return _answer_explain_drop(db_session, user, target_date=ctx_date, exercise=ex, metric=metric)

    if not use_ai:
        return {"ok": False, "error": "I can only answer a few kinds of questions without AI."}

    # Gemini planning fallback.
    keys_to_try = []
    if api_keys:
        keys_to_try.extend([k for k in api_keys if isinstance(k, dict) and k.get('api_key')])
    env_key = getattr(Config, 'GEMINI_API_KEY', None)
    if env_key:
        keys_to_try.append({"id": None, "api_key": env_key, "source": "env"})

    if not keys_to_try:
        return {
            "ok": False,
            "error": "No AI API key configured. Add a Gemini key in Settings → AI API Keys.",
        }

    options = exercise_options or []
    plan = None
    last_err = None
    for k in keys_to_try[:2]:
        try:
            plan = _gemini_plan_question(question=question, api_key=str(k.get('api_key') or ''), exercise_options=options)
            if plan:
                break
        except Exception as e:
            last_err = e
            continue

    if not plan:
        if last_err:
            logger.warning(f"History QA Gemini plan failed: {type(last_err).__name__}")
        return {"ok": False, "error": "I couldn't understand that question yet."}

    try:
        plan_intent = str(plan.get('intent') or '').strip()
    except Exception:
        plan_intent = ''

    plan_exercise = plan.get('exercise')
    plan_metric = plan.get('metric')

    if plan_intent == 'last_hit':
        weight = plan.get('weight_kg')
        weight_val = None
        try:
            if weight is not None:
                weight_val = float(weight)
        except Exception:
            weight_val = None

        ex = str(plan_exercise or '').strip() if isinstance(plan_exercise, str) else ''
        return _answer_last_hit(db_session, user, exercise=ex, weight_kg=weight_val)

    if plan_intent == 'best_day':
        since_days = plan.get('since_days')
        since_val = 30
        try:
            if since_days is not None:
                since_val = int(since_days)
        except Exception:
            since_val = 30

        day_type = str(plan.get('day_type') or 'pull').strip().lower() or 'pull'
        return _answer_best_day(db_session, user, day_type=day_type, since_days=since_val)

    if plan_intent == 'explain_drop':
        dt = plan.get('date')
        target = _parse_iso_date(str(dt)) if dt else None
        if not target:
            target = _parse_any_date(question)
        if not target:
            return {"ok": False, "error": "Please specify a date (e.g. 2026-01-30)."}

        metric = str(plan_metric or context_metric or 'e1rm').strip().lower()
        if metric == 'overall_progress':
            metric = 'data'
        ex = str(plan_exercise or context_exercise or '').strip() or None
        if ex and ex.lower() == 'overall progress':
            ex = None
        return _answer_explain_drop(db_session, user, target_date=target, exercise=ex, metric=metric)

    if plan_intent == 'best_relative':
        ex = str(plan_exercise or context_exercise or '').strip()
        metric = str(plan_metric or context_metric or 'e1rm').strip().lower()
        return _answer_best_relative(db_session, user, exercise=ex, metric=metric)

    return {"ok": False, "error": "I couldn't understand that question yet."}
