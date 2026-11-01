// The AI coach: a tool-using conversation (Groq or Gemini) over the person's own logs
// (services/ai_coach.py).
//
// The model never sees the database. It gets the read-only tools in web/core/coach_tools.js,
// asks for what it needs, and writes its answer from the results. Models are tried best first and
// any of them can take a question over mid-way, on any of the person's keys.
//
// As in the old app, when no key is set up or no model can answer, questions the built-in
// answers know (web/core/history_qa.js) still get answered; anything else says why not.

import { TOOLS, coachData, functionDeclarations, runTool } from '../../../web/core/coach_tools.js';
import { rulesReply } from '../../../web/core/history_qa.js';
import { formatG } from '../../../web/core/py.js';

export const GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta';
export const GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions';
export const PROVIDERS = ['gemini', 'groq'];
// Best expected answer first (quality over speed); AI_MODEL_ORDER overrides it without a deploy.
// gemini-3.8-flash sits last only because the free tier queues it past the request timeout today.
export const DEFAULT_MODEL_ORDER = [
  'groq:openai/gpt-oss-120b',
  'gemini:gemini-2.5-flash',
  'gemini:gemini-3.5-flash-lite',
  'groq:qwen/qwen3.8-27b',
  'gemini:gemini-3.8-flash',
];
const GROQ_REASONING_EFFORT = 'high'; // gpt-oss thinks harder before answering; worth the extra tokens
// Gemini 3 rejects a function call without a thought signature; this is its documented stand-in
// for calls another model wrote (e.g. when a question started on Groq).
const SKIP_SIGNATURE = 'skip_thought_signature_validator';
export const MAX_TOOL_ROUNDS = 8; // careful answers can need several lookups; the last round must answer
export const MAX_HISTORY_TURNS = 12;
export const MAX_MESSAGE_CHARS = 1500;
export const REQUEST_TIMEOUT_MS = 30000;
// Edge Functions stop after 150 s; past this the model must answer with what it has.
export const ANSWER_BY_MS = 100000;
const BAD_MODEL_TTL_MS = 3600000;

export const TOOL_LABELS = {
  list_exercises: 'Exercise list',
  get_exercise_history: 'Exercise history',
  get_personal_records: 'Personal records',
  get_workouts: 'Workouts',
  get_training_summary: 'Training summary',
  get_progress_trend: 'Progress trend',
  review_lifts: 'Lift review',
  compare_periods: 'Period comparison',
  get_plan: 'Workout plan',
  suggest_next_session: 'Next-session target',
};

// A model that 404s for a key (retired, or not on that key's tier) is skipped for a while.
// Kept per running copy of the function, as the old app kept it per process.
const badModels = new Map();

export class CoachUnavailable extends Error {}

