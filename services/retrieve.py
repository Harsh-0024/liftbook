from datetime import datetime, timedelta
import re
import statistics
from typing import Dict, List, Optional

from sqlalchemy import func

from config import Config
from models import (
    CustomRetrievalEvent,
    CustomRetrievalPreference,
    ExerciseGroupChoice,
    Plan,
    RepRange,
    User,
    UserRole,
    WorkoutLog,
)
from list_of_exercise import (
    BW_EXERCISES,
    DEFAULT_PLAN,
    DEFAULT_REP_RANGES,
    PREVIOUS_DEFAULT_PLANS,
    get_workout_days,
    list_of_exercises,
)
from services.best_scoring import best_workout_strength_score, coerce_equal_len_sets
from services.bodyweight import effective_sets_for_log, infer_log_uses_bodyweight, is_bodyweight_enabled
from services.workout_quality import WorkoutQualityScorer
from services.exercise_matching import (
    build_name_index,
    compound_vocabulary,
    normalize_exercise_name,
    resolve_equivalent_names,
    token_signature,
)
from services.rep_ranges import is_no_range, lookup_rep_target
from services.workout_title import classify_by_name, infer_workout_title, split_title, title_from_plan_day
from parsers.workout import _parse_plan_exercise_line, join_set_rows, parse_bw_weight, parse_set_row
from utils.dates import local_now


CUSTOM_RETRIEVAL_SORT_MODES = {
    "alpha_asc",
    "alpha_desc",
    "most_retrieved",
}
DEFAULT_CUSTOM_RETRIEVAL_SORT_MODE = "most_retrieved"
CUSTOM_RETRIEVAL_HISTORY_DAYS = 90
# Custom workout: which exercises someone trains often. See often_trained_keys().
PACE_HISTORY_DAYS = 182          # the pace is learned from the last 6 months
BREAK_COUNTS_AS_DAYS = 14        # a longer stretch without workouts counts as two weeks
WINDOW_PACES = 3                 # look back 3 times the pace...
WINDOW_MIN_DAYS = 28             # ...but at least 4 weeks
WINDOW_MAX_DAYS = 182            # ...and at most 6 months
OFTEN_MIN_DAYS = 2               # trained on 2 days in that time: part of the routine
MIN_REPEATS_TO_FOLD = 5          # fewer repeats than this: too early to tell, nothing folds
PLAN_FOLLOWED_SHARE = 0.5        # the plan counts when half its exercises were trained lately


def _normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines())


def _build_default_rep_text() -> str:
    return "\n".join(f"{ex}: {rng}" for ex, rng in DEFAULT_REP_RANGES.items())


def _normalized_email(value: str) -> str:
    return (value or "").strip().lower()


def _get_ordered_admins(db_session):
    admins = (
        db_session.query(User)
        .filter(User.role == UserRole.ADMIN)
        .order_by(User.id.asc())
        .all()
    )
    if not admins:
        return []

    preferred_email = _normalized_email(getattr(Config, "ADMIN_EMAIL", ""))
    if not preferred_email:
        return admins

    preferred = [admin for admin in admins if _normalized_email(getattr(admin, "email", "")) == preferred_email]
    if not preferred:
        return admins

    remaining = [admin for admin in admins if admin not in preferred]
    return preferred + remaining


def _get_admin_user(db_session):
    admins = _get_ordered_admins(db_session)
    return admins[0] if admins else None


def get_admin_display_name(db_session) -> str:
    admin_user = _get_admin_user(db_session)
    if not admin_user:
        return "Admin"

    full_name = (getattr(admin_user, "full_name", "") or "").strip()
    if full_name:
        return full_name

    username = (getattr(admin_user, "username", "") or "").strip()
    if username:
        return username

    email = (getattr(admin_user, "email", "") or "").strip()
    if email:
        return email.split("@", 1)[0]

    return "Admin"


def _own_plan_text(db_session, user) -> str:
    """The plan this account wrote, or "" if it has none. An untouched copy of an
    earlier built-in plan (copied into new accounts) counts as none, so it gets
    today's DEFAULT_PLAN instead."""
    plan_row = db_session.query(Plan).filter_by(user_id=user.id).first()
    text = (plan_row.text_content if plan_row else "") or ""
    if not text.strip():
        return ""
    if _normalize_text(text) in {_normalize_text(p) for p in PREVIOUS_DEFAULT_PLANS}:
        return ""
    return text


def _own_rep_ranges_text(db_session, user) -> str:
    rep_row = db_session.query(RepRange).filter_by(user_id=user.id).first()
    text = (rep_row.text_content if rep_row else "") or ""
    return text if text.strip() else ""


def is_plan_owner(db_session, user) -> bool:
    """The account whose plan and rep ranges others can follow. It can't follow itself."""
    owner = _get_admin_user(db_session)
    return bool(owner and user and owner.id == user.id)


def _get_admin_plan_text(db_session) -> str:
    """The main admin's own plan; if they have none, the next admin's."""
    for admin in _get_ordered_admins(db_session):
        text = _own_plan_text(db_session, admin)
        if text:
            return text
    return ""


def _get_admin_rep_ranges_text(db_session) -> str:
    for admin in _get_ordered_admins(db_session):
        text = _own_rep_ranges_text(db_session, admin)
        if text:
            return text
    return ""


def get_effective_plan_text(db_session, user) -> str:
    """Following (any account but the owner, admins included): the owner's plan.
    Otherwise the account's own plan. Either way DEFAULT_PLAN if there is none."""
    if getattr(user, 'follow_admin_plan', False) and not is_plan_owner(db_session, user):
        return _get_admin_plan_text(db_session) or DEFAULT_PLAN or ""
    return _own_plan_text(db_session, user) or DEFAULT_PLAN or ""


def get_effective_rep_ranges_text(db_session, user) -> str:
    if getattr(user, 'follow_admin_exercises', False) and not is_plan_owner(db_session, user):
        return _get_admin_rep_ranges_text(db_session) or _build_default_rep_text()
    return _own_rep_ranges_text(db_session, user) or _build_default_rep_text()


def generate_retrieve_output(db_session, user, category, day_id):
    day_key = f"{category} {day_id}"
    plan_text = get_effective_plan_text(db_session, user)
    if not plan_text:
        return "Plan not found.", 0, 0

    all_plans = get_workout_days(plan_text)
    try:
        exercises = all_plans["workout"][category][day_key]
    except KeyError:
        return f"Day '{day_key}' not found in plan.", 0, 0

    today_str = _retrieve_date_string()
    header_line = f"{today_str} - {day_key}"
    if str(category).strip().lower() == "session":
        titles = all_plans.get("session_titles") if isinstance(all_plans, dict) else None
        if isinstance(titles, dict):
            session_title = titles.get(str(day_id))
            if session_title:
                header_line = f"{today_str} - Session {day_id} - {session_title}"

    return _generate_retrieve_output_for_exercises(
        db_session,
        user,
        exercises,
        header_line=header_line,
    )


