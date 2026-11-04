"""
Read a workout the way saving would, and say what is wrong with it before anything is stored.

Used by the Log page's live preview, by saving from the web, and by the Apple Shortcut, so all
three agree on what blocks a save (numbers with no exercise name, nothing readable) and what is
only worth a warning (a line with no numbers, a name that looks like a typo).
"""
import difflib
import re
from datetime import datetime, timedelta

from utils.dates import local_now, local_today
from typing import Dict, List, Optional

from sqlalchemy import func

from list_of_exercise import get_workout_days
from models import WorkoutLog
from parsers.workout import TIME_TOKEN, is_time_only_exercise, workout_parser
from services.bodyweight import has_bodyweight_token
from services.exercise_matching import build_name_index, normalize_exercise_name, resolve_equivalent_names
from services.retrieve import _parse_plan_exercise_line, get_effective_plan_text


def _fmt_num(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:g}"


def _has_seconds_target(exercise_string: str) -> bool:
    """A bracket like "[2, 20-60s]" means the second numbers are seconds (not "Max reps"),
    as do sets written as times ("60s, 45s", "1:00") under the name."""
    match = re.search(r"\[([^\]]*)\]", exercise_string or "")
    if match and re.search(r"\d\s*s(?:ec(?:onds?)?)?\s*$", match.group(1), flags=re.IGNORECASE):
        return True
    return any(TIME_TOKEN.search(line) for line in (exercise_string or "").splitlines()[1:])


class _TimedNames:
    """Which exercises the user times in seconds, as the workout page will show them: their own
    answer to "timed, in seconds?", else the known timed list (Dead Hang, Plank, ...). One query."""

    def __init__(self, db_session, user):
        from models import TimedExercisePreference

        self.answers = {}
        user_id = getattr(user, "id", None)
        if db_session is not None and user_id is not None:
            rows = (
                db_session.query(TimedExercisePreference.exercise_key, TimedExercisePreference.is_timed)
                .filter(TimedExercisePreference.user_id == user_id)
                .all()
            )
            self.answers = {key: bool(is_timed) for key, is_timed in rows}

    def is_timed(self, name: str) -> bool:
        from services.logging import _KNOWN_TIMED_EXERCISE_KEYS, _timed_lookup_key

        key = _timed_lookup_key(name)
        if key in self.answers:
            return self.answers[key]
        return key in _KNOWN_TIMED_EXERCISE_KEYS


def _sets_label(weights, reps, *, bodyweight: bool, seconds: bool = False) -> str:
    parts = []
    for weight, rep in zip(weights or [], reps or []):
        if bodyweight:
            w = float(weight or 0)
            load = "BW" if abs(w) < 1e-9 else f"BW{'+' if w > 0 else '−'}{_fmt_num(abs(w))}"
        elif seconds and not float(weight or 0):
            parts.append(f"{rep}s")  # a time with nothing added: just the time
            continue
        else:
            load = _fmt_num(weight)
        parts.append(f"{load}×{rep}{'s' if seconds else ''}")
    return " · ".join(parts)


def _date_label(value: datetime) -> str:
    day = value.date()
    today = local_today()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    label = f"{day.strftime('%a')}, {day.day} {day.strftime('%b')}"
    return label if day.year == today.year else f"{label} {day.year}"


