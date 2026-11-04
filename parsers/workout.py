"""
Workout text parser for converting raw workout text into structured data.
"""
import re
import html
from datetime import datetime

from utils.dates import local_now
from typing import Optional, Dict, List, Tuple


def normalize(values):
    if not values:
        return []
    return list(values)


def align_sets(weights, reps, target_sets: Optional[int] = None):
    if not weights and not reps:
        return [], []

    def expand_shorthand(values, desired: int):
        if not values:
            return []
        if desired <= 0:
            return list(values)
        if len(values) == 1:
            return values * desired
        if len(values) == 2 and len(values) < desired:
            return [values[0]] + [values[1]] * (desired - 1)
        if len(values) < desired:
            return values + [values[-1]] * (desired - len(values))
        return values

    if not reps and weights:
        reps = [1] * len(weights)
    if not weights and reps:
        weights = [1.0] * len(reps)

    desired = target_sets if isinstance(target_sets, int) and target_sets > 0 else 3
    desired = max(desired, len(weights), len(reps))

    weights = expand_shorthand(weights, desired)
    reps = expand_shorthand(reps, desired)

    if len(weights) == 1 and len(reps) > 1:
        weights = weights * len(reps)
    elif len(reps) == 1 and len(weights) > 1:
        reps = reps * len(weights)
    elif len(weights) < len(reps) and weights:
        weights = weights + [weights[-1]] * (len(reps) - len(weights))
    elif len(reps) < len(weights) and reps:
        reps = reps + [reps[-1]] * (len(weights) - len(reps))

    reps = [int(r) for r in reps]
    return weights, reps


def _extract_declared_sets(line: str) -> tuple[Optional[int], str]:
    if not line:
        return None, line

    m = re.search(r'(?:\s*[-–—:]\s*)?(\d+)\s*sets?\s*$', line, flags=re.IGNORECASE)
    if not m:
        return None, line
    try:
        count = int(m.group(1))
    except Exception:
        return None, line
    if count <= 0:
        return None, line

    cleaned = line[: m.start()].rstrip()
    cleaned = re.sub(r'[-–—:]\s*$', '', cleaned).rstrip()
    return count, cleaned


def _extract_sets_from_bracket(line: str) -> Optional[int]:
    if not line or '[' not in line or ']' not in line:
        return None
    try:
        inside = line.split('[', 1)[1].split(']', 1)[0].strip()
    except Exception:
        return None
    if not inside:
        return None
    first = inside.split(',', 1)[0].strip()
    if not re.match(r'^\d+$', first):
        return None
    try:
        count = int(first)
    except Exception:
        return None
    return count if count > 0 else None


def _parse_plan_exercise_line(raw_line: str) -> Dict[str, Optional[str]]:
    """
    Parse plan line variants:
    - Exercise
    - Exercise - [n]
    - Exercise - [a-b]
    - Exercise - [n, a-b]
    - Exercise [n] / Exercise [n, a-b]  (no dash; the bracket must start with a number)
    """
    line = str(raw_line or "").strip()
    name = line
    declared_sets: Optional[int] = None
    inline_range: Optional[str] = None

    inside = None
    if " - [" in line and "]" in line:
        name = line.split(" - [", 1)[0].strip()
        try:
            inside = line.split("[", 1)[1].split("]", 1)[0].strip()
        except Exception:
            inside = ""
    else:
        # "Deadlift [3]", "Deadlift – [3, 3-6]": a trailing bracket of targets. Without
        # this the "[3]" stays in the name, so rep ranges and history never match.
        m = re.match(r"^(.*?\S)\s*(?:[-–—:]\s*)?\[\s*(\d[^\[\]]*)\]\s*$", line)
        if m:
            name = m.group(1).strip()
            inside = m.group(2).strip()

    if inside:
        first_token = inside.split(",", 1)[0].strip()
        if re.match(r"^\d+$", first_token):
            try:
                declared_sets = int(first_token)
            except Exception:
                declared_sets = None
            remainder = inside.split(",", 1)[1].strip() if "," in inside else ""
            if remainder:
                inline_range = remainder
        else:
            inline_range = inside

    if not declared_sets:
        bracket_sets = _extract_sets_from_bracket(line)
        if isinstance(bracket_sets, int) and bracket_sets > 0:
            declared_sets = int(bracket_sets)

    explicit_sets, cleaned = _extract_declared_sets(name)
    if isinstance(explicit_sets, int) and explicit_sets > 0:
        declared_sets = int(explicit_sets)
        name = cleaned

    return {
        "name": name.strip(),
        "declared_sets": declared_sets if isinstance(declared_sets, int) and declared_sets > 0 else None,
        "inline_range": (inline_range or "").strip() or None,
    }


def _has_time_range_hint(line: str) -> bool:
    if not line or '[' not in line or ']' not in line:
        return False
    try:
        inside = line.split('[', 1)[1].split(']', 1)[0].strip().lower()
    except Exception:
        return False
    return 's' in inside