DEFAULT_CUSTOM_WORKOUT_TITLE = "Custom Workout"


def clean_custom_workout_title(title) -> str:
    """Single-line, length-capped title that is safe to put in the header line."""
    cleaned = re.sub(r"\s+", " ", str(title or "")).strip(" -\u2013\u2014")
    return cleaned[:80].strip()


def infer_custom_workout_title(db_session, user, exercises) -> Optional[str]:
    """
    Infer a title such as "Chest & Triceps & Legs" for a custom selection by
    checking which plan sessions (and their titles) each exercise belongs to.
    Returns None when nothing can be inferred.
    """
    selected_names = []
    for exercise in exercises or []:
        name = str(_parse_plan_exercise_line(str(exercise or "")).get("name") or "").strip()
        if name:
            selected_names.append(name)
    if not selected_names:
        return None

    def key_fn(name):
        parsed = str(_parse_plan_exercise_line(str(name or "")).get("name") or name or "")
        keys = []
        norm = normalize_exercise_name(parsed)
        if norm:
            keys.append(norm)
        sig = token_signature(parsed, title_vocabulary)
        if sig:
            keys.append("sig:" + " ".join(sig))
        return keys

    sessions = []
    plan_titles = set()
    plan_data = get_workout_days(get_effective_plan_text(db_session, user) or "")
    workout_map = plan_data.get("workout", {}) if isinstance(plan_data, dict) else {}
    session_titles = plan_data.get("session_titles", {}) if isinstance(plan_data, dict) else {}
    if isinstance(workout_map, dict):
        for category, day_map in workout_map.items():
            if not isinstance(day_map, dict):
                continue
            for day_name, day_exercises in day_map.items():
                day_id = str(day_name).rsplit(" ", 1)[-1]
                title = title_from_plan_day(category, day_name, (session_titles or {}).get(day_id))
                if title and isinstance(day_exercises, list):
                    sessions.append((title, day_exercises))
                    plan_titles.add(split_title_key(title))

    # Exercises that are no longer in the plan may still have been logged in a
    # plan session before. Only trust history names that match a plan title, so
    # earlier custom titles never feed back into the inference.
    if plan_titles:
        try:
            history_rows = (
                db_session.query(WorkoutLog.workout_name, WorkoutLog.exercise)
                .filter(WorkoutLog.user_id == user.id, WorkoutLog.workout_name.isnot(None))
                .distinct()
                .all()
            )
        except Exception:
            history_rows = []
        for workout_name, exercise_name in history_rows or []:
            if split_title_key(workout_name) in plan_titles:
                sessions.append((str(workout_name), [exercise_name]))

    title_vocabulary = compound_vocabulary(
        selected_names + [str(e) for _, day_exercises in sessions for e in day_exercises]
    )
    try:
        return infer_workout_title(selected_names, sessions, key_fn=key_fn)
    except Exception:
        return None


def split_title_key(title) -> tuple:
    return tuple(part.lower() for part in split_title(str(title or "")))


def generate_custom_retrieve_output(db_session, user, exercises, *, set_overrides=None, title=None):
    """Generate the normal retrieve output for an explicitly selected exercise list."""
    title = clean_custom_workout_title(title) or DEFAULT_CUSTOM_WORKOUT_TITLE
    return _generate_retrieve_output_for_exercises(
        db_session,
        user,
        exercises,
        header_line=f"{_retrieve_date_string()} - {title}",
        set_overrides=set_overrides,
    )


def picks_for_plan_lines(db_session, user, lines):
    """[(picker key, sets)] for a plan day's lines, in order, with the sets a plan retrieve
    gives each (the plan's own count, else the rep range's, else 3): what Edit loads."""
    custom_ranges, custom_sets = _parse_rep_ranges_text(get_effective_rep_ranges_text(db_session, user))
    picks, seen = [], set()
    for line in lines or []:
        parsed = _parse_plan_exercise_line(str(line or ""))
        name = str(parsed.get("name") or line or "").strip()
        key = normalize_exercise_name(name)
        if not key or key == "unknown exercise" or key in seen:
            continue
        seen.add(key)
        sets = parsed.get("declared_sets")
        if sets is None:
            sets = lookup_rep_target(name, custom_ranges, custom_sets)[1]
        picks.append((key, int(sets) if isinstance(sets, int) and sets > 0 else 3))
    return picks


def get_custom_retrieval_sort_preference(db_session, user) -> str:
    preference = (
        db_session.query(CustomRetrievalPreference)
        .filter(CustomRetrievalPreference.user_id == user.id)
        .first()
    )
    mode = str(getattr(preference, "sort_mode", "") or "")
    return mode if mode in CUSTOM_RETRIEVAL_SORT_MODES else DEFAULT_CUSTOM_RETRIEVAL_SORT_MODE


def set_custom_retrieval_sort_preference(db_session, user, sort_mode: str) -> str:
    mode = str(sort_mode or "").strip()
    if mode not in CUSTOM_RETRIEVAL_SORT_MODES:
        raise ValueError("Invalid custom retrieval sort mode.")

    preference = (
        db_session.query(CustomRetrievalPreference)
        .filter(CustomRetrievalPreference.user_id == user.id)
        .first()
    )
    if preference is None:
        preference = CustomRetrievalPreference(user_id=user.id, sort_mode=mode)
        db_session.add(preference)
    else:
        preference.sort_mode = mode
        preference.updated_at = datetime.now()
    db_session.commit()
    return mode


def record_custom_retrieval(db_session, user, exercise_keys):
    unique_keys = []
    seen_keys = set()
    for key in exercise_keys or []:
        normalized_key = normalize_exercise_name(str(key or ""))
        if normalized_key and normalized_key not in seen_keys:
            seen_keys.add(normalized_key)
            unique_keys.append(normalized_key)

    if not unique_keys:
        return

    retrieved_at = datetime.now()
    db_session.add_all(
        CustomRetrievalEvent(
            user_id=user.id,
            exercise_key=exercise_key,
            retrieved_at=retrieved_at,
        )
        for exercise_key in unique_keys
    )
    db_session.commit()