def _plain(name: str) -> str:
    """Lower-case letters and digits only, for typo distance (no plural stripping)."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _changed_chars(a: str, b: str) -> int:
    matcher = difflib.SequenceMatcher(None, a, b)
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal")


class _KnownNames:
    """The user's logged exercise names plus their plan's, for "is this new?" and "did you mean?"."""

    def __init__(self, db_session, user):
        rows = (
            db_session.query(WorkoutLog.exercise, func.count(WorkoutLog.id))
            .filter(WorkoutLog.user_id == user.id)
            .group_by(WorkoutLog.exercise)
            .all()
        )
        counts = {name: count for name, count in rows if name and name != "Unknown Exercise"}
        self.history_index = build_name_index(counts.keys())

        plan_names = []
        try:
            data = get_workout_days(get_effective_plan_text(db_session, user) or "")
            for days in (data.get("workout") or {}).values():
                for lines in (days or {}).values():
                    for line in lines or []:
                        name = _parse_plan_exercise_line(line).get("name")
                        if name:
                            plan_names.append(name)
        except Exception:
            plan_names = []
        self.plan_norms = {normalize_exercise_name(n) for n in plan_names if normalize_exercise_name(n)}

        # Suggestion candidates: the most-logged spelling wins for each plain name.
        self.candidates: Dict[str, str] = {}
        for name in sorted(counts, key=lambda n: counts[n]):
            key = _plain(name)
            if key:
                self.candidates[key] = name
        for name in plan_names:
            key = _plain(name)
            if key and key not in self.candidates:
                self.candidates[key] = name

    def is_known(self, name: str) -> bool:
        if resolve_equivalent_names(name, self.history_index):
            return True
        return normalize_exercise_name(name) in self.plan_norms

    def suggestion(self, name: str) -> Optional[str]:
        # "A1 Back Squat": a superset label in front of a name you know.
        labelled = re.match(r"^[A-Ha-h][1-9]\s+(\S.*)$", name or "")
        if labelled and self.is_known(labelled.group(1)):
            return self.candidates.get(_plain(labelled.group(1))) or labelled.group(1)
        key = _plain(name)
        if not key:
            return None
        best, best_changes = None, None
        for candidate in difflib.get_close_matches(key, list(self.candidates), n=3, cutoff=0.8):
            changes = _changed_chars(key, candidate)
            if changes <= max(2, len(key) // 7) and (best_changes is None or changes < best_changes):
                best, best_changes = candidate, changes
        return self.candidates.get(best) if best else None


def _existing_day(db_session, user_id: int, day: datetime) -> Optional[Dict]:
    start = datetime.combine(day.date(), datetime.min.time())
    logs = (
        db_session.query(WorkoutLog)
        .filter(WorkoutLog.user_id == user_id)
        .filter(WorkoutLog.date >= start, WorkoutLog.date < start + timedelta(days=1))
        .order_by(WorkoutLog.id)
        .all()
    )
    if not logs:
        return None
    return {
        "date_str": start.strftime("%Y-%m-%d"),
        "date": logs[0].date,
        "title": logs[0].workout_name or "Workout",
        "exercise_count": len(logs),
        "exercises": {normalize_exercise_name(log.exercise) for log in logs},
    }


# What Retrieve writes under an exercise with no history, for the user to fill in.
_RETRIEVE_PLACEHOLDERS = {"1,1", "111,111", "bw/4,1"}


def _is_retrieve_placeholder(exercise_string: str) -> bool:
    lines = [line.strip() for line in (exercise_string or "").splitlines() if line.strip()]
    if len(lines) != 2:
        return False
    return re.sub(r"\s+", "", lines[1].lower()) in _RETRIEVE_PLACEHOLDERS


def _quote(text: str, limit: int = 40) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return f"“{text[:limit - 1]}…”" if len(text) > limit else f"“{text}”"


def check_workout_text(
    db_session, user, text: str, *, header: Optional[str] = None, append: bool = False, now: Optional[datetime] = None
) -> Dict:
    """
    Parse `text` like saving would and describe the result.

    `header` is a first line to put in front (the Edit page keeps title and date in their own fields);
    line numbers still refer to `text`. With `append`, exercises already logged that day are flagged.
    `now` stands in for today when the text has no date (a workout kept offline is dated when it was kept).
    """
    offset = 0
    source = text or ""
    if header:
        source = f"{header}\n{source}"
        offset = 1
    lines = source.split("\n")

    result: Dict = {
        "ok": False,
        "parsed": None,
        "errors": [],
        "warnings": [],
        "exercises": [],
        "exercise_count": 0,
        "set_count": 0,
        "existing": None,
    }

    parsed = workout_parser(
        source, bodyweight=getattr(user, "bodyweight", None), preserve_bodyweight_offsets=True, now=now,
    ) if source.strip() else None
    if not parsed:
        result["errors"].append({"line": None, "message": "Paste or type a workout first."})
        return result
    result["parsed"] = parsed

    parsed_date = parsed.get("date") or now or local_now()
    result.update({
        "title": parsed.get("workout_name") or "Workout",
        "date_str": parsed_date.strftime("%Y-%m-%d"),
        "date_label": _date_label(parsed_date),
        "date_found": bool(parsed.get("date_found")),
        "date_invalid": bool(parsed.get("invalid_date_text")),
        "bodyweight": parsed.get("bodyweight"),
    })

    if parsed.get("invalid_date_text"):
        result["errors"].append({
            "line": 1,
            "message": f"Line 1: {_quote(parsed['invalid_date_text'])} isn't a real date. Check the day and month.",
        })
    elif parsed_date.date() > local_today():
        result["warnings"].append({
            "line": None,
            "message": f"The date is in the future ({result['date_label']}). Check the first line if that's a typo.",
        })

    existing = _existing_day(db_session, user.id, parsed_date)
    if existing:
        result["existing"] = {k: v for k, v in existing.items() if k not in {"exercises", "date"}}

    known = _KnownNames(db_session, user)
    first_number_of = {}  # exercise -> its number in the check list (1, 2, 3...), to point out a second entry
    timed = _TimedNames(db_session, user)
    needs_bodyweight = False
    for item in parsed.get("exercises") or []:
        line_no = item.get("line")
        shown_line = (line_no - offset) if isinstance(line_no, int) else None
        raw_line = lines[line_no - 1] if isinstance(line_no, int) and 0 < line_no <= len(lines) else ""
        uses_bw = has_bodyweight_token(item.get("exercise_string") or "") or is_time_only_exercise(
            item.get("exercise_string") or "", item.get("source_name") or "")
        entry = {
            "line": shown_line,
            "name": item.get("name"),
            "sets_label": "",
            "set_count": 0,
            "state": "ok",
            "note": "",
            "suggestion": None,
            "fix_line": None,
        }

        if item.get("missing_name"):
            first_data = (item.get("exercise_string") or raw_line).split("\n", 1)[0]
            if not header and not result["exercises"] and not parsed.get("date_found"):
                # Pasted without the date/title line: the first exercise became the title.
                message = (
                    f"The first line, {_quote(result['title'])}, is read as the title, so line {shown_line} "
                    "has no exercise name. Start with a date and title line, like “27/9/26 - Push”."
                )
            else:
                message = (
                    f"Line {shown_line}: {_quote(first_data)} has numbers but no exercise name. "
                    "Put the exercise name on the line above it."
                )
            entry.update(state="missing", name="No exercise name", note="Add the exercise name above these numbers")
            result["errors"].append({"line": shown_line, "message": message})
            result["exercises"].append(entry)
            continue

        if item.get("valid") and _is_retrieve_placeholder(item.get("exercise_string") or ""):
            # Retrieve writes "1, 1" (or "bw/4, 1") for an exercise with no history yet. Left as it
            # is, it would be saved as real 1 kg x 1 sets, so it's skipped like an empty line.
            item["valid"] = False
            entry.update(state="skip", name=item.get("name"),
                         note="Still Retrieve's 1, 1: fill in your sets, or it won't be saved")
            result["warnings"].append({
                "line": shown_line,
                "message": f"Line {shown_line}: {_quote(item.get('name'))} still has Retrieve's placeholder sets, "
                           "so it won't be saved.",
            })
            result["exercises"].append(entry)
            continue

        if not item.get("valid"):
            # Numbers after the name that still gave no sets were written some other way.
            after_name = (item.get("exercise_string") or raw_line or "").replace(item.get("source_name") or "", "", 1)
            unread = bool(re.search(r"\d", after_name))
            entry.update(state="skip", name=(raw_line.strip() or item.get("name")),
                         note="Couldn't read the sets, so this line won't be saved" if unread
                         else "No numbers, so this line won't be saved")
            result["warnings"].append({
                "line": shown_line,
                "message": f"Line {shown_line}: {_quote(raw_line or item.get('name'))} "
                           + ("couldn't be read as sets" if unread else "has no numbers") + ", so it won't be saved.",
            })
            result["exercises"].append(entry)
            continue

        weights, reps = item.get("weights") or [], item.get("reps") or []
        entry["sets_label"] = _sets_label(
            weights, reps, bodyweight=uses_bw,
            seconds=_has_seconds_target(item.get("exercise_string") or "") or timed.is_timed(item.get("name") or ""),
        )
        entry["set_count"] = len(reps)
        result["exercise_count"] += 1
        result["set_count"] += len(reps)
        if uses_bw and getattr(user, "bodyweight", None) is None and parsed.get("bodyweight") is None:
            needs_bodyweight = True

        name = item.get("name") or ""
        name_key = normalize_exercise_name(name) or name.lower()
        # The list numbers every row but skipped lines, as the Log page shows them.
        number = sum(1 for e in result["exercises"] if e["state"] != "skip") + 1
        earlier_number = first_number_of.setdefault(name_key, number)
        if append and existing and normalize_exercise_name(name) in existing["exercises"]:
            entry.update(state="dup", note="Already logged that day, would be added again")
        elif earlier_number != number:
            # Often a paste slip; sometimes meant. Either way it's saved as its own entry.
            entry.update(state="twice", note=f"Also at no. {earlier_number}: saved as a second entry")
        elif not known.is_known(name):
            suggestion = known.suggestion(name)
            if suggestion:
                source_name = item.get("source_name") or ""
                fix_line = raw_line.replace(source_name, suggestion, 1) if source_name and source_name in raw_line else None
                entry.update(state="suggest", suggestion=suggestion, fix_line=fix_line,
                             note=f"New name. Did you mean {suggestion}?")
                result["warnings"].append({
                    "line": shown_line,
                    "message": f"Line {shown_line}: “{name}” is new. Did you mean {suggestion}?",
                })
            else:
                entry.update(state="new", note="New exercise")
        result["exercises"].append(entry)

    if needs_bodyweight:
        result["warnings"].append({
            "line": None,
            "message": "BW is used but no bodyweight is set. Add a “Body Weight - 73 kg” line or set it in Settings.",
        })

    if not result["errors"] and result["exercise_count"] == 0:
        result["errors"].append({
            "line": None,
            "message": "Couldn't find any exercise with numbers in this text. Nothing was saved.",
        })

    result["ok"] = not result["errors"]
    return result


def public_check(result: Dict) -> Dict:
    """The JSON-safe part of a check, for the Log page preview."""
    return {k: v for k, v in result.items() if k != "parsed"}
