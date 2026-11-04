from datetime import datetime, timedelta
import html
import json
import re
import threading
import time
from urllib.parse import urlsplit

from flask import Response, flash, jsonify, redirect, render_template, request, session, stream_with_context, url_for
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy import desc, func

from list_of_exercise import get_workout_days, list_of_exercises
from models import Session, User, WorkoutLog, UserApiKey, ShortcutKeyMap, RepRange
from services.logging import (
    handle_workout_log,
    classify_exercise_performance,
    resolve_timed_exercise_status,
    set_timed_exercise_preference,
    comparison_set_count,
    get_best_log_for_exercise_before_date,
    get_plan_target_sets_for_user,
    parse_rep_target_sets_text,
    resolve_target_sets_for_exercise,
    refresh_best_lift_pointers,
)
from services.ai_coach import key_provider
from services.retrieve import generate_retrieve_output, get_effective_plan_text
from parsers.workout import workout_parser
from services.log_check import check_workout_text, public_check
from services import workout_insights as insights
from services.exercise_matching import build_name_index, normalize_exercise_name, resolve_equivalent_names
from services.bodyweight import (
    backfill_bodyweight_log_flags,
    effective_sets_for_log,
    infer_log_uses_bodyweight,
    has_bodyweight_token,
)
from utils.errors import ParsingError, ValidationError, UserNotFoundError
from utils.logger import logger
from utils.profile_images import get_profile_image_url
from utils.rich_text import to_plain_text
from utils.validators import is_safe_redirect_url, sanitize_text_input, validate_username
from utils.dates import local_from_epoch_ms, local_now, local_today, utc_now


SHORTCUT_KEY_HELP = (
    "Copy your shortcut key again from Liftbook > Settings > Integrations > Apple Shortcuts. "
    "Then open this shortcut in the Shortcuts app and paste the key into the first box."
)
SHORTCUT_KEY_INVALID = "Your shortcut key isn't valid. " + SHORTCUT_KEY_HELP
SHORTCUT_KEY_MISSING = "Your shortcut key is missing. " + SHORTCUT_KEY_HELP
SHORTCUT_DAY_TAKEN = (
    "That day already has a workout, so nothing was saved. "
    "To add these exercises to it, paste them on the Log page and choose Add to that day."
)
# What the workout page says after a save from the Log page (timed questions, skipped lines).
LOG_SAVED_SESSION_KEY = 'log_saved'
SAVE_WORKOUT_FAILED = "Error saving workout. Please try again."


def deployment_name(host: str) -> str:
    host = host.lower()
    if host.split(':')[0] in {'localhost', '127.0.0.1'}:
        return 'Local'
    if host.endswith('.railway.app'):
        return 'Railway'
    if host.endswith('.onrender.com'):
        return 'Render'
    return host


