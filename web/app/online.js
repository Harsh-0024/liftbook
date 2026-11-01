// The parts of Liftbook that only work online: the AI coach and its keys (Edge Function
// supabase/functions/coach), and the Apple Shortcuts key (supabase/functions/shortcut).
// Everything else lives on the device (data.js).

import { ApiError } from './supabase.js';

export const KEY_LINKS = {
  gemini: 'https://aistudio.google.com/apikey',
  groq: 'https://console.groq.com/keys',
};

/** "gsk_..." is Groq; Gemini keys start "AIza". Anything else is probably pasted wrong. */
export function checkKey(raw) {
  const key = String(raw || '').trim();
  if (!key) throw new Error('Paste your key first.');
  if (/\s/.test(key)) throw new Error('A key has no spaces in it. Copy it again.');
  if (key.length < 20 || key.length > 255) throw new Error('That doesn’t look like a whole key. Copy it again.');
  if (!key.startsWith('gsk_') && !key.startsWith('AIza')) {
    throw new Error('That isn’t a Gemini key (starts AIza) or a Groq key (starts gsk_).');
  }
  return key;
}

export class Online {
  /** client: supabase.js client. fetchFn: for tests. */
  constructor(client, { fetchFn = (...a) => globalThis.fetch(...a) } = {}) {
    this.client = client;
    this.fetchFn = fetchFn;
  }

  /* ---------------- AI keys ---------------- */

  keys() {
    return this.client.db.select('ai_keys?select=id,label,key_hint,provider,is_active,created_at,last_used_at&order=created_at.desc,id.desc');
  }

  async addKey(label, rawKey) {
    const apiKey = checkKey(rawKey);
    await this.client.db.insert('ai_keys', { label: String(label || '').trim().slice(0, 100), api_key: apiKey });
  }

  setKey(id, fields) {
    return this.client.db.rest('PATCH', `ai_keys?id=eq.${Number(id)}`, fields, 'return=minimal');
  }

  deleteKey(id) {
    return this.client.db.rest('DELETE', `ai_keys?id=eq.${Number(id)}`, undefined, 'return=minimal');
  }

  /* ---------------- the coach ---------------- */

  /**
   * Ask the coach. messages: the chat so far, the question last ([{role, text}]).
   * onStep({label, args, ok}) is called as each lookup finishes. Returns the reply
   * ({ok, answer, steps, links, answer_id} or {ok: false, error}).
   */
  async ask(messages, { context = {}, onStep = () => {} } = {}) {
    const token = await this.client.auth.accessToken();
    if (!token) throw new ApiError(401, 'Sign in again.');
    let res;
    try {
      res = await this.fetchFn(`${this.client.url}/functions/v1/coach`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages, context, stream: true, tz_offset_minutes: -new Date().getTimezoneOffset() }),
      });
    } catch {
      throw new ApiError(0, 'The coach needs a connection. Try again when you’re online.');
    }
    const type = res.headers.get('content-type') || '';
    if (!type.includes('ndjson') || !res.body) {
      const body = await res.json().catch(() => null);
      return body && typeof body === 'object' ? body : { ok: false, error: `The coach didn’t answer (${res.status}).` };
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let done = null;
    const take = (line) => {
      if (!line.trim()) return;
      const ev = JSON.parse(line);
      if (ev.type === 'step') onStep(ev);
      else if (ev.type === 'done') {
        const { type: _t, ...reply } = ev;
        done = reply;
      }
    };
    for (;;) {
      const { value, done: end } = await reader.read();
      if (value) buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        take(buf.slice(0, i));
        buf = buf.slice(i + 1);
      }
      if (end) break;
    }
    take(buf);
    return done || { ok: false, error: 'The coach stopped before answering. Try again.' };
  }

  /** rating: 1, -1, or 0 to clear it. */
  rate(answerId, rating) {
    return this.client.db.rest('PATCH', `coach_answers?id=eq.${Number(answerId)}`, { rating: rating || null, ...(rating ? {} : { comment: null }) }, 'return=minimal');
  }

  recentAnswers(limit = 20) {
    return this.client.db.select(`coach_answers?select=id,question,answer,model,rating,created_at&order=created_at.desc&limit=${limit}`);
  }

  /* ---------------- Apple Shortcuts ---------------- */

  /** {key_hint, created_at, last_used_at}, or null when there is no key. */
  async shortcutKey() {
    const rows = await this.client.db.select('shortcut_keys?select=key_hint,created_at,last_used_at');
    return rows?.[0] || null;
  }

  /** A new key (replacing the old one). Shown once: only its hash is kept on the server. */
  newShortcutKey() {
    return this.client.db.rpc('new_shortcut_key');
  }

  removeShortcutKey() {
    return this.client.db.rpc('remove_shortcut_key');
  }

  shortcutUrls(key = '<your key>') {
    const base = `${this.client.url}/functions/v1/shortcut`;
    return { log: `${base}/log/${key}`, pick: `${base}/pick/${key}` };
  }
}
