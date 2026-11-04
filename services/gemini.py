import json
from datetime import date, datetime
import time
import re

import requests

from config import Config
from utils.logger import logger
from utils.dates import local_today, utc_now


class GeminiServiceError(Exception):
    pass


class GeminiService:
    DEFAULT_MODEL_CANDIDATES = (
        "gemini-2.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-flash",
    )
    _model_cache: dict[str, str] = {}
    _key_cooldown_until: dict[str, float] = {}
    _key_model_cooldown_until: dict[str, dict[str, float]] = {}
    _key_bad_models: dict[str, set[str]] = {}
    _available_models_cache: dict[str, dict] = {}
    _available_models_ttl_s: int = 600

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    @staticmethod
    def _headers(api_key: str) -> dict:
        return {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _list_models(api_key: str) -> list[str]:
        url = f"{GeminiService.BASE_URL}/models"
        resp = requests.get(url, headers=GeminiService._headers(api_key), timeout=20)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return []

        out: list[str] = []
        for m in models:
            if not isinstance(m, dict):
                continue
            name = m.get("name")
            supported = m.get("supportedGenerationMethods")
            if not isinstance(name, str):
                continue
            if not (isinstance(supported, list) and "generateContent" in supported):
                continue
            # API returns names like "models/gemini-1.5-flash"; normalize.
            out.append(name.replace("models/", "", 1))
        return out

    @staticmethod
    def _generate_content(*, api_key: str, model: str, payload: dict) -> dict:
        url = f"{GeminiService.BASE_URL}/models/{model}:generateContent"
        resp = requests.post(url, headers=GeminiService._headers(api_key), json=payload, timeout=20)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    @staticmethod
    def _parse_recent_date(value: object) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except Exception:
            return None

    @staticmethod
    def _build_reasons_from_history(
        *,
        category: str,
        day_id: int,
        categories: list[dict],
        plan_days: list[dict],
        recent_workouts: list[dict],
    ) -> list[str]:
        cat_key = str(category or "").strip().lower()
        today = local_today()

        def _norm_ex_name(name: str) -> str:
            if not name:
                return ""
            s = str(name).strip().lower()
            s = re.sub(r"^\s*\d+\s*[\).:-]\s*", "", s)
            s = re.sub(r"\s+", " ", s)
            return s

        def _infer_from_exercises(exercise_list: object) -> tuple[str | None, int | None]:
            if not isinstance(exercise_list, list):
                return (None, None)
            workout_ex = {_norm_ex_name(x) for x in exercise_list if _norm_ex_name(x)}
            if not workout_ex:
                return (None, None)

            best_cat = None
            best_day = None
            best_score = 0.0
            for day in plan_days or []:
                if not isinstance(day, dict):
                    continue
                day_ex = {_norm_ex_name(x) for x in (day.get("exercises") or []) if _norm_ex_name(x)}
                if not day_ex:
                    continue
                overlap = len(workout_ex.intersection(day_ex))
                day_len = len(day_ex)
                required_overlap = max(2, int(day_len * 0.7 + 0.999))
                if overlap < required_overlap:
                    continue
                score = overlap / max(day_len, 1)
                if score > best_score:
                    best_score = score
                    best_cat = day.get("category") if isinstance(day.get("category"), str) else None
                    best_day = day.get("day_id") if isinstance(day.get("day_id"), int) else None

            if best_score >= 0.7:
                return (best_cat, best_day)
            return (None, None)

        last_cat_date: date | None = None
        last_day_date: date | None = None
        last_done_day_id: int | None = None
        last_done_date: date | None = None

        last_by_cat: dict[str, date] = {}
        for w in recent_workouts or []:
            if not isinstance(w, dict):
                continue
            d = GeminiService._parse_recent_date(w.get("date"))
            if not d:
                continue

            trained_cats = w.get("trained_categories")
            if isinstance(trained_cats, list):
                for tc in trained_cats:
                    if not isinstance(tc, str) or not tc.strip():
                        continue
                    tc_key = tc.strip().lower()
                    prev = last_by_cat.get(tc_key)
                    if prev is None or d > prev:
                        last_by_cat[tc_key] = d
                    if tc_key == cat_key:
                        if last_cat_date is None or d > last_cat_date:
                            last_cat_date = d

            w_cat = w.get("category")
            w_day = w.get("day_id")

            if not (isinstance(w_cat, str) and w_cat.strip()) or not isinstance(w_day, int):
                inferred_cat, inferred_day = _infer_from_exercises(w.get("exercise_list"))
                if not (isinstance(w_cat, str) and w_cat.strip()) and isinstance(inferred_cat, str) and inferred_cat.strip():
                    w_cat = inferred_cat
                if not isinstance(w_day, int) and isinstance(inferred_day, int):
                    w_day = inferred_day

            if isinstance(w_cat, str) and w_cat.strip():
                w_cat_key = w_cat.strip().lower()
                prev = last_by_cat.get(w_cat_key)
                if prev is None or d > prev:
                    last_by_cat[w_cat_key] = d

            if isinstance(w_cat, str) and w_cat.strip().lower() == cat_key:
                if last_cat_date is None or d > last_cat_date:
                    last_cat_date = d

                if isinstance(w_day, int):
                    if last_done_date is None or d > last_done_date:
                        last_done_date = d
                        last_done_day_id = int(w_day)

                if isinstance(w_day, int) and w_day == int(day_id):
                    if last_day_date is None or d > last_day_date:
                        last_day_date = d

            day_matches = w.get("day_matches")
            if isinstance(day_matches, list):
                for m in day_matches:
                    if not isinstance(m, dict):
                        continue
                    m_cat = m.get("category")
                    m_day = m.get("day_id")
                    if not (isinstance(m_cat, str) and m_cat.strip()):
                        continue
                    if not isinstance(m_day, int):
                        continue
                    if m_cat.strip().lower() != cat_key:
                        continue
                    if last_cat_date is None or d > last_cat_date:
                        last_cat_date = d
                    if int(m_day) == int(day_id):
                        if last_day_date is None or d > last_day_date:
                            last_day_date = d

        reasons: list[str] = []

        cat_meta = None
        for c in categories or []:
            if not isinstance(c, dict):
                continue
            if str(c.get('name') or '').strip().lower() != cat_key:
                continue
            cat_meta = c
            break

        if cat_meta and isinstance(cat_meta.get('last_done_date'), str):
            meta_d = GeminiService._parse_recent_date(cat_meta.get('last_done_date'))
            if meta_d and (last_cat_date is None or meta_d > last_cat_date):
                last_cat_date = meta_d

        next_day_id = None
        done_ids: list[int] = []
        missing_ids: list[int] = []
        try:
            if cat_meta and isinstance(cat_meta.get('next_day_id'), int):
                next_day_id = int(cat_meta.get('next_day_id'))
        except Exception:
            next_day_id = None
        try:
            raw_done = cat_meta.get('cycle_done_day_ids') if cat_meta else None
            if isinstance(raw_done, list):
                done_ids = [int(x) for x in raw_done if isinstance(x, int)]
        except Exception:
            done_ids = []
        try:
            raw_missing = cat_meta.get('cycle_missing_day_ids') if cat_meta else None
            if isinstance(raw_missing, list):
                missing_ids = [int(x) for x in raw_missing if isinstance(x, int)]
        except Exception:
            missing_ids = []

        if isinstance(next_day_id, int) and next_day_id > 0:
            if done_ids:
                done_str = ", ".join(str(x) for x in done_ids)
                reasons.append(
                    f"Plan order: completed {category} day(s) {done_str} in the current cycle; next uncompleted is day {int(next_day_id)}."
                )
            else:
                reasons.append(f"Plan order: start {category} at day {int(next_day_id)} to keep your cycle consistent.")
        if last_cat_date:
            days_since = max((today - last_cat_date).days, 0)
            suffix = f" ({days_since} day(s) ago)" if days_since != 0 else " (today)"
            reasons.append(f"You last trained {category} on {last_cat_date.isoformat()}{suffix}.")
        else:
            reasons.append(f"You haven't logged {category} recently.")

        if last_day_date:
            days_since = max((today - last_day_date).days, 0)
            suffix = f" ({days_since} day(s) ago)" if days_since != 0 else " (today)"
            reasons.append(f"You last did {category} day {int(day_id)} on {last_day_date.isoformat()}{suffix}.")
        else:
            reasons.append(f"This matches your plan: {category} day {int(day_id)}.")

        cat_names = [
            str(c.get("name")).strip().lower()
            for c in categories
            if isinstance(c, dict) and isinstance(c.get("name"), str)
        ]
        overdue: list[tuple[str, int]] = []
        for ckey in cat_names:
            meta_last = None
            for c in categories or []:
                if not isinstance(c, dict):
                    continue
                if str(c.get('name') or '').strip().lower() != ckey:
                    continue
                if isinstance(c.get('last_done_date'), str):
                    meta_last = GeminiService._parse_recent_date(c.get('last_done_date'))
                break
            last_d = meta_last or last_by_cat.get(ckey)
            days_since = 999 if not last_d else max((today - last_d).days, 0)
            overdue.append((ckey, int(days_since)))
        if overdue:
            most_overdue = max(overdue, key=lambda x: x[1])
            if most_overdue[0] == cat_key:
                reasons.append("This is the least recently trained category in your split right now.")
            else:
                reasons.append("Keeps your training split balanced based on what you've trained most recently.")
        else:
            reasons.append("Keeps your training split balanced this week.")

        plan_day_name = None
        for d in plan_days or []:
            if not isinstance(d, dict):
                continue
            if str(d.get("category") or "").strip().lower() != cat_key:
                continue
            if d.get("day_id") == int(day_id):
                n = d.get("name")
                if isinstance(n, str) and n.strip():
                    plan_day_name = n.strip()
                break
        if plan_day_name:
            reasons.append(f"Selected plan day: {plan_day_name}.")

        out: list[str] = []
        seen: set[str] = set()
        for r in reasons:
            rr = str(r or "").strip()
            if not rr:
                continue
            k = rr.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(rr)
            if len(out) >= 6:
                break
        while len(out) < 3:
            out.append("Recommended based on your plan and recent workouts.")
        return out

    @staticmethod
    def _recover_reco_from_partial_json_text(text: str, category_names: list[str] | None = None) -> dict | None:
        if not isinstance(text, str) or not text:
            return None
        m_cat = re.search(r'"category"\s*:\s*"([^\"]*)', text)
        m_day = re.search(r'"day_id"\s*:\s*(?:"(\d+)"|(\d+))', text)
        if not m_cat or not m_day:
            return None

        category = (m_cat.group(1) or "").strip()
        if category_names:
            normalized = category.lower()
            exact = None
            for name in category_names:
                if isinstance(name, str) and name.strip().lower() == normalized:
                    exact = name
                    break
            if exact is not None:
                category = exact
            else:
                best = None
                for name in category_names:
                    if not isinstance(name, str):
                        continue
                    n = name.strip().lower()
                    if n and (n.startswith(normalized) or normalized.startswith(n)):
                        best = name
                        break
                if best is not None:
                    category = best

        if not category:
            return None
        day_id_str = m_day.group(1) or m_day.group(2)
        try:
            day_id = int(day_id_str)
        except Exception:
            return None

        return {"category": category, "day_id": day_id, "reasons": []}

    @staticmethod
    def recommend_workout(
        *,
        categories: list[dict],
        recent_workouts: list[dict],
        plan_days: list[dict],
        api_keys: list[dict] | None = None,
    ) -> dict:
        env_key = getattr(Config, "GEMINI_API_KEY", None)
        keys_to_try: list[dict] = []
        if api_keys:
            keys_to_try.extend([k for k in api_keys if k.get("api_key")])
        if env_key:
            keys_to_try.append({"id": None, "api_key": env_key, "source": "env"})
        if not keys_to_try:
            raise GeminiServiceError("GEMINI_API_KEY is not configured")

        max_keys_to_try = 2
        keys_to_try = keys_to_try[:max_keys_to_try]

        category_names = [c.get("name") for c in categories if isinstance(c, dict) and isinstance(c.get("name"), str)]

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "You are a strength training coach inside a workout logging app. "
                                "Given a user's workout plan categories/days and their recent workouts, "
                                "recommend which plan day they should do today.\n\n"
                                "Return ONLY valid JSON with this exact schema:\n"
                                "{\"category\": string, \"day_id\": integer, \"reasons\": [string, ...]}\n\n"
                                "Constraints:\n"
                                "- category must be one of the provided categories.\n"
                                "- day_id must be within 1..num_days for that category.\n"
                                "- Prefer the least-recently-trained day across the whole plan.\n"
                                "- Use recent workouts' exercises and details to match plan days. Titles may be arbitrary.\n"
                                "- Each category includes sequencing fields like next_day_id and last_done_date; recommend the next_day_id to keep days in order.\n"
                                "- Do not treat a workout as completing a plan day unless it clearly matches that full plan day (not just a single overlapping exercise).\n"
                                "- reasons must be 3-6 short bullet-style strings.\n\n"
                                f"Plan categories: {json.dumps(categories, ensure_ascii=False)}\n"
                                f"Plan days (name, category, day_id, exercises): {json.dumps(plan_days, ensure_ascii=False)}\n"
                                f"Recent workouts (most recent first): {json.dumps(recent_workouts, ensure_ascii=False)}\n"
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
                "responseJsonSchema": {
                    "type": "object",
                    "propertyOrdering": ["category", "day_id", "reasons"],
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Workout plan category name. Must match one of the provided categories.",
                        },
                        "day_id": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Day number within the selected category.",
                        },
                        "reasons": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 6,
                            "items": {"type": "string"},
                            "description": "3-6 short bullet-style reasons for the recommendation.",
                        },
                    },
                    "required": ["category", "day_id", "reasons"],
                },
            },
        }

        last_error: Exception | None = None

        for key_entry in keys_to_try:
            api_key = key_entry.get("api_key")
            if not api_key:
                continue

            key_label = key_entry.get("account_label") or key_entry.get("source") or f"key_id={key_entry.get('id')}"
            cache_key = (
                str(key_entry.get("id"))
                if key_entry.get("id")
                else key_entry.get("account_label")
                or key_entry.get("source")
                or f"suffix_{api_key[-6:]}"
            )

            now_ts = time.time()
            cooldown_until = GeminiService._key_cooldown_until.get(cache_key)
            if cooldown_until and cooldown_until > now_ts:
                continue

            models_to_try: list[str] = []
            try:
                available = None
                cached_models_entry = GeminiService._available_models_cache.get(cache_key)
                now_models_ts = time.time()
                if isinstance(cached_models_entry, dict):
                    cached_ts = cached_models_entry.get("ts")
                    cached_models = cached_models_entry.get("models")
                    if isinstance(cached_ts, (int, float)) and isinstance(cached_models, list):
                        if now_models_ts - float(cached_ts) < float(GeminiService._available_models_ttl_s):
                            available = cached_models

                if available is None:
                    available = GeminiService._list_models(api_key)
                    GeminiService._available_models_cache[cache_key] = {"ts": now_models_ts, "models": available}
                if available:
                    preferred = [m for m in GeminiService.DEFAULT_MODEL_CANDIDATES if m in available]
                    models_to_try = preferred
                else:
                    logger.warning("Gemini listModels returned no available models", extra={"key": key_label})
            except requests.RequestException as e:
                last_error = e
                logger.warning(
                    "Gemini listModels failed",
                    extra={"error": type(e).__name__, "key": key_label},
                )
                models_to_try = list(GeminiService.DEFAULT_MODEL_CANDIDATES)

            if not models_to_try:
                models_to_try = list(GeminiService.DEFAULT_MODEL_CANDIDATES)
            # Try preferred models first, then any available models for the key.
            cached_model = GeminiService._model_cache.get(cache_key)
            if cached_model:
                if cached_model in models_to_try:
                    models_to_try.remove(cached_model)
                models_to_try.insert(0, cached_model)

            models_tried = 0
            max_models_per_key = 2
            for model in models_to_try:
                model_cd = None
                try:
                    model_cd = GeminiService._key_model_cooldown_until.get(cache_key, {}).get(model)
                except Exception:
                    model_cd = None
                if model_cd and model_cd > time.time():
                    continue

                bad_models = GeminiService._key_bad_models.get(cache_key)
                if bad_models and model in bad_models:
                    continue

                models_tried += 1
                if models_tried > max_models_per_key:
                    break
                try:
                    data = GeminiService._generate_content(api_key=api_key, model=model, payload=payload)
                    candidate0 = None
                    try:
                        candidates = data.get("candidates") if isinstance(data, dict) else None
                        if isinstance(candidates, list) and candidates:
                            candidate0 = candidates[0] if isinstance(candidates[0], dict) else None
                    except Exception:
                        candidate0 = None

                    text_parts: list[str] = []
                    try:
                        content = candidate0.get("content") if candidate0 else None
                        parts = content.get("parts") if isinstance(content, dict) else None
                        if isinstance(parts, list):
                            for part in parts:
                                if isinstance(part, dict) and isinstance(part.get("text"), str):
                                    text_parts.append(part.get("text") or "")
                    except Exception:
                        text_parts = []

                    text = "".join(text_parts).strip()
                    if not text:
                        text = (
                            data.get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [{}])[0]
                            .get("text", "")
                        )

                    # If Gemini wraps JSON in code fences, strip them.
                    if isinstance(text, str) and "```" in text:
                        cleaned_lines = []
                        in_fence = False
                        for line in text.splitlines():
                            if line.strip().startswith("```"):
                                in_fence = not in_fence
                                continue
                            cleaned_lines.append(line)
                        text = "\n".join(cleaned_lines).strip()
                    if not text:
                        finish_reason = None
                        try:
                            finish_reason = candidate0.get("finishReason") if candidate0 else None
                        except Exception:
                            finish_reason = None

                        block_reason = None
                        try:
                            prompt_feedback = data.get("promptFeedback") if isinstance(data, dict) else None
                            if isinstance(prompt_feedback, dict):
                                block_reason = prompt_feedback.get("blockReason")
                        except Exception:
                            block_reason = None

                        raise GeminiServiceError(
                            f"Empty response from Gemini (finish_reason={finish_reason}, block_reason={block_reason})"
                        )

                    start = text.find('{')
                    end = text.rfind('}')
                    if start == -1:
                        finish_reason = None
                        try:
                            finish_reason = candidate0.get("finishReason") if candidate0 else None
                        except Exception:
                            finish_reason = None

                        block_reason = None
                        try:
                            prompt_feedback = data.get("promptFeedback") if isinstance(data, dict) else None
                            if isinstance(prompt_feedback, dict):
                                block_reason = prompt_feedback.get("blockReason")
                        except Exception:
                            block_reason = None

                        excerpt = text.strip().replace("\n", " ")
                        if len(excerpt) > 240:
                            excerpt = excerpt[:240] + "…"
                        raise GeminiServiceError(
                            f"Gemini response was not valid JSON (finish_reason={finish_reason}, block_reason={block_reason}, excerpt={excerpt})"
                        )

                    if end == -1 or end <= start:
                        recovered = GeminiService._recover_reco_from_partial_json_text(text, category_names=category_names)
                        if recovered is None:
                            finish_reason = None
                            try:
                                finish_reason = candidate0.get("finishReason") if candidate0 else None
                            except Exception:
                                finish_reason = None

                            block_reason = None
                            try:
                                prompt_feedback = data.get("promptFeedback") if isinstance(data, dict) else None
                                if isinstance(prompt_feedback, dict):
                                    block_reason = prompt_feedback.get("blockReason")
                            except Exception:
                                block_reason = None

                            excerpt = text.strip().replace("\n", " ")
                            if len(excerpt) > 240:
                                excerpt = excerpt[:240] + "…"
                            raise GeminiServiceError(
                                f"Gemini response was not valid JSON (finish_reason={finish_reason}, block_reason={block_reason}, excerpt={excerpt})"
                            )
                        obj = recovered
                    else:
                        obj = json.loads(text[start : end + 1])
                    if not isinstance(obj, dict):
                        raise GeminiServiceError("Gemini response JSON was not an object")

                    if not isinstance(obj.get("category"), str) or not obj["category"].strip():
                        raise GeminiServiceError("Missing category")
                    day_id_val = obj.get("day_id")
                    if isinstance(day_id_val, str) and day_id_val.strip().isdigit():
                        day_id_val = int(day_id_val.strip())
                        obj["day_id"] = day_id_val
                    if not isinstance(day_id_val, int):
                        raise GeminiServiceError("Missing day_id")
                    obj["category"] = obj["category"].strip()

                    original_day_id_val = int(day_id_val)
                    desired_day_id = None
                    for c in categories or []:
                        if not isinstance(c, dict):
                            continue
                        if str(c.get('name') or '').strip().lower() != obj["category"].strip().lower():
                            continue
                        if isinstance(c.get('next_day_id'), int):
                            desired_day_id = int(c.get('next_day_id'))
                        elif isinstance(c.get('last_done_day_id'), int) and isinstance(c.get('num_days'), int):
                            nd = int(c.get('last_done_day_id')) + 1
                            if nd > int(c.get('num_days')):
                                nd = 1
                            desired_day_id = nd
                        break

                    day_overridden = False
                    if isinstance(desired_day_id, int) and desired_day_id > 0 and desired_day_id != int(day_id_val):
                        day_id_val = int(desired_day_id)
                        obj["day_id"] = int(desired_day_id)
                        day_overridden = True

                    reasons_val = obj.get("reasons")
                    reasons_clean: list[str] = []
                    if isinstance(reasons_val, list):
                        for r in reasons_val:
                            if isinstance(r, str) and r.strip():
                                reasons_clean.append(r.strip())

                    generic_line = "recommended based on your plan and recent workouts."
                    if reasons_clean and all(str(r).strip().lower() == generic_line for r in reasons_clean):
                        reasons_clean = []

                    seen_reason: set[str] = set()
                    uniq: list[str] = []
                    for r in reasons_clean:
                        k = r.lower()
                        if k in seen_reason:
                            continue
                        seen_reason.add(k)
                        uniq.append(r)
                    reasons_clean = uniq

                    default_reasons = GeminiService._build_reasons_from_history(
                        category=obj["category"],
                        day_id=int(day_id_val),
                        categories=categories,
                        plan_days=plan_days,
                        recent_workouts=recent_workouts,
                    )

                    if day_overridden or int(obj.get("day_id") or 0) != int(day_id_val) or int(original_day_id_val) != int(day_id_val):
                        reasons_clean = default_reasons
                    elif not reasons_clean:
                        reasons_clean = default_reasons
                    else:
                        existing = {x.lower() for x in reasons_clean}
                        for r in default_reasons:
                            if len(reasons_clean) >= 6:
                                break
                            if r.lower() not in existing:
                                existing.add(r.lower())
                                reasons_clean.append(r)
                        if len(reasons_clean) < 3:
                            reasons_clean = default_reasons

                    obj["reasons"] = reasons_clean[:6]

                    GeminiService._model_cache[cache_key] = model

                    return {
                        "category": obj["category"],
                        "day_id": int(obj["day_id"]),
                        "reasons": obj["reasons"],
                        "model": model,
                        "generated_at": utc_now().isoformat() + "Z",
                        "key_id": key_entry.get("id"),
                    }
                except requests.HTTPError as e:
                    last_error = e
                    status = getattr(e.response, "status_code", None)
                    body = ""
                    try:
                        body = (e.response.text or "") if getattr(e, "response", None) is not None else ""
                    except Exception:
                        body = ""
                    if body and len(body) > 800:
                        body = body[:800] + "…"

                    logger.warning(
                        f"Gemini model call failed (key={key_label}, model={model}, status={status}, body={body})"
                    )
                    # 404 means model not available for this API key / region. Try next model.
                    if status == 404:
                        if GeminiService._model_cache.get(cache_key) == model:
                            GeminiService._model_cache.pop(cache_key, None)
                        continue
                    # Auth or quota: try next key.
                    if status in {401, 403}:
                        break

                    if status == 429:
                        retry_after_s = None
                        try:
                            retry_after_header = None
                            if getattr(e, "response", None) is not None:
                                retry_after_header = e.response.headers.get("retry-after")
                            if retry_after_header:
                                retry_after_s = float(retry_after_header)
                        except Exception:
                            retry_after_s = None

                        if retry_after_s is None:
                            try:
                                m = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", body, flags=re.IGNORECASE)
                                if m:
                                    retry_after_s = float(m.group(1))
                            except Exception:
                                retry_after_s = None

                        if body and "limit: 0" in body:
                            GeminiService._key_bad_models.setdefault(cache_key, set()).add(model)
                            continue

                        if retry_after_s and retry_after_s > 0:
                            GeminiService._key_model_cooldown_until.setdefault(cache_key, {})[model] = (
                                time.time() + float(retry_after_s) + 0.5
                            )
                            if body and "model:" not in body:
                                GeminiService._key_cooldown_until[cache_key] = time.time() + float(retry_after_s) + 0.5
                        continue
                    raise GeminiServiceError(f"Gemini request failed: HTTP {status}")
                except (requests.RequestException, GeminiServiceError, ValueError, json.JSONDecodeError) as e:
                    last_error = e
                    msg = str(e) if e else ""
                    msg = msg.replace("\n", " ")
                    if msg and len(msg) > 400:
                        msg = msg[:400] + "…"
                    logger.warning(
                        f"Gemini request error (key={key_label}, model={model}, error={type(e).__name__}, message={msg})"
                    )
                    continue

        if last_error:
            raise GeminiServiceError(f"Gemini request failed: {type(last_error).__name__}")

        raise GeminiServiceError("Gemini request failed")

