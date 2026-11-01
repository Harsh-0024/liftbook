// POST /functions/v1/coach - one question to the AI coach, from the signed-in app.
//
// Body: {messages: [{role, text}], context?: {page, exercise, metric, date}, stream?: true,
//        tz_offset_minutes?: 330}
// The person's sign-in token (Authorization) says who is asking. Their training is read with that
// token (so only their own rows); their AI keys and the record of the answer need the service
// key, because nobody can read a key back through the API.
//
// Reply: {ok, answer, steps, links, model, answer_id, source} or {ok: false, error}. With
// stream, one JSON object per line: {type: "step", label, args, ok} as each lookup finishes,
// then {type: "done", ...the reply}.

import { supabaseFor, bearer } from '../_shared/supabase.js';
import { json, preflight, CORS } from '../_shared/http.js';
import { loadLiftbook, localToday, tzOffset } from '../_shared/liftbook.js';
import { answer, modelOrder } from './coach.js';

// Per person, like the old app: 30 answers in 10 minutes.
export const RATE_LIMIT = 30;
export const RATE_WINDOW_MS = 10 * 60 * 1000;

/** Never a bare 500: the app (and a Shortcut) always gets a reply it can read. */
export async function handle(req, env, options = {}) {
  try {
    return await serve(req, env, options);
  } catch (err) {
    console.error('failed', err);
    return json({ ok: false, error: 'Unable to answer right now.' }, 500);
  }
}

async function serve(req, env, { fetchFn = (...a) => globalThis.fetch(...a), now = () => Date.now() } = {}) {
  if (req.method === 'OPTIONS') return preflight();
  if (req.method !== 'POST') return json({ ok: false, error: 'Use POST.' }, 405);
  const sb = supabaseFor(env, fetchFn);
  const token = bearer(req);
  const user = await sb.user(token);
  if (!user) return json({ ok: false, error: 'Sign in again.' }, 401);

  let body;
  try {
    body = await req.json();
  } catch {
    return json({ ok: false, error: 'Please enter a question.' }, 400);
  }
  const service = sb.asService();
  const mine = `user_id=eq.${encodeURIComponent(user.id)}`;

  const since = new Date(now() - RATE_WINDOW_MS).toISOString();
  const recent = await service.get(`coach_answers?select=id&${mine}&created_at=gt.${encodeURIComponent(since)}&limit=${RATE_LIMIT}`);
  if ((recent || []).length >= RATE_LIMIT) {
    return json({ ok: false, error: "You're asking a lot! Give it a few minutes and try again." }, 429);
  }

  const keys = await service.get(`ai_keys?select=id,api_key&${mine}&is_active=eq.true&order=created_at.desc,id.desc`);
  if (!keys?.length) return json({ ok: false, no_key: true, error: 'Add a Gemini or Groq key first: the coach answers with your own key.' }, 400);

  const { lb } = await loadLiftbook(sb.asUser(token), user.id);
  const today = localToday(tzOffset(body.tz_offset_minutes), now());
  const question = {
    messages: body.messages, context: body.context, keys, today, fetchFn, now,
    models: modelOrder({ order: env.AI_MODEL_ORDER, preferred: env.GEMINI_COACH_MODEL }),
    profile: lb.profile() || {},
    data: { history: lb.history(), settings: lb.exerciseSettings(), planText: lb.planText(), repRangesText: lb.repRangesText() },
  };

  const finish = async (result) => {
    const { usage, key_id: keyId, ...reply } = result;
    if (result.ok) {
      // Kept so answers can be rated and models compared; never at the cost of the answer.
      try {
        const [row] = await service.insert('coach_answers', [{
          user_id: user.id, question: usage.question, answer: reply.answer, source: 'ai', model: String(reply.model).slice(0, 80),
          steps: usage.steps.map((s) => ({ tool: s.tool, args: s.args, ok: s.ok })),
          calls: usage.calls, tokens: usage.tokens, ms: usage.ms, failed: usage.failed.slice(0, 300) || null,
        }], 'id');
        reply.answer_id = row?.id ?? null;
        if (keyId) await service.update(`ai_keys?id=eq.${keyId}&${mine}`, { last_used_at: new Date(now()).toISOString() });
      } catch (err) {
        console.warn('could not record coach answer', err.message);
      }
    }
    reply.steps = (reply.steps || []).map((s) => ({ label: s.label, args: s.args, ok: s.ok }));
    return reply;
  };

  if (!body.stream) {
    const reply = await finish(await answer(question));
    return json(reply, reply.ok ? 200 : 400);
  }
  const enc = new TextEncoder();
  const stream = new ReadableStream({
    async start(ctl) {
      const send = (obj) => ctl.enqueue(enc.encode(`${JSON.stringify(obj)}\n`));
      try {
        const result = await answer({ ...question, onStep: (s) => send({ type: 'step', label: s.label, args: s.args, ok: s.ok }) });
        send({ type: 'done', ...(await finish(result)) });
      } catch (err) {
        console.error('coach stream failed', err);
        send({ type: 'done', ok: false, error: 'Unable to answer right now.' });
      }
      ctl.close();
    },
  });
  return new Response(stream, { headers: { ...CORS, 'Content-Type': 'application/x-ndjson', 'Cache-Control': 'no-cache' } });
}
