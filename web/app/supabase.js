// Talking to Liftbook's Supabase project: sign-in (Auth), the tables (REST), functions (RPC)
// and profile photos (Storage), with plain fetch. Only the public URL and the anon key are
// used; row-level security keeps each person to their own rows.
//
// The sign-in is kept in localStorage, so the app opens signed in with no connection.

const TIMEOUT_MS = 15000;
const REFRESH_EARLY_S = 120;
const SESSION_KEY = 'liftbook-session';

export class ApiError extends Error {
  constructor(status, message, payload = null) {
    super(message);
    this.status = status;
    this.payload = payload;
  }

  get offline() {
    return this.status === 0;
  }
}

/** Supabase's error body -> a sentence a person can act on. */
function errorMessage(status, payload) {
  const text = payload && typeof payload === 'object'
    ? String(payload.msg || payload.message || payload.error_description || payload.error || '')
    : '';
  const code = payload && typeof payload === 'object' ? String(payload.error_code || payload.code || '') : '';
  if (code === 'invalid_credentials' || /invalid login credentials/i.test(text)) return 'That email and password don’t match.';
  if (code === 'email_not_confirmed' || /email not confirmed/i.test(text)) return 'Confirm your email first: open the link we sent you.';
  if (code === 'user_already_exists' || /already registered/i.test(text)) return 'There is already an account with that email. Sign in instead.';
  if (code === 'weak_password' || /password should/i.test(text)) return text || 'Choose a stronger password.';
  if (code === 'over_email_send_rate_limit' || status === 429) return 'Too many tries. Wait a minute and try again.';
  if (code === 'same_password') return 'That is your current password. Choose a new one.';
  if (status === 401 || status === 403) return text || 'Your sign-in has expired. Sign in again.';
  return text || `The server said no (${status}).`;
}

