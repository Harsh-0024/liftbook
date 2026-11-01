// What the Edge Functions need from Supabase: who is signed in (Auth) and one person's rows
// (REST), with plain fetch.
//
// Two kinds of access:
//   asUser(token)  - the person's own sign-in: row-level security keeps it to their rows.
//   asService()    - the service key, which Supabase gives every Edge Function (never the app).
//                    It sees every row, so every query here names the person's user_id.

export class SupabaseError extends Error {
  constructor(status, message, payload = null) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

const PAGE = 1000;

/**
 * env: {SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY}, as Supabase sets them for
 * every Edge Function.
 */
export function supabaseFor(env, fetchFn = (...a) => globalThis.fetch(...a)) {
  const base = String(env.SUPABASE_URL || '').replace(/\/+$/, '');
  if (!base || !env.SUPABASE_ANON_KEY || !env.SUPABASE_SERVICE_ROLE_KEY) throw new Error('Supabase settings are missing');

  async function request(method, path, { key, token, body, headers = {} }) {
    const res = await fetchFn(base + path, {
      method,
      headers: {
        apikey: key, Authorization: `Bearer ${token || key}`, Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await res.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = text;
    }
    if (!res.ok) {
      const msg = payload && typeof payload === 'object' ? payload.message || payload.msg || payload.error : payload;
      throw new SupabaseError(res.status, `${method} ${path.split('?')[0]}: ${res.status} ${msg || ''}`.trim(), payload);
    }
    return payload;
  }

  function rest(key, token) {
    const call = (method, path, body, prefer) => request(method, `/rest/v1/${path}`, { key, token, body, headers: prefer ? { Prefer: prefer } : {} });
    return {
      get: (path) => call('GET', path),
      /** Every row a query matches, a page at a time (PostgREST stops at 1000). */
      async all(path) {
        const out = [];
        for (let offset = 0; ; offset += PAGE) {
          const rows = (await call('GET', `${path}${path.includes('?') ? '&' : '?'}limit=${PAGE}&offset=${offset}`)) || [];
          out.push(...rows);
          if (rows.length < PAGE) return out;
        }
      },
      insert: (table, rows, select = null) => call('POST', `${table}${select ? `?select=${select}` : ''}`, rows,
        select ? 'return=representation' : 'return=minimal'),
      upsert: (table, onConflict, rows) => call('POST', `${table}?on_conflict=${onConflict}`, rows, 'resolution=merge-duplicates,return=minimal'),
      update: (pathWithFilter, fields) => call('PATCH', pathWithFilter, fields, 'return=minimal'),
      rpc: (name, args = {}) => call('POST', `rpc/${name}`, args),
    };
  }

  return {
    url: base,
    /** The person a sign-in token belongs to ({id, email}), or null if it isn't valid. */
    async user(token) {
      if (!token) return null;
      try {
        const u = await request('GET', '/auth/v1/user', { key: env.SUPABASE_ANON_KEY, token });
        return u && u.id ? { id: u.id, email: u.email } : null;
      } catch (err) {
        if (err instanceof SupabaseError && err.status < 500) return null;
        throw err;
      }
    },
    asUser: (token) => rest(env.SUPABASE_ANON_KEY, token),
    asService: () => rest(env.SUPABASE_SERVICE_ROLE_KEY),
  };
}

/** The bearer token of a request, or null. */
export function bearer(req) {
  const m = /^Bearer\s+(.+)$/i.exec(req.headers.get('authorization') || '');
  return m ? m[1].trim() : null;
}
