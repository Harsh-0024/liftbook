// A stand-in for Supabase as the Edge Functions see it: Auth (/auth/v1/user), REST tables with
// the filters the functions use, and a few rules of supabase/schema.sql (the service key sees
// everything; a person's token only their own rows; legacy_id can't be written; keep_newest).
// Also fake Gemini and Groq, answering from a script.

const SERVICE = 'service-key';
const ANON = 'anon-key';

export const ENV = {
  SUPABASE_URL: 'https://example.supabase.co', SUPABASE_ANON_KEY: ANON, SUPABASE_SERVICE_ROLE_KEY: SERVICE,
};

const KEYS = { workout_logs: ['id'], user_texts: ['kind'], exercise_settings: ['exercise_key'], retrieval_events: ['id'], exercise_renames: ['id'], profiles: [], app_settings: [] };

export function fakeSupabase() {
  const tables = {
    profiles: [], workout_logs: [], user_texts: [], exercise_settings: [], retrieval_events: [], exercise_renames: [],
    app_settings: [], ai_keys: [], coach_answers: [], shortcut_keys: [], admins: [],
  };
  const tokens = new Map(); // token -> user id
  const requests = [];
  let nextId = 1;
  let clock = Date.parse('2026-11-01T06:00:00Z');
  const stamp = () => new Date((clock += 1)).toISOString();

  // Scripted model replies: each a function (url, body) -> {status, json}.
  const ai = { replies: [], seen: [] };

  function matches(row, params) {
    for (const [k, v] of params) {
      if (['select', 'order', 'limit', 'offset', 'on_conflict'].includes(k)) continue;
      const val = row[k];
      if (v === 'is.null') {
        if (val !== null && val !== undefined) return false;
      } else if (v.startsWith('eq.')) {
        if (String(val) !== v.slice(3)) return false;
      } else if (v.startsWith('gt.')) {
        if (!(String(val) > v.slice(3))) return false;
      } else throw new Error(`filter not faked: ${k}=${v}`);
    }
    return true;
  }

  function rest(method, path, body, who) {
    const [table, query = ''] = path.split('?');
    const params = [...new URLSearchParams(query)];
    const q = Object.fromEntries(params);
    if (table.startsWith('rpc/')) {
      const name = table.slice(4);
      if (name === 'shared_plan') return { plan: null, rep_ranges: null, updated_at: null };
      if (name === 'is_admin') return who !== 'service' && tables.admins.some((a) => a.user_id === who);
      throw new Error(`rpc not faked: ${name}`);
    }
    const rows = tables[table];
    if (!rows) throw new Error(`no table ${table}`);
    const visible = (r) => who === 'service' || r.user_id === who;
    if (method === 'GET') {
      if (who !== 'service' && ['ai_keys', 'coach_answers', 'shortcut_keys'].includes(table) && q.select?.includes('api_key')) {
        return { status: 401, json: { message: 'permission denied for column api_key' } };
      }
      let out = rows.filter((r) => visible(r) && matches(r, params));
      if (q.order?.startsWith('created_at.desc')) out = [...out].reverse();
      const offset = Number(q.offset || 0);
      out = out.slice(offset, q.limit ? offset + Number(q.limit) : undefined);
      return structuredClone(out);
    }
    if (method === 'POST') {
      const list = Array.isArray(body) ? body : [body];
      const saved = [];
      for (const r of list) {
        if ('legacy_id' in r) return { status: 401, json: { message: 'permission denied for column legacy_id' } };
        if (who !== 'service' && r.user_id && r.user_id !== who) return { status: 403, json: { message: 'row-level security' } };
        if (q.on_conflict) {
          const cols = q.on_conflict.split(',');
          const old = rows.find((x) => cols.every((c) => x[c] === r[c]));
          if (old) {
            if (r.updated_at && old.updated_at && r.updated_at <= old.updated_at) continue;
            Object.assign(old, structuredClone(r), { server_updated_at: stamp() });
            saved.push(old);
            continue;
          }
        }
        const row = { ...structuredClone(r), server_updated_at: stamp() };
        if (['ai_keys', 'coach_answers'].includes(table)) {
          row.id = nextId++;
          row.created_at ??= new Date(clock).toISOString();
        }
        rows.push(row);
        saved.push(row);
      }
      return q.select ? structuredClone(saved) : null;
    }
    if (method === 'PATCH') {
      for (const r of rows.filter((x) => visible(x) && matches(x, params))) Object.assign(r, body);
      return null;
    }
    throw new Error(`method not faked: ${method}`);
  }

  async function fetchFn(url, init = {}) {
    const u = new URL(url);
    const method = init.method || 'GET';
    const headers = Object.fromEntries(Object.entries(init.headers || {}).map(([k, v]) => [k.toLowerCase(), v]));
    const body = init.body ? JSON.parse(init.body) : undefined;
    requests.push({ url, method, headers, body });
    const reply = (status, json) => new Response(json === null || json === undefined ? '' : JSON.stringify(json), { status, headers: { 'Content-Type': 'application/json' } });

    if (u.hostname !== 'example.supabase.co') {
      ai.seen.push({ url, body, headers });
      const next = ai.replies.shift();
      if (!next) return reply(500, { error: 'no scripted reply' });
      const r = next(url, body, headers);
      return reply(r.status || 200, r.json);
    }
    const token = (headers.authorization || '').replace(/^Bearer /, '');
    if (u.pathname === '/auth/v1/user') {
      const id = tokens.get(token);
      return id ? reply(200, { id, email: `${id}@example.com` }) : reply(401, { msg: 'invalid JWT' });
    }
    if (!u.pathname.startsWith('/rest/v1/')) return reply(404, { message: 'not faked' });
    let who;
    if (token === SERVICE && headers.apikey === SERVICE) who = 'service';
    else if (headers.apikey === ANON && tokens.has(token)) who = tokens.get(token);
    else return reply(401, { message: 'bad key' });
    const out = rest(method, u.pathname.slice('/rest/v1/'.length) + u.search, body, who);
    if (out && typeof out === 'object' && 'status' in out && 'json' in out) return reply(out.status, out.json);
    return reply(200, out);
  }

  return {
    tables, requests, ai, fetchFn,
    signIn(userId) {
      const token = `token-${userId}`;
      tokens.set(token, userId);
      return token;
    },
    seed(table, row) {
      const r = { deleted_at: null, updated_at: '2026-10-01T00:00:00.000Z', ...row, server_updated_at: stamp() };
      if (['ai_keys', 'coach_answers'].includes(table)) r.id ??= nextId++;
      tables[table].push(r);
      return r;
    },
    keysOf: (table) => KEYS[table],
  };
}

/** A workout_logs row as the import left it. */
export function logRow(userId, id, date, exercise, weights, reps, extra = {}) {
  const top = Math.max(...weights);
  const topReps = reps[weights.indexOf(top)];
  return {
    user_id: userId, id, legacy_id: null, date, workout_name: extra.workout_name ?? 'Session 1 - Chest & Biceps', exercise,
    exercise_string: `${exercise}\n${weights.join(' ')}, ${reps.join(' ')}`, sets: { weights, reps }, bodyweight: null,
    uses_bodyweight: false, top_weight: top, top_reps: topReps, estimated_1rm: Math.round(top * (1 + topReps / 30) * 10) / 10,
    created_at: `${date}Z`, ...extra,
  };
}