export class HttpError extends Error {
  constructor(status, body = '') {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

/** today: "YYYY-MM-DD". profile: {full_name, username, bodyweight}. */
export function systemPrompt(profile, context = {}, today) {
  const [y, m, d] = today.split('-').map(Number);
  const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  const name = String(profile?.full_name || profile?.username || 'the lifter').split(' ')[0];
  const bodyweight = profile?.bodyweight;
  const lines = [
    'You are Coach, a sharp, friendly strength coach built into a workout logging app.',
    `You are talking with ${name}. Today is ${today} (${weekday}). Weights are in kg.`,
    bodyweight ? `Their bodyweight is ${formatG(Number(bodyweight))} kg.` : '',
    '',
    'How to work:',
    '- Answer from their real data. Call tools to look things up; never guess or invent numbers, dates or lifts.',
    '- Call several tools if needed (e.g. summary + trend) before answering. Resolve vague exercise names with list_exercises.',
    '- Before answering, check you have every number the answer rests on. Look one more thing up rather than '
      + 'answer vaguely, and never end by asking the user for something you could look up yourself.',
    "- If a tool returns an error, fix the arguments and try again. When an exercise name doesn't match, use the "
      + "closest logged name it suggests (e.g. 'bench press' -> 'Flat Barbell Press') and say which one you used.",
    '- e1RM means estimated one-rep max (from the logged weight and reps). Timed holds (timed_hold, hold_score) '
      + 'log seconds, not reps, and have no e1RM; never compare them with lifts.',
    '- If the period they ask about has no workouts, say so in one line, then still answer from their most recent '
      + 'training (e.g. widen the trend window) instead of stopping there.',
    '',
    'How to answer:',
    '- Lead with the answer in one sentence, then the numbers behind it. Be complete first and brief second: '
      + 'cover what the question needs (usually 80-200 words) and never pad.',
    "- Use short bullet points ('- ') and **bold** for key numbers. No tables, no headings.",
    '- Write dates as YYYY-MM-DD so the app can link them to the workout.',
    '- When it helps, end with one concrete, specific next step. For load/rep targets use suggest_next_session '
      + 'rather than inventing numbers, and give the targets themselves: never tell the user to run, check or '
      + 'look something up that you could fetch now (for several lifts, fetch each).',
    "- Never mention tool names, field names or JSON to the user; just use what you found. Call any e1RM "
      + "just 'e1RM'.",
    '- An e1RM marked e1rm_unreliable comes from a long set (over 12 reps); say so once, briefly, not per line. '
      + 'Strength rankings use ranking_e1rm_kg, which counts at most 12 reps a set; quote that when ranking. '
      + 'On includes_bodyweight rows top_weight_kg already includes bodyweight; use the load text as given.',
    '- Training advice should be evidence-based and conservative; for pain or injury, suggest seeing a professional.',
    '- Stay on training, nutrition-for-training and recovery. Politely decline unrelated requests.',
  ];
  const ctx = context || {};
  const pageBits = [];
  if (ctx.page) pageBits.push(`page '${ctx.page}'`);
  if (ctx.exercise) pageBits.push(`exercise '${ctx.exercise}'`);
  if (ctx.metric) pageBits.push(`chart metric '${ctx.metric}'`);
  if (ctx.date) pageBits.push(`selected date ${ctx.date}`);
  if (pageBits.length) {
    lines.push('', `The user is currently looking at ${pageBits.join(', ')}. 'This exercise', 'this day' or 'the graph' refer to that.`);
  }
  return lines.join('\n');
}

/** The page the question was asked from: page, exercise, metric, date (each short text). */
export function cleanContext(raw) {
  const out = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const k of ['page', 'exercise', 'metric', 'date']) {
    const v = String(raw[k] ?? '').trim().slice(0, 120);
    if (v) out[k] = v;
  }
  return out;
}

/** Client-sent turns -> [{role: user|model, text}]. Only text survives; the first turn must be the user's. */
export function cleanHistory(messages) {
  const out = [];
  if (!Array.isArray(messages)) return out;
  for (const m of messages.slice(-MAX_HISTORY_TURNS)) {
    if (!m || typeof m !== 'object' || Array.isArray(m)) continue;
    const role = m.role === 'assistant' || m.role === 'model' ? 'model' : 'user';
    const text = Array.from(String(m.text || '').trim()).slice(0, MAX_MESSAGE_CHARS).join('');
    if (!text) continue;
    if (out.length && out[out.length - 1].role === role) out[out.length - 1].text += `\n\n${text}`;
    else out.push({ role, text });
  }
  while (out.length && out[0].role !== 'user') out.shift();
  return out;
}

/** Saved keys have no provider column; Groq keys start with gsk_, everything else is Gemini (AIza...). */
export function keyProvider(apiKey) {
  return String(apiKey || '').trim().startsWith('gsk_') ? 'groq' : 'gemini';
}

/** The person's active keys, newest first, at most three per provider. */
export function usableKeys(rows) {
  const per = { gemini: 0, groq: 0 };
  const out = [];
  for (const k of rows || []) {
    if (!k || !k.api_key) continue;
    const provider = keyProvider(k.api_key);
    if (per[provider] >= 3) continue;
    per[provider] += 1;
    out.push({ id: k.id ?? null, api_key: String(k.api_key).trim(), provider });
  }
  return out;
}

/** [provider, model] pairs to try, best first. A bare model name means Gemini. */
export function modelOrder({ order = '', preferred = '' } = {}) {
  const raw = String(order || '').trim();
  const entries = raw ? raw.split(',').map((e) => e.trim()).filter(Boolean) : [...DEFAULT_MODEL_ORDER];
  if (String(preferred || '').trim()) entries.unshift(String(preferred).trim());
  const out = [];
  for (const entry of entries) {
    const i = entry.indexOf(':');
    let [provider, model] = i < 0 ? ['gemini', entry] : [entry.slice(0, i), entry.slice(i + 1)];
    provider = provider.trim().toLowerCase();
    model = model.trim();
    if (PROVIDERS.includes(provider) && model && !out.some(([p, mm]) => p === provider && mm === model)) out.push([provider, model]);
  }
  return out;
}

/* ---------------- one conversation, two wire formats ---------------- */
// A turn is {role: user, text} | {role: model, text, calls, gemini_parts} | {role: tool, results}.
// Calls carry an id either way; native_id says whether the model itself sent one (Gemini 2.5 doesn't).

export function geminiPayload(system, turns, final = false) {
  const contents = [];
  for (const t of turns) {
    if (t.role === 'user') {
      contents.push({ role: 'user', parts: [{ text: t.text }] });
    } else if (t.role === 'model') {
      let parts = t.gemini_parts;
      if (parts === null || parts === undefined) { // written by another provider: rebuild it, with the stand-in signature
        parts = t.text ? [{ text: t.text }] : [];
        (t.calls || []).forEach((c, i) => {
          const part = { functionCall: { name: c.name, args: c.args, id: c.id } };
          if (i === 0) part.thoughtSignature = SKIP_SIGNATURE;
          parts.push(part);
        });
      }
      // Gemini's own turn goes back untouched so its thought signatures survive.
      contents.push({ role: 'model', parts });
    } else {
      contents.push({
        role: 'user',
        parts: t.results.map((r) => ({ functionResponse: { ...(r.native_id ? { id: r.id } : {}), name: r.name, response: r.response } })),
      });
    }
  }
  return {
    systemInstruction: { parts: [{ text: system }] },
    contents,
    tools: [{ functionDeclarations: functionDeclarations() }],
    // On the last round the tools stay declared (the history uses them) but can't be called.
    toolConfig: { functionCallingConfig: { mode: final ? 'NONE' : 'AUTO' } },
    // 2.5 counts its thinking against this cap, so a tight one can cut answers short.
    generationConfig: { temperature: 0.4, maxOutputTokens: 8192 },
  };
}

export function openaiPayload(system, turns, model, final = false) {
  const messages = [{ role: 'system', content: system }];
  for (const t of turns) {
    if (t.role === 'user') {
      messages.push({ role: 'user', content: t.text });
    } else if (t.role === 'model') {
      const calls = t.calls || [];
      const msg = { role: 'assistant', content: t.text || (calls.length ? null : '') };
      if (calls.length) {
        msg.tool_calls = calls.map((c) => ({ id: c.id, type: 'function', function: { name: c.name, arguments: JSON.stringify(c.args) } }));
      }
      messages.push(msg);
    } else {
      for (const r of t.results) messages.push({ role: 'tool', tool_call_id: r.id, content: JSON.stringify(r.response) });
    }
  }
  const payload = {
    model,
    messages,
    tools: functionDeclarations().map((d) => ({
      type: 'function',
      function: { name: d.name, description: d.description, parameters: d.parameters || { type: 'object', properties: {} } },
    })),
    tool_choice: final ? 'none' : 'auto',
    temperature: 0.4,
    max_completion_tokens: 8192,
  };
  if (model.includes('gpt-oss')) payload.reasoning_effort = GROQ_REASONING_EFFORT;
  return payload;
}

function candidateParts(data) {
  const parts = data?.candidates?.[0]?.content?.parts;
  return Array.isArray(parts) ? [...parts] : [];
}

/** The answer's text parts, minus stray leading fragments ("0", "oon") that flash-lite sometimes emits. */
export function answerText(parts) {
  const texts = parts.filter((p) => p && typeof p === 'object' && !p.thought).map((p) => p.text || '');
  while (texts.length > 1 && !/\s/.test(texts[0].trim())) texts.shift();
  const text = texts.join('').trim();
  if (!/[A-Za-z]/.test(text) || (text.length < 4 && !/\s/.test(text))) return ''; // a lone fragment; ask another model
  return text;
}

export function parseGemini(data, roundNo) {
  const parts = candidateParts(data);
  const calls = [];
  for (const p of parts) {
    const fc = p && typeof p === 'object' ? p.functionCall : null;
    if (fc && typeof fc === 'object') {
      calls.push({
        id: fc.id || `call_${roundNo}_${calls.length}`,
        native_id: Boolean(fc.id),
        name: String(fc.name || ''),
        args: fc.args && typeof fc.args === 'object' && !Array.isArray(fc.args) ? fc.args : {},
      });
    }
  }
  return {
    text: answerText(parts),
    calls,
    gemini_parts: parts,
    tokens: Number(data?.usageMetadata?.totalTokenCount || 0),
    finish: String(data?.candidates?.[0]?.finishReason || ''),
  };
}

export function parseOpenai(data, roundNo) {
  const choice = data?.choices?.[0] || {};
  const msg = choice.message || {};
  const calls = [];
  for (const tc of msg.tool_calls || []) {
    const fn = tc.function || {};
    let args;
    try {
      args = JSON.parse(fn.arguments || '{}');
    } catch {
      args = {};
    }
    calls.push({
      id: tc.id || `call_${roundNo}_${calls.length}`,
      native_id: true,
      name: String(fn.name || ''),
      args: args && typeof args === 'object' && !Array.isArray(args) ? args : {},
    });
  }
  return {
    text: answerText([{ text: msg.content || '' }]),
    calls,
    gemini_parts: null,
    tokens: Number(data?.usage?.total_tokens || 0),
    finish: String(choice.finish_reason || ''),
  };
}

async function post(fetchFn, url, headers, payload, timeoutMs) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  let res;
  try {
    res = await fetchFn(url, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: ctl.signal });
  } finally {
    clearTimeout(timer);
  }
  const text = await res.text();
  if (!res.ok) throw new HttpError(res.status, text.slice(0, 500));
  return text ? JSON.parse(text) : {};
}

