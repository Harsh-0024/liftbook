"""The admin-only AI coach: a tool-using conversation (Groq or Gemini) over the user's own logs.

The model never sees the database. It gets a set of read-only tools (services.coach_tools),
asks for what it needs, and writes its answer from the results. Models are tried best first and
any of them can take a question over mid-way. When there is no key or every model is down,
questions the rule-based assistant (services.history_qa) knows still get answered.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter, deque
from typing import Any, Deque, Dict, Iterator, List, Optional

import requests

from config import Config
from services import coach_tools
from services.history_qa import answer_history_question
from utils.dates import local_today
from utils.logger import logger

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
PROVIDERS = ("gemini", "groq")
# Best expected answer first (quality over speed); AI_MODEL_ORDER overrides it without a deploy of code.
# gemini-3.8-flash sits last only because the free tier queues it past the request timeout today.
DEFAULT_MODEL_ORDER = (
    "groq:openai/gpt-oss-120b",
    "gemini:gemini-2.5-flash",
    "gemini:gemini-3.5-flash-lite",
    "groq:qwen/qwen3.8-27b",
    "gemini:gemini-3.8-flash",
)
GROQ_REASONING_EFFORT = "high"  # gpt-oss thinks harder before answering; worth the extra tokens
# Gemini 3 rejects a function call without a thought signature; this is its documented stand-in
# for calls another model wrote (e.g. when a question started on Groq).
SKIP_SIGNATURE = "skip_thought_signature_validator"
MAX_TOOL_ROUNDS = 8  # careful answers can need several lookups; the last round must answer
MAX_HISTORY_TURNS = 12
MAX_MESSAGE_CHARS = 1500
REQUEST_TIMEOUT_S = 30

# Per-user request budget, in-process like the auth rate limits.
RATE_LIMIT = 30
RATE_WINDOW_S = 600
_rate_lock = threading.Lock()
_rate_hits: Dict[int, Deque[float]] = {}

# A model that 404s for a key (retired, or not on that key's tier) is skipped for a while.
_bad_models: Dict[str, float] = {}
_BAD_MODEL_TTL_S = 3600

TOOL_LABELS = {
    "list_exercises": "Exercise list",
    "get_exercise_history": "Exercise history",
    "get_personal_records": "Personal records",
    "get_workouts": "Workouts",
    "get_training_summary": "Training summary",
    "get_progress_trend": "Progress trend",
    "review_lifts": "Lift review",
    "compare_periods": "Period comparison",
    "get_plan": "Workout plan",
    "suggest_next_session": "Next-session target",
}


class CoachUnavailable(Exception):
    pass


def allow_request(user_id: int, now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    with _rate_lock:
        hits = _rate_hits.setdefault(int(user_id), deque())
        while hits and now - hits[0] > RATE_WINDOW_S:
            hits.popleft()
        if len(hits) >= RATE_LIMIT:
            return False
        hits.append(now)
        return True


def system_prompt(user, context: Optional[Dict[str, Any]] = None) -> str:
    today = local_today()
    name = (getattr(user, "full_name", None) or getattr(user, "username", None) or "the lifter").split(" ")[0]
    bodyweight = getattr(user, "bodyweight", None)
    lines = [
        "You are Coach, a sharp, friendly strength coach built into a workout logging app.",
        f"You are talking with {name}. Today is {today.isoformat()} ({today.strftime('%A')}). Weights are in kg.",
        f"Their bodyweight is {bodyweight:g} kg." if bodyweight else "",
        "",
        "How to work:",
        "- Answer from their real data. Call tools to look things up; never guess or invent numbers, dates or lifts.",
        "- Call several tools if needed (e.g. summary + trend) before answering. Resolve vague exercise names with list_exercises.",
        "- Before answering, check you have every number the answer rests on. Look one more thing up rather than "
        "answer vaguely, and never end by asking the user for something you could look up yourself.",
        "- If a tool returns an error, fix the arguments and try again. When an exercise name doesn't match, use the "
        "closest logged name it suggests (e.g. 'bench press' -> 'Flat Barbell Press') and say which one you used.",
        "- e1RM means estimated one-rep max (from the logged weight and reps). Timed holds (timed_hold, hold_score) "
        "log seconds, not reps, and have no e1RM; never compare them with lifts.",
        "- If the period they ask about has no workouts, say so in one line, then still answer from their most recent "
        "training (e.g. widen the trend window) instead of stopping there.",
        "",
        "How to answer:",
        "- Lead with the answer in one sentence, then the numbers behind it. Be complete first and brief second: "
        "cover what the question needs (usually 80-200 words) and never pad.",
        "- Use short bullet points ('- ') and **bold** for key numbers. No tables, no headings.",
        "- Write dates as YYYY-MM-DD so the app can link them to the workout.",
        "- When it helps, end with one concrete, specific next step. For load/rep targets use suggest_next_session "
        "rather than inventing numbers, and give the targets themselves: never tell the user to run, check or "
        "look something up that you could fetch now (for several lifts, fetch each).",
        "- Never mention tool names, field names or JSON to the user; just use what you found. Call any e1RM "
        "just 'e1RM'.",
        "- An e1RM marked e1rm_unreliable comes from a long set (over 12 reps); say so once, briefly, not per line. "
        "Strength rankings use ranking_e1rm_kg, which counts at most 12 reps a set; quote that when ranking. "
        "On includes_bodyweight rows top_weight_kg already includes bodyweight; use the load text as given.",
        "- Training advice should be evidence-based and conservative; for pain or injury, suggest seeing a professional.",
        "- Stay on training, nutrition-for-training and recovery. Politely decline unrelated requests.",
    ]
    ctx = context or {}
    page_bits = []
    if ctx.get("page"):
        page_bits.append(f"page '{ctx['page']}'")
    if ctx.get("exercise"):
        page_bits.append(f"exercise '{ctx['exercise']}'")
    if ctx.get("metric"):
        page_bits.append(f"chart metric '{ctx['metric']}'")
    if ctx.get("date"):
        page_bits.append(f"selected date {ctx['date']}")
    if page_bits:
        lines += ["", "The user is currently looking at " + ", ".join(page_bits) +
                  ". 'This exercise', 'this day' or 'the graph' refer to that."]
    return "\n".join(l for l in lines if l is not None)


def _clean_history(messages: Any) -> List[Dict[str, Any]]:
    """Client-sent turns -> [{role: user|model, text}]. Only text survives; the first turn must be the user's."""
    out: List[Dict[str, Any]] = []
    if not isinstance(messages, list):
        return out
    for m in messages[-MAX_HISTORY_TURNS:]:
        if not isinstance(m, dict):
            continue
        role = "model" if m.get("role") in ("assistant", "model") else "user"
        text = str(m.get("text") or "").strip()[:MAX_MESSAGE_CHARS]
        if not text:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["text"] += "\n\n" + text
        else:
            out.append({"role": role, "text": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def key_provider(api_key: Any) -> str:
    """Saved keys have no provider column; Groq keys start with gsk_, everything else is Gemini (AIza...)."""
    return "groq" if str(api_key or "").strip().startswith("gsk_") else "gemini"


def _keys(api_keys: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    keys = [
        {**k, "provider": key_provider(k["api_key"])}
        for k in (api_keys or []) if isinstance(k, dict) and k.get("api_key")
    ]
    for provider, env_key in (("gemini", getattr(Config, "GEMINI_API_KEY", None)),
                              ("groq", getattr(Config, "GROQ_API_KEY", None))):
        if env_key:
            keys.append({"id": None, "api_key": env_key, "source": f"env-{provider}", "provider": provider})
    out, per_provider = [], Counter()
    for k in keys:
        if per_provider[k["provider"]] < 3:
            per_provider[k["provider"]] += 1
            out.append(k)
    return out


def _model_order() -> List[tuple]:
    """(provider, model) pairs to try, best first. A bare model name means Gemini, as GEMINI_COACH_MODEL always did."""
    raw = str(getattr(Config, "AI_MODEL_ORDER", "") or "").strip()
    entries = [e.strip() for e in raw.split(",") if e.strip()] if raw else list(DEFAULT_MODEL_ORDER)
    preferred = str(getattr(Config, "GEMINI_COACH_MODEL", "") or "").strip()
    if preferred:
        entries.insert(0, preferred)
    out: List[tuple] = []
    for entry in entries:
        provider, _, model = entry.partition(":")
        if not model:
            provider, model = "gemini", provider
        pair = (provider.strip().lower(), model.strip())
        if pair[0] in PROVIDERS and pair[1] and pair not in out:
            out.append(pair)
    return out


def _post(api_key: str, model: str, payload: dict) -> dict:
    resp = requests.post(
        f"{BASE_URL}/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _post_groq(api_key: str, model: str, payload: dict) -> dict:
    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


# --- one conversation, two wire formats ----------------------------------------------------
# A turn is {role: user, text} | {role: model, text, calls, gemini_parts} | {role: tool, results}.
# Calls carry an id either way; native_id says whether the model itself sent one (Gemini 2.5 doesn't).

def _gemini_payload(system: str, turns: List[Dict[str, Any]], final: bool = False) -> dict:
    contents = []
    for t in turns:
        if t["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": t["text"]}]})
        elif t["role"] == "model":
            parts = t.get("gemini_parts")
            if parts is None:  # written by another provider: rebuild it, with the stand-in signature
                parts = [{"text": t["text"]}] if t.get("text") else []
                for i, c in enumerate(t.get("calls") or []):
                    part = {"functionCall": {"name": c["name"], "args": c["args"], "id": c["id"]}}
                    if i == 0:
                        part["thoughtSignature"] = SKIP_SIGNATURE
                    parts.append(part)
            # Gemini's own turn goes back untouched so its thought signatures survive.
            contents.append({"role": "model", "parts": parts})
        else:
            contents.append({"role": "user", "parts": [
                {"functionResponse": {**({"id": r["id"]} if r["native_id"] else {}),
                                      "name": r["name"], "response": r["response"]}}
                for r in t["results"]
            ]})
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "tools": [{"functionDeclarations": coach_tools.function_declarations()}],
        # On the last round the tools stay declared (the history uses them) but can't be called.
        "toolConfig": {"functionCallingConfig": {"mode": "NONE" if final else "AUTO"}},
        # 2.5 counts its thinking against this cap, so a tight one can cut answers short.
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8192},
    }