def get_custom_retrieval_exercise_catalog(db_session, user, *, sort_mode=None):
    """Return selectable exercises from the plan, rep ranges, shared catalogue and user history,
    each marked "often" when it's in the plan or trained regularly of late."""
    catalog = {}

    key_by_signature = {}
    plan_text = get_effective_plan_text(db_session, user)
    plan_data = get_workout_days(plan_text or "")
    logged_exercises = (
        db_session.query(WorkoutLog.exercise)
        .filter(WorkoutLog.user_id == user.id)
        .distinct()
        .all()
    )
    rep_ranges_text = get_effective_rep_ranges_text(db_session, user)
    # Words written as one anywhere here let the same word written as two join it:
    # "Rod Push Down" in the history is the plan's "Rod Pushdown".
    vocabulary = compound_vocabulary(
        [str(e) for day_map in (plan_data.get("workout") or {}).values() if isinstance(day_map, dict)
         for exercises in day_map.values() if isinstance(exercises, list) for e in exercises]
        + list(list_of_exercises)
        + [row[0] for row in logged_exercises or [] if row and row[0]]
        + [line.split(":", 1)[0] for line in (rep_ranges_text or "").splitlines() if ":" in line]
    )

    def add_exercise(raw_exercise, *, preserve_plan_details=False, yours=False, merge_twins=False):
        raw_value = str(raw_exercise or "").strip()
        if not raw_value:
            return None

        parsed = _parse_plan_exercise_line(raw_value)
        display_name = str(parsed.get("name") or raw_value).strip()
        key = normalize_exercise_name(display_name)
        if not key or key == "unknown exercise":
            return None
        # "Lat Dumbbell Rows" in the history is the plan's "Dumbbell Lat Row": the same
        # words in another order. Keep one row, under the name already in the list.
        signature = token_signature(display_name, vocabulary)
        twin = key_by_signature.get(signature) if signature else None
        if merge_twins and twin and twin != key and key not in catalog:
            if yours:
                catalog[twin]["yours"] = True
            return twin
        if signature:
            key_by_signature.setdefault(signature, key)

        # A plan item may carry inline set/rep targets, so it wins over the
        # generic catalogue or a logged-name variant for the same exercise.
        if key not in catalog or preserve_plan_details:
            catalog[key] = {
                "key": key,
                "name": display_name,
                "exercise_line": raw_value if preserve_plan_details else display_name,
                "yours": bool(yours) or bool(catalog.get(key, {}).get("yours")),
            }
        elif yours:
            catalog[key]["yours"] = True
        return key

    plan_keys = set()
    workout_map = plan_data.get("workout", {}) if isinstance(plan_data, dict) else {}
    if isinstance(workout_map, dict):
        for day_map in workout_map.values():
            if not isinstance(day_map, dict):
                continue
            for exercises in day_map.values():
                if not isinstance(exercises, list):
                    continue
                for exercise in exercises:
                    plan_keys.add(add_exercise(exercise, preserve_plan_details=True, yours=True))

    for exercise in list_of_exercises:
        add_exercise(exercise, merge_twins=True)

    key_by_logged_name = {}
    for row in logged_exercises or []:
        try:
            name = row[0]
        except (IndexError, KeyError, TypeError):
            name = row
        key_by_logged_name[name] = add_exercise(name, yours=True, merge_twins=True)

    # Every exercise in the rep ranges, too: the list can hold many not in the plan or history.
    # They're yours when the rep ranges are; a list followed from the admin or the defaults
    # shows like the built-in list.
    own_rep_ranges = bool((_own_rep_ranges_text(db_session, user) or "").strip())
    for line in (rep_ranges_text or "").splitlines():
        if ":" in line:
            add_exercise(line.split(":", 1)[0], yours=own_rep_ranges, merge_twins=True)

    often_keys = _often_trained_catalog_keys(db_session, user, key_by_logged_name, plan_keys)

    cutoff = datetime.now() - timedelta(days=CUSTOM_RETRIEVAL_HISTORY_DAYS)
    usage_rows = (
        db_session.query(
            CustomRetrievalEvent.exercise_key,
            func.count(CustomRetrievalEvent.id),
            func.max(CustomRetrievalEvent.retrieved_at),
        )
        .filter(
            CustomRetrievalEvent.user_id == user.id,
            CustomRetrievalEvent.retrieved_at >= cutoff,
        )
        .group_by(CustomRetrievalEvent.exercise_key)
        .all()
    )
    usage_by_key = {
        str(row[0]): {
            "count": int(row[1] or 0),
            "last_retrieved_at": row[2],
        }
        for row in usage_rows or []
    }

    plan_parts = _plan_parts_by_exercise(plan_data)
    custom_ranges, custom_sets = _parse_rep_ranges_text(rep_ranges_text)
    moved = get_exercise_group_choices(db_session, user)
    for key, item in catalog.items():
        usage = usage_by_key.get(key, {})
        item["retrieval_count"] = int(usage.get("count") or 0)
        item["last_retrieved_at"] = usage.get("last_retrieved_at")
        # The same sets and reps a plan retrieve would give this exercise.
        parsed = _parse_plan_exercise_line(item["exercise_line"])
        rep_range, rep_range_sets = lookup_rep_target(item["name"], custom_ranges, custom_sets)
        declared = parsed.get("declared_sets")
        if declared is None:
            declared = rep_range_sets
        item["default_sets"] = int(declared) if isinstance(declared, int) and declared > 0 else 3
        item["rep_range"] = rep_range or parsed.get("inline_range") or ""
        item["auto_group"] = _picker_group(item["name"], plan_parts.get(key))
        item["group"] = moved.get(key) or item["auto_group"]
        item["often"] = often_keys is None or key in often_keys

    mode = sort_mode if sort_mode in CUSTOM_RETRIEVAL_SORT_MODES else get_custom_retrieval_sort_preference(db_session, user)
    return _sort_custom_retrieval_catalog(list(catalog.values()), mode)