/** Prefers the first provider/model/key that works for the rest of the turn, moving on when it fails. */
export class Transport {
  constructor(keys, { fetchFn, models, timeoutMs = REQUEST_TIMEOUT_MS, now = () => Date.now() }) {
    this.keys = keys;
    this.fetchFn = fetchFn;
    this.models = models;
    this.timeoutMs = timeoutMs;
    this.now = now;
    this.chosen = null;
    this.skipped = [];
    this.calls = 0;
    this.tokens = 0;
    this.failures = [];
    this.refused = new Set(); // keys that answered 401/403
  }

  /** Leave the current pair out for the rest of this turn (e.g. it answered with nothing). */
  skipChosen() {
    if (this.chosen) this.skipped.push(this.chosen);
    this.chosen = null;
  }

  pairs() {
    // Model first, then key: the best model on any key beats a weaker model on the first key.
    const same = (a, b) => a && b && a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
    const pairs = [];
    for (const [provider, model] of this.models) {
      for (const key of this.keys) {
        if (key.provider === provider && !this.skipped.some((s) => same(s, [provider, model, key]))) pairs.push([provider, model, key]);
      }
    }
    const i = pairs.findIndex((p) => same(p, this.chosen));
    if (i > 0) pairs.unshift(...pairs.splice(i, 1));
    return pairs;
  }