def _openai_payload(system: str, turns: List[Dict[str, Any]], model: str, final: bool = False) -> dict:
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
    for t in turns:
        if t["role"] == "user":
            messages.append({"role": "user", "content": t["text"]})
        elif t["role"] == "model":
            calls = t.get("calls") or []
            msg: Dict[str, Any] = {"role": "assistant", "content": t.get("text") or (None if calls else "")}
            if calls:
                msg["tool_calls"] = [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                    for c in calls
                ]
            messages.append(msg)
        else:
            messages += [
                {"role": "tool", "tool_call_id": r["id"], "content": json.dumps(r["response"], ensure_ascii=False)}
                for r in t["results"]
            ]
    payload = {
        "model": model,
        "messages": messages,
        "tools": [
            {"type": "function", "function": {
                "name": d["name"], "description": d["description"],
                "parameters": d.get("parameters") or {"type": "object", "properties": {}},
            }}
            for d in coach_tools.function_declarations()
        ],
        "tool_choice": "none" if final else "auto",
        "temperature": 0.4,
        "max_completion_tokens": 8192,
    }
    if "gpt-oss" in model:
        payload["reasoning_effort"] = GROQ_REASONING_EFFORT
    return payload


def _parse_gemini(data: dict, round_no: int) -> Dict[str, Any]:
    parts = _candidate_parts(data)
    calls = []
    for p in parts:
        fc = p.get("functionCall") if isinstance(p, dict) else None
        if isinstance(fc, dict):
            calls.append({
                "id": fc.get("id") or f"call_{round_no}_{len(calls)}",
                "native_id": bool(fc.get("id")),
                "name": str(fc.get("name") or ""),
                "args": fc.get("args") if isinstance(fc.get("args"), dict) else {},
            })
    return {
        "text": _answer_text(parts),
        "calls": calls,
        "gemini_parts": parts,
        "tokens": int((data.get("usageMetadata") or {}).get("totalTokenCount") or 0),
        "finish": _finish_reason(data),
    }