def parse_bodyweight_line(line: str) -> Tuple[Optional[float], Optional[str]]:
    line = (line or '').strip()
    if not line:
        return None, None
    match = re.match(
        r'^(?:body\s*weight|bodyweight)\s*[-:]\s*(\d+(?:\.\d+)?)\s*(kg|kgs|lb|lbs)?\s*$',
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None
    try:
        value = float(match.group(1))
    except ValueError:
        return None, None
    unit = (match.group(2) or '').lower()
    if unit == 'kgs':
        unit = 'kg'
    if unit == 'lb':
        unit = 'lbs'
    return value, unit or None


def parse_weight_x_reps(segment, base_weight=None):
    segment = _drop_seconds_suffix(segment).replace('×', 'x').replace('*', 'x').lower()
    segment = re.sub(r'\bbody\s*weight\b', 'bw', segment)
    segment = re.sub(r'(kg|lbs|lb)', '', segment)
    bare_reps = _sets_with_bare_reps(segment, base_weight)
    if bare_reps:
        return bare_reps
    matches = re.findall(
        r'(?:(bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)\s*)?x\s*(\d+)',
        segment,
    )
    if not matches:
        return None, None

    weights, reps = [], []
    last_weight = None
    for w, r in matches:
        if w:
            bw_weight = parse_bw_weight(w, base_weight)
            last_weight = bw_weight if bw_weight is not None else float(w)
        if last_weight is None:
            return None, None
        weights.append(last_weight)
        reps.append(int(r))
    return weights, reps


# A number as people write one. float() also takes "nan", "inf", "1e5" and other scripts'
# digits: "nan" crashed the parser and "1e5" would have been a 100,000 kg set.
_PLAIN_NUMBER = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$')


def _plain_float(token: str) -> float:
    if not _PLAIN_NUMBER.match(token or ''):
        raise ValueError(f"not a plain number: {token!r}")
    return float(token)


# "45s", "60 sec": a time is its number of seconds wherever reps are read.
_SECONDS_SUFFIX = re.compile(r'(\d)\s*(?:seconds?|secs?|s)\b', re.IGNORECASE)


def _drop_seconds_suffix(segment: str) -> str:
    return _SECONDS_SUFFIX.sub(r'\1', segment or '')


def extract_numbers(segment):
    segment = _drop_seconds_suffix(segment)
    segment = re.sub(r'(kg|lbs|lb)', '', segment.lower())
    numbers = []
    # FIX: Replace comma with space to ensure "16,16" parses as two numbers
    segment = segment.replace(',', ' ')
    for t in segment.split():
        try:
            numbers.append(_plain_float(t))
        except ValueError:
            continue
    return numbers


def parse_bw_weight(token, base_weight=None):
    token = token.strip().lower()
    token = re.sub(r'^body\s*weight', 'bw', token)
    token = re.sub(r'^bodyweight', 'bw', token)
    if not token.startswith('bw'):
        return None
    token = token.replace('bw', '', 1)
    token = re.sub(r'(kg|lbs|lb)', '', token).strip()
    base = base_weight if base_weight is not None else 0.0

    divisor = 1.0
    if token.startswith('/'):
        m = re.match(r'^/(\d+(?:\.\d+)?)(.*)$', token)
        if m:
            try:
                divisor = float(m.group(1))
                token = (m.group(2) or '').strip()
            except ValueError:
                divisor = 1.0

    if divisor == 0:
        divisor = 1.0

    effective_base = base / divisor
    if token in ('', '+', '-'):
        return effective_base

    try:
        adjustment = _plain_float(token)
    except ValueError:
        return effective_base

    if token.startswith(('+', '-')):
        return effective_base + adjustment
    return effective_base + adjustment if base_weight is not None else adjustment


def extract_weights(segment, base_weight=None):
    segment = re.sub(r'(kg|lbs|lb)', '', segment.lower())
    segment = re.sub(r'\bbody\s*weight\b', 'bw', segment)
    segment = segment.replace(',', ' ')
    numbers = []
    for t in segment.split():
        bw_weight = parse_bw_weight(t, base_weight)
        if bw_weight is not None:
            numbers.append(bw_weight)
            continue
        try:
            numbers.append(_plain_float(t))
        except ValueError:
            continue
    return numbers


# What may follow a number on a set line without it being read as "1 Squat": the "x" of
# "100 x 5", a unit ("100 kg, 5") and the "at" of "3x5 at 100".
_SET_WORD = re.compile(r'^(?:x\d*|kgs?|lbs?|bw\S*|at|@|for|secs?|seconds?)[,;:]?$', re.IGNORECASE)

# Words that follow a number inside an exercise name ("1 Arm Row", "45 Degree Back
# Extension"), so the number isn't dropped as a list number.
_NAME_NUMBER_WORDS = r'(?:arms?|legs?|hands?|handed|degrees?|deg|ways?|point|count|inch(?:es)?)\b'


def strip_list_number(line: str) -> str:
    """Drop a list number in front of a name ("1. Squat", "2) Row", "3 - Curl", "4 Dips"),
    keeping numbers that are part of it ("1-Arm Row", "45 Degree Hyperextension", "21s Curl")."""
    line = (line or '').strip()
    # A superset label written with a mark ("A1. Squat", "A2) Row", "B1: Curl", "B2 - Row").
    line = re.sub(r'^[A-Ha-h][1-9]\s*(?:[.):]|\s[-–—])\s*(?=[A-Za-z])', '', line)
    stripped = re.sub(r'^\d+\s*[.)]\s*', '', line)
    if stripped == line:
        stripped = re.sub(r'^\d+\s*[:\-–—]\s+', '', line)
    if stripped == line:
        stripped = re.sub(rf'^\d+\s+(?!{_NAME_NUMBER_WORDS})(?=[A-Za-z])', '', line, flags=re.IGNORECASE)
    return stripped

_WEIGHT = r'(?:bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)'
_SETS_LINE = re.compile(rf'^(?:\s*(?:{_WEIGHT})?\s*x\s*\d+\s*[,;]?)+\s*$')
# Several sets at one weight, as people write them. The forms without "@"/"at" need the
# weight to carry a unit or be BW, since "5 x 10 8" could as well be 5 kg for 10 and 8 reps.
_SETS_AT_WEIGHT = re.compile(rf'^(\d+)\s*x\s*(\d+)\s*(?:@|\bat\b)\s*({_WEIGHT})$')   # 3x5 @ 100
_SETS_THEN_WEIGHT = re.compile(rf'^(\d+)\s*x\s*(\d+)\s+({_WEIGHT})$')                  # 3x5 100kg
_WEIGHT_THEN_SETS = re.compile(rf'^({_WEIGHT})\s+(\d+)\s*x\s*(\d+)$')                  # 100kg 3x5
_THREE_NUMBERS = re.compile(rf'^({_WEIGHT})\s*x\s*(\d+)\s*x\s*({_WEIGHT})$')           # 100x5x3, 3x5x100
_ONE_SET = re.compile(rf'^({_WEIGHT})?\s*x\s*(\d+)$')                                   # 100x5, x5
_MOST_SETS = 10


# "3 sets of 8 at 60" / "3 sets x 8 reps @ 60" read as "3x8 at 60". Only with a weight after
# it: a bare "3 sets of 8" is left alone rather than read as 3 kg for 8.
_SETS_OF = re.compile(
    r'\b(\d+)\s*sets?\s*(?:of|x|×)\s*(\d+)(?:\s*reps?\b)?(?=\s*(?:@|at\b|\d|bw|body))', re.IGNORECASE)


def _sets_of(text: str) -> str:
    return _SETS_OF.sub(r'\1x\2', text or '')


def _set_text(line: str) -> str:
    text = _sets_of(line).lower().replace('×', 'x').replace('*', 'x')
    text = re.sub(r'\bbody\s*weight\b', 'bw', text)
    return re.sub(r'\s*(?:kgs?|lbs?)\b', '', text)


def is_sets_line(line: str) -> bool:
    """A line of "weight x reps" sets only: "100x5", "100 x 5, 90 x 8", "BW+10 x 8"."""
    return bool(_SETS_LINE.match(_set_text(line)))


# Times written as times: "60s", "45 sec", "1:00". A line of only those is a timed exercise's sets.
_SECONDS_WORD = r'(?:seconds?|secs?|s)'
TIME_TOKEN = re.compile(rf'\b\d+:[0-5]\d\b|\b\d+(?:\.\d+)?\s*{_SECONDS_WORD}\b', re.IGNORECASE)
_SETS_OF_SECONDS = re.compile(rf'^(\d+)\s*x\s*(\d+)\s*{_SECONDS_WORD}$', re.IGNORECASE)   # 3 x 60s
_SECONDS_TIMES_SETS = re.compile(rf'^(\d+)\s*{_SECONDS_WORD}\s*x\s*(\d+)$', re.IGNORECASE)  # 60 sec x 3


def _token_seconds(token: str) -> int:
    token = token.strip().lower()
    if ':' in token:
        minutes, seconds = token.split(':', 1)
        return int(minutes) * 60 + int(seconds)
    return int(round(float(re.match(r'\d+(?:\.\d+)?', token).group(0))))


def parse_time_sets(segment) -> Optional[Tuple[Optional[int], List[int]]]:
    """Sets written only as times: "60s, 45s", "60s 45s", "1:00, 0:45", "3 x 60s", "60 sec x 3".
    Returns (sets written as a count, or None; seconds per set), else None."""
    text = (segment or '').strip().lower().replace('×', 'x').replace('*', 'x')
    if not text:
        return None
    for pattern, sets_at, seconds_at in ((_SETS_OF_SECONDS, 1, 2), (_SECONDS_TIMES_SETS, 2, 1)):
        m = pattern.match(text)
        if m:
            sets, seconds = int(m.group(sets_at)), int(m.group(seconds_at))
            if 0 < sets <= _MOST_SETS and seconds > 0:
                return sets, [seconds] * sets
            return None
    times = TIME_TOKEN.findall(text)
    if not times or re.sub(r'[\s,;]+', '', TIME_TOKEN.sub('', text)):
        return None
    seconds = [_token_seconds(token) for token in times]
    return (None, seconds) if all(value > 0 for value in seconds) else None


def is_time_only_exercise(exercise_string: str, name: str = "") -> bool:
    """True when the sets under (or after) the name are only times ("Plank\n60s, 45s"): nothing
    is added, so the load is bodyweight, as if "BW, 60 45" had been written."""
    lines = [line.strip() for line in (exercise_string or "").splitlines() if line.strip()]
    if not lines:
        return False
    if len(lines) == 1:
        if not name or not lines[0].lower().startswith(name.lower()):
            return False
        data = lines[0][len(name):]
    else:
        data = ", ".join(lines[1:])
    return bool(parse_time_sets(data.strip(" -–—:")))


def _weight_value(token, base_weight):
    weight = parse_bw_weight(token, base_weight)
    return weight if weight is not None else _plain_float(token)


def _set_group(piece: str, has_unit: bool):
    """(sets, reps, weight token) for one "3x5 @ 100"-style piece, else None."""
    m = _SETS_AT_WEIGHT.match(piece)
    if m:
        return int(m.group(1)), int(m.group(2)), m.group(3)
    m = _SETS_THEN_WEIGHT.match(piece)
    if m and (has_unit or m.group(3).startswith('bw')):
        return int(m.group(1)), int(m.group(2)), m.group(3)
    m = _WEIGHT_THEN_SETS.match(piece)
    if m and (has_unit or m.group(1).startswith('bw')):
        return int(m.group(2)), int(m.group(3)), m.group(1)
    m = _THREE_NUMBERS.match(piece)
    if m:
        first, reps, last = m.group(1), int(m.group(2)), m.group(3)
        # Weight x reps x sets ("100x5x3") unless only the first number can be the sets ("3x5x100").
        if re.fullmatch(r'\d+', last) and int(last) <= _MOST_SETS:
            return int(last), reps, first
        if re.fullmatch(r'\d+', first) and int(first) <= _MOST_SETS:
            return int(first), reps, last
    return None


def parse_sets_at_weight(segment, base_weight=None):
    """Sets written as a count at a weight: "3x5 @ 100", "3x5 at 100", "3x5 100kg", "100kg 3x5",
    "100x5x3" (weight x reps x sets), or several such parts: "2x10 @ 60, 1x8 @ 70".
    Returns (number of sets, weights, reps), or None when the segment isn't written that way."""
    pieces = [piece.strip() for piece in re.split(r'[,;]', segment or '') if piece.strip()]
    if not pieces:
        return None
    weights, reps, grouped = [], [], False
    for raw_piece in pieces:
        has_unit = bool(re.search(r'\d\s*(?:kgs?|lbs?)\b', raw_piece, re.IGNORECASE))
        piece = _set_text(raw_piece).strip()
        group = _set_group(piece, has_unit)
        if group:
            sets, rep_count, weight_token = group
            if not 0 < sets <= _MOST_SETS or rep_count <= 0:
                return None
            grouped = True
        else:
            # A plain "90x8" next to a group ("3x5 @ 100, 90x8") is one more set.
            m = _ONE_SET.match(piece)
            if not m or not m.group(1):
                return None
            sets, rep_count, weight_token = 1, int(m.group(2)), m.group(1)
        try:
            weight = _weight_value(weight_token, base_weight)
        except ValueError:
            return None
        weights += [weight] * sets
        reps += [rep_count] * sets
    if not grouped:
        return None
    return len(weights), weights, reps


# One weight, then the reps done with it. The weight has to be marked (a unit right after it, or
# ":", " - ", "for" before the reps, or "@" after them) and the reps evenly separated, so the
# documented "weights, reps" form ("80 75, 8 10") is never read this way.
_REPS_LIST = r'\d+(?:(?:\s*,\s*|\s+)\d+)+'
_UNIT = r'(?:kgs?|lbs?)'
_WEIGHT_THEN_REPS = (
    re.compile(rf'^({_WEIGHT})\s*{_UNIT}\s*[:\-–—]?\s*({_REPS_LIST}|\d+)$', re.IGNORECASE),     # 100kg 5 5 5
    re.compile(rf'^(bw(?:/\d+(?:\.\d+)?)?(?:[+-]\d+(?:\.\d+)?)?)\s+(\d+(?:\s+\d+)+)$', re.IGNORECASE),  # BW 10 8 6
    # Two reps or more here: "5 - 8" alone is a rep range.
    re.compile(rf'^({_WEIGHT})\s*(?:{_UNIT})?\s*(?::|\s[-–—]|\sfor)\s*({_REPS_LIST})$', re.IGNORECASE),  # 100: 5 5 5
)
_REPS_THEN_WEIGHT = re.compile(rf'^({_REPS_LIST}|\d+)\s*(?:reps?)?\s*(?:@|\bat\b)\s*({_WEIGHT})\s*(?:{_UNIT})?$', re.IGNORECASE)


def parse_reps_at_weight(segment, base_weight=None, max_rep_value: int = 30):
    """"100kg 5 5 5", "100 kg: 5, 5, 5", "100 - 5 5 5", "100 for 5, 5, 5", "5 5 5 @ 100":
    (weights, reps), or None when the segment isn't written that way."""
    text = re.sub(r'\bbody\s*weight\b', 'bw', (segment or '').strip().replace('×', 'x'), flags=re.IGNORECASE)
    if not text:
        return None
    found = None
    for pattern in _WEIGHT_THEN_REPS:
        m = pattern.match(text)
        if m:
            found = (m.group(1), m.group(2))
            break
    if not found:
        m = _REPS_THEN_WEIGHT.match(text)
        if m:
            found = (m.group(2), m.group(1))
    if not found:
        return None
    weight_token, reps_text = found
    separators = set(re.findall(r'\s*,\s*|\s+', reps_text.strip()))
    if len({',' if ',' in sep else ' ' for sep in separators}) > 1:
        return None
    reps = [int(value) for value in re.findall(r'\d+', reps_text)]
    if not all(0 < value <= max_rep_value for value in reps):
        return None
    if ',' in reps_text and len(reps) < 3 and not re.search(r'[:\-–—@]|\bfor\b|\bat\b', text):
        # "60kg 20, 12" is as likely the usual "weights, reps" (60 and 20 kg, 12 reps).
        return None
    try:
        weight = _weight_value(weight_token.lower(), base_weight)
    except ValueError:
        return None
    return [weight] * len(reps), reps


def _sets_with_bare_reps(segment, base_weight=None):
    """"BW x 10, 10, 8" / "100x5, 5, 4": a set, then more reps at the same weight."""
    pieces = [piece.strip() for piece in re.split(r'[,;]', segment) if piece.strip()]
    if len(pieces) < 2:
        return None
    weights, reps, last_weight, bare = [], [], None, False
    for piece in pieces:
        m = _ONE_SET.match(piece)
        if m:
            if m.group(1):
                try:
                    last_weight = _weight_value(m.group(1), base_weight)
                except ValueError:
                    return None
            if last_weight is None:
                return None
            weights.append(last_weight)
            reps.append(int(m.group(2)))
        elif re.fullmatch(r'\d+', piece) and last_weight is not None:
            weights.append(last_weight)
            reps.append(int(piece))
            bare = True
        else:
            return None
    return (weights, reps) if bare else None


def is_data_line(line):
    if not line:
        return False
    stripped = _sets_of(line.strip())
    if parse_set_row(stripped):
        return True
    if re.match(r'^\d+(?:[.)\-:])\s*[A-Za-z]', stripped):
        return False
    tokens = stripped.split()
    # "1. 3/4 Squat": a list number, then the name.
    if len(tokens) > 1 and re.match(r'^\d+[.)]$', tokens[0]) and re.search(r'[A-Za-z]', stripped):
        return False
    # "2 - Squat": a list number, then the name.
    if len(tokens) > 2 and re.match(r'^\d+$', tokens[0]) and tokens[1] in ('-', '–', '—', ':') \
            and re.match(r'^[A-Za-z]', tokens[2]):
        return False
    # A number followed by a word is a name ("1 Squat", "45 Degree ...", "21s Curl", "3/4 Squat"),
    # unless the word belongs to the sets ("100 x 5", "100 kg, 5", "60 sec").
    if len(tokens) > 1 and re.match(r'^\d', tokens[0]) and re.match(r'^[A-Za-z]', tokens[1]):
        set_word = bool(_SET_WORD.match(tokens[1]))
        if set_word and tokens[1].lower() == 'x':
            set_word = len(tokens) > 2 and bool(re.match(r'^\d', tokens[2]))
        if not set_word:
            return False
    return bool(re.match(r'^(?:,|-?\d|bw|body\s*weight|bodyweight)', stripped.lower()))


def is_probable_data_segment(segment: str) -> bool:
    segment = (segment or '').strip()
    if not segment:
        return False

    if parse_time_sets(segment) or parse_reps_at_weight(segment):
        return True
    lowered = re.sub(r'\bbody\s*weight\b', 'bw', _sets_of(segment).lower())
    if re.search(r'[x×*]', lowered):
        return True
    if ',' in lowered:
        return True

    tokens = re.split(r'\s+', lowered)
    for token in tokens:
        if not token:
            continue
        cleaned = re.sub(r'[,:]+$', '', token)
        if cleaned.startswith('bw') or cleaned.startswith('bodyweight') or cleaned == 'body':
            continue
        cleaned = re.sub(r'(kg|lbs|lb)', '', cleaned)
        if re.match(r'^-?\d+(?:\.\d+)?$', cleaned):
            continue
        return False

    return True


def parse_weight_reps_pairs(segment, base_weight: Optional[float] = None, max_rep_value: int = 30):
    segment = re.sub(r'\bbody\s*weight\b', 'bw', (segment or '').strip(), flags=re.IGNORECASE)
    if not segment:
        return None, None
    if ',' in segment:
        return None, None
    if re.search(r'[x×*]', segment, flags=re.IGNORECASE):
        return None, None

    tokens = segment.split()
    if len(tokens) < 2:
        return None, None

    if len(tokens) != 2 and len(tokens) % 2 != 0:
        return None, None

    def parse_weight_token(token: str):
        bw_weight = parse_bw_weight(token, base_weight)
        if bw_weight is not None:
            return bw_weight
        try:
            return _plain_float(token)
        except ValueError:
            return None

    def parse_reps_token(token: str):
        if not re.match(r'^\d+$', token):
            return None
        try:
            return int(token)
        except ValueError:
            return None

    if len(tokens) == 2:
        w_token, r_token = tokens[0], tokens[1]
        w_val = parse_weight_token(w_token)
        r_val = parse_reps_token(r_token)
        if w_val is None or r_val is None:
            return None, None
        if r_val <= 0 or r_val > max_rep_value:
            return None, None
        weight_hint = (
            '.' in w_token
            or w_token.lower().startswith('bw')
            or w_token.startswith('-')
            or w_token != r_token
        )
        if not weight_hint:
            return None, None
        return [w_val], [r_val]

    weights, reps = [], []
    for idx in range(0, len(tokens), 2):
        w = parse_weight_token(tokens[idx])
        r = parse_reps_token(tokens[idx + 1])
        if w is None or r is None:
            return None, None
        if r <= 0 or r > max_rep_value:
            return None, None
        weights.append(w)
        reps.append(r)
    return weights, reps


def parse_weight_reps_halves(segment, base_weight: Optional[float] = None, max_rep_value: int = 30):
    segment = re.sub(r'\bbody\s*weight\b', 'bw', (segment or '').strip(), flags=re.IGNORECASE)
    if not segment:
        return None, None
    if ',' in segment:
        return None, None
    if re.search(r'[x×*]', segment, flags=re.IGNORECASE):
        return None, None

    tokens = segment.split()
    if len(tokens) < 4 or len(tokens) % 2 != 0:
        return None, None

    half = len(tokens) // 2
    weights_tokens = tokens[:half]
    reps_tokens = tokens[half:]

    reps = []
    for tok in reps_tokens:
        if not re.match(r'^\d+$', tok):
            return None, None
        try:
            val = int(tok)
        except ValueError:
            return None, None
        if val <= 0 or val > max_rep_value:
            return None, None
        reps.append(val)

    weights = []
    for tok in weights_tokens:
        bw_weight = parse_bw_weight(tok, base_weight)
        if bw_weight is not None:
            weights.append(bw_weight)
            continue
        try:
            weights.append(_plain_float(tok))
        except ValueError:
            return None, None

    return weights, reps


_MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}
_MONTH_WORD = r'([A-Za-z]{3,9})\.?'
_DAY_WORD = r'(\d{1,2})(?:st|nd|rd|th)?'
_YEAR_WORD = r'(?:,?\s+(\d{4}|\d{2}))?'
_TITLE_END = r'(?=\s|$|[-–—:,])'