  async call(provider, key, model, system, turns, roundNo, final) {
    if (provider === 'groq') {
      const data = await post(this.fetchFn, GROQ_URL, { Authorization: `Bearer ${key.api_key}` },
        openaiPayload(system, turns, model, final), this.timeoutMs);
      return parseOpenai(data, roundNo);
    }
    const data = await post(this.fetchFn, `${GEMINI_URL}/models/${model}:generateContent`, { 'x-goog-api-key': key.api_key },
      geminiPayload(system, turns, final), this.timeoutMs);
    return parseGemini(data, roundNo);
  }

  async generate(system, turns, roundNo, final = false) {
    // Mid-turn the chosen pair goes first; if it's rate-limited or down, any other model, on
    // either provider, can pick the conversation up from the shared turns.
    let lastError = null;
    const deadKeys = new Set();
    for (const [provider, model, key] of this.pairs()) {
      if (deadKeys.has(key)) continue;
      const badKey = `${key.id ?? key.provider}:${model}`;
      if ((badModels.get(badKey) || 0) > this.now()) continue;
      try {
        this.calls += 1;
        const reply = await this.call(provider, key, model, system, turns, roundNo, final);
        this.chosen = [provider, model, key];
        this.tokens += reply.tokens;
        return { reply, key, model };
      } catch (err) {
        lastError = err;
        if (err instanceof HttpError) {
          this.failures.push(`${model}:${err.status}`);
          if (err.status === 404) badModels.set(badKey, this.now() + BAD_MODEL_TTL_MS);
          else if (err.status === 401 || err.status === 403) {
            deadKeys.add(key); // this key is bad; its other models would fail too
            this.refused.add(key);
          }
          // 400 (e.g. Groq's tool_use_failed), 413, 429 and 5xx: another model may manage it.
        } else {
          this.failures.push(`${model}:${err?.name === 'AbortError' ? 'Timeout' : err?.name || 'Error'}`);
        }
      }
    }
    throw new CoachUnavailable(lastError ? lastError.message : 'no usable key');
  }
}