def _parse_openai(data: dict, round_no: int) -> Dict[str, Any]:
    choice = (data.get("choices") or [{}])[0] or {}
    msg = choice.get("message") or {}
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {}
        calls.append({
            "id": tc.get("id") or f"call_{round_no}_{len(calls)}",
            "native_id": True,
            "name": str(fn.get("name") or ""),
            "args": args if isinstance(args, dict) else {},
        })
    return {
        "text": _answer_text([{"text": msg.get("content") or ""}]),
        "calls": calls,
        "gemini_parts": None,
        "tokens": int((data.get("usage") or {}).get("total_tokens") or 0),
        "finish": str(choice.get("finish_reason") or ""),
    }


def _call(provider: str, key: Dict[str, Any], model: str, system: str, turns: List[Dict[str, Any]],
          round_no: int, final: bool) -> Dict[str, Any]:
    if provider == "groq":
        return _parse_openai(_post_groq(key["api_key"], model, _openai_payload(system, turns, model, final)), round_no)
    return _parse_gemini(_post(key["api_key"], model, _gemini_payload(system, turns, final)), round_no)


def _describe(error: Exception) -> str:
    response = getattr(error, "response", None)
    if response is not None:
        return f"{type(error).__name__} {response.status_code}"
    return type(error).__name__