def _month_number(word: str) -> Optional[int]:
    word = (word or '').lower()
    if word in _MONTHS:
        return _MONTHS[word]
    full = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12}
    return full.get(word)


def _month_name_date(title_line: str):
    """"30 Sep Push", "Sep 30 Push", "30 Sep 25 Push", "1st Oct - Legs": (day, month, year or None,
    rest of the title). None when the title doesn't start with a date written that way."""
    line = title_line or ''
    for pattern, day_at, month_at in (
        (rf'^\s*{_DAY_WORD}\s+{_MONTH_WORD}{_YEAR_WORD}{_TITLE_END}', 1, 2),
        (rf'^\s*{_MONTH_WORD}\s+{_DAY_WORD}{_YEAR_WORD}{_TITLE_END}', 2, 1),
    ):
        m = re.match(pattern, line)
        if not m:
            continue
        month = _month_number(m.group(month_at))
        if not month:
            continue
        year = m.group(3)
        return int(m.group(day_at)), month, (int(year) + (2000 if len(year) == 2 else 0)) if year else None, line[m.end():]
    return None


_WEEKDAY_BEFORE_DATE = re.compile(
    r'^(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)'
    r'\.?,?\s+(?=\d{1,2}[/.\-]\d|\d{4}-\d|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3}|[A-Za-z]{3,9}\.?\s+\d)',
    re.IGNORECASE,
)