def often_trained_keys(workouts, plan_keys=()) -> Optional[set]:
    """Which exercises someone trains often, learned from their own workouts.

    workouts: [(date, {exercise keys done that day})]. Returns the keys trained often, or
    None when there isn't enough history yet to tell (then nothing is folded away).

    1. The pace: how many days usually pass before an exercise comes back - the median of
       every repeat in the last 6 months, so a rare comeback after months doesn't skew it.
    2. Look back 3 paces from the latest workout (at least 4 weeks, at most 6 months).
    3. Often = trained on 2+ days in that time. Also often: an exercise done for the first
       time within the last pace (just started), and the plan's exercises when the plan is
       followed (half of them trained in the last 6 months).
    Throughout, a stretch without workouts counts as at most two weeks, so a holiday or an
    illness doesn't fold away someone's routine. Worked out fresh each time, so it follows
    any change in how often someone trains.
    """
    days = sorted({day for day, _ in workouts})
    if not days:
        return None
    # A clock that runs on training time: breaks count as two weeks at most.
    clock, now = {}, 0
    for previous, day in zip([None] + days, days):
        if previous is not None:
            now += min(BREAK_COUNTS_AS_DAYS, (day - previous).days)
        clock[day] = now
    times = {}
    for day, keys in workouts:
        for key in keys or ():
            if key:
                times.setdefault(key, set()).add(clock[day])
    times = {key: sorted(ts) for key, ts in times.items()}

    gaps = [b - a for ts in times.values() for a, b in zip(ts, ts[1:]) if b > now - PACE_HISTORY_DAYS]
    if len(gaps) < MIN_REPEATS_TO_FOLD:
        return None
    pace = statistics.median(gaps)
    window = min(WINDOW_MAX_DAYS, max(WINDOW_MIN_DAYS, WINDOW_PACES * pace))

    often = set()
    for key, ts in times.items():
        if sum(t > now - window for t in ts) >= OFTEN_MIN_DAYS:
            often.add(key)
        elif len(ts) == 1 and now - ts[0] <= pace:
            often.add(key)
    plan_keys = {key for key in plan_keys if key}
    if plan_keys:
        trained_lately = {key for key, ts in times.items() if ts[-1] > now - PACE_HISTORY_DAYS}
        if len(plan_keys & trained_lately) >= PLAN_FOLLOWED_SHARE * len(plan_keys):
            often |= plan_keys
    return often


def _often_trained_catalog_keys(db_session, user, key_by_logged_name, plan_keys) -> Optional[set]:
    """often_trained_keys() for this user's logged workouts, under the picker's keys."""
    rows = (
        db_session.query(WorkoutLog.exercise, WorkoutLog.date)
        .filter(WorkoutLog.user_id == user.id)
        .all()
    )
    by_day = {}
    for name, when in rows:
        key = key_by_logged_name.get(name)
        if key and when:
            by_day.setdefault(when.date(), set()).add(key)
    return often_trained_keys(sorted(by_day.items()), plan_keys)


def _sort_custom_retrieval_catalog(catalog, sort_mode):
    if sort_mode == "alpha_desc":
        return sorted(catalog, key=lambda item: item["name"].casefold(), reverse=True)
    if sort_mode == "most_retrieved":
        def most_retrieved_key(item):
            last_retrieved_at = item.get("last_retrieved_at")
            timestamp = last_retrieved_at.timestamp() if isinstance(last_retrieved_at, datetime) else 0
            return (-int(item.get("retrieval_count") or 0), -timestamp, item["name"].casefold())

        return sorted(catalog, key=most_retrieved_key)
    return sorted(catalog, key=lambda item: item["name"].casefold())


def _retrieve_date_string() -> str:
    today = local_now()
    return f"{today.day}/{today.month}/{today.year % 100:02d}"


def _parse_rep_ranges_text(rep_text):
    """Rep-range settings ("Bench Press: 3, 6-8") -> (ranges, set counts), keyed by lower and normalised name."""
    custom_ranges = {}
    custom_sets = {}
    for line in (rep_text or "").split('\n'):
        if ':' not in line:
            continue
        k, v = line.split(':', 1)
        exercise_key_raw = k.strip()
        exercise_key = exercise_key_raw.lower()
        exercise_key_norm = normalize_exercise_name(exercise_key_raw)
        value = "" if is_no_range(v) else v.strip()
        m = re.match(r'^(\d+)\s*,\s*(.+)$', value)
        if m:
            try:
                set_count = int(m.group(1))
            except Exception:
                set_count = None
            range_value = m.group(2).strip()
            custom_sets[exercise_key] = set_count
            custom_ranges[exercise_key] = range_value
            if exercise_key_norm:
                custom_sets[exercise_key_norm] = set_count
                custom_ranges[exercise_key_norm] = range_value
        else:
            custom_ranges[exercise_key] = value
            if exercise_key_norm:
                custom_ranges[exercise_key_norm] = value
    return custom_ranges, custom_sets


# Muscle groups for the custom workout picker, in the order they are shown.
CUSTOM_PICKER_GROUPS = ("Chest", "Back", "Shoulders", "Biceps", "Triceps", "Forearms", "Legs", "Abs", "Other")


def get_exercise_group_choices(db_session, user) -> Dict[str, str]:
    """Exercises this user moved to another group: {exercise key: group}."""
    rows = (
        db_session.query(ExerciseGroupChoice.exercise_key, ExerciseGroupChoice.group_name)
        .filter(ExerciseGroupChoice.user_id == user.id)
        .all()
    )
    return {key: group for key, group in rows if group in CUSTOM_PICKER_GROUPS}


def set_exercise_group_choice(db_session, user, exercise_key, group, auto_group) -> None:
    """Remember a move; moving it back to where the app would put it forgets the choice."""
    if group not in CUSTOM_PICKER_GROUPS:
        raise ValueError("Unknown group.")
    choice = (
        db_session.query(ExerciseGroupChoice)
        .filter(ExerciseGroupChoice.user_id == user.id, ExerciseGroupChoice.exercise_key == exercise_key)
        .first()
    )
    if group == auto_group:
        if choice is not None:
            db_session.delete(choice)
    elif choice is None:
        db_session.add(ExerciseGroupChoice(user_id=user.id, exercise_key=exercise_key, group_name=group))
    else:
        choice.group_name = group
        choice.updated_at = datetime.now()
    db_session.commit()


def _plan_parts_by_exercise(plan_data) -> Dict[str, list]:
    """For each plan exercise, the muscles named in the titles of the days it is on."""
    plan_parts = {}
    workout_map = plan_data.get("workout", {}) if isinstance(plan_data, dict) else {}
    session_titles = plan_data.get("session_titles", {}) if isinstance(plan_data, dict) else {}
    if isinstance(workout_map, dict):
        for category, day_map in workout_map.items():
            if not isinstance(day_map, dict):
                continue
            for day_name, exercises in day_map.items():
                day_id = str(day_name).rsplit(" ", 1)[-1]
                parts = set(split_title(title_from_plan_day(category, day_name, (session_titles or {}).get(day_id))))
                for exercise in exercises if isinstance(exercises, list) else []:
                    name = str(_parse_plan_exercise_line(str(exercise)).get("name") or exercise)
                    plan_parts.setdefault(normalize_exercise_name(name), []).append(parts)
    return plan_parts