class _Transport:
    """Prefers the first provider/model/key that works for the rest of the turn, moving on when it fails."""

    def __init__(self, keys: List[Dict[str, Any]]):
        self.keys = keys
        self.chosen: Optional[tuple] = None
        self.skipped: List[tuple] = []
        self.calls = 0
        self.tokens = 0
        self.failures: List[str] = []

    def skip_chosen(self) -> None:
        """Leave the current pair out for the rest of this turn (e.g. it answered with nothing)."""
        if self.chosen:
            self.skipped.append(self.chosen)
            self.chosen = None

    def _pairs(self) -> List[tuple]:
        # Model first, then key: the best model on any key beats a weaker model on the first key.
        pairs = [
            (provider, model, key)
            for provider, model in _model_order()
            for key in self.keys
            if key["provider"] == provider and (provider, model, key) not in self.skipped
        ]
        if self.chosen in pairs:
            pairs.remove(self.chosen)
            pairs.insert(0, self.chosen)
        return pairs

    def generate(self, system: str, turns: List[Dict[str, Any]], round_no: int, final: bool = False) -> tuple:
        # Mid-turn the chosen pair goes first; if it's rate-limited or down, any other model, on
        # either provider, can pick the conversation up from the shared turns.
        last_error: Optional[Exception] = None
        dead_keys: set = set()
        for provider, model, key in self._pairs():
            if id(key) in dead_keys:
                continue
            bad_key = f"{key.get('id') or key.get('source')}:{model}"
            if _bad_models.get(bad_key, 0) > time.time():
                continue
            try:
                self.calls += 1
                reply = _call(provider, key, model, system, turns, round_no, final)
                self.chosen = (provider, model, key)
                self.tokens += reply["tokens"]
                return reply, key, model
            except requests.HTTPError as e:
                last_error = e
                status = e.response.status_code if e.response is not None else None
                self.failures.append(f"{model}:{status}")
                if status == 404:
                    _bad_models[bad_key] = time.time() + _BAD_MODEL_TTL_S
                elif status in (401, 403):
                    dead_keys.add(id(key))  # this key is bad; its other models would fail too
                # 400 (e.g. Groq's tool_use_failed), 413, 429 and 5xx: another model may manage it.
            except requests.RequestException as e:
                last_error = e
                self.failures.append(f"{model}:{type(e).__name__}")
        raise CoachUnavailable(_describe(last_error) if last_error else "no usable key")


def _candidate_parts(data: dict) -> List[Dict[str, Any]]:
    try:
        cand = (data.get("candidates") or [])[0]
        return list((cand.get("content") or {}).get("parts") or [])
    except (AttributeError, IndexError, TypeError):
        return []