# One set on its own line. A dot counts only with a space after it ("25. 4", what a double
# space types), so "25.4" stays a decimal weight.
_SET_ROW_RE = re.compile(
    r'^(?P<weight>bw(?:/\d+(?:\.\d+)?)?(?:\s*[+-]\s*\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)'
    r'\s*(?:kgs|kg|lbs|lb)?\s*(?:,|x|×|\*|\.(?=\s))\s*(?P<reps>\d+)$',
    flags=re.IGNORECASE,
)


def parse_set_row(line: str) -> Optional[Tuple[str, str]]:
    """One set on its own line: "45, 3" (as retrieve writes it), "25. 4", "bw+10, 7" or "45 x 3".
    Returns the (weight, reps) tokens, or None when the line is anything else."""
    line = re.sub(r'\bbody\s*weight\b', 'bw', (line or '').strip(), flags=re.IGNORECASE)
    match = _SET_ROW_RE.match(line)
    if not match:
        return None
    return re.sub(r'\s+', '', match.group('weight')), match.group('reps')


def join_set_rows(rows: List[str]) -> str:
    """Set rows as the classic one-line form ("45 40 35, 3 4 6"), which everything that
    reads a logged exercise's text already understands."""
    pairs = [parse_set_row(row) for row in rows]
    return f"{' '.join(w for w, _ in pairs)}, {' '.join(r for _, r in pairs)}"