let toolNameRe = null;

/** Models sometimes name a tool or field despite the prompt; swap those for their plain label. */
export function plainWords(text) {
  toolNameRe ??= new RegExp(`\`?\\b(${Object.keys(TOOLS).sort((a, b) => b.length - a.length).join('|')})\\b\`?`, 'g');
  return text.replace(toolNameRe, (_, name) => (TOOL_LABELS[name] || name).toLowerCase())
    .replace(/\branking[ _]e1rm(?:_kg)?\b/gi, 'e1RM');
}

/** Dates in the answer, as links to that day's workout in the app. */
export function linksFor(text) {
  const seen = new Set();
  const links = [];
  for (const [, d] of String(text || '').matchAll(/\b(20\d{2}-\d{2}-\d{2})\b/g)) {
    if (seen.has(d)) continue;
    seen.add(d);
    links.push({ label: d, url: `#/workout/${d}` });
  }
  return links.slice(0, 6);
}

function compact(result, limit = 12000) {
  const text = JSON.stringify(result);
  if (text.length <= limit) return JSON.parse(text);
  return { truncated: true, partial_json: text.slice(0, limit) };
}

function unavailableMessage(transport, keys) {
  if (keys.length && transport.refused.size === keys.length) {
    return keys.length === 1
      ? 'Your AI key was refused. Check it is correct and still active, or add a new one under AI keys.'
      : 'Your AI keys were refused. Check they are correct and still active, or add a new one under AI keys.';
  }
  if (transport.failures.some((f) => f.endsWith(':429'))) {
    return 'Your AI keys have reached their limit for now. Try again in a minute.';
  }
  return 'The AI is unavailable right now. Try again in a minute.';
}

/**
 * Answer one question.
 * messages: the chat so far, [{role: user|assistant, text}], the question last.
 * keys:     the person's active keys, newest first, [{id, api_key}].
 * data:     the person's training data for the tools (see coach_tools.js).
 * onStep:   called with each lookup as it finishes.
 * Returns {ok, answer, steps, links, model, key_id, source, usage} or {ok: false, error, usage}.
 */