def _answer_text(parts: List[Dict[str, Any]]) -> str:
    """The answer's text parts, minus stray leading fragments ("0", "oon") that flash-lite sometimes emits."""
    texts = [p.get("text") or "" for p in parts if isinstance(p, dict) and not p.get("thought")]
    while len(texts) > 1 and not re.search(r"\s", texts[0].strip()):
        texts.pop(0)
    text = "".join(texts).strip()
    if not re.search(r"[A-Za-z]", text) or (len(text) < 4 and not re.search(r"\s", text)):
        return ""  # a lone fragment; the caller asks another model
    return text


_TOOL_NAME_RE = None


def _plain_words(text: str) -> str:
    """Models sometimes name a tool or field despite the prompt ("use `suggest_next_session`");
    swap those for their plain label so the answer never reads like code."""
    global _TOOL_NAME_RE
    if _TOOL_NAME_RE is None:
        names = sorted(coach_tools.TOOLS, key=len, reverse=True)
        _TOOL_NAME_RE = re.compile(r"`?\b(" + "|".join(map(re.escape, names)) + r")\b`?")
    text = _TOOL_NAME_RE.sub(lambda m: TOOL_LABELS.get(m.group(1), m.group(1)).lower(), text)
    return re.sub(r"\branking[ _]e1rm(?:_kg)?\b", "e1RM", text, flags=re.IGNORECASE)


def _finish_reason(data: dict) -> str:
    try:
        return str((data.get("candidates") or [])[0].get("finishReason") or "")
    except (AttributeError, IndexError, TypeError):
        return ""


_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def _links_for(text: str) -> List[Dict[str, str]]:
    seen, links = set(), []
    for d in _DATE_RE.findall(text or ""):
        if d not in seen:
            seen.add(d)
            links.append({"label": d, "url": f"/workout/{d}"})
    return links[:6]


def run_coach(db_session, user, **kwargs) -> Dict[str, Any]:
    """Answer one question; the result is the last event of run_coach_events."""
    result: Dict[str, Any] = {}
    for event in run_coach_events(db_session, user, **kwargs):
        if event["type"] == "done":
            result = event["result"]
    return result