def _title_case(name: str) -> str:
    """Capitalise the first letter of each word and leave every other letter as typed:
    "oh" -> "Oh", "oH" -> "OH", "EZ-bar" -> "EZ-Bar", "LEG PRESS" stays. A word starts after
    a space, hyphen, slash or bracket, not after an apostrophe ("farmer's" -> "Farmer's").
    Matching ignores case everywhere, so this only decides how a name looks."""
    return re.sub(r"(^|[\s\-/(\[])([a-z])", lambda m: m.group(1) + m.group(2).upper(), name)


_UNSPACED_TARGET = re.compile(r'^(.*?[A-Za-z)])\s*[-–—]?\s*(\[[\d\s,.\-–—sS]*\].*)$')


# Emoji and pictographs ("Squat 💪", "Deadlift 🔥"): flair, not part of the exercise's name.
_EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0E\uFE0F\u200D]')


def clean_exercise_name(name: str) -> str:
    """Drop stray separators, list bullets, emoji and tabs around a typed name
    ("Forearm Roller -" -> "Forearm Roller", "• Squat" -> "Squat", "Squat 💪" -> "Squat")."""
    name = _EMOJI.sub(' ', name or '')
    name = re.sub(r'\s+', ' ', name).strip()
    return name.strip('-–—:,.; •◦▪‣*·').strip()