export async function answer({
  messages, context = {}, keys: keyRows, data, profile, today, fetchFn = (...a) => globalThis.fetch(...a),
  models = modelOrder(), onStep = () => {}, now = () => Date.now(), answerByMs = ANSWER_BY_MS, timeoutMs = REQUEST_TIMEOUT_MS,
}) {
  const turns = cleanHistory(messages);
  const usage = { question: null, calls: 0, tokens: 0, steps: [], ms: 0, failed: '' };
  if (!turns.length || turns[turns.length - 1].role !== 'user') return { ok: false, error: 'Please enter a question.', usage };
  usage.question = turns[turns.length - 1].text;

  const question = usage.question;
  // Built-in answer when the AI can't give one; the reason why stays if it doesn't know either.
  const rules = (note, failure) => {
    const r = rulesReply({ ...data, today }, question, cleanContext(context), note);
    return r.ok ? r : failure;
  };

  const keys = usableKeys(keyRows);
  if (!keys.length) {
    const noKey = { ok: false, error: 'Add a Gemini or Groq key first: the coach answers with your own key.', no_key: true };
    return { ...rules('No AI key is set up, so only built-in questions work. Add a Gemini or Groq key below.', noKey), no_key: true, usage };
  }

  const tools = coachData({ ...data, today });
  const system = systemPrompt(profile, cleanContext(context), today);
  const transport = new Transport(keys, { fetchFn, models, timeoutMs, now });
  const steps = [];
  const startedAt = now();
  let retriedEmpty = false;
  const done = (result) => {
    Object.assign(usage, { calls: transport.calls, tokens: transport.tokens, steps, ms: now() - startedAt, failed: transport.failures.join(',') });
    return { ...result, usage };
  };
  try {
    for (let roundNo = 0; roundNo <= MAX_TOOL_ROUNDS; roundNo++) {
      // Out of rounds, lookups or time: the model must answer from what it has rather than lose it all.
      const final = roundNo === MAX_TOOL_ROUNDS || steps.length >= MAX_TOOL_ROUNDS * 4 || now() - startedAt > answerByMs;
      let { reply, key, model } = await transport.generate(system, turns, roundNo, final);
      if (final && reply.calls.length) reply = { ...reply, calls: [] }; // a model that calls anyway: keep its text
      if (!reply.calls.length) {
        if (!reply.text) {
          if (!retriedEmpty) {
            // Models sometimes end a turn with no text after reading tool results; ask another.
            retriedEmpty = true;
            transport.skipChosen();
            continue;
          }
          throw new CoachUnavailable(`empty answer (${reply.finish || 'no reason'})`);
        }
        const text = plainWords(reply.text);
        return done({ ok: true, answer: text, steps, links: linksFor(text), model, key_id: key.id, source: 'ai' });
      }
      turns.push({ role: 'model', text: reply.text, calls: reply.calls, gemini_parts: reply.gemini_parts });
      const results = [];
      for (const call of reply.calls) {
        const started = now();
        const result = runTool(tools, call.name, call.args);
        const args = Object.fromEntries(Object.entries(call.args).filter(([, v]) => v !== null && v !== undefined && v !== ''));
        steps.push({ tool: call.name, label: TOOL_LABELS[call.name] || call.name, args, ok: !('error' in result), ms: now() - started });
        onStep(steps[steps.length - 1]);
        results.push({ id: call.id, native_id: call.native_id, name: call.name, response: compact(result) });
      }
      turns.push({ role: 'tool', results });
    }
    throw new CoachUnavailable('too many tool rounds');
  } catch (err) {
    if (!(err instanceof CoachUnavailable)) console.error('coach failed', err);
    if (err instanceof CoachUnavailable) {
      return done(rules('The AI is unavailable right now, so this is the built-in answer.', { ok: false, error: unavailableMessage(transport, keys) }));
    }
    return done(rules('The AI hit an error, so this is the built-in answer.', { ok: false, error: 'The coach hit an error. Try again.' }));
  }
}