def register_workout_routes(app):
    serializer = URLSafeSerializer(app.config.get('SECRET_KEY', 'workout-share'))

    _reco_cache = {}
    _reco_cache_lock = threading.Lock()

    def _make_share_token(user_id, workout_date):
        payload = {
            "user_id": user_id,
            "date": workout_date.strftime('%Y-%m-%d'),
        }
        return serializer.dumps(payload)

    def _load_share_token(token):
        return serializer.loads(token)

    def _make_shortcut_token(user_id: int):
        payload = {
            "user_id": user_id,
            "scope": "shortcut_recommend",
        }
        return serializer.dumps(payload)

    def _load_shortcut_token(token: str) -> dict:
        payload = serializer.loads(token)
        if not isinstance(payload, dict) or payload.get("scope") != "shortcut_recommend":
            raise BadSignature("Invalid shortcut token")
        return payload

    def _make_shortcut_pick_token(user_id: int):
        payload = {
            "user_id": user_id,
            "scope": "shortcut_pick",
        }
        return serializer.dumps(payload)

    def _make_shortcut_key(user_id: int):
        # One key for both downloadable shortcuts (logging and retrieving).
        return serializer.dumps({"user_id": user_id, "scope": "shortcut"})

    def _load_shortcut_pick_token(token: str) -> dict:
        payload = serializer.loads(token)
        if not isinstance(payload, dict) or payload.get("scope") not in ("shortcut_pick", "shortcut"):
            raise BadSignature("Invalid shortcut pick token")
        return payload

    def _make_shortcut_log_token(user_id: int):
        payload = {
            "user_id": user_id,
            "scope": "shortcut_log",
        }
        return serializer.dumps(payload)

    def _load_shortcut_log_token(token: str) -> dict:
        payload = serializer.loads(token)
        if not isinstance(payload, dict) or payload.get("scope") not in ("shortcut_log", "shortcut"):
            raise BadSignature("Invalid shortcut log token")
        return payload

    def _count_sets(sets_json=None, sets_display=None):
        if sets_json and isinstance(sets_json, dict):
            weights = sets_json.get('weights') or []
            reps = sets_json.get('reps') or []
            count = max(len(weights), len(reps))
        elif sets_display:
            matches = re.findall(
                r'(bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)\s*[x×]\s*\d+',
                sets_display,
                flags=re.IGNORECASE,
            )
            count = (len(matches) if matches else 0)
        else:
            count = 0
        return count

    def _workout_day_bounds(value):
        if isinstance(value, datetime):
            workout_day = value.date()
        else:
            workout_day = value
        start_dt = datetime.combine(workout_day, datetime.min.time())
        end_dt = start_dt + timedelta(days=1)
        return workout_day, start_dt, end_dt

    def _find_existing_workout_for_day(user_id, workout_date):
        _, start_dt, end_dt = _workout_day_bounds(workout_date)
        return (
            Session.query(WorkoutLog)
            .filter_by(user_id=user_id)
            .filter(WorkoutLog.date >= start_dt)
            .filter(WorkoutLog.date < end_dt)
            .order_by(WorkoutLog.id.asc())
            .first()
        )

    def _log_uses_bw(log):
        return infer_log_uses_bodyweight(Session, log)

    def _display_sets(log, effective_sets, uses_bw):
        """Sets as the user thinks of them: added load on top of bodyweight for BW exercises."""
        if not uses_bw or not effective_sets:
            return getattr(log, 'sets_json', None)
        if getattr(log, 'bodyweight', None) is None:
            # No bodyweight saved: loads were stored as offsets, with 1 as the legacy "just BW" marker.
            raw = getattr(log, 'sets_json', None) or {}
            weights = []
            for weight in raw.get('weights') or []:
                try:
                    weights.append(0.0 if float(weight) <= 1 else float(weight))
                except (TypeError, ValueError):
                    weights.append(weight)
            return {'weights': weights, 'reps': list(raw.get('reps') or [])}
        bodyweight = float(log.bodyweight)
        weights = []
        for weight in effective_sets.get('weights') or []:
            try:
                weights.append(round(float(weight) - bodyweight, 2))
            except (TypeError, ValueError):
                weights.append(weight)
        return {'weights': weights, 'reps': list(effective_sets.get('reps') or [])}

    def build_exercise_text(logs):
        lines = []
        for log in logs:
            if getattr(log, 'exercise_string', None):
                lines.append(log.exercise_string.strip())
                continue

            if getattr(log, 'sets_display', None):
                lines.append(f"{log.exercise} {log.sets_display}")
            elif log.top_weight and log.top_reps:
                lines.append(f"{log.exercise} {log.top_weight} x {log.top_reps}")
            else:
                lines.append(log.exercise)
        return "\n\n".join(lines)

    def _norm_ex_name(name: str) -> str:
        if not name:
            return ""
        s = html.unescape(str(name)).strip().lower()
        s = s.replace("•", " ")
        s = s.replace("–", "-").replace("—", "-")
        # Normalize hyphens to spaces so "pull-ups" and "pull ups" match.
        s = s.replace("-", " ")
        s = s.replace("’", "'").replace("‘", "'")
        try:
            s = re.sub(r"\bcurls\b", "curl", s)
            s = re.sub(r"\brows\b", "row", s)
            s = re.sub(r"\bpulldowns\b", "pulldown", s)
            s = re.sub(r"\bextensions\b", "extension", s)
            s = re.sub(r"\braises\b", "raise", s)
            s = re.sub(r"\bpulldown\b", "pull down", s)
            s = re.sub(r"\bpushdown\b", "push down", s)
            s = re.sub(r"\bpullups\b", "pull ups", s)
            s = re.sub(r"\bpullup\b", "pull up", s)
            s = re.sub(r"\bchinups\b", "chin ups", s)
            s = re.sub(r"\bchinup\b", "chin up", s)
            s = re.sub(r"\bpull up\b", "pull ups", s)
            s = re.sub(r"\bchin up\b", "chin ups", s)
        except Exception:
            pass
        s = re.sub(r"\s*\([^)]*\)\s*", " ", s)
        s = re.sub(r"^\s*\d+\s*[\).:-]\s*", "", s)
        s = re.sub(r"\s+", " ", s)
        s = s.strip()
        # Order-invariant normalization helps match variants like
        # "Standing Calf Raises" vs "Calf Raises Standing".
        try:
            tokens = [t for t in s.split(" ") if t]
            tokens = [t for t in tokens if t not in {"and", "the"}]
            tokens.sort()
            s = " ".join(tokens).strip()
        except Exception:
            s = s.strip()
        return s

    def _norm_title_key(title: str) -> str:
        s = str(title or "").strip().lower()
        s = re.sub(r"\s+", " ", s)
        return s

    def _norm_day_title_key(title: str) -> str:
        s = str(title or "").strip().lower()
        s = s.replace("•", " ")
        s = s.replace("–", "-").replace("—", "-")
        s = s.replace("’", "'").replace("‘", "'")
        s = re.sub(r"\bday\b", " ", s, flags=re.IGNORECASE)
        s = re.sub(r"[^a-z0-9&]+", " ", s)
        return s

    def _clean_workout_title(title: str) -> str:
        cleaned = html.unescape(str(title or "").strip())
        cleaned = cleaned.lstrip('-–—').strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned or "Workout"

    def _contains_phrase(haystack: str, needle: str) -> bool:
        if not haystack or not needle:
            return False
        try:
            pat = r"(^|[^a-z0-9])" + re.escape(str(needle)) + r"($|[^a-z0-9])"
            return re.search(pat, str(haystack)) is not None
        except Exception:
            return False

    def _best_match_plan_day(*, title: str, exercise_list: list[str], plan_days: list[dict], day_lookup: dict):
        workout_ex = {_norm_ex_name(x) for x in (exercise_list or []) if _norm_ex_name(x)}
        if workout_ex:
            workout_len = len(workout_ex)
            best = None
            best_score = None
            for day in plan_days:
                day_ex = {_norm_ex_name(x) for x in (day.get('exercises') or []) if _norm_ex_name(x)}
                if not day_ex:
                    continue
                overlap = len(workout_ex.intersection(day_ex))
                if overlap < 2 or not workout_len:
                    continue
                precision = overlap / float(workout_len)
                recall = overlap / float(max(len(day_ex), 1))
                f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
                score = (f1, overlap, precision)
                if best_score is None or score > best_score:
                    best_score = score
                    best = day

            if best and best_score is not None:
                f1, overlap, _precision = best_score
                if overlap >= 4 or (overlap >= 3 and f1 >= 0.5):
                    return best, "exercises"

        title_key = _norm_day_title_key(title)
        if title_key in day_lookup:
            return day_lookup[title_key], "title"

        for day in plan_days:
            day_name = day.get('name')
            if not isinstance(day_name, str) or not day_name.strip():
                continue
            day_key = _norm_day_title_key(day_name)
            if title_key == day_key or (day_key and title_key.startswith(day_key + " ")) or _contains_phrase(title_key, day_key):
                return day, "title"

        return None, None

    def get_recent_workouts(user, limit=50, include_details=True):
        try:
            logs = (
                Session.query(WorkoutLog)
                .filter_by(user_id=user.id)
                .order_by(desc(WorkoutLog.date), WorkoutLog.id)
                .all()
            )

            workouts = []
            by_date = {}
            for log in logs:
                date_key = log.date.date() if isinstance(log.date, datetime) else log.date

                if date_key not in by_date:
                    by_date[date_key] = {
                        'date': log.date,
                        'title': _clean_workout_title(log.workout_name or "Workout"),
                        'exercises': [],
                        'logs': [],
                    }
                # Exercises in the order they were logged.
                if log.exercise not in by_date[date_key]['exercises']:
                    by_date[date_key]['exercises'].append(log.exercise)
                by_date[date_key]['logs'].append(log)

            for date_key in sorted(by_date.keys(), reverse=True):
                item = by_date[date_key]
                exercise_list = item['exercises']
                workouts.append({
                    'date': item['date'],
                    'title': item['title'],
                    'exercises': ", ".join(exercise_list),
                    'exercise_list': exercise_list,
                    'exercise_details': build_exercise_text(item['logs']) if include_details else '',
                })
                if limit is not None and len(workouts) >= limit:
                    break

            return workouts
        except Exception as e:
            logger.error(f"Error getting recent workouts: {e}", exc_info=True)
            return []

    def get_workout_stats(user):
        try:
            total_workouts = (
                Session.query(func.date(WorkoutLog.date))
                .filter_by(user_id=user.id)
                .distinct()
                .count()
            )

            total_exercises = (
                Session.query(WorkoutLog.exercise)
                .filter_by(user_id=user.id)
                .distinct()
                .count()
            )

            latest = (
                Session.query(WorkoutLog.date)
                .filter_by(user_id=user.id)
                .order_by(desc(WorkoutLog.date))
                .first()
            )

            latest_date = latest[0] if latest else None

            return {
                'total_workouts': total_workouts,
                'total_exercises': total_exercises,
                'latest_workout': latest_date,
            }
        except Exception as e:
            logger.error(f"Error getting workout stats: {e}", exc_info=True)
            return {
                'total_workouts': 0,
                'total_exercises': 0,
                'latest_workout': None,
            }

    _SESSION_TITLE_RE = re.compile(r"^(session\s+\d+)\s*[-–—:]\s*(.+)$", re.IGNORECASE)

    def _home_history(workouts):
        """Workouts grouped by month, newest first, for Home and All workouts."""
        months = []
        for w in workouts:
            d = w['date'].date() if isinstance(w['date'], datetime) else w['date']
            title = w.get('title') or 'Workout'
            session_label = ''
            match = _SESSION_TITLE_RE.match(title)
            if match:
                session_label = match.group(1).title()
                title = match.group(2).strip()
            key = (d.year, d.month)
            if not months or months[-1]['key'] != key:
                months.append({'key': key, 'label': d.strftime('%B %Y'), 'items': []})
            months[-1]['items'].append({
                'iso': d.isoformat(),
                'day': d.day,
                'weekday': d.strftime('%a'),
                'date_label': f"{d.strftime('%a')}, {d.day} {d.strftime('%b %Y')}",
                'title': title,
                'full_title': w.get('title') or 'Workout',
                'session_label': session_label,
                'exercises': w.get('exercise_list') or [],
                'search': ' '.join([
                    w.get('title') or '',
                    d.strftime('%Y-%m-%d'), d.strftime('%d-%m-%y'), f"{d.day} {d.strftime('%b %B %Y %A')}",
                    w.get('exercises') or '',
                ]).lower(),
            })
        return months

    def index():
        if current_user.is_authenticated:
            return redirect(url_for('user_dashboard', username=current_user.username))
        return redirect(url_for('login'))

    @login_required
    def user_dashboard(username):
        try:
            username = validate_username(username)
            normalized_current = (current_user.username or '').strip().lower()

            if username == normalized_current:
                user = current_user
            else:
                user = Session.query(User).filter(func.lower(User.username) == username).first()

            if not user:
                if username != normalized_current:
                    return redirect(url_for('user_dashboard', username=normalized_current or current_user.username))
                raise UserNotFoundError("User not found")

            if user.id != current_user.id and not current_user.is_admin():
                flash("You can only view your own dashboard.", "error")
                return redirect(url_for('user_dashboard', username=normalized_current or current_user.username))

            # Home only shows the last few; the full list lives on /workouts.
            recent_workouts = get_recent_workouts(user, limit=3, include_details=False)
            recent = [item for month in _home_history(recent_workouts) for item in month['items']]

            profile_image_url = get_profile_image_url(getattr(user, 'profile_image', None))

            display_name = (user.full_name or user.username or '').strip()
            first_name = display_name.split()[0] if display_name else ''
            return render_template(
                'index.html',
                first_name=first_name,
                initial=(display_name[:1] or '?').upper(),
                recent=recent,
                profile_image_url=profile_image_url,
            )
        except (ValidationError, UserNotFoundError) as e:
            flash(str(e), "error")
            return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Error in user_dashboard: {e}", exc_info=True)
            flash("An error occurred. Please try again.", "error")
            return redirect(url_for('index'))

    @login_required
    def view_workout(date_str):
        user = current_user
        
        try:
            workout_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_dt = datetime.combine(workout_date, datetime.min.time())
            end_dt = start_dt + timedelta(days=1)
            
            logs = (
                Session.query(WorkoutLog)
                .filter_by(user_id=user.id)
                .filter(WorkoutLog.date >= start_dt)
                .filter(WorkoutLog.date < end_dt)
                .order_by(WorkoutLog.id)
                .all()
            )
            
            if not logs:
                flash("Workout not found.", "error")
                return redirect(url_for('user_dashboard', username=user.username))

            if backfill_bodyweight_log_flags(Session, user.id):
                Session.commit()
                logs = (
                    Session.query(WorkoutLog)
                    .filter_by(user_id=user.id)
                    .filter(WorkoutLog.date >= start_dt)
                    .filter(WorkoutLog.date < end_dt)
                    .order_by(WorkoutLog.id)
                    .all()
                )

            default_back_url = url_for('user_dashboard', username=user.username)
            back_url = default_back_url
            return_to = (request.args.get('return_to') or '').strip()
            if return_to:
                parsed = urlsplit(return_to)
                if (not parsed.scheme) and (not parsed.netloc):
                    candidate = parsed.path or ''
                    if candidate.startswith('/workout/') or candidate.startswith('/stats') or candidate == '/workouts':
                        back_url = candidate + ((f"?{parsed.query}") if parsed.query else '')

            current_workout_url = url_for('view_workout', date_str=date_str)

            workout_name = _clean_workout_title(logs[0].workout_name or "Workout")
            exercise_count = len(logs)
            set_count = 0
            missing_bw_exercises = set()

            rep_row = Session.query(RepRange).filter_by(user_id=user.id).first()
            rep_target_sets = parse_rep_target_sets_text(rep_row.text_content if rep_row else "")
            plan_target_sets = get_plan_target_sets_for_user(Session, user)
            distinct_log_exercises = (
                Session.query(WorkoutLog.exercise)
                .filter(WorkoutLog.user_id == user.id)
                .distinct()
                .all()
            )
            log_ex_index = build_name_index([row[0] for row in distinct_log_exercises or []])
            for names in (log_ex_index.get("by_sig") or {}).values():
                if len(names) < 2:
                    continue
                for name in names:
                    norm = normalize_exercise_name(name)
                    if norm:
                        log_ex_index.setdefault("by_norm", {})[norm] = list(names)

            rows = []
            summary_counts = {"new_best": 0, "up": 0, "down": 0, "steady": 0}
            for log in logs:
                exercise_text = str(getattr(log, 'exercise_string', '') or '')
                inferred_set_count = comparison_set_count(getattr(log, "sets_json", None), exercise_text)
                target_sets, strict_target_sets = resolve_target_sets_for_exercise(
                    exercise_name=log.exercise,
                    exercise_string=exercise_text,
                    rep_target_sets=rep_target_sets,
                    plan_target_sets=plan_target_sets,
                    inferred_set_count=inferred_set_count,
                    default_sets=3,
                )
                is_timed = bool(
                    resolve_timed_exercise_status(
                        Session,
                        user.id,
                        log.exercise,
                        exercise_text,
                        log_ex_index=log_ex_index,
                    ).get("is_timed")
                )
                perf = classify_exercise_performance(
                    Session,
                    user.id,
                    log.exercise,
                    getattr(log, 'sets_json', None),
                    target_sets=target_sets,
                    strict_target_sets=strict_target_sets,
                    is_timed=is_timed,
                    current_log_id=getattr(log, 'id', None),
                    current_exercise_string=exercise_text,
                    summary_mode=False,
                    historical_before_dt=start_dt,
                    log_ex_index=log_ex_index,
                )
                set_count += _count_sets(log.sets_json, log.sets_display)
                uses_bw = _log_uses_bw(log)
                if user.bodyweight is None and uses_bw:
                    missing_bw_exercises.add(log.exercise)

                exercise_candidates = resolve_equivalent_names(log.exercise, log_ex_index) or [log.exercise]
                prev_candidates = (
                    Session.query(WorkoutLog)
                    .filter(WorkoutLog.user_id == user.id)
                    .filter(WorkoutLog.exercise.in_(exercise_candidates))
                    .filter(WorkoutLog.date < start_dt)
                    .order_by(WorkoutLog.date.desc(), WorkoutLog.id.desc())
                    .all()
                )
                # In strict mode only sessions that reached the target set count are comparable.
                comparable = [
                    candidate for candidate in prev_candidates
                    if not strict_target_sets
                    or comparison_set_count(
                        getattr(candidate, "sets_json", None),
                        getattr(candidate, "exercise_string", "") or "",
                    ) >= target_sets
                ]
                prev_log = comparable[0] if comparable else None
                if not prev_log:
                    perf = {**perf, "key": "first_log"}

                # Link "Vs best" to the exact workout the medal was scored against.
                best_log = None
                if prev_log:
                    reference_log_id = perf.get('reference_log_id')
                    best_log = Session.get(WorkoutLog, reference_log_id) if reference_log_id else None
                    if best_log is None:
                        best_log = get_best_log_for_exercise_before_date(
                            Session,
                            user.id,
                            log.exercise,
                            target_sets=target_sets,
                            strict_target_sets=strict_target_sets,
                            log_ex_index=log_ex_index,
                            is_timed=is_timed,
                            workout_day_start_dt=start_dt,
                        )

                def _sets_for(entry):
                    # Label every session of a bodyweight exercise relative to bodyweight
                    # (older logs stored the full load, e.g. 73, which should read "BW").
                    effective = effective_sets_for_log(Session, entry)
                    display = _display_sets(entry, effective, uses_bw)
                    return effective, display, uses_bw

                def _ranked(entry):
                    effective, display, entry_uses_bw = _sets_for(entry)
                    return insights.ranked_sets(display, effective, uses_bodyweight=entry_uses_bw, is_timed=is_timed)

                def _score(entry):
                    effective, _display, _uses = _sets_for(entry)
                    return insights.session_score(effective, top_n=target_sets, is_timed=is_timed)

                today_effective, today_display, _ = _sets_for(log)
                today_ranked = insights.ranked_sets(
                    today_display, today_effective, uses_bodyweight=uses_bw, is_timed=is_timed
                )
                today_score = insights.session_score(today_effective, top_n=target_sets, is_timed=is_timed)

                history = [
                    {"id": entry.id, "date": entry.date, "score": _score(entry), "entry": entry}
                    for entry in comparable[: insights.SPARKLINE_SESSIONS - 1]
                ]
                trend = insights.trend(today_score, history)
                best_info = insights.best_summary(perf, has_history=bool(prev_candidates))

                if perf.get("key") in insights.MEDAL_KEYS:
                    summary_counts["new_best"] += 1
                if trend:
                    summary_counts[trend["direction"]] += 1

                def _comparison(entry):
                    if entry is None:
                        return None
                    entry_iso = entry.date.strftime('%Y-%m-%d')
                    return {
                        "date_text": insights.short_date(entry.date, ref_year=workout_date.year),
                        "url": url_for('view_workout', date_str=entry_iso, return_to=current_workout_url),
                        "ranked": _ranked(entry),
                        "bodyweight": getattr(entry, "bodyweight", None),
                    }

                def _point_details(entry):
                    return {
                        "date_text": insights.long_date(entry.date),
                        "sets": " · ".join(item["label"] for item in _ranked(entry)),
                    }

                best_id = getattr(best_log, "id", None)
                spark_points = [
                    {
                        "score": row["score"],
                        "date": row["date"],
                        "is_best": row["id"] == best_id,
                        "url": url_for(
                            'view_workout',
                            date_str=row["date"].strftime('%Y-%m-%d'),
                            return_to=current_workout_url,
                        ),
                        **_point_details(row["entry"]),
                    }
                    for row in reversed(history)
                ]
                spark_points.append({
                    "score": today_score,
                    "date": log.date,
                    "is_today": True,
                    **_point_details(log),
                })

                last_cmp = _comparison(prev_log)
                best_cmp = _comparison(best_log)
                best_is_last = bool(best_log and prev_log and best_log.id == prev_log.id)
                table = insights.compare_columns(
                    today_ranked,
                    (last_cmp or {}).get("ranked"),
                    None if best_is_last else (best_cmp or {}).get("ranked"),
                ) if last_cmp else []
                # For bodyweight exercises a changed bodyweight moves the % even when the sets match.
                bodyweight_note = None
                if uses_bw and last_cmp and log.bodyweight and last_cmp.get("bodyweight") \
                        and abs(float(log.bodyweight) - float(last_cmp["bodyweight"])) >= 0.1:
                    bodyweight_note = (
                        f"Bodyweight {float(log.bodyweight):g} kg today vs "
                        f"{float(last_cmp['bodyweight']):g} kg last time, which is included in the comparison."
                    )
                rows.append({
                    "name": log.exercise,
                    # Numbers saved without an exercise name (the parser's placeholder).
                    "missing_name": log.exercise == "Unknown Exercise",
                    "performance_key": perf.get("key"),
                    "performance_label": perf.get("label"),
                    "sets_line": insights.format_sets_line(
                        today_display, uses_bodyweight=uses_bw, is_timed=is_timed
                    ) or (log.sets_display or ""),
                    # Strongest first, matching the 1st/2nd/3rd ranking in the expanded table.
                    "sets_ranked": [entry["label"] for entry in today_ranked],
                    "needs_bodyweight": log.exercise in missing_bw_exercises,
                    "trend": trend,
                    "trend_dates": ", ".join(
                        insights.short_date(d, ref_year=workout_date.year) for d in (trend or {}).get("dates", [])
                    ),
                    "best": best_info,
                    "last": last_cmp,
                    "best_cmp": best_cmp,
                    "prev_workout_url": (last_cmp or {}).get("url"),
                    "best_workout_url": (best_cmp or {}).get("url"),
                    "best_is_last": best_is_last,
                    "table": table,
                    "bodyweight_note": bodyweight_note,
                    "spark": insights.sparkline(spark_points, average=(trend or {}).get("average")),
                    "spark_first": insights.short_date(
                        spark_points[0]["date"], ref_year=workout_date.year
                    ),
                    "stats_url": url_for('stats_index', exercise=log.exercise),
                })

            share_token = _make_share_token(user.id, workout_date)
            share_url = url_for('shared_workout', token=share_token, _external=True)

            saved = None
            saved_state = session.get(LOG_SAVED_SESSION_KEY)
            if request.args.get('saved') and isinstance(saved_state, dict) and saved_state.get('date') == date_str:
                saved = saved_state

            return render_template(
                'workout_detail.html',
                date=date_str,
                date_label=f"{workout_date.strftime('%a')}, {workout_date.day} {workout_date.strftime('%b %Y')}",
                workout_name=workout_name,
                rows=rows,
                summary_counts=summary_counts,
                exercise_count=exercise_count,
                set_count=set_count,
                missing_bw_exercises=sorted(missing_bw_exercises),
                share_url=share_url,
                back_url=back_url,
                saved=saved,
                missing_name_count=sum(1 for row in rows if row.get("missing_name")),
            )
        except ValueError:
            flash("That link doesn't point to a workout.", "error")
            return redirect(url_for('user_dashboard', username=user.username))
        except Exception as e:
            logger.error(f"Error viewing workout: {e}", exc_info=True)
            flash("Error loading workout.", "error")
            return redirect(url_for('user_dashboard', username=user.username))

    @login_required
    def workout_summary(date_str):
        # Old post-log summary link (Shortcut replies sent before the redesign): the workout page shows it all.
        return redirect(url_for('view_workout', date_str=date_str))

    @login_required
    def workout_history():
        workouts = get_recent_workouts(current_user, limit=None, include_details=False)
        count = len(workouts)
        subtitle = f"{count} workout{'' if count == 1 else 's'} logged" if count else ''
        return render_template('workout_history.html', history=_home_history(workouts), subtitle=subtitle)

    def _recommend_workout_payload(
        user,
        *,
        use_cache: bool = True,
        cache_key_prefix: str = "u:",
        use_ai: bool = True,
        debug: bool = False,
    ):
        now = time.time()
        cache_key = f"{cache_key_prefix}{user.id}"
        if use_cache:
            with _reco_cache_lock:
                cached = _reco_cache.get(cache_key)
                ttl = cached.get("ttl", 120) if cached else 120
                if cached and now - cached.get("ts", 0) < ttl:
                    return cached["payload"], 200

        try:
            plan_text = get_effective_plan_text(Session, user)
            plan_data = get_workout_days(plan_text or "")
            workout_map = plan_data.get("workout", {}) if isinstance(plan_data, dict) else {}

            categories: list[dict] = []
            plan_days: list[dict] = []
            day_lookup: dict[str, dict] = {}

            for cat, cat_map in workout_map.items():
                if not isinstance(cat_map, dict):
                    continue
                num_days = len(cat_map)
                if num_days > 0:
                    categories.append({"name": str(cat), "num_days": int(num_days)})
                for day_name, exercises in cat_map.items():
                    if not isinstance(day_name, str):
                        continue
                    match = re.search(r"\s+(\d+)$", day_name)
                    if not match:
                        continue
                    day_id = int(match.group(1))
                    entry = {
                        "category": str(cat),
                        "day_id": day_id,
                        "name": day_name,
                        "exercises": exercises if isinstance(exercises, list) else [],
                    }
                    plan_days.append(entry)
                    day_lookup[day_name.strip().lower()] = entry
                    day_lookup[_norm_title_key(day_name)] = entry
                    day_lookup[_norm_day_title_key(day_name)] = entry

            if not categories:
                return {"ok": False, "error": "No workout plan found."}, 400

            # Precompute normalized exercise sets per plan day for overlap scoring.
            plan_days_by_cat: dict[str, list[tuple[dict, set[str]]]] = {}
            for d in plan_days:
                cat = d.get("category")
                if not isinstance(cat, str) or not cat.strip():
                    continue
                ex_set = {_norm_ex_name(x) for x in (d.get("exercises") or []) if _norm_ex_name(x)}
                plan_days_by_cat.setdefault(cat.strip().lower(), []).append((d, ex_set))

            plan_ex_freq: dict[str, int] = {}
            for _cat_key, days in plan_days_by_cat.items():
                for _day, day_ex in days:
                    for ex in (day_ex or set()):
                        plan_ex_freq[ex] = plan_ex_freq.get(ex, 0) + 1
            plan_ex_weight: dict[str, float] = {}
            for ex, freq in plan_ex_freq.items():
                try:
                    f = max(int(freq), 1)
                except Exception:
                    f = 1
                plan_ex_weight[ex] = 1.0 / (float(f) ** 0.5)

            # --- Session detection: exercise-first with optional title hint as a *small* boost. ---
            session_days: list[tuple[dict, set[str]]] = plan_days_by_cat.get("session") or []
            session_day_ex_by_id: dict[int, set[str]] = {}
            session_day_name_by_id: dict[int, str] = {}
            for day, day_ex in session_days:
                try:
                    did = int(day.get("day_id") or 0)
                except Exception:
                    continue
                if did <= 0:
                    continue
                session_day_ex_by_id[did] = set(day_ex or set())
                nm = day.get("name")
                if isinstance(nm, str) and nm.strip():
                    session_day_name_by_id[did] = nm

            for did in list(session_day_ex_by_id.keys()):
                nm0 = session_day_name_by_id.get(int(did)) or ""
                try:
                    s0 = str(nm0 or "").lower()
                except Exception:
                    s0 = ""
                has_tag_word = bool(
                    ("chest" in s0)
                    or ("shoulder" in s0)
                    or ("back" in s0)
                    or ("leg" in s0)
                    or ("bicep" in s0)
                    or ("tricep" in s0)
                    or ("forearm" in s0)
                    or ("abs" in s0)
                )
                if not has_tag_word:
                    extracted = _extract_session_title(plan_text, int(did))
                    if extracted:
                        session_day_name_by_id[int(did)] = extracted

            session_day_tags: dict[int, set[str]] = {}
            for did, nm in session_day_name_by_id.items():
                try:
                    s = str(nm or "").lower()
                except Exception:
                    s = ""
                tags: set[str] = set()
                if "chest" in s:
                    tags.add("chest")
                if "shoulder" in s:
                    tags.add("shoulders")
                if "back" in s:
                    tags.add("back")
                if "leg" in s:
                    tags.add("legs")
                if "bicep" in s:
                    tags.add("biceps")
                if "tricep" in s:
                    tags.add("triceps")
                if "forearm" in s:
                    tags.add("forearms")
                if "abs" in s:
                    tags.add("abs")
                if tags:
                    session_day_tags[int(did)] = tags

            tag_to_exercises: dict[str, set[str]] = {}
            for did, tags in session_day_tags.items():
                exs = session_day_ex_by_id.get(int(did)) or set()
                for t in (tags or set()):
                    tag_to_exercises.setdefault(str(t), set()).update(exs)

            # Down-weight exercises that appear in many session days (accessories) so they don't dominate matches.
            session_ex_freq: dict[str, int] = {}
            for _did, exs in session_day_ex_by_id.items():
                for ex in exs:
                    session_ex_freq[ex] = session_ex_freq.get(ex, 0) + 1

            session_ex_weight: dict[str, float] = {}
            for ex, freq in session_ex_freq.items():
                try:
                    f = max(int(freq), 1)
                except Exception:
                    f = 1
                # 1/sqrt(freq): unique-ish movements ~1.0, very common ones shrink.
                session_ex_weight[ex] = 1.0 / (float(f) ** 0.5)

            session_anchors: dict[int, set[str]] = {}
            for did, exs in session_day_ex_by_id.items():
                ranked = sorted(exs, key=lambda e: session_ex_weight.get(e, 1.0), reverse=True)
                session_anchors[did] = set(ranked[:4])

            session_plan_ex_tokens_by_key: dict[str, set[str]] = {}
            for _did, exs in session_day_ex_by_id.items():
                for ex in (exs or set()):
                    try:
                        toks = {t for t in str(ex).split(" ") if t}
                    except Exception:
                        toks = set()
                    if toks:
                        session_plan_ex_tokens_by_key[str(ex)] = toks
            session_plan_key_set = set(session_plan_ex_tokens_by_key.keys())

            def _map_workout_ex_to_session_keys(workout_ex: set[str]) -> set[str]:
                if not workout_ex:
                    return set()
                muscle_tokens = {
                    "back",
                    "chest",
                    "shoulder",
                    "shoulders",
                    "leg",
                    "legs",
                    "glute",
                    "glutes",
                    "quad",
                    "quads",
                    "hamstring",
                    "hamstrings",
                    "calf",
                    "calves",
                    "bicep",
                    "biceps",
                    "tricep",
                    "triceps",
                    "forearm",
                    "forearms",
                    "abs",
                    "core",
                }
                singleton_ok = {
                    "curl",
                    "extension",
                    "pulldown",
                    "pushdown",
                    "pull",
                    "push",
                    "dip",
                    "pullup",
                    "pullups",
                    "chinup",
                    "chinups",
                    "deadlift",
                    "squat",
                    "lunge",
                    "shrug",
                }
                mapped: set[str] = set()
                for wkey in workout_ex:
                    if not wkey:
                        continue
                    if wkey in session_plan_key_set:
                        mapped.add(wkey)
                        continue

                    try:
                        wtok = {t for t in str(wkey).split(" ") if t}
                    except Exception:
                        wtok = set()
                    if not wtok:
                        mapped.add(wkey)
                        continue

                    best = None
                    best_score = -1
                    for pkey, ptok in session_plan_ex_tokens_by_key.items():
                        if not ptok:
                            continue
                        # Only map when the plan exercise is a subset of the workout tokens.
                        # This lets variants like "wide grip seated row" map to "seated row",
                        # but prevents mapping "seated row" to "barbell seated row".
                        ptok0 = set(ptok)
                        pmus = ptok0.intersection(muscle_tokens)
                        wmus = set(wtok).intersection(muscle_tokens)
                        if pmus and wmus and not set(wmus).issubset(set(pmus)):
                            continue
                        ptok_core = set(ptok0).difference(muscle_tokens)
                        if not ptok_core:
                            continue
                        if not set(ptok_core).issubset(set(wtok)):
                            continue
                        if len(ptok_core) < 2:
                            t0 = next(iter(ptok_core))
                            if str(t0) not in singleton_ok:
                                continue
                        score = len(ptok_core)
                        if score > best_score:
                            best_score = score
                            best = pkey
                    mapped.add(best if best else wkey)
                return mapped

            def _session_title_hint_id(title_str: str) -> int | None:
                if not isinstance(title_str, str) or not title_str:
                    return None
                m = re.search(r"\bsession\s*(\d+)\b", title_str, flags=re.IGNORECASE)
                if not m:
                    return None
                try:
                    return int(m.group(1))
                except Exception:
                    return None

            def _score_session_day(*, workout_ex: set[str], day_id: int) -> dict:
                day_ex = session_day_ex_by_id.get(int(day_id)) or set()
                overlap = workout_ex.intersection(day_ex)
                overlap_count = len(overlap)
                overlap_w = sum(session_ex_weight.get(e, 1.0) for e in overlap)
                # Penalize lots of extras slightly (weights for unknown exercises are lower).
                workout_w = sum(session_ex_weight.get(e, 0.7) for e in workout_ex) or 0.0
                day_w = sum(session_ex_weight.get(e, 1.0) for e in day_ex) or 0.0
                wprec = (overlap_w / workout_w) if workout_w else 0.0
                wrec = (overlap_w / day_w) if day_w else 0.0
                wf1 = (2 * wprec * wrec / (wprec + wrec)) if (wprec + wrec) else 0.0
                anchors = session_anchors.get(int(day_id)) or set()
                anchor_hit = bool(anchors.intersection(overlap))
                return {
                    "wf1": float(wf1),
                    "overlap_count": int(overlap_count),
                    "overlap_w": float(overlap_w),
                    "overlap_ex": set(overlap),
                    "anchor_hit": bool(anchor_hit),
                }

            def _best_session_match(*, workout_ex: set[str], title_hint_id: int | None) -> dict:
                """
                Returns:
                  - accepted: match dict (for day_matches) or None
                  - evidence: dict describing accepted/partial evidence (for cycle credit) or None
                """
                if not isinstance(workout_ex, set) or len(workout_ex) < 2:
                    return {"accepted": None, "evidence": None}
                allow_classify = len(workout_ex) >= 3

                workout_ex = _map_workout_ex_to_session_keys(workout_ex)

                workout_has_biceps = any("curl" in str(ex) for ex in (workout_ex or set()))
                workout_has_triceps = any(
                    any(k in str(ex) for k in ("pushdown", "skull", "extension"))
                    for ex in (workout_ex or set())
                )

                best_accept = None
                second_accept = None
                best_partial = None
                evidence_list: list[dict] = []
                for did in session_day_ex_by_id.keys():
                    s = _score_session_day(workout_ex=workout_ex, day_id=did)
                    # Base acceptance: exercise evidence required.
                    oc = s["overlap_count"]
                    wf1 = s["wf1"]
                    is_accept = bool(
                        allow_classify
                        and (
                            oc >= 4
                            or (oc >= 3 and wf1 >= 0.47)
                            or (s["anchor_hit"] and oc >= 3 and wf1 >= 0.52)
                        )
                    )
                    is_partial = bool(s["anchor_hit"] and oc >= 2 and wf1 >= 0.33)

                    if is_accept or is_partial:
                        creditable0 = bool(
                            s["overlap_count"] >= 4
                            or (s["anchor_hit"] and s["overlap_count"] >= 3 and s["wf1"] >= 0.50)
                        )
                        try:
                            overlap_ex0 = {str(x) for x in (s.get("overlap_ex") or set()) if x}
                        except Exception:
                            overlap_ex0 = set()
                        evidence_list.append(
                            {
                                "day_id": int(did),
                                "creditable": bool(creditable0),
                                "partial": not bool(creditable0),
                                "overlap_ex": sorted(list(overlap_ex0)),
                                "overlap_count": int(s.get("overlap_count") or 0),
                                "wf1": float(s.get("wf1") or 0.0),
                                "anchor_hit": bool(s.get("anchor_hit")),
                                "overlap_w": float(s.get("overlap_w") or 0.0),
                            }
                        )

                    if is_accept:
                        bonus = 0.0
                        if title_hint_id is not None and int(title_hint_id) == int(did):
                            # Title is a hint only; add a small controlled bias if the exercise match is already strong.
                            bonus = 0.03

                        # Exercise-driven tie-break: if the workout clearly contains biceps vs triceps movements,
                        # bias toward plan days whose label matches (does NOT use workout titles).
                        try:
                            nm0 = str(session_day_name_by_id.get(int(did)) or "").lower()
                        except Exception:
                            nm0 = ""
                        day_has_biceps = "bicep" in nm0
                        day_has_triceps = "tricep" in nm0
                        if workout_has_biceps and not workout_has_triceps and day_has_biceps and not day_has_triceps:
                            bonus += 0.02
                        elif workout_has_triceps and not workout_has_biceps and day_has_triceps and not day_has_biceps:
                            bonus += 0.02

                        score_tup = (min(wf1 + bonus, 1.0), s["overlap_w"], s["overlap_count"])
                        cand = {"day_id": int(did), "score": score_tup, "raw": s}
                        if best_accept is None or cand["score"] > best_accept["score"]:
                            second_accept = best_accept
                            best_accept = cand
                        elif second_accept is None or cand["score"] > second_accept["score"]:
                            second_accept = cand
                        continue

                    if is_partial:
                        # For partial evidence we do NOT apply title bonus; exercises are the foundation.
                        bonus = 0.0
                        try:
                            nm0 = str(session_day_name_by_id.get(int(did)) or "").lower()
                        except Exception:
                            nm0 = ""
                        day_has_biceps = "bicep" in nm0
                        day_has_triceps = "tricep" in nm0
                        if workout_has_biceps and not workout_has_triceps and day_has_biceps and not day_has_triceps:
                            bonus += 0.01
                        elif workout_has_triceps and not workout_has_biceps and day_has_triceps and not day_has_biceps:
                            bonus += 0.01
                        score_tup = (min(wf1 + bonus, 1.0), s["overlap_w"], s["overlap_count"])
                        cand = {"day_id": int(did), "score": score_tup, "raw": s}
                        if best_partial is None or cand["score"] > best_partial["score"]:
                            best_partial = cand

                if not best_accept and not best_partial:
                    return {"accepted": None, "evidence": None}

                if best_accept and second_accept:
                    best_primary = float(best_accept["score"][0])
                    second_primary = float(second_accept["score"][0])
                    if (
                        abs(best_primary - second_primary) < 0.04
                        and abs(best_accept["raw"]["overlap_count"] - second_accept["raw"]["overlap_count"]) <= 1
                    ):
                        try:
                            best_ow = float(best_accept["raw"].get("overlap_w") or 0.0)
                            second_ow = float(second_accept["raw"].get("overlap_w") or 0.0)
                        except Exception:
                            best_ow = 0.0
                            second_ow = 0.0
                        best_anchor = bool(best_accept["raw"].get("anchor_hit"))
                        second_anchor = bool(second_accept["raw"].get("anchor_hit"))
                        keep = bool((best_anchor and not second_anchor) or (abs(best_ow - second_ow) >= 0.35))
                        if not keep:
                            if (
                                title_hint_id is not None
                                and int(title_hint_id) == int(best_accept["day_id"])
                                and (best_primary - second_primary) >= 0.02
                            ):
                                pass
                            else:
                                raw0 = best_accept.get("raw") or {}
                                try:
                                    overlap_ex0 = {str(x) for x in (raw0.get("overlap_ex") or set()) if x}
                                except Exception:
                                    overlap_ex0 = set()
                                evidence0 = {
                                    "day_id": int(best_accept["day_id"]),
                                    "creditable": False,
                                    "partial": True,
                                    "overlap_ex": sorted(list(overlap_ex0)),
                                    "overlap_count": int(raw0.get("overlap_count") or 0),
                                    "wf1": float(raw0.get("wf1") or 0.0),
                                    "anchor_hit": bool(raw0.get("anchor_hit")),
                                    "ambiguous": True,
                                }
                                try:
                                    evidence_list = sorted(
                                        evidence_list,
                                        key=lambda x: (
                                            float(x.get("wf1") or 0.0),
                                            float(x.get("overlap_w") or 0.0),
                                            int(x.get("overlap_count") or 0),
                                        ),
                                        reverse=True,
                                    )
                                except Exception:
                                    pass
                                if evidence_list:
                                    evidence_list = evidence_list[:4]
                                return {"accepted": None, "evidence": evidence0, "evidence_list": evidence_list}

                if best_accept:
                    did = int(best_accept["day_id"])
                    raw = best_accept["raw"]
                    match = {
                        "category": "Session",
                        "day_id": did,
                        "day_name": session_day_name_by_id.get(did) or f"Session {did}",
                        "source": "exercises",
                    }

                    # Cycle credit should be a bit stricter than classification.
                    creditable = bool(
                        raw["overlap_count"] >= 4
                        or (raw["anchor_hit"] and raw["overlap_count"] >= 3 and raw["wf1"] >= 0.50)
                    )
                    evidence = {
                        "day_id": did,
                        "creditable": creditable,
                        "partial": not creditable,
                        "overlap_ex": sorted(list(raw["overlap_ex"])),
                        "overlap_count": raw["overlap_count"],
                        "wf1": raw["wf1"],
                        "anchor_hit": raw["anchor_hit"],
                    }
                    try:
                        evidence_list = sorted(
                            evidence_list,
                            key=lambda x: (
                                float(x.get("wf1") or 0.0),
                                float(x.get("overlap_w") or 0.0),
                                int(x.get("overlap_count") or 0),
                            ),
                            reverse=True,
                        )
                    except Exception:
                        pass
                    if evidence_list:
                        evidence_list = evidence_list[:4]
                    return {"accepted": match, "evidence": evidence, "evidence_list": evidence_list}

                did = int(best_partial["day_id"])
                raw = best_partial["raw"]
                evidence = {
                    "day_id": did,
                    "creditable": False,
                    "partial": True,
                    "overlap_ex": sorted(list(raw["overlap_ex"])),
                    "overlap_count": raw["overlap_count"],
                    "wf1": raw["wf1"],
                    "anchor_hit": raw["anchor_hit"],
                }
                try:
                    evidence_list = sorted(
                        evidence_list,
                        key=lambda x: (
                            float(x.get("wf1") or 0.0),
                            float(x.get("overlap_w") or 0.0),
                            int(x.get("overlap_count") or 0),
                        ),
                        reverse=True,
                    )
                except Exception:
                    pass
                if evidence_list:
                    evidence_list = evidence_list[:4]
                return {"accepted": None, "evidence": evidence, "evidence_list": evidence_list}

            recent = get_recent_workouts(user, limit=60)
            recent_context: list[dict] = []

            for w in recent:
                dt = w.get("date")
                title = w.get("title") or "Workout"
                workout_ex = {_norm_ex_name(x) for x in (w.get("exercise_list") or []) if _norm_ex_name(x)}

                session_evidence = None
                day_matches: list[dict] = []

                # Exercise-based best match per category (non-session).
                if workout_ex:
                    workout_w = sum(plan_ex_weight.get(e, 0.7) for e in workout_ex) or 0.0
                    best_by_cat: dict[str, dict] = {}
                    for cat_key, days in plan_days_by_cat.items():
                        if cat_key == "session":
                            continue
                        best = None
                        best_score = None
                        for day, day_ex in days:
                            if not day_ex:
                                continue
                            overlap_set = workout_ex.intersection(day_ex)
                            overlap = len(overlap_set)
                            if overlap < 2:
                                continue
                            overlap_w = sum(plan_ex_weight.get(e, 1.0) for e in overlap_set)
                            day_w = sum(plan_ex_weight.get(e, 1.0) for e in day_ex) or 0.0
                            precision = (overlap_w / workout_w) if workout_w else 0.0
                            recall = (overlap_w / day_w) if day_w else 0.0
                            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
                            score = (f1, overlap_w, overlap)
                            if best_score is None or score > best_score:
                                best_score = score
                                best = day
                        if best and best_score is not None:
                            f1, overlap_w, overlap = best_score
                            if overlap >= 4 or (overlap >= 3 and f1 >= 0.5) or (overlap >= 2 and overlap_w >= 2.6 and f1 >= 0.58):
                                best_by_cat[cat_key] = {
                                    "category": best.get("category"),
                                    "day_id": best.get("day_id"),
                                    "day_name": best.get("name"),
                                    "source": "exercises",
                                }
                    day_matches.extend(best_by_cat.values())

                # Session match: exercise-first, title is only a small hint boost.
                if workout_ex and session_day_ex_by_id:
                    sm = _best_session_match(workout_ex=workout_ex, title_hint_id=None)
                    if isinstance(sm, dict):
                        accepted = sm.get("accepted")
                        if isinstance(accepted, dict):
                            day_matches.append(accepted)
                        ev = sm.get("evidence")
                        if isinstance(ev, dict):
                            session_evidence = ev
                        evl = sm.get("evidence_list")
                        if isinstance(evl, list) and evl:
                            try:
                                session_evidence_list = [x for x in evl if isinstance(x, dict) and isinstance(x.get("day_id"), int)]
                            except Exception:
                                session_evidence_list = []
                        else:
                            session_evidence_list = []
                    else:
                        session_evidence_list = []
                else:
                    session_evidence_list = []

                # Deduplicate: one match per category, prefer exercise-based.
                dedup: dict[str, dict] = {}
                for m in day_matches:
                    cat = m.get("category")
                    if not isinstance(cat, str) or not cat.strip():
                        continue
                    cat_key = cat.strip().lower()
                    prev = dedup.get(cat_key)
                    if not prev:
                        dedup[cat_key] = m
                        continue
                    if prev.get("source") != "exercises" and m.get("source") == "exercises":
                        dedup[cat_key] = m
                day_matches = list(dedup.values())

                trained_categories: set[str] = set()
                if workout_ex:
                    for cat_key, days in plan_days_by_cat.items():
                        best_score = 0.0
                        for _day, day_ex in days:
                            if not day_ex:
                                continue
                            overlap_set = workout_ex.intersection(day_ex)
                            overlap = len(overlap_set)
                            if overlap < 2:
                                continue
                            overlap_w = sum(plan_ex_weight.get(e, 1.0) for e in overlap_set)
                            day_w = sum(plan_ex_weight.get(e, 1.0) for e in day_ex) or 0.0
                            score = (overlap_w / day_w) if day_w else 0.0
                            if score > best_score:
                                best_score = score
                        if best_score >= 0.30:
                            for c in categories:
                                nm = c.get("name") if isinstance(c, dict) else None
                                if isinstance(nm, str) and nm.strip().lower() == cat_key:
                                    trained_categories.add(nm.strip())
                                    break

                for m in day_matches:
                    cat = m.get("category")
                    if isinstance(cat, str) and cat.strip():
                        if m.get("source") == "exercises":
                            trained_categories.add(cat.strip())

                # Primary: prefer exercises for the UI label + per-workout day_id.
                primary = None
                for m in day_matches:
                    if m.get("source") == "exercises":
                        primary = m
                        break
                if not primary and day_matches:
                    primary = day_matches[0]

                matched_day = None
                matched_source = None
                if primary:
                    if primary.get("source") == "exercises":
                        for d in plan_days:
                            if (
                                str(d.get("category") or "").strip().lower()
                                == str(primary.get("category") or "").strip().lower()
                                and d.get("day_id") == primary.get("day_id")
                            ):
                                matched_day = d
                                matched_source = primary.get("source")
                                break

                recent_context.append(
                    {
                        "date": dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt),
                        "title": title,
                        "exercises": w.get("exercises") or "",
                        "exercise_list": w.get("exercise_list") or [],
                        "exercise_details": w.get("exercise_details") or "",
                        "session_evidence": session_evidence,
                        "session_evidence_list": session_evidence_list,
                        "category": matched_day["category"] if matched_day else None,
                        "day_id": matched_day["day_id"] if matched_day else None,
                        "day_name": matched_day["name"] if matched_day else None,
                        "match_source": matched_source,
                        "day_matches": day_matches,
                        "trained_categories": sorted(list(trained_categories)),
                    }
                )

            today = local_today()
            matched_items: list[tuple[datetime.date, str, int]] = []
            category_trained: dict[str, datetime.date] = {}
            session_evidence_items: list[tuple[datetime.date, dict]] = []

            for item in recent_context:
                date_str = item.get("date")
                try:
                    d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
                except Exception:
                    continue

                trained = item.get("trained_categories")
                if isinstance(trained, list):
                    for cat in trained:
                        if not isinstance(cat, str) or not cat.strip():
                            continue
                        key = cat.strip().lower()
                        prev = category_trained.get(key)
                        if prev is None or d > prev:
                            category_trained[key] = d

                ev = item.get("session_evidence")
                best_ev = None
                if isinstance(ev, dict) and isinstance(ev.get("day_id"), int):
                    best_ev = ev
                else:
                    evl = item.get("session_evidence_list")
                    if isinstance(evl, list) and evl:
                        for ev1 in evl:
                            if isinstance(ev1, dict) and isinstance(ev1.get("day_id"), int):
                                best_ev = ev1
                                break
                if isinstance(best_ev, dict):
                    session_evidence_items.append((d, best_ev))

                matches = item.get("day_matches")
                if isinstance(matches, list):
                    for m in matches:
                        if not isinstance(m, dict):
                            continue
                        cat = m.get("category")
                        day_id = m.get("day_id")
                        src = m.get("source")
                        if not (isinstance(cat, str) and cat.strip()):
                            continue
                        if not isinstance(day_id, int):
                            continue
                        if src != "exercises":
                            continue
                        cat_key = cat.strip().lower()
                        if cat_key == "session":
                            # Session cycle is tracked via session_evidence_items (exercise-first).
                            continue
                        matched_items.append((d, cat_key, int(day_id)))

            matched_items.sort(key=lambda x: x[0])
            session_evidence_items.sort(key=lambda x: x[0])

            # --- Compute cycle done/missing per category (non-session) ---
            cycle_done: dict[str, set[int]] = {}
            num_days_by_cat: dict[str, int] = {}
            for c in categories:
                if not isinstance(c, dict):
                    continue
                name = c.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                key = name.strip().lower()
                nd = int(c.get("num_days") or 0)
                if nd > 0:
                    num_days_by_cat[key] = nd
                    cycle_done.setdefault(key, set())

            for d, cat_key, day_id in matched_items:
                nd = num_days_by_cat.get(cat_key)
                if not nd or day_id < 1 or day_id > int(nd):
                    continue
                s = cycle_done.setdefault(cat_key, set())
                s.add(int(day_id))
                if len(s) >= int(nd):
                    s.clear()

            # --- Session cycle progress: credit based on exercise evidence (with partial aggregation). ---
            heading_sessions = plan_data.get("heading_sessions") if isinstance(plan_data, dict) else None
            session_headings = plan_data.get("headings") if isinstance(plan_data, dict) else None
            if not (isinstance(session_headings, list) and session_headings):
                if isinstance(heading_sessions, dict) and heading_sessions:
                    session_headings = sorted([h for h in heading_sessions.keys() if isinstance(h, str)])
                else:
                    session_headings = []

            cycles: list[list[int]] = []
            if isinstance(heading_sessions, dict) and session_headings:
                for h in session_headings:
                    ids = heading_sessions.get(h)
                    if isinstance(ids, list) and ids:
                        cleaned = sorted({int(x) for x in ids if isinstance(x, int)})
                        if cleaned:
                            cycles.append(cleaned)
            if not cycles and session_day_ex_by_id:
                cycles = [sorted(session_day_ex_by_id.keys())]

            day_to_cycle_index: dict[int, int] = {}
            for idx, ids in enumerate(cycles):
                for sid in ids:
                    day_to_cycle_index[int(sid)] = int(idx)

            def _session_union_creditable(day_id: int, covered_ex: set[str]) -> bool:
                day_ex = session_day_ex_by_id.get(int(day_id)) or set()
                if not day_ex:
                    return False
                covered = set(covered_ex or set()).intersection(day_ex)
                oc = len(covered)
                if oc >= 4:
                    return True
                overlap_w = sum(session_ex_weight.get(e, 1.0) for e in covered)
                day_w = sum(session_ex_weight.get(e, 1.0) for e in day_ex) or 0.0
                recall = (overlap_w / day_w) if day_w else 0.0
                anchors = session_anchors.get(int(day_id)) or set()
                anchor_hit = bool(anchors.intersection(covered))
                anchor_cov = 0
                try:
                    anchor_cov = len(set(anchors).intersection(covered))
                except Exception:
                    anchor_cov = 0
                return bool(
                    (anchor_hit and oc >= 3 and recall >= 0.45)
                    or (anchor_cov >= 2 and oc >= 3 and recall >= 0.42)
                    or (anchor_hit and oc >= 3 and overlap_w >= 2.6)
                    or (anchor_cov >= 2 and oc >= 3 and overlap_w >= 2.4)
                )

            session_credit_events: list[tuple[datetime.date, int]] = []
            pending: dict[int, dict] = {}
            window_days = 35
            for d, ev in session_evidence_items:
                try:
                    sid = int(ev.get("day_id"))
                except Exception:
                    continue
                if sid <= 0:
                    continue

                overlap_ex = set()
                try:
                    overlap_ex = {str(x) for x in (ev.get("overlap_ex") or []) if isinstance(x, str) and x}
                except Exception:
                    overlap_ex = set()

                if bool(ev.get("creditable")):
                    session_credit_events.append((d, sid))
                    pending.pop(sid, None)
                    continue

                # Partial / non-credit evidence: aggregate within a small window.
                p = pending.get(sid)
                if not p or (d - p.get("start", d)).days > window_days:
                    pending[sid] = {"start": d, "covered": set(overlap_ex)}
                else:
                    p["covered"] = set(p.get("covered") or set()).union(overlap_ex)

                if _session_union_creditable(sid, set(pending[sid].get("covered") or set())):
                    session_credit_events.append((d, sid))
                    pending.pop(sid, None)

            last_workout_ex0: set[str] = set()
            last_workout_date0: datetime.date | None = None
            try:
                if recent_context:
                    last_workout_ex0 = {
                        _norm_ex_name(x)
                        for x in (recent_context[0].get("exercise_list") or [])
                        if _norm_ex_name(x)
                    }
                    last_workout_date0 = datetime.strptime(
                        str(recent_context[0].get("date"))[:10], "%Y-%m-%d"
                    ).date()
            except Exception:
                last_workout_ex0 = set()
                last_workout_date0 = None

            last_done_by_session_id: dict[int, datetime.date] = {}
            tag_last_done: dict[str, datetime.date] = {}
            for d0, sid0 in session_credit_events:
                try:
                    sid_i = int(sid0)
                except Exception:
                    continue
                prev = last_done_by_session_id.get(sid_i)
                if prev is None or d0 > prev:
                    last_done_by_session_id[sid_i] = d0
                for tag in (session_day_tags.get(sid_i) or set()):
                    prevt = tag_last_done.get(tag)
                    if prevt is None or d0 > prevt:
                        tag_last_done[tag] = d0

            if session_day_tags and recent_context:
                try:
                    scan_window_days = 12
                    max_scan_workouts = 30
                    for it in (recent_context[:max_scan_workouts] if isinstance(recent_context, list) else []):
                        date_str = it.get("date")
                        try:
                            d_it = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
                        except Exception:
                            continue
                        try:
                            if (today - d_it).days > int(scan_window_days):
                                continue
                        except Exception:
                            continue

                        ev_candidates: list[dict] = []
                        evl = it.get("session_evidence_list")
                        if isinstance(evl, list) and evl:
                            for ev0 in evl:
                                if isinstance(ev0, dict) and isinstance(ev0.get("day_id"), int):
                                    ev_candidates.append(ev0)
                        ev1 = it.get("session_evidence")
                        if isinstance(ev1, dict) and isinstance(ev1.get("day_id"), int):
                            ev_candidates.append(ev1)
                        if not ev_candidates:
                            continue

                        strong: list[tuple[tuple, dict]] = []
                        for ev in ev_candidates:
                            try:
                                did = int(ev.get("day_id"))
                            except Exception:
                                continue
                            if did <= 0:
                                continue
                            creditable = bool(ev.get("creditable"))
                            try:
                                overlap_w = float(ev.get("overlap_w") or 0.0)
                            except Exception:
                                overlap_w = 0.0
                            try:
                                wf1 = float(ev.get("wf1") or 0.0)
                            except Exception:
                                wf1 = 0.0
                            try:
                                oc = int(ev.get("overlap_count") or 0)
                            except Exception:
                                oc = 0
                            anchor_hit = bool(ev.get("anchor_hit"))

                            is_strong = bool(
                                creditable
                                or oc >= 4
                                or (anchor_hit and oc >= 3 and wf1 >= 0.45)
                                or (overlap_w >= 2.8 and wf1 >= 0.42)
                            )
                            if not is_strong:
                                continue
                            score = (
                                int(creditable),
                                float(overlap_w),
                                float(wf1),
                                int(oc),
                            )
                            strong.append((score, ev))

                        if not strong:
                            continue
                        try:
                            strong = sorted(strong, key=lambda x: x[0], reverse=True)
                        except Exception:
                            pass

                        for _score, ev in strong[:2]:
                            try:
                                did = int(ev.get("day_id"))
                            except Exception:
                                continue
                            tags = session_day_tags.get(int(did)) or set()
                            if not tags:
                                continue
                            for tag in tags:
                                prevt = tag_last_done.get(str(tag))
                                if prevt is None or d_it > prevt:
                                    tag_last_done[str(tag)] = d_it
                except Exception:
                    pass

            # Simulate cycle progression from credited session events.
            session_done_set: set[int] = set()
            session_missing: list[int] = []
            session_next_day: int = 1
            session_cycle_label = None
            last_session_date = None

            session_choice_reason = None
            session_base_cycle_idx = None
            session_last_sid_in_cycle = None
            session_candidate_order: list[int] = []
            session_candidate_scan: list[dict] = []
            done_by_cycle: list[set[int]] = []
            last_sid_by_cycle: list[int | None] = []

            if cycles:
                cur_cycle_idx = 0
                cycle_sets = [set(ids) for ids in cycles]
                done_by_cycle: list[set[int]] = [set() for _ in cycles]
                last_sid_by_cycle: list[int | None] = [None for _ in cycles]
                last_event_cycle_idx: int | None = None
                advance_cycle_idx: int | None = None

                try:
                    session_credit_events0 = sorted(session_credit_events, key=lambda x: x[0])
                except Exception:
                    session_credit_events0 = list(session_credit_events)

                for d, sid in session_credit_events0:
                    idx = day_to_cycle_index.get(int(sid))
                    if idx is None:
                        continue
                    idx = int(idx)
                    done_by_cycle[idx].add(int(sid))
                    last_sid_by_cycle[idx] = int(sid)
                    last_session_date = d
                    last_event_cycle_idx = idx
                    if done_by_cycle[idx].issuperset(cycle_sets[idx]):
                        done_by_cycle[idx] = set()
                        last_sid_by_cycle[idx] = None
                        advance_cycle_idx = (idx + 1) % len(cycles)

                if advance_cycle_idx is not None:
                    cur_cycle_idx = int(advance_cycle_idx)
                elif last_event_cycle_idx is not None:
                    cur_cycle_idx = int(last_event_cycle_idx)

                base_cycle_idx = int(cur_cycle_idx)
                session_base_cycle_idx = int(base_cycle_idx)

                cur_cycle_idx = int(base_cycle_idx)
                current_cycle_ids = cycles[cur_cycle_idx] if 0 <= cur_cycle_idx < len(cycles) else []
                session_done_set = set(done_by_cycle[cur_cycle_idx] or set()) if 0 <= cur_cycle_idx < len(cycles) else set()
                session_missing = [i for i in current_cycle_ids if i not in session_done_set]
                if not session_missing:
                    session_missing = list(current_cycle_ids)

                session_last_sid_in_cycle = (
                    last_sid_by_cycle[cur_cycle_idx]
                    if 0 <= cur_cycle_idx < len(last_sid_by_cycle)
                    else None
                )

                tag_min_rest_days = {
                    "back": 2,
                    "legs": 2,
                    "chest": 2,
                    "shoulders": 2,
                    "biceps": 1,
                    "triceps": 1,
                    "forearms": 0,
                    "abs": 0,
                }

                scan_ids: list[int] = []
                if current_cycle_ids:
                    start_idx = 0
                    if session_last_sid_in_cycle in current_cycle_ids:
                        try:
                            start_idx = (
                                int(current_cycle_ids.index(int(session_last_sid_in_cycle))) + 1
                            ) % len(current_cycle_ids)
                        except Exception:
                            start_idx = 0
                    scan_ids = list(current_cycle_ids[start_idx:]) + list(current_cycle_ids[:start_idx])

                missing_set = set(int(x) for x in (session_missing or []) if isinstance(x, int))
                if missing_set and scan_ids:
                    scan_ids = [int(x) for x in scan_ids if int(x) in missing_set]
                elif missing_set:
                    scan_ids = [int(x) for x in (session_missing or []) if isinstance(x, int)]
                else:
                    scan_ids = [int(x) for x in (current_cycle_ids or []) if isinstance(x, int)]

                session_candidate_order = list(scan_ids)

                session_next_day = int(min(current_cycle_ids)) if current_cycle_ids else 1
                session_choice_reason = "cycle_empty" if not scan_ids else None
                first_missing_sid = None
                chosen_ready_sid = None

                for cand_sid in scan_ids:
                    try:
                        cand_sid_i = int(cand_sid)
                    except Exception:
                        continue
                    if cand_sid_i in (session_done_set or set()):
                        continue
                    if first_missing_sid is None:
                        first_missing_sid = int(cand_sid_i)

                    tags = session_day_tags.get(int(cand_sid_i)) or set()
                    ready = True
                    min_days_since_tag = 999
                    rest_failures: list[dict] = []

                    if tags:
                        for t in tags:
                            td = tag_last_done.get(str(t))
                            ds = 999
                            if td:
                                try:
                                    ds = max((today - td).days, 0)
                                except Exception:
                                    ds = 999
                            min_days_since_tag = min(min_days_since_tag, int(ds))
                            need = int(tag_min_rest_days.get(str(t), 1))
                            if td and int(ds) < int(need):
                                ready = False
                                if debug:
                                    rest_failures.append(
                                        {
                                            "tag": str(t),
                                            "days_since": int(ds),
                                            "min_rest": int(need),
                                            "last_done": td.isoformat() if hasattr(td, "isoformat") else str(td),
                                        }
                                    )

                    if debug:
                        session_candidate_scan.append(
                            {
                                "sid": int(cand_sid_i),
                                "tags": sorted([str(x) for x in (tags or set()) if x]),
                                "ready": bool(ready),
                                "min_days_since_tag": int(min_days_since_tag),
                                "rest_failures": rest_failures,
                            }
                        )

                    if ready:
                        chosen_ready_sid = int(cand_sid_i)
                        break

                if chosen_ready_sid is not None:
                    session_next_day = int(chosen_ready_sid)
                    session_choice_reason = "forward_first_ready"
                elif first_missing_sid is not None:
                    session_next_day = int(first_missing_sid)
                    session_choice_reason = "forward_fallback_not_ready"
                elif not session_choice_reason:
                    session_choice_reason = "no_candidates"

                if isinstance(session_headings, list) and len(session_headings) == len(cycles):
                    session_cycle_label = session_headings[cur_cycle_idx]

            if last_session_date:
                prev = category_trained.get("session")
                if prev is None or last_session_date > prev:
                    category_trained["session"] = last_session_date

            for c in categories:
                if not isinstance(c, dict):
                    continue
                name = c.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                cat_key = name.strip().lower()
                nd = int(c.get("num_days") or 0)
                done_set = cycle_done.get(cat_key) or set()

                if cat_key == "session" and session_day_ex_by_id:
                    c["cycle_done_day_ids"] = sorted(list(session_done_set))
                    c["cycle_missing_day_ids"] = session_missing or sorted(session_day_ex_by_id.keys())
                    last_date = category_trained.get("session")
                    c["last_done_date"] = last_date.isoformat() if last_date else None
                    c["next_day_id"] = int(session_next_day or 1)
                    if session_cycle_label:
                        c["cycle_label"] = session_cycle_label
                    continue

                missing = [i for i in range(1, nd + 1) if i not in done_set] if nd > 0 else [1]
                next_day = int(min(missing)) if missing else 1
                last_date = category_trained.get(cat_key)
                c["cycle_done_day_ids"] = sorted(done_set)
                c["cycle_missing_day_ids"] = missing
                c["last_done_date"] = last_date.isoformat() if last_date else None
                c["next_day_id"] = next_day

            # --- Choose a category/day (fallback heuristic) ---
            chosen_category = None
            chosen_next_day = 1
            best_score = None

            total_plan_days = 0
            try:
                total_plan_days = sum(int(c.get("num_days") or 0) for c in categories if isinstance(c, dict))
            except Exception:
                total_plan_days = 0
            if total_plan_days <= 0:
                total_plan_days = 1

            last_any_workout_date = None
            last_workout_ex = set()
            try:
                if recent_context:
                    last_any_workout_date = datetime.strptime(str(recent_context[0].get("date"))[:10], "%Y-%m-%d").date()
                    last_workout_ex = {
                        _norm_ex_name(x)
                        for x in (recent_context[0].get("exercise_list") or [])
                        if _norm_ex_name(x)
                    }
            except Exception:
                last_any_workout_date = None
                last_workout_ex = set()
            days_since_any = 999
            try:
                if last_any_workout_date:
                    days_since_any = max((today - last_any_workout_date).days, 0)
            except Exception:
                days_since_any = 999

            for c in categories:
                if not isinstance(c, dict):
                    continue
                name = c.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                nd = int(c.get("num_days") or 0)
                next_day = int(c.get("next_day_id") or 1)

                last_done_date = c.get("last_done_date")
                last_d = None
                if isinstance(last_done_date, str) and last_done_date:
                    try:
                        last_d = datetime.strptime(last_done_date[:10], "%Y-%m-%d").date()
                    except Exception:
                        last_d = None
                days_since = 999 if not last_d else max((today - last_d).days, 0)

                try:
                    missing_count = len(c.get("cycle_missing_day_ids") or [])
                except Exception:
                    missing_count = 0

                expected_spacing = float(total_plan_days) / float(max(nd, 1))
                behind = float(days_since) / float(max(expected_spacing, 1.0))
                if days_since <= 1:
                    behind -= 0.75

                overlap_ratio = 0.0
                try:
                    if last_workout_ex:
                        day_ex = None
                        for d0, ex0 in (plan_days_by_cat.get(name.strip().lower()) or []):
                            if int(d0.get("day_id") or 0) == int(next_day):
                                day_ex = ex0
                                break
                        if isinstance(day_ex, set) and day_ex:
                            overlap_set = last_workout_ex.intersection(day_ex)
                            overlap_w = sum(plan_ex_weight.get(e, 1.0) for e in overlap_set)
                            day_w = sum(plan_ex_weight.get(e, 1.0) for e in day_ex) or 0.0
                            overlap_ratio = (overlap_w / day_w) if day_w else 0.0
                except Exception:
                    overlap_ratio = 0.0
                behind -= min(max(float(overlap_ratio), 0.0), 1.0) * 0.6

                next_day_len = 0
                try:
                    for d0, ex0 in (plan_days_by_cat.get(name.strip().lower()) or []):
                        if int(d0.get("day_id") or 0) == int(next_day):
                            next_day_len = len(ex0 or set())
                            break
                except Exception:
                    next_day_len = 0
                if days_since_any >= 7 and next_day_len:
                    behind += max(0.0, (8.0 - float(next_day_len)) * 0.02)

                score = (behind, days_since, missing_count, -nd)
                if best_score is None or score > best_score:
                    best_score = score
                    chosen_category = name.strip()
                    chosen_next_day = next_day

            if not chosen_category:
                chosen_category = categories[0]["name"]
                chosen_next_day = int(categories[0].get("next_day_id") or 1)

            from services.gemini import GeminiService, GeminiServiceError

            api_keys = (
                Session.query(UserApiKey)
                .filter_by(user_id=user.id, is_active=True)
                .order_by(UserApiKey.created_at.desc())
                .all()
            )
            api_key_payloads = [
                {"id": key.id, "api_key": key.api_key, "account_label": key.account_label}
                for key in api_keys
                if key.api_key and key_provider(key.api_key) == "gemini"  # this feature only speaks Gemini
            ]

            fallback_warning = None
            source = "fallback"
            reco = {
                "category": chosen_category,
                "day_id": int(chosen_next_day),
                "reasons": [],
                "model": "heuristic",
            }

            if use_ai:
                try:
                    reco_ai = GeminiService.recommend_workout(
                        categories=categories,
                        recent_workouts=recent_context,
                        plan_days=plan_days,
                        api_keys=api_key_payloads,
                    )
                    if isinstance(reco_ai, dict) and isinstance(reco_ai.get("category"), str) and reco_ai.get("category").strip():
                        reco["category"] = reco_ai.get("category").strip()
                    if isinstance(reco_ai, dict) and isinstance(reco_ai.get("day_id"), int):
                        reco["day_id"] = int(reco_ai.get("day_id"))
                    if isinstance(reco_ai, dict) and isinstance(reco_ai.get("reasons"), list):
                        reco["reasons"] = reco_ai.get("reasons") or []
                    reco["model"] = reco_ai.get("model") if isinstance(reco_ai, dict) else reco.get("model")
                    key_id = reco_ai.get("key_id") if isinstance(reco_ai, dict) else None
                    if key_id:
                        key_row = Session.query(UserApiKey).filter_by(id=key_id, user_id=user.id).first()
                        if key_row:
                            key_row.last_used_at = utc_now()
                            Session.commit()
                    source = "gemini"
                except GeminiServiceError as e:
                    logger.warning(f"Gemini unavailable, using fallback: {e}")
                    fallback_warning = "Gemini is busy right now. Showing a smart fallback suggestion."
            else:
                source = "heuristic"

            if not isinstance(reco.get("reasons"), list) or len(reco.get("reasons") or []) < 3:
                try:
                    reco["reasons"] = GeminiService._build_reasons_from_history(
                        category=str(reco.get("category") or ""),
                        day_id=int(reco.get("day_id") or 1),
                        categories=categories,
                        plan_days=plan_days,
                        recent_workouts=recent_context,
                    )
                except Exception:
                    reco["reasons"] = [
                        "Recommended based on your plan and recent workouts.",
                        "Keeps your training split balanced.",
                        "Suggested to stay consistent with your program.",
                    ]

            raw_category = (reco.get("category") or "").strip()
            raw_day_id = int(reco.get("day_id") or 0)

            category_lookup = {c["name"].strip().lower(): c for c in categories}
            chosen = category_lookup.get(raw_category.lower())
            if not chosen:
                chosen = categories[0]
                raw_category = chosen["name"]

            num_days = int(chosen.get("num_days") or 0)
            if raw_day_id < 1 or raw_day_id > num_days:
                raw_day_id = 1

            deep_link = url_for("retrieve_final", category=raw_category, day_id=raw_day_id)

            display_label = ""
            try:
                match_day = next(
                    (
                        d
                        for d in plan_days
                        if isinstance(d, dict)
                        and str(d.get("category") or "").strip().lower() == str(raw_category).strip().lower()
                        and int(d.get("day_id") or 0) == int(raw_day_id)
                    ),
                    None,
                )
                if match_day and isinstance(match_day.get("name"), str):
                    display_label = _format_plan_day_label(match_day.get("name"))
            except Exception:
                display_label = ""

            if str(raw_category).strip().lower() == "session" and (
                not display_label or display_label.strip().lower() == "session"
            ):
                extracted = _extract_session_title(plan_text, raw_day_id)
                if extracted:
                    display_label = extracted

            payload = {
                "ok": True,
                "category": raw_category,
                "day_id": raw_day_id,
                "label": display_label,
                "reasons": reco.get("reasons") or [],
                "url": deep_link,
                "model": reco.get("model"),
                "source": source,
                "warning": fallback_warning,
            }

            if debug:
                try:
                    sess_evidence_tail = []
                    for dd, ev in (session_evidence_items[-25:] if isinstance(session_evidence_items, list) else []):
                        if not isinstance(ev, dict):
                            continue
                        row = dict(ev)
                        row["date"] = dd.isoformat() if hasattr(dd, "isoformat") else str(dd)
                        sess_evidence_tail.append(row)
                except Exception:
                    sess_evidence_tail = []
                try:
                    sess_credit = [
                        ((d0.isoformat() if hasattr(d0, "isoformat") else str(d0)), int(sid0))
                        for d0, sid0 in (session_credit_events or [])
                    ]
                except Exception:
                    sess_credit = []
                payload["debug"] = {
                    "session_next_day": int(session_next_day or 1),
                    "session_cycle_label": session_cycle_label,
                    "session_base_cycle_idx": session_base_cycle_idx,
                    "session_last_sid_in_cycle": session_last_sid_in_cycle,
                    "session_choice_reason": session_choice_reason,
                    "session_candidate_order": [int(x) for x in (session_candidate_order or []) if isinstance(x, int)],
                    "session_candidate_scan": session_candidate_scan,
                    "session_cycles": [[int(x) for x in ids] for ids in (cycles or []) if isinstance(ids, list)],
                    "session_done_by_cycle": [sorted([int(x) for x in (s or set())]) for s in (done_by_cycle or [])],
                    "session_last_sid_by_cycle": [int(x) if isinstance(x, int) else None for x in (last_sid_by_cycle or [])],
                    "session_done_day_ids": sorted([int(x) for x in (session_done_set or set())]),
                    "session_missing_day_ids": [int(x) for x in (session_missing or [])],
                    "session_credit_events": sess_credit,
                    "session_evidence_tail": sess_evidence_tail,
                    "tag_last_done": {
                        str(k): (v.isoformat() if hasattr(v, "isoformat") else str(v))
                        for k, v in (tag_last_done or {}).items()
                        if k and v
                    },
                }

            if use_cache:
                with _reco_cache_lock:
                    ttl = 60 if source == "fallback" else 120
                    _reco_cache[cache_key] = {"ts": now, "payload": payload, "ttl": ttl}

            return payload, 200
        except Exception as e:
            logger.error(f"Workout recommendation failed: {e}", exc_info=True)
            return {"ok": False, "error": "Unable to generate a recommendation right now."}, 500

    @login_required
    def recommend_workout_api():
        user = current_user
        nocache = str(request.args.get("nocache") or "").strip().lower() in {"1", "true", "yes"}
        debug = str(request.args.get("debug") or "").strip().lower() in {"1", "true", "yes"}
        ai_arg = str(request.args.get("ai") or "").strip().lower()
        use_ai = ai_arg not in {"0", "false", "no", "off"}
        payload, status = _recommend_workout_payload(
            user,
            use_cache=not nocache,
            cache_key_prefix="u:",
            use_ai=use_ai,
            debug=debug,
        )
        return jsonify(payload), status

    @login_required
    def history_qa_api():
        user = current_user
        try:
            if not user.is_admin():
                return jsonify({"ok": False, "error": "AI assistant is currently limited to admins."}), 403
            body = request.get_json(silent=True)
            if body is None:
                body = {}
            question = body.get('question')
            context_exercise = body.get('exercise')
            context_metric = body.get('metric')
            context_date = body.get('date')

            api_keys = (
                Session.query(UserApiKey)
                .filter_by(user_id=user.id, is_active=True)
                .order_by(UserApiKey.created_at.desc())
                .all()
            )
            api_key_payloads = [
                {"id": key.id, "api_key": key.api_key, "account_label": key.account_label}
                for key in api_keys
                if key.api_key and key_provider(key.api_key) == "gemini"  # this feature only speaks Gemini
            ]

            from services.history_qa import answer_history_question

            exercises = (
                Session.query(WorkoutLog.exercise)
                .filter_by(user_id=user.id)
                .distinct()
                .order_by(WorkoutLog.exercise)
                .all()
            )
            exercise_options = [e[0] for e in exercises if e and e[0]]

            payload = answer_history_question(
                Session,
                user,
                question=str(question or ''),
                context_exercise=str(context_exercise or '').strip() or None,
                context_metric=str(context_metric or '').strip() or None,
                context_date=str(context_date or '').strip() or None,
                api_keys=api_key_payloads,
                exercise_options=exercise_options,
            )

            if not isinstance(payload, dict):
                return jsonify({"ok": False, "error": "Unexpected response."}), 500
            status = 200 if payload.get('ok') else 400
            return jsonify(payload), status
        except Exception as e:
            logger.error(f"History QA failed: {e}", exc_info=True)
            return jsonify({"ok": False, "error": "Unable to answer right now."}), 500

    def _active_api_key_payloads(user):
        return [
            {"id": key.id, "api_key": key.api_key, "account_label": key.account_label}
            for key in (
                Session.query(UserApiKey)
                .filter_by(user_id=user.id, is_active=True)
                .order_by(UserApiKey.created_at.desc())
                .all()
            )
            if key.api_key
        ]

    def _coach_finish(user, payload):
        """Record the answer for review, stamp the key's last use, and shape it for the client."""
        from services import coach_answers

        answer_id = coach_answers.record(Session, user, payload)
        payload.pop("usage", None)
        if answer_id:
            payload["answer_id"] = answer_id
        key_id = payload.pop("key_id", None)
        if key_id:
            key_row = Session.query(UserApiKey).filter_by(id=key_id, user_id=user.id).first()
            if key_row:
                key_row.last_used_at = utc_now()
                Session.commit()
        return payload

    @login_required
    def ai_coach_api():
        user = current_user
        if not user.is_admin():
            return jsonify({"ok": False, "error": "The AI coach is currently limited to admins."}), 403
        from services import ai_coach

        if not ai_coach.allow_request(user.id):
            return jsonify({"ok": False, "error": "You're asking a lot! Give it a few minutes and try again."}), 429
        body = request.get_json(silent=True) or {}
        raw_context = body.get('context') if isinstance(body.get('context'), dict) else {}
        context = {
            k: str(raw_context.get(k) or '').strip()[:120]
            for k in ('page', 'exercise', 'metric', 'date')
            if str(raw_context.get(k) or '').strip()
        }
        kwargs = dict(messages=body.get('messages') or [], api_keys=_active_api_key_payloads(user), context=context)

        if body.get('stream'):
            # One JSON object per line: each lookup as it happens, then the answer, so the
            # chat can show its progress on long, careful answers.
            def events():
                try:
                    for event in ai_coach.run_coach_events(Session, user, **kwargs):
                        if event["type"] == "step":
                            step = event["step"]
                            yield json.dumps({"type": "step", "label": step["label"], "args": step["args"],
                                              "ok": step["ok"]}) + "\n"
                        else:
                            yield json.dumps({"type": "done", **_coach_finish(user, event["result"])}) + "\n"
                except Exception as e:
                    Session.rollback()
                    logger.error(f"AI coach stream failed: {e}", exc_info=True)
                    yield json.dumps({"type": "done", "ok": False, "error": "Unable to answer right now."}) + "\n"

            return Response(stream_with_context(events()), mimetype='application/x-ndjson',
                            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
        try:
            payload = _coach_finish(user, ai_coach.run_coach(Session, user, **kwargs))
            return jsonify(payload), (200 if payload.get('ok') else 400)
        except Exception as e:
            Session.rollback()
            logger.error(f"AI coach request failed: {e}", exc_info=True)
            return jsonify({"ok": False, "error": "Unable to answer right now."}), 500

    @login_required
    def ai_coach_rate_api():
        user = current_user
        if not user.is_admin():
            return jsonify({"ok": False, "error": "The AI coach is currently limited to admins."}), 403
        from services import coach_answers

        body = request.get_json(silent=True) or {}
        if not coach_answers.rate(Session, user, body.get('answer_id'), body.get('rating'), body.get('comment')):
            return jsonify({"ok": False, "error": "That answer can't be rated."}), 400
        return jsonify({"ok": True})

    @login_required
    def ai_coach_suggestions_api():
        user = current_user
        if not user.is_admin():
            return jsonify({"ok": False, "error": "The AI coach is currently limited to admins."}), 403
        from config import Config
        from services import ai_coach

        try:
            has_key = (bool(_active_api_key_payloads(user)) or bool(getattr(Config, 'GEMINI_API_KEY', None))
                       or bool(getattr(Config, 'GROQ_API_KEY', None)))
            return jsonify({"ok": True, "suggestions": ai_coach.suggestions(Session, user), "ai_enabled": has_key})
        except Exception as e:
            logger.error(f"AI coach suggestions failed: {e}", exc_info=True)
            return jsonify({"ok": True, "suggestions": [], "ai_enabled": False})

    def _format_reco_label(category: str, day_id: int) -> str:
        cat = str(category or "").strip()
        if not cat:
            cat = "Workout"
        try:
            day = int(day_id)
        except Exception:
            day = 1
        return f"{cat} • Day {day}"

    def _format_plan_day_label(day_name: str) -> str:
        name = str(day_name or '').strip()
        if not name:
            return ''
        name = re.sub(r'\s+(\d+)\s*$', '', name).strip()
        name = name.replace('–', '-').replace('—', '-').replace('•', '-').strip()
        name = re.sub(r'\s*-\s*', ' - ', name)
        name = re.sub(r'\s{2,}', ' ', name)
        return name

    def _extract_session_title(plan_text: str, day_id: int) -> str:
        text = str(plan_text or '')
        if not text.strip():
            return ''
        try:
            did = int(day_id)
        except Exception:
            return ''

        patterns = [
            rf'^\s*Session\s*{did}\s*[–—-]\s*(.+?)\s*$',
            rf'^\s*Session\s*{did}\s*[:]\s*(.+?)\s*$',
            rf'^\s*Session\s*{did}\b\s*(.+?)\s*$',
        ]
        for line in text.splitlines():
            if not line or not line.strip():
                continue
            for pat in patterns:
                m = re.match(pat, line.strip(), flags=re.IGNORECASE)
                if not m:
                    continue
                tail = (m.group(1) or '').strip()
                tail = tail.lstrip('–—-:').strip()
                if tail:
                    tail = tail.replace('–', '-').replace('—', '-').strip()
                    tail = re.sub(r'\s*-\s*', ' - ', tail)
                    tail = re.sub(r'\s{2,}', ' ', tail)
                    return f"Session {did} - {tail}"
                return f"Session {did}"
        return ''

    def _normalize_shortcut_key(value: str) -> str:
        text = html.unescape(str(value or "")).strip().lower()
        if not text:
            return ""
        text = text.replace("–", "-").replace("—", "-").replace("•", " ")
        text = re.sub(r"[^a-z0-9\s\-]", " ", text)
        text = text.replace("-", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _shortcut_day_token(category: str, day_id: int) -> str:
        cat = str(category or "").strip().lower()
        cat = re.sub(r"[^a-z0-9]+", "_", cat).strip("_")
        return f"{cat}:{int(day_id)}"

    def _load_shortcut_key_map(user) -> dict[str, str]:
        row = Session.query(ShortcutKeyMap).filter_by(user_id=user.id).first()
        raw = (row.text_content if row else "") or ""
        if not str(raw).strip():
            return {}
        try:
            data = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in data.items():
            token = str(k or "").strip()
            val = str(v or "").strip()
            if not token or not val:
                continue
            out[token] = val[:120]
        return out

    def _build_shortcut_plan_day_rows(user) -> list[dict]:
        plan_text = get_effective_plan_text(Session, user)
        if not plan_text:
            return []
        plan_data = get_workout_days(plan_text or "")
        workout_map = plan_data.get("workout", {}) if isinstance(plan_data, dict) else {}
        if not isinstance(workout_map, dict):
            return []
        session_titles = plan_data.get("session_titles") if isinstance(plan_data, dict) else {}
        if not isinstance(session_titles, dict):
            session_titles = {}

        rows: list[dict] = []
        for category, days in workout_map.items():
            if not isinstance(days, dict):
                continue
            cat_name = str(category or "").strip()
            if not cat_name:
                continue
            for day_name in days.keys():
                if not isinstance(day_name, str):
                    continue
                m = re.search(r"\s+(\d+)\s*$", day_name)
                if not m:
                    continue
                day_id = int(m.group(1))
                session_title = ""
                if cat_name.lower() == "session":
                    session_title = str(session_titles.get(str(day_id)) or "").strip()
                    if not session_title:
                        extracted = _extract_session_title(plan_text, day_id)
                        if extracted.lower().startswith("session "):
                            session_title = re.sub(
                                rf"^\s*session\s*{day_id}\s*[-:–—]?\s*",
                                "",
                                extracted,
                                flags=re.IGNORECASE,
                            ).strip()
                label = f"{cat_name} {day_id}"
                if cat_name.lower() == "session" and session_title:
                    label = f"Session {day_id} - {session_title}"
                default_key = label
                rows.append(
                    {
                        "category": cat_name,
                        "day_id": day_id,
                        "label": label,
                        "token": _shortcut_day_token(cat_name, day_id),
                        "default_key": default_key,
                    }
                )
        rows.sort(key=lambda x: (str(x.get("category") or "").lower(), int(x.get("day_id") or 0)))
        return rows

    def _resolve_shortcut_pick_day(user, raw_key: str):
        plan_text = get_effective_plan_text(Session, user)
        if not plan_text:
            return None, "No workout plan found."

        plan_data = get_workout_days(plan_text or "")
        workout_map = plan_data.get("workout", {}) if isinstance(plan_data, dict) else {}
        if not isinstance(workout_map, dict) or not workout_map:
            return None, "No workout plan found."

        key = _normalize_shortcut_key(raw_key)
        if not key:
            return None, "Missing key."

        session_titles = plan_data.get("session_titles") if isinstance(plan_data, dict) else {}
        if not isinstance(session_titles, dict):
            session_titles = {}

        alias_map: dict[str, list[dict]] = {}
        all_labels: set[str] = set()

        token_to_entry: dict[str, dict] = {}
        for category, days in workout_map.items():
            if not isinstance(days, dict):
                continue
            cat_name = str(category or "").strip()
            if not cat_name:
                continue

            for day_name in days.keys():
                if not isinstance(day_name, str):
                    continue
                m = re.search(r"\s+(\d+)\s*$", day_name)
                if not m:
                    continue

                day_id = int(m.group(1))
                session_title = ""
                if cat_name.lower() == "session":
                    session_title = str(session_titles.get(str(day_id)) or "").strip()
                    if not session_title:
                        extracted = _extract_session_title(plan_text, day_id)
                        if extracted.lower().startswith("session "):
                            session_title = re.sub(
                                rf"^\s*session\s*{day_id}\s*[-:–—]?\s*",
                                "",
                                extracted,
                                flags=re.IGNORECASE,
                            ).strip()

                label = f"{cat_name} {day_id}"
                if cat_name.lower() == "session" and session_title:
                    label = f"Session {day_id} - {session_title}"
                all_labels.add(label)

                entry = {
                    "category": cat_name,
                    "day_id": day_id,
                    "label": label,
                }
                token_to_entry[_shortcut_day_token(cat_name, day_id)] = entry

                aliases = {
                    day_name,
                    f"{cat_name} {day_id}",
                    f"{cat_name}:{day_id}",
                    f"{cat_name}-{day_id}",
                    # The day's number alone ("1" is Session 1, not every session with a 1 in it).
                    str(day_id),
                }
                if cat_name.lower() == "session":
                    aliases.add(f"session {day_id}")
                    aliases.add(f"s{day_id}")
                    if session_title:
                        aliases.add(session_title)
                        aliases.add(f"session {day_id} {session_title}")
                        aliases.add(f"session {day_id} - {session_title}")

                for alias in aliases:
                    norm = _normalize_shortcut_key(alias)
                    if not norm:
                        continue
                    alias_map.setdefault(norm, []).append(entry)

        custom_map = _load_shortcut_key_map(user)
        custom_alias_map: dict[str, list[dict]] = {}
        for token, custom_key in custom_map.items():
            entry = token_to_entry.get(str(token))
            if not entry:
                continue
            norm = _normalize_shortcut_key(custom_key)
            if not norm:
                continue
            custom_alias_map.setdefault(norm, []).append(entry)

        def _unique_entries(entries: list[dict]) -> list[dict]:
            out: dict[tuple[str, int], dict] = {}
            for item in entries:
                k = (str(item.get("category") or ""), int(item.get("day_id") or 0))
                if k[0] and k[1] > 0:
                    out[k] = item
            return list(out.values())

        custom_exact = _unique_entries(custom_alias_map.get(key) or [])
        if len(custom_exact) == 1:
            return custom_exact[0], None
        if len(custom_exact) > 1:
            labels = sorted({x.get("label") for x in custom_exact if x.get("label")})
            return None, f"Ambiguous key '{raw_key}'. Matches: {', '.join(labels[:8])}"

        exact = _unique_entries(alias_map.get(key) or [])
        if len(exact) == 1:
            return exact[0], None
        if len(exact) > 1:
            labels = sorted({x.get("label") for x in exact if x.get("label")})
            return None, f"Ambiguous key '{raw_key}'. Matches: {', '.join(labels[:8])}"

        partial_candidates: list[dict] = []
        for alias, items in alias_map.items():
            # A number only ever matches a day's own number (above): "0" isn't part of Session 10.
            if key.isdigit() or alias.isdigit():
                continue
            if key in alias or alias in key:
                partial_candidates.extend(items)
        partial = _unique_entries(partial_candidates)
        if len(partial) == 1:
            return partial[0], None
        if len(partial) > 1:
            labels = sorted({x.get("label") for x in partial if x.get("label")})
            return None, f"Ambiguous key '{raw_key}'. Matches: {', '.join(labels[:8])}"

        sample = ", ".join(sorted(all_labels)[:8])
        return None, f"No workout day matched '{raw_key}'. Try one of: {sample}"

    _deployment_name = deployment_name

    def _deployment_base_urls() -> list[tuple[str, str]]:
        """(name, base URL) for this site first, then every other deployment."""
        current = request.host_url.rstrip('/')
        bases = [(_deployment_name(request.host), current)]
        seen = {urlsplit(current).netloc.lower()}
        for entry in str(app.config.get('DEPLOYMENT_URLS') or '').split(','):
            name, _, url = entry.strip().rpartition('=')
            url = url.strip().rstrip('/')
            host = urlsplit(url).netloc.lower()
            if not host or host in seen:
                continue
            seen.add(host)
            bases.append((name.strip() or _deployment_name(host), url))
        return bases

    @login_required
    def shortcut_urls():
        log_path = url_for('shortcut_log', token=_make_shortcut_log_token(current_user.id))
        pick_path = url_for('shortcut_pick', token=_make_shortcut_pick_token(current_user.id))
        deployments = [
            {'name': name, 'log_url': base + log_path, 'retrieve_url': base + pick_path}
            for name, base in _deployment_base_urls()
        ]
        return render_template(
            'shortcut_urls.html',
            deployments=deployments,
            shortcut_key=_make_shortcut_key(current_user.id),
        )

    @login_required
    def shortcut_recommend_url():
        token = _make_shortcut_token(current_user.id)
        shortcut_url = url_for('shortcut_recommend', token=token, _external=True)
        return jsonify({"ok": True, "url": shortcut_url})

    @login_required
    def shortcut_pick_url():
        token = _make_shortcut_pick_token(current_user.id)
        shortcut_url = url_for('shortcut_pick', token=token, _external=True)
        return jsonify({"ok": True, "url": shortcut_url, "query_param": "key"})

    @login_required
    def shortcut_log_url():
        token = _make_shortcut_log_token(current_user.id)
        shortcut_url = url_for('shortcut_log', token=token, _external=True)
        return jsonify(
            {
                "ok": True,
                "url": shortcut_url,
                "method": "POST",
                "body_param": "workout_text",
            }
        )

    def shortcut_recommend(token):
        try:
            payload = _load_shortcut_token(token)
            user_id = payload.get("user_id")
            if not user_id:
                raise BadSignature("Missing user")
            user = Session.get(User, user_id)
            if not user:
                raise BadSignature("Unknown user")
        except BadSignature:
            return Response("Invalid shortcut token.", status=401, mimetype="text/plain")
        except Exception as e:
            logger.error(f"Shortcut token error: {e}", exc_info=True)
            return Response("Invalid shortcut token.", status=401, mimetype="text/plain")

        reco_payload, status = _recommend_workout_payload(user, use_cache=False, cache_key_prefix="shortcut:")
        if status != 200 or not reco_payload.get("ok"):
            msg = reco_payload.get("error") if isinstance(reco_payload, dict) else "Unable to generate a recommendation right now."
            return Response(str(msg), status=status, mimetype="text/plain")

        category = reco_payload.get("category")
        day_id = reco_payload.get("day_id")
        output, _, _ = generate_retrieve_output(Session, user, category, day_id)
        return Response(str(output), mimetype="text/plain")

    def _shortcut_json(payload: dict, status: int = 200):
        # "server" is always present, so a Shortcut can tell this app's reply
        # from a host error page and fall back to the other deployment.
        return jsonify({**payload, "server": _deployment_name(request.host)}), status

    def shortcut_pick(token):
        as_json = str(request.args.get("format") or "").strip().lower() == "json" or bool(request.args.get("list"))

        def reply(text: str, status: int = 200):
            if as_json:
                key = "text" if status == 200 else "error"
                return _shortcut_json({"ok": status == 200, key: text}, status)
            return Response(text, status=status, mimetype="text/plain")

        try:
            payload = _load_shortcut_pick_token(token)
            user_id = payload.get("user_id")
            if not user_id:
                raise BadSignature("Missing user")
            user = Session.get(User, user_id)
            if not user:
                raise BadSignature("Unknown user")
        except BadSignature:
            return reply(SHORTCUT_KEY_INVALID if as_json else "Invalid shortcut token.", 401)
        except Exception as e:
            logger.error(f"Shortcut token error: {e}", exc_info=True)
            return reply(SHORTCUT_KEY_INVALID if as_json else "Invalid shortcut token.", 401)

        if request.args.get("list"):
            # The user's own sessions, so a shared Get Workout shortcut needs no hard-coded list.
            sessions = [row["label"] for row in _build_shortcut_plan_day_rows(user)]
            if not sessions:
                return _shortcut_json({"ok": False, "error": "No workout plan yet. Add one in Settings first."})
            return _shortcut_json({"ok": True, "sessions": sessions})

        raw_key = str(request.args.get("key") or request.args.get("session") or request.args.get("word") or "").strip()
        if len(raw_key) > 140:
            raw_key = raw_key[:140]
        if not raw_key:
            return reply("Missing key. Pass ?key=<session-name-or-day>.", 400)

        picked_day, error = _resolve_shortcut_pick_day(user, raw_key)
        if error:
            return reply(str(error), 400)

        category = picked_day.get("category")
        day_id = picked_day.get("day_id")
        output, _, _ = generate_retrieve_output(Session, user, category, day_id)
        return reply(str(output))

    def shortcut_log(token):
        try:
            payload = _load_shortcut_log_token(token)
            user_id = payload.get("user_id")
            if not user_id:
                raise BadSignature("Missing user")
            user = Session.get(User, user_id)
            if not user:
                raise BadSignature("Unknown user")
        except BadSignature:
            return _shortcut_json({"ok": False, "error": SHORTCUT_KEY_INVALID})
        except Exception as e:
            logger.error(f"Shortcut token error: {e}", exc_info=True)
            return _shortcut_json({"ok": False, "error": SHORTCUT_KEY_INVALID})

        raw_text = ""
        source = "none"
        try:
            if request.method == 'POST':
                raw_text = str(request.form.get("workout_text") or "").strip()
                if raw_text:
                    source = "form.workout_text"
                if not raw_text:
                    raw_text = str(request.form.get("text") or request.form.get("note") or "").strip()
                    if raw_text:
                        source = "form.text_or_note"
                if not raw_text and request.form:
                    values = [str(v or "").strip() for v in request.form.values()]
                    values = [v for v in values if v]
                    if values:
                        raw_text = max(values, key=len)
                        source = "form.any"
                if not raw_text and request.is_json:
                    payload_json = request.get_json(silent=True)
                    if isinstance(payload_json, dict):
                        raw_text = str(
                            payload_json.get("workout_text")
                            or payload_json.get("text")
                            or payload_json.get("note")
                            or ""
                        ).strip()
                        if raw_text:
                            source = "json.named"
                    if not raw_text:
                        str_values = [
                            str(v or "").strip()
                            for v in payload_json.values()
                            if isinstance(v, (str, int, float))
                        ] if isinstance(payload_json, dict) else []
                        str_values = [v for v in str_values if v]
                        if str_values:
                            raw_text = max(str_values, key=len)
                            source = "json.any"
                if not raw_text and request.files:
                    # Rich-text notes can arrive as an uploaded file (RTF/HTML).
                    uploads = [f.read(200_000) for f in request.files.values()]
                    uploads = [u for u in uploads if u and u.strip()]
                    if uploads:
                        raw_text = to_plain_text(max(uploads, key=len))
                        source = "file"
                if not raw_text and not request.form and not request.is_json:
                    raw_text = to_plain_text(request.get_data())
                    if raw_text:
                        source = "raw.body"
            else:
                raw_text = str(
                    request.args.get("workout_text")
                    or request.args.get("text")
                    or request.args.get("note")
                    or ""
                ).strip()
                if raw_text:
                    source = "query"
        except Exception:
            raw_text = ""
            source = "error"

        if len(raw_text) > 60000:
            raw_text = raw_text[:60000]

        result, error = _parse_and_save_workout_text(user, raw_text)
        if error:
            logger.info(
                "Shortcut log failed: %s (source=%s, content_type=%s, chars=%s, unusual=%s)",
                error, source, request.content_type, len(raw_text),
                sorted({f"U+{ord(c):04X}" for c in raw_text if ord(c) > 126})[:20],
            )
            return _shortcut_json(
                {
                    "ok": False,
                    "error": error,
                    "received_chars": len(raw_text),
                    "input_source": source,
                }
            )

        date_str = result.get("date_str")
        detail_url = url_for('view_workout', date_str=date_str, _external=True)
        if result.get("already_exists") and not _same_workout_already_saved(
                user, raw_text, datetime.strptime(date_str, '%Y-%m-%d')):
            # A different workout for a day that has one: nothing was saved, so don't say it was.
            return _shortcut_json({
                "ok": False,
                "error": SHORTCUT_DAY_TAKEN,
                "date": date_str,
                "result_url": detail_url,
                "already_exists": True,
                "input_source": source,
            })
        skipped = result.get("skipped") or []
        success_message = "Workout logged."
        if skipped:
            success_message += " Not saved: " + " ".join(skipped)
        return _shortcut_json(
            {
                "ok": True,
                "date": date_str,
                "exercise_count": int(result.get("exercise_count") or 0),
                "set_count": int(result.get("set_count") or 0),
                "result_url": detail_url,
                "bodyweight_hint": bool(result.get("needs_bodyweight_info")),
                "input_source": source,
                "already_exists": bool(result.get("already_exists")),
                "message": result.get("message") or (
                    "Workout already there." if result.get("already_exists") else success_message
                ),
            }
        )

    @login_required
    def shortcut_key_map_settings():
        user = current_user

        rows = _build_shortcut_plan_day_rows(user)
        if request.method == 'POST':
            try:
                tokens = request.form.getlist("day_token")
                keys = request.form.getlist("day_key")
                mapping: dict[str, str] = {}
                seen_keys: dict[str, str] = {}
                allowed_tokens = {str(r.get("token")) for r in rows}

                for idx, token in enumerate(tokens):
                    tok = str(token or "").strip()
                    if not tok or tok not in allowed_tokens:
                        continue
                    val = str(keys[idx] if idx < len(keys) else "").strip()
                    if not val:
                        continue
                    val = val[:120]
                    norm = _normalize_shortcut_key(val)
                    if not norm:
                        continue
                    prev = seen_keys.get(norm)
                    if prev and prev != tok:
                        flash("Each shortcut key must be unique across sessions/days.", "error")
                        return redirect(url_for('shortcut_key_map_settings'))
                    seen_keys[norm] = tok
                    mapping[tok] = val

                row = Session.query(ShortcutKeyMap).filter_by(user_id=user.id).first()
                if not row:
                    row = ShortcutKeyMap(user_id=user.id, text_content="")
                    Session.add(row)
                row.text_content = json.dumps(mapping, ensure_ascii=False, separators=(",", ":"))
                row.updated_at = datetime.now()
                Session.commit()
                flash("Shortcut key mapping updated.", "success")
                return redirect(url_for('shortcut_key_map_settings'))
            except Exception as e:
                Session.rollback()
                logger.error(f"Shortcut key mapping update failed: {e}", exc_info=True)
                flash("Failed to update shortcut key mapping.", "error")
                return redirect(url_for('shortcut_key_map_settings'))

        custom_map = _load_shortcut_key_map(user)
        for row in rows:
            token = str(row.get("token"))
            row["custom_key"] = custom_map.get(token) or str(row.get("default_key") or "")

        return render_template(
            'shortcut_key_map.html',
            rows=rows,
        )

    def shared_workout(token):
        try:
            payload = _load_share_token(token)
            user_id = payload.get('user_id')
            date_str = payload.get('date')
            if not user_id or not date_str:
                raise BadSignature("Missing data")

            share_user = Session.get(User, user_id)
            share_username = share_user.username.title() if share_user else "Liftbook user"
            # Public URL (static upload or R2 public bucket), so logged-out friends can load it.
            share_avatar_url = get_profile_image_url(getattr(share_user, 'profile_image', None)) if share_user else None

            workout_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_dt = datetime.combine(workout_date, datetime.min.time())
            end_dt = start_dt + timedelta(days=1)

            logs = (
                Session.query(WorkoutLog)
                .filter_by(user_id=user_id)
                .filter(WorkoutLog.date >= start_dt)
                .filter(WorkoutLog.date < end_dt)
                .order_by(WorkoutLog.id)
                .all()
            )

            if not logs:
                return render_template('share_workout.html', missing=True)

            workout_name = _clean_workout_title(logs[0].workout_name or "Workout")
            rows = _shared_exercise_rows(share_user, logs, start_dt) if share_user else []
            set_count = sum(_count_sets(log.sets_json, log.sets_display) for log in logs)
            new_bests = sum(1 for row in rows if row["medal"])
            date_label = f"{workout_date.strftime('%a')}, {workout_date.day} {workout_date.strftime('%b %Y')}"
            summary_bits = [
                f"{len(logs)} exercise{'' if len(logs) == 1 else 's'}",
                f"{set_count} set{'' if set_count == 1 else 's'}",
            ]
            if new_bests:
                summary_bits.append(f"{new_bests} new personal best{'' if new_bests == 1 else 's'}")
            # What "Copy" puts on the clipboard: every set written out, no app shorthand.
            workout_text = insights.readable_workout_text(
                workout_name,
                date_label,
                [
                    {"name": row["name"], "target": row["target"], "sets": row["readable_sets"] or row["sets"]}
                    for row in rows
                ],
                footer=f"Shared from Liftbook: {request.url}",
            )

            return render_template(
                'share_workout.html',
                date=date_str,
                date_label=date_label,
                share_username=share_username,
                share_avatar_url=share_avatar_url,
                workout_name=workout_name,
                rows=rows,
                exercise_count=len(logs),
                set_count=set_count,
                new_bests=new_bests,
                share_description=f"{' · '.join(summary_bits)} · {date_label}",
                share_url=request.url,
                workout_text=workout_text,
                missing=False,
            )
        except BadSignature:
            return render_template('share_workout.html', missing=True)
        except Exception as e:
            logger.error(f"Error loading shared workout: {e}", exc_info=True)
            return render_template('share_workout.html', missing=True)

    def _shared_exercise_rows(owner, logs, start_dt):
        """Sets (strongest first) and any new-best medal for each exercise on a shared workout."""
        rep_row = Session.query(RepRange).filter_by(user_id=owner.id).first()
        rep_target_sets = parse_rep_target_sets_text(rep_row.text_content if rep_row else "")
        plan_target_sets = get_plan_target_sets_for_user(Session, owner)
        log_ex_index = build_name_index([
            row[0]
            for row in Session.query(WorkoutLog.exercise).filter(WorkoutLog.user_id == owner.id).distinct().all()
        ])

        rows = []
        for log in logs:
            exercise_text = str(getattr(log, 'exercise_string', '') or '')
            target_sets, strict_target_sets = resolve_target_sets_for_exercise(
                exercise_name=log.exercise,
                exercise_string=exercise_text,
                rep_target_sets=rep_target_sets,
                plan_target_sets=plan_target_sets,
                inferred_set_count=comparison_set_count(getattr(log, "sets_json", None), exercise_text),
                default_sets=3,
            )
            is_timed = bool(
                resolve_timed_exercise_status(
                    Session, owner.id, log.exercise, exercise_text, log_ex_index=log_ex_index
                ).get("is_timed")
            )
            perf = classify_exercise_performance(
                Session,
                owner.id,
                log.exercise,
                getattr(log, 'sets_json', None),
                target_sets=target_sets,
                strict_target_sets=strict_target_sets,
                is_timed=is_timed,
                current_log_id=getattr(log, 'id', None),
                current_exercise_string=exercise_text,
                historical_before_dt=start_dt,
                log_ex_index=log_ex_index,
            )
            uses_bw = _log_uses_bw(log)
            effective = effective_sets_for_log(Session, log)
            display = _display_sets(log, effective, uses_bw) or {}
            # In the order they were done: a friend reads this as "what they did".
            done = [
                (float(w), int(r))
                for w, r in zip(display.get('weights') or [], display.get('reps') or [])
                if w is not None and r is not None and int(r) > 0
            ]
            medal = None
            if perf.get("key") in insights.MEDAL_KEYS:
                best = insights.best_summary(perf, has_history=True)
                medal = {"emoji": best["emoji"], "kind": best["kind"].split(" ")[-1], "pct": best["chip"]}
            rows.append({
                "name": log.exercise,
                "sets": [
                    insights.format_set(w, r, uses_bodyweight=uses_bw, is_timed=is_timed) for w, r in done
                ] or ([log.sets_display] if log.sets_display else []),
                "readable_sets": [
                    insights.readable_set(w, r, uses_bodyweight=uses_bw, is_timed=is_timed) for w, r in done
                ],
                "target": insights.target_range(exercise_text, is_timed=is_timed),
                "medal": medal,
            })
        return rows

    @login_required
    def edit_workout(date_str):
        user = current_user

        try:
            workout_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_dt = datetime.combine(workout_date, datetime.min.time())
            end_dt = start_dt + timedelta(days=1)

            logs = (
                Session.query(WorkoutLog)
                .filter_by(user_id=user.id)
                .filter(WorkoutLog.date >= start_dt)
                .filter(WorkoutLog.date < end_dt)
                .order_by(WorkoutLog.id)
                .all()
            )

            if not logs:
                flash("Workout not found.", "error")
                return redirect(url_for('user_dashboard', username=user.username))

            workout_name = logs[0].workout_name or "Workout"
            workout_text = build_exercise_text(logs)

            def render_edit(*, title=None, date_value=None, text=None, errors=None, status=200):
                return render_template(
                    'workout_edit.html',
                    workout_date=date_value or workout_date.strftime('%Y-%m-%d'),
                    workout_name=title if title is not None else workout_name,
                    workout_text=text if text is not None else workout_text,
                    date=date_str,
                    errors=errors or [],
                    exercise_list=_log_name_suggestions(user),
                ), status

            if request.method == 'POST':
                title = sanitize_text_input(request.form.get('workout_title', ''), max_length=100) or "Workout"
                date_input = request.form.get('workout_date', '').strip()
                exercises_input = request.form.get('workout_text', '').strip()

                keep = dict(title=title, date_value=date_input, text=exercises_input, status=422)
                if not date_input:
                    return render_edit(errors=["Pick a date for this workout."], **keep)

                if not exercises_input:
                    return render_edit(errors=["Add at least one exercise."], **keep)

                try:
                    new_date = datetime.strptime(date_input, '%Y-%m-%d').date()
                except ValueError:
                    return render_edit(errors=["Pick a valid date."], **keep)

                new_start_dt = datetime.combine(new_date, datetime.min.time())
                new_end_dt = new_start_dt + timedelta(days=1)

                if new_date != workout_date:
                    conflict = (
                        Session.query(WorkoutLog)
                        .filter_by(user_id=user.id)
                        .filter(WorkoutLog.date >= new_start_dt)
                        .filter(WorkoutLog.date < new_end_dt)
                        .first()
                    )
                    if conflict:
                        return render_edit(errors=["That date already has a workout. Edit that day instead."], **keep)

                header = f"{new_date.day}/{new_date.month}/{new_date.strftime('%y')} {title}"
                check = check_workout_text(Session, user, exercises_input, header=header)
                if check.get("errors"):
                    # Keep the edits so they can be fixed in place.
                    return render_edit(
                        title=title, date_value=date_input, text=exercises_input,
                        errors=[e["message"] for e in check["errors"]], status=422,
                    )
                parsed = check["parsed"]

                parsed['date'] = new_start_dt
                parsed['workout_name'] = title
                # The edit box has no bodyweight line: keep the day's, not today's.
                logged_bodyweight = next((log.bodyweight for log in logs if log.bodyweight), None)
                if parsed.get('bodyweight') is None and logged_bodyweight:
                    parsed['logged_bodyweight'] = logged_bodyweight

                old_exercises = [log.exercise for log in logs]

                Session.query(WorkoutLog).filter_by(user_id=user.id).filter(
                    WorkoutLog.date >= start_dt,
                    WorkoutLog.date < end_dt,
                ).delete(synchronize_session=False)
                # The rows are gone; forget the loaded copies so the new rows never meet them.
                for log in logs:
                    Session.expunge(log)

                handle_workout_log(Session, user, parsed)
                refresh_best_lift_pointers(Session, user, old_exercises)
                Session.commit()

                flash("Workout saved.", "success")
                return redirect(url_for('view_workout', date_str=new_date.strftime('%Y-%m-%d')))

            return render_edit()[0]
        except ValueError:
            flash("That link doesn't point to a workout.", "error")
            return redirect(url_for('user_dashboard', username=user.username))
        except ParsingError as e:
            Session.rollback()
            flash(str(e), "error")
            return redirect(url_for('edit_workout', date_str=date_str))
        except Exception as e:
            Session.rollback()
            logger.error(f"Error editing workout: {e}", exc_info=True)
            flash("Couldn't save the workout. Please try again.", "error")
            return redirect(url_for('edit_workout', date_str=date_str))

    @login_required
    def delete_workout(date_str):
        user = current_user

        try:
            workout_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_dt = datetime.combine(workout_date, datetime.min.time())
            end_dt = start_dt + timedelta(days=1)

            affected_exercises = [
                row[0] for row in (
                    Session.query(WorkoutLog.exercise)
                    .filter_by(user_id=user.id)
                    .filter(WorkoutLog.date >= start_dt)
                    .filter(WorkoutLog.date < end_dt)
                    .distinct()
                    .all()
                )
            ]

            deleted = (
                Session.query(WorkoutLog)
                .filter_by(user_id=user.id)
                .filter(WorkoutLog.date >= start_dt)
                .filter(WorkoutLog.date < end_dt)
                .delete(synchronize_session=False)
            )
            if deleted:
                refresh_best_lift_pointers(Session, user, affected_exercises)
            Session.commit()

            if deleted:
                flash("Workout deleted.", "success")
            else:
                flash("Workout not found.", "error")

            return redirect(url_for('user_dashboard', username=user.username))
        except ValueError:
            flash("That link doesn't point to a workout.", "error")
            return redirect(url_for('user_dashboard', username=user.username))
        except Exception as e:
            Session.rollback()
            logger.error(f"Error deleting workout: {e}", exc_info=True)
            flash("Error deleting workout.", "error")
            return redirect(url_for('edit_workout', date_str=date_str))

    @login_required
    def bulk_delete_workouts():
        user = current_user

        selected_dates = request.form.getlist('selected_dates')
        if not selected_dates:
            flash("Select at least one workout day to delete.", "error")
            return redirect(url_for('workout_history'))

        unique_dates = []
        seen = set()
        for raw in selected_dates:
            key = str(raw or '').strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique_dates.append(key)

        if not unique_dates:
            flash("Select at least one workout day to delete.", "error")
            return redirect(url_for('workout_history'))

        total_deleted_days = 0
        affected_exercises = set()
        try:
            for date_str in unique_dates:
                try:
                    workout_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    continue

                start_dt = datetime.combine(workout_date, datetime.min.time())
                end_dt = start_dt + timedelta(days=1)

                affected_exercises.update(
                    row[0] for row in (
                        Session.query(WorkoutLog.exercise)
                        .filter_by(user_id=user.id)
                        .filter(WorkoutLog.date >= start_dt)
                        .filter(WorkoutLog.date < end_dt)
                        .distinct()
                        .all()
                    )
                )

                deleted = (
                    Session.query(WorkoutLog)
                    .filter_by(user_id=user.id)
                    .filter(WorkoutLog.date >= start_dt)
                    .filter(WorkoutLog.date < end_dt)
                    .delete(synchronize_session=False)
                )
                if deleted:
                    total_deleted_days += 1

            if affected_exercises:
                refresh_best_lift_pointers(Session, user, affected_exercises)
            Session.commit()

            if total_deleted_days:
                flash(f"Deleted {total_deleted_days} workout{'' if total_deleted_days == 1 else 's'}.", "success")
            else:
                flash("No matching workouts were found to delete.", "info")

            return redirect(url_for('workout_history'))
        except Exception as e:
            Session.rollback()
            logger.error(f"Error bulk deleting workouts: {e}", exc_info=True)
            flash("Error deleting selected workouts.", "error")
            return redirect(url_for('workout_history'))

    def _check_error_message(check):
        errors = check.get("errors") or []
        if not errors:
            return None
        message = errors[0]["message"]
        if len(errors) > 1:
            message += f" ({len(errors) - 1} more like this.)"
        return message

    def _parse_and_save_workout_text(user, raw_text: str, *, append: bool = False, saved_at=None):
        text = to_plain_text(raw_text)
        if not text:
            return None, "Please enter workout data."

        try:
            # saved_at: a workout kept on the phone offline is dated the day it was kept.
            check = check_workout_text(Session, user, text, append=append, now=saved_at)
        except Exception as e:
            logger.error(f"Parsing error: {e}", exc_info=True)
            return None, "Error parsing workout data. Please check the format."
        error = _check_error_message(check)
        if error:
            return None, error
        parsed = check["parsed"]

        needs_bodyweight_info = bool(user.bodyweight is None and has_bodyweight_token(text))
        skipped = [w["message"] for w in check.get("warnings") or [] if "won't be saved" in w["message"]]

        existing_log = _find_existing_workout_for_day(user.id, parsed['date'])
        if existing_log and not append:
            existing_day, _, _ = _workout_day_bounds(existing_log.date)
            return {
                "summary": [],
                "date_str": existing_day.strftime('%Y-%m-%d'),
                "exercise_count": 0,
                "set_count": 0,
                "needs_bodyweight_info": needs_bodyweight_info,
                "already_exists": True,
                "message": "Workout already there.",
            }, None
        if existing_log and append:
            # Join the day that is already there: same timestamp and title.
            parsed['date'] = existing_log.date
            parsed['workout_name'] = existing_log.workout_name

        try:
            summary = handle_workout_log(Session, user, parsed)
            timed_prompt_rows = []
            seen_timed_prompt_keys = set()
            for row in (summary or []):
                if not row.get("timed_prompt_needed"):
                    continue
                exercise_name = str(row.get("timed_prompt_exercise") or row.get("name") or "").strip()
                if not exercise_name:
                    continue
                dedup_key = exercise_name.lower()
                if dedup_key in seen_timed_prompt_keys:
                    continue
                seen_timed_prompt_keys.add(dedup_key)
                timed_prompt_rows.append({"exercise": exercise_name})
            Session.commit()
            logger.info(
                f"Workout logged successfully for user {user.username} on {parsed['date']}"
            )
            return {
                "summary": summary,
                "date_str": parsed['date'].strftime('%Y-%m-%d'),
                "exercise_count": int(check.get("exercise_count") or 0),
                "set_count": int(check.get("set_count") or 0),
                "timed_prompts": timed_prompt_rows,
                "needs_bodyweight_info": needs_bodyweight_info,
                "already_exists": False,
                "appended": bool(existing_log and append),
                "skipped": skipped,
            }, None
        except Exception as e:
            Session.rollback()
            logger.error(f"Error saving workout: {e}", exc_info=True)
            return None, SAVE_WORKOUT_FAILED

    def _client_saved_at(value):
        """When a workout kept on the phone offline was saved (milliseconds since
        the epoch), as local time; None if missing or implausible."""
        saved_at = local_from_epoch_ms(value)
        if saved_at is None:
            return None
        now = local_now()
        if saved_at > now + timedelta(minutes=5) or saved_at < now - timedelta(days=365):
            return None
        return saved_at

    def _same_workout_already_saved(user, raw_text, day):
        """True when the day's workout already holds every exercise in raw_text:
        an upload that got through before the phone gave up waiting."""
        try:
            parsed = workout_parser(to_plain_text(raw_text), bodyweight=user.bodyweight, preserve_bodyweight_offsets=True)
        except Exception:
            return False
        names = {normalize_exercise_name(item.get('name') or '') for item in (parsed or {}).get('exercises') or []}
        names.discard('')
        if not names:
            return False
        _, start_dt, end_dt = _workout_day_bounds(day)
        logged = {
            normalize_exercise_name(row[0] or '')
            for row in Session.query(WorkoutLog.exercise)
            .filter(WorkoutLog.user_id == user.id, WorkoutLog.date >= start_dt, WorkoutLog.date < end_dt)
            .all()
        }
        return names <= logged

    def upload_offline_workout():
        """Takes a workout the phone kept while offline. Always answers in JSON,
        so the phone knows whether to drop it, keep it, or ask for a fix."""
        if not current_user.is_authenticated:
            return jsonify({'ok': False, 'status': 'signed_out'}), 401
        user = current_user
        payload = request.get_json(silent=True) or {}
        # Kept on the phone for this account: by id when the phone knows it (a username
        # can change while a workout waits), else by the username it was kept under.
        owner_id = payload.get('user_id')
        owner = str(payload.get('user') or '').strip().lower()
        if owner_id is not None and str(owner_id).strip():
            if str(owner_id).strip() != str(user.id):
                return jsonify({'ok': False, 'status': 'wrong_user'}), 409
        elif owner and owner != (user.username or '').strip().lower():
            return jsonify({'ok': False, 'status': 'wrong_user'}), 409

        raw_text = str(payload.get('text') or '').strip()
        saved_at = _client_saved_at(payload.get('saved_at'))
        result, error = _parse_and_save_workout_text(user, raw_text, saved_at=saved_at)
        if error == SAVE_WORKOUT_FAILED:
            return jsonify({'ok': False, 'status': 'retry'}), 503
        if error:
            body = {'ok': False, 'status': 'invalid', 'error': str(error)}
            # The phone names the workout by the date written in it ("Your Thu 25 Sept
            # workout couldn't be read"), not the day it happened to be kept.
            try:
                parsed = workout_parser(to_plain_text(raw_text), now=saved_at)
                if parsed and parsed.get('date_found'):
                    body['date'] = parsed['date'].strftime('%Y-%m-%d')
            except Exception:
                pass
            return jsonify(body), 422

        date_str = result.get('date_str')
        body = {
            'ok': True,
            'date': date_str,
            'url': url_for('workout_summary', date_str=date_str),
        }
        if result.get('already_exists'):
            day = datetime.strptime(date_str, '%Y-%m-%d')
            if not _same_workout_already_saved(user, raw_text, day):
                body['status'] = 'already_there'
                body['url'] = url_for('view_workout', date_str=date_str)
                return jsonify(body)
        body['status'] = 'saved'
        return jsonify(body)

    @login_required
    def csrf_token_api():
        # For a page opened offline whose own token has gone stale.
        response = jsonify({'token': generate_csrf()})
        response.headers['Cache-Control'] = 'no-store'
        return response

    def _log_name_suggestions(user):
        # The user's own exercises first (most logged first). Spellings of one exercise
        # ("Cable Oh Extension" / "Cable OH Extension") count together and are offered the way
        # they were last logged, so a corrected spelling takes over at once.
        rows = (
            Session.query(WorkoutLog.exercise, func.count(WorkoutLog.id), func.max(WorkoutLog.date))
            .filter(WorkoutLog.user_id == user.id)
            .group_by(WorkoutLog.exercise)
            .all()
        )
        groups = {}
        for name, count, last in rows:
            if not name or name == "Unknown Exercise":
                continue
            key = normalize_exercise_name(name) or name.lower()
            group = groups.setdefault(key, {"count": 0, "name": name, "last": last})
            group["count"] += count
            if last and (group["last"] is None or last > group["last"]):
                group["name"], group["last"] = name, last
        own = [g["name"] for g in sorted(groups.values(), key=lambda g: -g["count"])]
        own_keys = set(groups)
        return own + [name for name in list_of_exercises if (normalize_exercise_name(name) or name.lower()) not in own_keys]

    def _offline_fix_fields():
        """A workout kept offline being fixed and sent again: its id on the phone and
        when it was kept, so a failed try can be sent again as the same workout."""
        offline_id = (request.form.get('offline_id') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9-]{1,64}', offline_id):
            return None
        saved_at = (request.form.get('saved_at') or '').strip()
        return {"id": offline_id, "saved_at": saved_at if saved_at.isdigit() else ''}

    def _render_log_page(text='', *, error=None, errors=None, existing=None, status=200):
        return render_template(
            'log.html',
            exercise_list=_log_name_suggestions(current_user),
            workout_text=text,
            error=error,
            errors=errors or [],
            existing=existing,
            offline_fix=_offline_fix_fields() if request.method == 'POST' else None,
        ), status

    @login_required
    def log_workout():
        user = current_user

        if request.method == 'GET':
            return _render_log_page()[0]

        raw_text = request.form.get('workout_text', '').strip()
        append = 'append' in request.form.getlist('mode')
        # Set when a workout kept offline is being fixed and sent again.
        saved_at = _client_saved_at(request.form.get('saved_at'))
        result, error = _parse_and_save_workout_text(user, raw_text, append=append, saved_at=saved_at)
        if error:
            # Keep the text so it can be fixed in place.
            try:
                errors = [e["message"] for e in check_workout_text(Session, user, to_plain_text(raw_text)).get("errors") or []]
            except Exception:
                errors = []
            return _render_log_page(raw_text, error=error, errors=errors, status=422)
        if result.get("already_exists"):
            existing_log = _find_existing_workout_for_day(user.id, datetime.strptime(result["date_str"], '%Y-%m-%d'))
            return _render_log_page(raw_text, existing={
                "date_str": result["date_str"],
                "title": _clean_workout_title((existing_log.workout_name if existing_log else None) or "Workout"),
                "url": url_for('view_workout', date_str=result["date_str"]),
            }, status=409)

        session[LOG_SAVED_SESSION_KEY] = {
            "date": result.get("date_str"),
            "timed_prompts": [p["exercise"] for p in result.get("timed_prompts") or []],
            "skipped": result.get("skipped") or [],
            "appended": bool(result.get("appended")),
            "needs_bodyweight": bool(result.get("needs_bodyweight_info")),
        }
        offline_fix = _offline_fix_fields()
        # The phone forgets its kept copy once it lands here (see offline-sync.js).
        offline_saved = offline_fix["id"] if offline_fix else None
        return redirect(url_for('view_workout', date_str=result.get("date_str"), saved=1, offline_saved=offline_saved))

    @login_required
    def log_preview():
        text = to_plain_text(request.form.get('workout_text', ''))
        append = request.form.get('mode') == 'append'
        header = None
        title = (request.form.get('title') or '').strip()
        date_value = (request.form.get('date') or '').strip()
        if date_value:
            # Edit page: title and date live in their own fields.
            try:
                header_date = datetime.strptime(date_value, '%Y-%m-%d')
            except ValueError:
                return jsonify({"ok": False, "errors": [{"line": None, "message": "Pick a valid date."}]}), 400
            header = f"{header_date.day}/{header_date.month}/{header_date.strftime('%y')} {title or 'Workout'}"
        try:
            check = check_workout_text(
                Session, current_user, text, header=header, append=append,
                now=_client_saved_at(request.form.get('saved_at')),
            )
        except Exception as e:
            logger.error(f"Log preview failed: {e}", exc_info=True)
            return jsonify({"ok": False, "errors": [{"line": None, "message": "Couldn't read this right now."}]}), 500
        payload = public_check(check)
        existing = payload.get("existing")
        if existing:
            existing["url"] = url_for('view_workout', date_str=existing["date_str"])
            existing["title"] = _clean_workout_title(existing.get("title") or "Workout")
        return jsonify(payload)

    @login_required
    def set_timed_preference():
        user = current_user
        exercise_name = (request.args.get('exercise') or '').strip()
        choice = (request.args.get('is_timed') or '').strip().lower()
        next_url = (request.args.get('next') or '').strip()

        if not is_safe_redirect_url(next_url, request.host_url):
            next_url = url_for('log_workout')

        if not exercise_name or choice not in {'yes', 'no'}:
            flash("Invalid timed exercise preference request.", "error")
            return redirect(next_url)

        try:
            set_timed_exercise_preference(Session, user.id, exercise_name, choice == 'yes')
            Session.commit()
            saved = session.get(LOG_SAVED_SESSION_KEY)
            if isinstance(saved, dict) and saved.get("timed_prompts"):
                saved["timed_prompts"] = [
                    name for name in saved["timed_prompts"] if name.lower() != exercise_name.lower()
                ]
                session[LOG_SAVED_SESSION_KEY] = saved
        except Exception as e:
            Session.rollback()
            logger.error(f"Error saving timed preference: {e}", exc_info=True)
            flash("Could not save timed preference. Please try again.", "error")

        return redirect(next_url)

    app.add_url_rule('/', endpoint='index', view_func=index, methods=['GET'])
    app.add_url_rule('/workouts', endpoint='workout_history', view_func=workout_history, methods=['GET'])
    app.add_url_rule('/share/<token>', endpoint='shared_workout', view_func=shared_workout, methods=['GET'])
    app.add_url_rule('/shortcut/urls', endpoint='shortcut_urls', view_func=shortcut_urls, methods=['GET'])
    app.add_url_rule('/shortcut/recommend', endpoint='shortcut_recommend_url', view_func=shortcut_recommend_url, methods=['GET'])
    app.add_url_rule('/shortcut/recommend/<token>', endpoint='shortcut_recommend', view_func=shortcut_recommend, methods=['GET'])
    app.add_url_rule('/shortcut/pick', endpoint='shortcut_pick_url', view_func=shortcut_pick_url, methods=['GET'])
    app.add_url_rule('/shortcut/pick/<token>', endpoint='shortcut_pick', view_func=shortcut_pick, methods=['GET'])
    app.add_url_rule('/shortcut/log', endpoint='shortcut_log_url', view_func=shortcut_log_url, methods=['GET'])
    app.add_url_rule('/shortcut/log/<token>', endpoint='shortcut_log', view_func=shortcut_log, methods=['GET', 'POST'])
    app.add_url_rule('/shortcut/mapping', endpoint='shortcut_key_map_settings', view_func=shortcut_key_map_settings, methods=['GET', 'POST'])
    app.add_url_rule(
        '/<username>',
        endpoint='user_dashboard',
        view_func=user_dashboard,
        methods=['GET'],
    )
    app.add_url_rule('/workout/<date_str>', endpoint='view_workout', view_func=view_workout, methods=['GET'])
    app.add_url_rule('/summary/<date_str>', endpoint='workout_summary', view_func=workout_summary, methods=['GET'])
    app.add_url_rule('/workout/<date_str>/edit', endpoint='edit_workout', view_func=edit_workout, methods=['GET', 'POST'])
    app.add_url_rule('/workout/<date_str>/delete', endpoint='delete_workout', view_func=delete_workout, methods=['POST'])
    app.add_url_rule('/workouts/delete-selected', endpoint='bulk_delete_workouts', view_func=bulk_delete_workouts, methods=['POST'])
    app.add_url_rule('/log', endpoint='log_workout', view_func=log_workout, methods=['GET', 'POST'])
    app.add_url_rule('/log/preview', endpoint='log_preview', view_func=log_preview, methods=['POST'])
    app.add_url_rule('/timed-preference/set', endpoint='set_timed_preference', view_func=set_timed_preference, methods=['GET'])
    app.add_url_rule('/api/recommend-workout', endpoint='recommend_workout_api', view_func=recommend_workout_api, methods=['GET'])
    app.add_url_rule('/api/csrf-token', endpoint='csrf_token_api', view_func=csrf_token_api, methods=['GET'])
    app.add_url_rule('/api/offline-workouts', endpoint='upload_offline_workout', view_func=upload_offline_workout, methods=['POST'])
    app.add_url_rule('/api/history-qa', endpoint='history_qa_api', view_func=history_qa_api, methods=['POST'])
    app.add_url_rule('/api/ai-coach', endpoint='ai_coach_api', view_func=ai_coach_api, methods=['POST'])
    app.add_url_rule('/api/ai-coach/rate', endpoint='ai_coach_rate_api', view_func=ai_coach_rate_api, methods=['POST'])
    app.add_url_rule('/api/ai-coach/suggestions', endpoint='ai_coach_suggestions_api',
                     view_func=ai_coach_suggestions_api, methods=['GET'])