def workout_parser(
    workout_day_received: str,
    bodyweight: Optional[float] = None,
    preserve_bodyweight_offsets: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Dict]:
    """
    Parse raw workout text into structured data.
    
    Args:
        workout_day_received: Raw workout text string
        now: When the workout was saved (defaults to the current time); used
            for undated workouts and to pick the year of a dated one
        
    Returns:
        Dictionary with date, workout_name, and exercises list, or None if parsing fails
    """
    if not workout_day_received or not workout_day_received.strip():
        return None
    
    raw_lines: List[str] = []
    # 1-based line number in the given text for each kept line, so problems can point at it.
    line_numbers: List[int] = []
    parsed_bodyweight: Optional[float] = None
    parsed_bodyweight_unit: Optional[str] = None
    for line_no, line in enumerate(workout_day_received.split("\n"), start=1):
        stripped = (line or "").strip()
        if not stripped:
            continue
        # Treat comment / section markers (e.g., "#Gym") as separators, not exercises.
        if stripped.startswith("#"):
            continue
        bw_value, bw_unit = parse_bodyweight_line(stripped)
        if bw_value is not None:
            parsed_bodyweight = bw_value
            parsed_bodyweight_unit = bw_unit
            continue
        raw_lines.append(stripped)
        line_numbers.append(line_no)
    if not raw_lines:
        return None

    # Header
    title_line = raw_lines[0]
    # "Monday 30/9 Push", "Tue, 29 Sep - Legs": the weekday in front of a date is dropped.
    weekday = _WEEKDAY_BEFORE_DATE.match(title_line)
    if weekday:
        title_line = title_line[weekday.end():]
    now = now or local_now()
    current_year = now.year
    # "2026-09-28 Push": year first, as other apps and exports write it.
    iso = re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?=\s|$|[-–—:,])', title_line)
    date_nums = re.findall(r'\d+', title_line.split()[0]) if not iso else []

    # A date that was written but doesn't exist ("31/9", "29/2" outside a leap year), so the
    # check can say so instead of quietly filing the workout under today.
    invalid_date_text = None
    month_name_date = None if (len(date_nums) >= 2 or iso) else _month_name_date(title_line)
    if iso:
        try:
            date_obj = datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            date_found = True
        except ValueError:
            date_obj = now
            date_found = False
            invalid_date_text = iso.group(0)
    elif month_name_date:
        day, month, written_year, rest = month_name_date
        year = written_year or (current_year - 1 if month > now.month + 1 else current_year)
        try:
            date_obj = datetime(year, month, day)
            date_found = True
        except ValueError:
            date_obj = now
            date_found = False
            invalid_date_text = title_line[:len(title_line) - len(rest)].strip()
    elif len(date_nums) >= 2:
        parsed_month = int(date_nums[1])
        year = current_year - 1 if parsed_month > now.month + 1 else current_year
        # A written year wins ("15/3/25" is 2025, not this year's 15 March).
        if len(date_nums) >= 3 and len(date_nums[2]) in (2, 4):
            year = int(date_nums[2]) + (2000 if len(date_nums[2]) == 2 else 0)
        try:
            date_obj = datetime.strptime(f"{date_nums[0]}-{date_nums[1]}-{year}", "%d-%m-%Y")
            date_found = True
        except ValueError:
            date_obj = now
            date_found = False
            first_token = title_line.split()[0]
            if re.fullmatch(r'\d{1,2}[/.\-]\d{1,2}(?:[/.\-]\d{2,4})?', first_token):
                invalid_date_text = first_token
    else:
        date_obj = now
        date_found = False

    workout_name = title_line
    if iso:
        workout_name = title_line[iso.end():]
    elif month_name_date and date_found:
        workout_name = month_name_date[3].strip()
    elif len(date_nums) >= 2:
        parts = title_line.split(' ', 1)
        if len(parts) > 1:
            workout_name = parts[1].strip()
        elif date_found:
            workout_name = ""  # a date and nothing else: no title of its own
    workout_name = html.unescape(workout_name)
    workout_name = workout_name.lstrip('-–—:,').strip()

    effective_bodyweight = None if preserve_bodyweight_offsets else (
        parsed_bodyweight if parsed_bodyweight is not None else bodyweight
    )
    workout_day = {
        "date": date_obj,
        "date_found": date_found,
        "invalid_date_text": invalid_date_text,
        "workout_name": workout_name,
        "bodyweight": parsed_bodyweight,
        "bodyweight_unit": parsed_bodyweight_unit,
        "exercises": [],
    }

    # Exercises
    list_of_lines = []
    kept_numbers: List[int] = []
    for line, line_no in zip(raw_lines, line_numbers):
        stripped = line.strip()
        # "Squat" then "3 sets" on a line of its own: the count belongs to the name above.
        if (len(list_of_lines) > 1 and re.fullmatch(r'\d+\s*sets?', stripped, flags=re.IGNORECASE)
                and not is_data_line(list_of_lines[-1])
                and _extract_declared_sets(list_of_lines[-1])[0] is None):
            list_of_lines[-1] = f"{list_of_lines[-1]} {stripped}"
            continue
        if is_data_line(stripped):
            list_of_lines.append(stripped)
        else:
            list_of_lines.append(strip_list_number(stripped))
        kept_numbers.append(line_no)
    line_numbers = kept_numbers
    i = 1
    while i < len(list_of_lines):
        clean_line = list_of_lines[i]
        name, weights, reps = "", [], []
        data_part = ""
        time_range_hint = _has_time_range_hint(clean_line)
        declared_sets, cleaned_line = _extract_declared_sets(clean_line)
        # "Squat [3]" / "Squat-[8-12]": a target in brackets written without the " - ".
        unspaced = _UNSPACED_TARGET.match(cleaned_line)
        if unspaced and " - [" not in cleaned_line:
            cleaned_line = f"{unspaced.group(1)} - {unspaced.group(2)}"
        bracket_sets = _extract_sets_from_bracket(cleaned_line)
        if bracket_sets is not None:
            declared_sets = bracket_sets

        exercise_lines = [cleaned_line]
        consumed = 1

        if " - [" in cleaned_line:
            name = cleaned_line.split(" - [", 1)[0].strip()
            if "]" in cleaned_line:
                tail = cleaned_line.split("]", 1)[1].strip()
                tail = tail.lstrip("-:").strip()
                data_part = tail

            if not data_part and i + 1 < len(list_of_lines) and is_data_line(list_of_lines[i + 1]):
                data_line = list_of_lines[i + 1].strip()
                exercise_lines.append(data_line)
                data_part = data_line
                consumed += 1

                if "," not in data_part and not parse_set_row(data_part) and i + 2 < len(list_of_lines) and is_data_line(list_of_lines[i + 2]):
                    reps_line = list_of_lines[i + 2].strip()
                    exercise_lines.append(reps_line)
                    data_part = f"{data_part}, {reps_line}"
                    consumed += 1
        else:
            # The line without a written set count ("Squat 3 sets" is Squat, with its sets below).
            tokens = cleaned_line.split()
            first_num_idx = -1
            # Numbers inside the name ("45 Degree Hyperextension 20, 12") aren't the sets:
            # the sets start after the first word.
            first_word = next(
                (idx for idx, token in enumerate(tokens)
                 if re.match(r'^[A-Za-z]', token) and not _SET_WORD.match(token)
                 and not re.match(r'^body', token, re.IGNORECASE)),
                -1,
            )
            for idx, token in enumerate(tokens):
                if 0 <= first_word and idx <= first_word:
                    continue
                token_lower = token.lower()
                if (
                    re.match(r'^-?\d', token)
                    or token.startswith(',')
                    or token_lower.startswith('bw')
                    or token_lower.startswith('bodyweight')
                    or (token_lower == 'body' and idx + 1 < len(tokens) and tokens[idx + 1].lower().startswith('weight'))
                ):
                    first_num_idx = idx
                    break
            if first_num_idx != -1:
                name = " ".join(tokens[:first_num_idx]).strip()
                data_part = " ".join(tokens[first_num_idx:]).strip()
            else:
                name, data_part = cleaned_line, ""

        if not data_part and i + 1 < len(list_of_lines) and is_data_line(list_of_lines[i + 1]):
            data_line = list_of_lines[i + 1].strip()
            exercise_lines.append(data_line)
            data_part = data_line
            consumed += 1

            if "," not in data_part and not parse_set_row(data_part) and i + 2 < len(list_of_lines) and is_data_line(list_of_lines[i + 2]):
                reps_line = list_of_lines[i + 2].strip()
                exercise_lines.append(reps_line)
                data_part = f"{data_part}, {reps_line}"
                consumed += 1

        # One set per line ("100x5" / "90x8" / "80x10"): keep reading set lines.
        if data_part and is_sets_line(data_part):
            while i + consumed < len(list_of_lines) and is_sets_line(list_of_lines[i + consumed]):
                extra = list_of_lines[i + consumed].strip()
                exercise_lines.append(extra)
                data_part = f"{data_part}, {extra}"
                consumed += 1
        # One set per line with a comma or a dot ("45, 3" / "40. 4"), as retrieve writes them:
        # stored in the one-line form ("45 40, 3 4"), which reads exactly like the same sets on
        # one line everywhere a logged exercise's text is read.
        elif data_part and parse_set_row(data_part):
            rows = [data_part]
            if consumed > 1:
                while i + consumed < len(list_of_lines) and parse_set_row(list_of_lines[i + consumed]):
                    rows.append(list_of_lines[i + consumed].strip())
                    consumed += 1
            # A lone "45, 3" is already the one-line form; keep it as typed.
            if len(rows) > 1 or ',' not in data_part:
                data_part = join_set_rows(rows)
                if consumed > 1:
                    exercise_lines = [exercise_lines[0], data_part]

        if data_part and not is_probable_data_segment(data_part):
            data_part = ""

        time_sets = parse_time_sets(data_part) if data_part else None
        sets_at_weight = None if time_sets else (
            parse_sets_at_weight(data_part, effective_bodyweight) if data_part else None)
        if time_sets:
            # No weight written: none added (bodyweight exercises still count bodyweight).
            counted_sets, reps = time_sets
            weights = [0.0] * len(reps)
            if counted_sets:
                declared_sets = counted_sets
        elif sets_at_weight:
            declared_sets, weights, reps = sets_at_weight
        elif data_part and parse_reps_at_weight(data_part, effective_bodyweight, 600 if time_range_hint else 30):
            weights, reps = parse_reps_at_weight(data_part, effective_bodyweight, 600 if time_range_hint else 30)
        elif data_part:
            w_list, r_list = parse_weight_x_reps(data_part, effective_bodyweight)
            if w_list:
                weights, reps = w_list, r_list
            elif ',' in data_part:
                subparts = data_part.split(',', 1)
                weights = extract_weights(subparts[0], effective_bodyweight)
                reps = extract_numbers(subparts[1])

                if not weights and reps:
                    weights = [1.0] * len(reps)
                elif weights and not reps:
                    reps = [1] * len(weights)
            else:
                max_rep_value = 600 if time_range_hint else 30
                w_pairs, r_pairs = parse_weight_reps_pairs(
                    data_part,
                    effective_bodyweight,
                    max_rep_value=max_rep_value,
                )
                if w_pairs and r_pairs:
                    weights, reps = w_pairs, r_pairs
                else:
                    w_halves, r_halves = parse_weight_reps_halves(
                        data_part,
                        effective_bodyweight,
                        max_rep_value=max_rep_value,
                    )
                    if w_halves and r_halves:
                        weights, reps = w_halves, r_halves
                    else:
                        weights = extract_weights(data_part, effective_bodyweight)
                        reps = [1] * len(weights)

        source_name = name
        name = clean_exercise_name(name)
        missing_name = not name
        if missing_name:
            name = "Unknown Exercise"

        inferred_sets = max(len(weights), len(reps)) if (weights or reps) else 0
        if declared_sets is not None:
            target_sets = max(int(declared_sets), inferred_sets)
        else:
            target_sets = inferred_sets if inferred_sets > 3 else 3

        weights, reps = align_sets(weights, reps, target_sets=target_sets)
        is_valid = bool(reps) or any(w != 0 for w in weights)

        workout_day["exercises"].append({
            "name": _title_case(name),
            "exercise_string": "\n".join(exercise_lines).strip(),
            "weights": weights,
            "reps": reps,
            "valid": is_valid,
            "line": line_numbers[i],
            "source_name": source_name,
            "missing_name": missing_name,
        })

        i += consumed

    return workout_day