export function createClient({ url, key, fetchFn = (...args) => globalThis.fetch(...args), storage = globalThis.localStorage }) {
  const base = String(url || '').replace(/\/+$/, '');
  let refreshing = null;
  const listeners = new Set();

  async function request(method, path, body, { token = null, headers = {}, raw = false } = {}) {
    const h = { apikey: key, Accept: 'application/json', ...headers };
    if (body !== undefined && body !== null && !raw) h['Content-Type'] = 'application/json';
    h.Authorization = `Bearer ${token || key}`;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
    let res;
    try {
      res = await fetchFn(base + path, {
        method, headers: h, signal: ctl.signal,
        body: body === undefined || body === null ? undefined : raw ? body : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, 'No connection right now. Your changes are kept on this device.');
    } finally {
      clearTimeout(timer);
    }
    const text = await res.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = text;
    }
    if (!res.ok) throw new ApiError(res.status, errorMessage(res.status, payload), payload);
    return payload;
  }

  /* ---------------- the session ---------------- */

  function readSession() {
    try {
      const s = JSON.parse(storage.getItem(SESSION_KEY) || 'null');
      return s && s.refresh_token ? s : null;
    } catch {
      return null;
    }
  }

  function writeSession(payload) {
    if (!payload) {
      storage.removeItem(SESSION_KEY);
    } else {
      const s = {
        access_token: payload.access_token,
        refresh_token: payload.refresh_token,
        expires_at: payload.expires_at || Math.floor(Date.now() / 1000) + Number(payload.expires_in || 3600),
        user: { id: payload.user.id, email: payload.user.email, user_metadata: payload.user.user_metadata || {} },
      };
      storage.setItem(SESSION_KEY, JSON.stringify(s));
    }
    for (const fn of listeners) fn(readSession());
    return readSession();
  }

  /** A valid access token, renewed if needed; null when signed out. Offline it throws (status 0). */
  async function accessToken() {
    const s = readSession();
    if (!s) return null;
    if (s.expires_at - REFRESH_EARLY_S > Date.now() / 1000) return s.access_token;
    refreshing ??= (async () => {
      try {
        const payload = await request('POST', '/auth/v1/token?grant_type=refresh_token', { refresh_token: s.refresh_token });
        return writeSession({ ...payload, user: payload.user || s.user }).access_token;
      } catch (err) {
        // Signed out elsewhere or the sign-in was revoked: signed out here too.
        if ([400, 401, 403].includes(err.status)) {
          writeSession(null);
          return null;
        }
        throw err;
      } finally {
        refreshing = null;
      }
    })();
    return refreshing;
  }

  const auth = {
    session: readSession,
    user: () => readSession()?.user || null,
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    accessToken,
    async signIn(email, password) {
      const payload = await request('POST', '/auth/v1/token?grant_type=password', { email, password });
      return writeSession(payload);
    },
    /** Returns the session, or null when the email has to be confirmed first. */
    async signUp(email, password, data = {}, redirectTo = null) {
      const q = redirectTo ? `?redirect_to=${encodeURIComponent(redirectTo)}` : '';
      const payload = await request('POST', `/auth/v1/signup${q}`, { email, password, data });
      return payload && payload.access_token ? writeSession(payload) : null;
    },
    async sendPasswordReset(email, redirectTo) {
      const q = redirectTo ? `?redirect_to=${encodeURIComponent(redirectTo)}` : '';
      await request('POST', `/auth/v1/recover${q}`, { email });
    },
    async updatePassword(password) {
      const token = await accessToken();
      if (!token) throw new ApiError(401, 'Sign in again first.');
      await request('PUT', '/auth/v1/user', { password }, { token });
    },
    /**
     * The sign-in an emailed link carries (confirming an account, or resetting a password):
     * "#access_token=...&refresh_token=...&type=recovery". Returns {type} or null.
     */
    async fromLink(hash) {
      const p = new URLSearchParams(String(hash || '').replace(/^#/, ''));
      if (p.get('error_description')) throw new ApiError(400, p.get('error_description'));
      const access = p.get('access_token');
      const refresh = p.get('refresh_token');
      if (!access || !refresh) return null;
      const user = await request('GET', '/auth/v1/user', null, { token: access });
      writeSession({ access_token: access, refresh_token: refresh, expires_in: Number(p.get('expires_in') || 3600), user });
      return { type: p.get('type') || 'signup' };
    },
    async signOut() {
      const s = readSession();
      if (s) {
        try {
          // This device only; Supabase's default would sign out every device.
          await request('POST', '/auth/v1/logout?scope=local', {}, { token: s.access_token });
        } catch {
          // Offline: forgetting the sign-in here is enough.
        }
      }
      writeSession(null);
    },
  };

  /* ---------------- tables and functions ---------------- */

  async function authed() {
    const token = await accessToken();
    if (!token) throw new ApiError(401, 'Sign in again.');
    return token;
  }

  async function rest(method, path, body, prefer) {
    return request(method, `/rest/v1/${path}`, body, { token: await authed(), headers: prefer ? { Prefer: prefer } : {} });
  }

  const db = {
    rest,
    /** Add or update rows (the server keeps whichever change is newer). */
    upsert: (table, onConflict, rows) =>
      rest('POST', `${table}?on_conflict=${onConflict}`, rows, 'resolution=merge-duplicates,return=minimal'),
    /** One page of rows the server stamped after `since` (all rows when since is null), oldest first. */
    pullPage(table, since, offset, limit) {
      let q = `select=*&order=server_updated_at.asc&limit=${limit}&offset=${offset}`;
      if (since) q += `&server_updated_at=gt.${encodeURIComponent(since)}`;
      return rest('GET', `${table}?${q}`);
    },
    insert: (table, row) => rest('POST', table, row, 'return=minimal'),
    select: (pathAndQuery) => rest('GET', pathAndQuery),
    rpc: (name, args = {}) => rest('POST', `rpc/${name}`, args),
    /** Before signing in (sign-up): the anon key alone. */
    rpcAnon: (name, args = {}) => request('POST', `/rest/v1/rpc/${name}`, args),
  };

  /* ---------------- profile photos ---------------- */

  const storageApi = {
    async upload(bucket, path, blob) {
      const token = await authed();
      return request('POST', `/storage/v1/object/${bucket}/${path}`, blob, {
        token, raw: true, headers: { 'Content-Type': blob.type || 'application/octet-stream', 'x-upsert': 'true' },
      });
    },
    async signedUrl(bucket, path, expiresIn = 3600) {
      const token = await authed();
      const payload = await request('POST', `/storage/v1/object/sign/${bucket}/${path}`, { expiresIn }, { token });
      return payload && payload.signedURL ? `${base}/storage/v1${payload.signedURL}` : null;
    },
    async remove(bucket, paths) {
      const token = await authed();
      return request('DELETE', `/storage/v1/object/${bucket}`, { prefixes: paths }, { token });
    },
  };

  return { auth, db, storage: storageApi, url: base };
}