def exercise_groups_for(db_session, user, names) -> Dict[str, str]:
    """{name: muscle group} for these exercises, the same groups the Custom workout page shows
    (including any the user moved there)."""
    plan_parts = _plan_parts_by_exercise(get_workout_days(get_effective_plan_text(db_session, user) or ""))
    moved = get_exercise_group_choices(db_session, user)
    out = {}
    for name in names:
        key = normalize_exercise_name(name)
        out[name] = moved.get(key) or _picker_group(name, plan_parts.get(key))
    return out


def _picker_group(name, plan_day_parts=None) -> str:
    """The exercise's muscle, from its name first.

    When the name doesn't say (a "Superman", a "Mudgal"), the plan decides, but only
    when every day the exercise is on names the same single muscle; an exercise that
    only sits on "Chest & Biceps" days could be either, so it stays in Other.
    """
    muscles = classify_by_name(name)
    if not muscles and plan_day_parts:
        common = set.intersection(*[set(parts) for parts in plan_day_parts])
        common &= set(CUSTOM_PICKER_GROUPS) - {"Other"}
        if len(common) == 1:
            muscles = common
    for group in CUSTOM_PICKER_GROUPS:
        if group in muscles:
            return group
    return "Other"


def _generate_retrieve_output_for_exercises(db_session, user, exercises, *, header_line, set_overrides=None):
    exercise_lines = [str(exercise or "").strip() for exercise in exercises or []]
    exercise_lines = [exercise for exercise in exercise_lines if exercise]
    if not exercise_lines:
        return "No exercises selected.", 0, 0

    # Build once per request so we can do conservative aliasing like
    # "Standing Calf Raises" <-> "Calf Raises Standing" (only when unambiguous).
    distinct_logged = (
        db_session.query(WorkoutLog.exercise)
        .filter(WorkoutLog.user_id == user.id)
        .distinct()
        .all()
    )
    logged_exercise_index = build_name_index([row[0] for row in distinct_logged or []])

    custom_ranges, custom_sets = _parse_rep_ranges_text(get_effective_rep_ranges_text(db_session, user))

    output_lines = [header_line, ""]
    bodyweight_line = _format_bodyweight_line(db_session, user)
    if bodyweight_line:
        output_lines.extend([bodyweight_line, ""])

    exercise_count = len(exercise_lines)
    set_count = 0
    normalized_set_overrides = {}
    for key, value in (set_overrides or {}).items():
        normalized_key = normalize_exercise_name(str(key or ""))
        try:
            set_count_override = int(value)
        except (TypeError, ValueError):
            continue
        if normalized_key and set_count_override > 0:
            normalized_set_overrides[normalized_key] = set_count_override

    for ex in exercise_lines:
        parsed_plan_ex = _parse_plan_exercise_line(ex)
        ex_name = str(parsed_plan_ex.get("name") or ex).strip()
        plan_declared_sets = parsed_plan_ex.get("declared_sets")
        plan_inline_range = parsed_plan_ex.get("inline_range")

        ex_key_norm = normalize_exercise_name(ex_name)
        # "Preacher Curl (Wellness)" takes Preacher Curl's rep range unless it has its own.
        rng, rep_range_sets = lookup_rep_target(ex_name, custom_ranges, custom_sets)
        if not rng and plan_inline_range:
            rng = plan_inline_range

        declared_sets = plan_declared_sets
        if declared_sets is None:
            declared_sets = rep_range_sets
        if ex_key_norm in normalized_set_overrides:
            declared_sets = normalized_set_overrides[ex_key_norm]
        fmt_rng = ""
        if rng and declared_sets:
            fmt_rng = f" - [{declared_sets}, {rng}]"
        elif declared_sets:
            fmt_rng = f" - [{declared_sets}]"
        elif rng:
            fmt_rng = f" - [{rng}]"

        target_sets = int(declared_sets) if isinstance(declared_sets, int) and declared_sets > 0 else 3
        target_rep_range = _parse_rep_range(rng)

        sets_line = _build_best_sets_line_from_logs(
            db_session,
            user,
            ex_name,
            target_sets=target_sets,
            target_rep_range=target_rep_range,
            logged_exercise_index=logged_exercise_index,
        )

        if _is_bw_exercise(db_session, user.id, ex_name):
            if not sets_line:
                sets_line = "bw/4, 1"
            sets_line = _normalize_bw(sets_line)
        elif not sets_line:
            sets_line = "1, 1"

        if sets_line:
            set_count += _count_sets_from_line(sets_line, target_sets=target_sets)

        output_lines.append(f"{ex_name}{fmt_rng}")
        if sets_line:
            output_lines.extend(_sets_line_as_rows(sets_line, target_sets=target_sets))
        output_lines.append("")

    return "\n".join(output_lines).rstrip(), exercise_count, set_count


def _exercise_candidates(exercise_name: str):
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


def _format_bodyweight_line(db_session, user) -> str:
    bodyweight = getattr(user, "bodyweight", None)
    if bodyweight is None:
        return ""
    try:
        value = float(bodyweight)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return f"Body Weight - {_format_value(value)} {_infer_weight_unit(db_session, user)}"


def _infer_weight_unit(db_session, user) -> str:
    try:
        logs = (
            db_session.query(WorkoutLog.exercise_string)
            .filter(WorkoutLog.user_id == user.id)
            .order_by(WorkoutLog.date.desc(), WorkoutLog.id.desc())
            .limit(50)
            .all()
        )
    except Exception:
        return "kg"

    counts = {"kg": 0, "lbs": 0}
    for row in logs or []:
        text = str(row[0] or "").lower()
        counts["kg"] += len(re.findall(r"\bkg(?:s)?\b", text))
        counts["lbs"] += len(re.findall(r"\blbs?\b", text))

    return "lbs" if counts["lbs"] > counts["kg"] else "kg"


def _parse_rep_range(value: str):
    if not value:
        return None
    nums = re.findall(r"\d+", str(value))
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    if len(nums) == 1:
        n = int(nums[0])
        return n, n
    return None


def _compress_shorthand_values(values):
    if not values:
        return []
    if len(values) == 1:
        return list(values)
    if all(v == values[0] for v in values):
        return [values[0]]
    if all(v == values[1] for v in values[1:]) and values[0] != values[1]:
        return [values[0], values[1]]
    return list(values)