def run_coach_events(
    db_session,
    user,
    *,
    messages: List[Dict[str, Any]],
    api_keys: Optional[List[Dict[str, Any]]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Iterator[Dict[str, Any]]:
    """{type: step, step} as each lookup finishes, then {type: done, result}.

    result["usage"] holds what the answer cost (question, model calls, tokens, ms, failed models)
    for the caller to record; it isn't meant for the client.
    """
    usage: Dict[str, Any] = {}
    result = yield from _answer(db_session, user, messages, api_keys, context, usage)
    if result.get("ok"):
        result["usage"] = usage
    yield {"type": "done", "result": result}


def _answer(db_session, user, messages, api_keys, context, usage: Dict[str, Any]):
    turns = _clean_history(messages)
    if not turns or turns[-1]["role"] != "user":
        return {"ok": False, "error": "Please enter a question."}
    question = turns[-1]["text"]
    usage["question"] = question
    ctx = context or {}

    keys = _keys(api_keys)
    if not keys:
        return _rules_answer(db_session, user, question, ctx, note="No AI key is set up, so only built-in questions work. "
                                                                    "Add a Gemini or Groq key in Settings → Integrations.")

    system = system_prompt(user, ctx)
    transport = _Transport(keys)
    steps: List[Dict[str, Any]] = []
    retried_empty = False
    started_at = time.perf_counter()
    outcome = "rules"
    try:
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            # Out of rounds (or lookups): the model must answer from what it has rather than lose it all.
            final = round_no == MAX_TOOL_ROUNDS or len(steps) >= MAX_TOOL_ROUNDS * 4
            reply, key, model = transport.generate(system, turns, round_no, final)
            if final and reply["calls"]:
                reply = {**reply, "calls": []}  # a model that calls anyway: keep whatever text it wrote
            if not reply["calls"]:
                text = reply["text"]
                if not text:
                    if not retried_empty:
                        # Models sometimes end a turn with no text after reading tool results; ask another.
                        retried_empty = True
                        transport.skip_chosen()
                        continue
                    raise CoachUnavailable(f"empty answer ({reply['finish'] or 'no reason'})")
                outcome = f"ai:{model}"
                text = _plain_words(text)
                return {
                    "ok": True,
                    "answer": text,
                    "steps": steps,
                    "links": _links_for(text),
                    "model": model,
                    "key_id": key.get("id"),
                    "source": "ai",
                }
            turns.append({"role": "model", "text": reply["text"], "calls": reply["calls"],
                          "gemini_parts": reply["gemini_parts"]})
            results = []
            for call in reply["calls"]:
                started = time.perf_counter()
                result = coach_tools.run_tool(db_session, user, call["name"], call["args"])
                steps.append({
                    "tool": call["name"],
                    "label": TOOL_LABELS.get(call["name"], call["name"]),
                    "args": {k: v for k, v in call["args"].items() if v not in (None, "")},
                    "ok": "error" not in result,
                    "ms": int((time.perf_counter() - started) * 1000),
                })
                yield {"type": "step", "step": steps[-1]}
                results.append({"id": call["id"], "native_id": call["native_id"], "name": call["name"],
                                "response": _compact(result)})
            turns.append({"role": "tool", "results": results})
        raise CoachUnavailable("too many tool rounds")
    except CoachUnavailable as e:
        logger.warning(f"AI coach unavailable: {e}")
        return _rules_answer(db_session, user, question, ctx, note="The AI is unavailable right now, so this is the built-in answer.")
    except Exception as e:
        logger.error(f"AI coach failed: {type(e).__name__}: {e}", exc_info=True)
        return _rules_answer(db_session, user, question, ctx, note="The AI hit an error, so this is the built-in answer.")
    finally:
        usage.update(calls=transport.calls, tokens=transport.tokens, steps=steps,
                     ms=int((time.perf_counter() - started_at) * 1000), failed=",".join(transport.failures))
        # One line per question while the beta is tested: where it went, what it cost, how long it took.
        logger.info(
            f"AI coach user={getattr(user, 'id', None)} outcome={outcome} calls={transport.calls} "
            f"tokens={transport.tokens} tools={len(steps)} ms={int((time.perf_counter() - started_at) * 1000)}"
            + (f" failed={','.join(transport.failures)}" if transport.failures else "")
        )


def _compact(result: Dict[str, Any], limit: int = 12000) -> Dict[str, Any]:
    text = json.dumps(result, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return json.loads(text)
    return {"truncated": True, "partial_json": text[:limit]}


def _rules_answer(db_session, user, question: str, ctx: Dict[str, Any], *, note: str) -> Dict[str, Any]:
    exercise_options = coach_tools._logged_names(db_session, user)
    result = answer_history_question(
        db_session,
        user,
        question=question,
        context_exercise=ctx.get("exercise") or None,
        context_metric=ctx.get("metric") or None,
        context_date=ctx.get("date") or None,
        api_keys=None,
        exercise_options=exercise_options,
        use_ai=False,
    )
    if not result.get("ok"):
        return {"ok": False, "error": f"{note} {result.get('error') or ''}".strip(), "source": "rules"}
    lines = [str(result.get("answer") or "")]
    for r in (result.get("results") or [])[:6]:
        bits = [r.get("exercise") or r.get("date") or ""]
        if r.get("top_weight") is not None and r.get("top_reps") is not None:
            bits.append(f"{r['top_weight']:g} x {r['top_reps']}")
        if r.get("estimated_1rm"):
            bits.append(f"e1RM {float(r['estimated_1rm']):.1f}")
        lines.append("- " + " — ".join(b for b in bits if b))
    links = [{"label": "Open workout", "url": result["workout_url"]}] if result.get("workout_url") else []
    return {"ok": True, "answer": "\n".join(lines), "steps": [], "links": links, "source": "rules", "note": note}


def suggestions(db_session, user) -> List[str]:
    """Starter questions built from what this user actually trains."""
    top = coach_tools.list_exercises(db_session, user, limit=3).get("exercises") or []
    out = ["How has my training gone over the last 4 weeks?"]
    if top:
        out.append(f"How is my {top[0]['exercise']} progressing?")
    out.append("Which of my lifts are stalling?")
    if len(top) > 1:
        out.append(f"What should I aim for next time on {top[1]['exercise']}?")
    out += ["What should I train today?", "Which muscle groups am I neglecting?", "What are my strongest lifts?"]
    return out[:6]