def _is_bw_exercise(db_session, user_id: int, exercise: str) -> bool:
    if is_bodyweight_enabled(db_session, user_id, exercise):
        return True
    if exercise in BW_EXERCISES:
        return True
    normalized = exercise.strip().lower().replace("-", " ").replace("_", " ")
    for bw in BW_EXERCISES:
        if bw.lower().replace("-", " ").replace("_", " ") == normalized:
            return True
    return False


def _format_weight_token(
    exercise: str,
    weight,
    bodyweight,
    *,
    force_bw: bool = False,
    current_bodyweight=None,
    render_as_bw: bool = False,
):
    token = _format_value(weight)
    if force_bw:
        return 'bw'
    if not render_as_bw:
        return token
    if bodyweight is None and current_bodyweight is None:
        return token

    try:
        weight_value = float(weight)
    except Exception:
        return token

    try:
        bw_logged = float(bodyweight) if bodyweight is not None else None
    except Exception:
        bw_logged = None

    try:
        bw_current = float(current_bodyweight) if current_bodyweight is not None else None
    except Exception:
        bw_current = None

    base_bw = bw_current if bw_current is not None else bw_logged
    if base_bw is None:
        return token

    offset = weight_value - base_bw
    if abs(offset) < 0.05:
        return "bw"
    sign = "+" if offset > 0 else "-"
    offset_str = _format_value(abs(round(offset, 2)))
    return f"bw{sign}{offset_str}"


def _build_best_sets_line_from_logs(
    db_session,
    user,
    exercise: str,
    target_sets: int = 3,
    target_rep_range=None,
    logged_exercise_index=None,
) -> str:
    candidates = resolve_equivalent_names(exercise, logged_exercise_index) if logged_exercise_index else []
    if not candidates:
        candidates = _exercise_candidates(exercise)
    if not candidates:
        return ""

    logs = (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user.id)
        .filter(WorkoutLog.exercise.in_(candidates))
        .order_by(WorkoutLog.date.desc())
        .all()
    )
    if not logs:
        return ""

    required_sets = int(target_sets) if isinstance(target_sets, int) and target_sets > 0 else 3
    preferred = []
    fallback = []

    for log in logs:
        sets_json = effective_sets_for_log(db_session, log)
        sets_json = sets_json if isinstance(sets_json, dict) else None
        if not sets_json:
            continue
        weights = sets_json.get("weights") or []
        reps = sets_json.get("reps") or []
        if not weights and not reps:
            continue

        metrics = best_workout_strength_score(sets_json, top_n=required_sets)
        score = float(metrics.get("score") or 0.0)
        set_count = int(metrics.get("set_count") or 0)
        if score <= 0:
            continue

        row = (log, score, set_count)
        if set_count >= required_sets:
            preferred.append(row)
        else:
            fallback.append(row)

    pool = preferred if preferred else fallback
    if not pool:
        return ""
    best_log, _, _ = max(
        pool,
        key=lambda row: (
            row[1],
            row[2],
            getattr(row[0], "date", datetime.min),
        ),
    )

    use_bw_format = _log_uses_bw_notation(best_log, exercise)

    sets_json = effective_sets_for_log(db_session, best_log)
    sets_json = sets_json if isinstance(sets_json, dict) else None
    if not sets_json:
        if use_bw_format and best_log.exercise_string:
            extracted = _extract_sets_line(best_log.exercise_string, best_log.exercise)
            return _rebase_bw_sets_line(
                best_log,
                exercise,
                extracted,
                current_bodyweight=getattr(user, "bodyweight", None),
                target_sets=required_sets,
            )
        return ""
    weights = sets_json.get("weights") or []
    reps = sets_json.get("reps") or []
    weights, reps = coerce_equal_len_sets(weights, reps)
    if not weights or not reps:
        if use_bw_format and best_log.exercise_string:
            extracted = _extract_sets_line(best_log.exercise_string, best_log.exercise)
            return _rebase_bw_sets_line(
                best_log,
                exercise,
                extracted,
                current_bodyweight=getattr(user, "bodyweight", None),
                target_sets=required_sets,
            )
        return ""

    scored = []
    for idx, (w, r) in enumerate(zip(weights, reps)):
        if w is None or r is None:
            continue
        if r <= 0:
            continue
        est = WorkoutQualityScorer.estimate_1rm(float(w), int(r))
        scored.append((est, float(w), int(r), idx))

    if not scored:
        return ""

    # Display order should be intuitive for progression: heaviest to lightest.
    # For same weight, higher reps first.
    scored.sort(key=lambda t: (t[1], t[2], t[0]), reverse=True)
    top = scored[: min(required_sets, len(scored))]
    weights_top = [t[1] for t in top]
    reps_top = [t[2] for t in top]

    log_bodyweight = getattr(best_log, "bodyweight", None)
    current_bodyweight = getattr(user, "bodyweight", None)
    original_bw_tokens = (
        _extract_original_bw_tokens(
            best_log,
            exercise,
            target_sets=max(required_sets, len(weights), len(reps)),
        )
        if use_bw_format
        else []
    )
    weight_tokens = [
        _format_retrieved_weight_token(
            exercise,
            t[1],
            logged_bodyweight=log_bodyweight,
            current_bodyweight=current_bodyweight,
            render_as_bw=use_bw_format,
            original_token=(
                original_bw_tokens[t[3]]
                if t[3] < len(original_bw_tokens)
                else ""
            ),
        )
        for t in top
    ]
    rep_tokens = [str(int(r)) for r in reps_top]

    weight_tokens = _compress_shorthand_values(weight_tokens)
    rep_tokens = _compress_shorthand_values(rep_tokens)

    weights_part = " ".join(weight_tokens).strip()
    reps_part = " ".join(rep_tokens).strip()
    if not weights_part or not reps_part:
        return ""
    return f"{weights_part}, {reps_part}"


def _format_value(value):
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _format_sets_json(sets_json):
    if not sets_json or not isinstance(sets_json, dict):
        return ""
    weights = sets_json.get("weights") or []
    reps = sets_json.get("reps") or []
    if not weights and not reps:
        return ""
    weights_line = " ".join(_format_value(w) for w in weights) if weights else ""
    reps_line = " ".join(str(int(r)) if isinstance(r, (int, float)) else str(r) for r in reps) if reps else ""
    if weights_line and reps_line:
        return f"{weights_line}, {reps_line}"
    return weights_line or reps_line


def _extract_original_bw_tokens(log, exercise: str, target_sets: int = 3):
    sets_line = _extract_sets_line(getattr(log, "exercise_string", ""), exercise)
    if not sets_line:
        return []
    weights, _ = _parse_sets_line_tokens(sets_line, target_sets=target_sets)
    tokens = []
    for token in weights:
        token = _normalize_bw(str(token or "").strip())
        if parse_bw_weight(token, getattr(log, "bodyweight", None)) is not None:
            tokens.append(token)
        else:
            tokens.append("")
    return tokens


def _format_retrieved_weight_token(
    exercise: str,
    weight,
    *,
    logged_bodyweight=None,
    current_bodyweight=None,
    render_as_bw: bool = False,
    original_token: str = "",
):
    if not render_as_bw:
        return _format_value(weight)

    original_token = _normalize_bw(str(original_token or "").strip())
    if original_token:
        try:
            current_token_weight = parse_bw_weight(original_token, current_bodyweight)
            stored_weight = float(weight)
        except (TypeError, ValueError):
            current_token_weight = None
            stored_weight = None
        if (
            current_token_weight is not None
            and stored_weight is not None
            and abs(float(current_token_weight) - stored_weight) < 0.05
        ):
            return original_token

    return _format_weight_token(
        exercise,
        weight,
        logged_bodyweight or current_bodyweight,
        force_bw=False,
        current_bodyweight=current_bodyweight,
        render_as_bw=True,
    )


def _rebase_bw_sets_line(log, exercise: str, sets_line: str, *, current_bodyweight=None, target_sets: int = 3) -> str:
    if not sets_line:
        return ""
    weights, reps = _parse_sets_line_tokens(sets_line, target_sets=target_sets)
    if not weights or not reps:
        return _normalize_bw(sets_line)

    logged_bodyweight = getattr(log, "bodyweight", None)
    weight_tokens = []
    for token in weights:
        token = _normalize_bw(str(token or "").strip())
        parsed_weight = parse_bw_weight(token, logged_bodyweight)
        if parsed_weight is None:
            weight_tokens.append(token)
            continue
        weight_tokens.append(
            _format_retrieved_weight_token(
                exercise,
                parsed_weight,
                logged_bodyweight=logged_bodyweight,
                current_bodyweight=current_bodyweight,
                render_as_bw=True,
                original_token=token,
            )
        )
    return f"{' '.join(_compress_shorthand_values(weight_tokens))}, {' '.join(_compress_shorthand_values(reps))}"


def _parse_sets_line_tokens(sets_line: str, target_sets: int = 3):
    normalized = _normalize_sets_line(sets_line, target_sets=target_sets)
    x_matches = re.findall(
        r'(bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)\s*[x×]\s*(\d+)',
        normalized,
        flags=re.IGNORECASE,
    )
    if x_matches:
        return [m[0] for m in x_matches], [m[1] for m in x_matches]

    parts = normalized.split(',', 1)
    weights_part = parts[0].strip() if parts else ""
    reps_part = parts[1].strip() if len(parts) > 1 else ""
    weights_part = re.sub(r'(kg|lbs|lb)', '', weights_part, flags=re.IGNORECASE)
    reps_part = re.sub(r'(kg|lbs|lb)', '', reps_part, flags=re.IGNORECASE)
    weights = [t for t in weights_part.replace(',', ' ').split() if t]
    reps = [t for t in reps_part.replace(',', ' ').split() if t]
    return weights, reps


def _is_default_numeric_sets(value: str) -> bool:
    normalized = (value or "").strip().lower().replace("  ", " ")
    return normalized in {"1 1 1, 1 1 1", "1, 1"}


def _extract_sets_line(best_string: str, exercise: str) -> str:
    trimmed = (best_string or "").strip()
    if not trimmed:
        return ""
    lines = [line.strip() for line in trimmed.splitlines() if line.strip()]
    data_like = lambda s: bool(re.match(r'^(?:bw|,|-?\d)', (s or "").strip().lower()))
    if len(lines) >= 3 and data_like(lines[-2]) and data_like(lines[-1]) and "," not in lines[-2]:
        return f"{lines[-2]}, {lines[-1]}".strip()
    if len(lines) >= 2:
        if data_like(lines[-1]):
            return lines[-1]
    if " - [" in trimmed and "]" in trimmed:
        tail = trimmed.split("]", 1)[1].strip()
        tail = tail.lstrip("-:").strip()
        if tail:
            return tail
    if trimmed.lower().startswith(exercise.lower()):
        tail = trimmed[len(exercise):].strip()
        tail = tail.lstrip("-:").strip()
        if tail:
            return tail
    return trimmed


def _log_uses_bw_notation(log, exercise: str) -> bool:
    if infer_log_uses_bodyweight(None, log):
        return True
    sets_line = _extract_sets_line(getattr(log, "exercise_string", ""), exercise)
    if not sets_line:
        return False
    return bool(
        re.search(
            r"\bbw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?\b",
            sets_line,
            flags=re.IGNORECASE,
        )
    )


def _normalize_bw(value: str) -> str:
    value = re.sub(r"\bbw/", "bw/", value, flags=re.IGNORECASE)
    value = re.sub(r"\bbw(?=[+-])", "bw", value, flags=re.IGNORECASE)
    value = re.sub(r"\bbw\b", "bw", value, flags=re.IGNORECASE)
    return value


def _expand_shorthand_tokens(tokens, target_sets: int = 3):
    if not tokens:
        return []
    if target_sets <= 0:
        return list(tokens)
    if len(tokens) == 1:
        return [tokens[0]] * target_sets
    if len(tokens) == 2 and len(tokens) < target_sets:
        return [tokens[0]] + [tokens[1]] * (target_sets - 1)
    if len(tokens) < target_sets:
        return list(tokens) + [tokens[-1]] * (target_sets - len(tokens))
    return list(tokens)


def _normalize_sets_line(sets_line: str, default_weight: str = "1", target_sets: int = 3) -> str:
    if not sets_line:
        return ""

    x_matches = re.findall(
        r'(bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)\s*[x×]\s*(\d+)',
        sets_line,
        flags=re.IGNORECASE,
    )
    if x_matches:
        weights = [m[0] for m in x_matches]
        reps = [m[1] for m in x_matches]
    else:
        parts = sets_line.split(',', 1)
        weights_part = parts[0].strip() if parts else ""
        reps_part = parts[1].strip() if len(parts) > 1 else ""

        weights_part = re.sub(r'(kg|lbs|lb)', '', weights_part, flags=re.IGNORECASE)
        reps_part = re.sub(r'(kg|lbs|lb)', '', reps_part, flags=re.IGNORECASE)

        weights = [t for t in weights_part.replace(',', ' ').split() if t]
        reps = [t for t in reps_part.replace(',', ' ').split() if t]

    if not weights and not reps:
        weights = [default_weight]
        reps = ["1"]
    elif not weights:
        weights = [default_weight] * len(reps)
    elif not reps:
        reps = ["1"] * len(weights)

    weights = _expand_shorthand_tokens(weights, target_sets=target_sets)
    reps = _expand_shorthand_tokens(reps, target_sets=target_sets)

    if len(weights) == 1 and len(reps) > 1:
        weights = weights * len(reps)
    elif len(reps) == 1 and len(weights) > 1:
        reps = reps * len(weights)
    elif len(weights) < len(reps) and weights:
        weights = weights + [weights[-1]] * (len(reps) - len(weights))
    elif len(reps) < len(weights) and reps:
        reps = reps + [reps[-1]] * (len(weights) - len(reps))

    if x_matches:
        return ", ".join(f"{w} x {r}" for w, r in zip(weights, reps))

    return f"{' '.join(weights)}, {' '.join(reps)}"


def _sets_line_as_rows(sets_line: str, target_sets: int = 3) -> List[str]:
    """One set per line ("45, 3" then "40, 4"), shorthand spelled out, so every set reads
    on its own and is edited on its own."""
    weights, reps = _parse_sets_line_tokens(sets_line, target_sets=target_sets)
    if not weights or len(weights) != len(reps):
        return [sets_line]
    return [f"{w}, {r}" for w, r in zip(weights, reps)]


def _count_sets_from_line(sets_line: str, target_sets: int = 3) -> int:
    """Count sets for the display line.

    If the line contains fewer tokens than target_sets, we assume trailing-repeat
    expansion up to target_sets.
    """
    if not sets_line:
        return 0

    # Check for 'x' notation (e.g., 'bw x5 x5 x5' or '100kg x5 x5')
    x_matches = re.findall(r'(bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)\s*x\s*\d+', sets_line, flags=re.IGNORECASE)
    if x_matches:
        raw = len(x_matches)
        return int(target_sets) if target_sets and raw < int(target_sets) else raw
    
    # Check for comma-separated format (weights, reps)
    if ',' in sets_line:
        parts = sets_line.split(',', 1)
        weights_part = parts[0].strip()
        reps_part = parts[1].strip() if len(parts) > 1 else ''
        
        # Count tokens in weights part
        weight_tokens = weights_part.replace('kg', '').replace('lbs', '').replace('lb', '').strip().split()
        weight_count = len([t for t in weight_tokens if t])
        
        # Count tokens in reps part
        rep_tokens = reps_part.replace('kg', '').replace('lbs', '').replace('lb', '').strip().split()
        rep_count = len([t for t in rep_tokens if t])
        
        # Use maximum and apply shorthand
        raw_count = max(weight_count, rep_count)
        return int(target_sets) if target_sets and raw_count < int(target_sets) else raw_count
    
    # Single line of weights or values
    tokens = sets_line.replace('kg', '').replace('lbs', '').replace('lb', '').strip().split()
    raw_count = len([t for t in tokens if t])
    return int(target_sets) if target_sets and raw_count < int(target_sets) else raw_count


def _target_label(declared_sets, inline_range) -> str:
    """Gym shorthand: "3 × 10–15" (sets × reps), or "2 sets" / "10–15 reps" when only one is set."""
    rng = (inline_range or "").strip()
    timed = bool(re.fullmatch(r"[\d\s\-–—]+s", rng, flags=re.IGNORECASE))
    if timed:
        rng = f"{rng[:-1].strip()} s"
    elif rng and not re.fullmatch(r"[\d\s\-–—]+", rng):
        rng = rng[:1].lower() + rng[1:]
    if declared_sets and rng:
        return f"{declared_sets} × {rng}"
    if declared_sets:
        return f"{declared_sets} set{'' if declared_sets == 1 else 's'}"
    if rng and re.fullmatch(r"[\d\s\-–—]+", rng):
        return f"{rng} reps"
    return rng


def _pretty_load(token: str) -> str:
    token = str(token or "").strip()
    if token.lower().startswith("bw"):
        return "BW" + token[2:].replace("-", "−")
    try:
        return f"{float(token):g}"
    except ValueError:
        return token


def describe_retrieve_output(output: str) -> Dict:
    """
    Split retrieve text into what the plan page shows: bodyweight, and per exercise its
    target and last numbers as "30×7 · 26.4×7". The text itself is what gets copied.
    """
    blocks = [block for block in re.split(r"\n\s*\n", (output or "").strip()) if block.strip()]
    described = {"header": "", "bodyweight": None, "exercises": []}
    if not blocks:
        return described
    described["header"] = blocks[0].split("\n", 1)[0].strip()
    for block in blocks[1:]:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        bw_match = re.match(r"^body\s*weight\s*[-:]\s*(.+)$", lines[0], flags=re.IGNORECASE)
        if bw_match and len(lines) == 1:
            described["bodyweight"] = bw_match.group(1).strip()
            continue
        plan = _parse_plan_exercise_line(lines[0])
        declared = plan.get("declared_sets")
        inline_range = plan.get("inline_range")
        target_sets = int(declared) if declared else 3
        rows = lines[1:]
        if len(rows) > 1 and all(parse_set_row(row) for row in rows):
            fresh = all(row.lower().replace(" ", "") in {"1,1", "bw/4,1"} for row in rows)
            sets_line = join_set_rows(rows)
        else:
            sets_line = rows[0] if rows else ""
            fresh = not sets_line or _is_default_numeric_sets(sets_line) or sets_line.lower().replace(" ", "") == "bw/4,1"
        sets_label = ""
        if not fresh:
            try:
                normalized = _normalize_sets_line(sets_line, target_sets=target_sets)
                if " x " in normalized:
                    pairs = [pair.split(" x ") for pair in normalized.split(", ")]
                else:
                    weights_part, reps_part = normalized.split(",", 1)
                    pairs = list(zip(weights_part.split(), reps_part.split()))
                # "20–60s" is seconds; "Max reps" merely ends in an s.
                timed = bool(inline_range and re.search(r"\d\s*s$", str(inline_range).strip(), flags=re.IGNORECASE))
                sets_label = " · ".join(
                    f"{_pretty_load(w)}×{r}{'s' if timed else ''}" for w, r in pairs
                )
            except Exception:
                sets_label = sets_line
        described["exercises"].append({
            "name": plan.get("name") or lines[0],
            "target": _target_label(declared, inline_range),
            "sets_label": sets_label,
            "fresh": fresh,
        })
    return described
