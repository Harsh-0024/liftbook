// Which plan day a Shortcut asks for ("Session 2", "push 1", "2", or the person's own word for it),
// as the old app's /shortcut/pick worked it out (liftbook/routes/workouts.py).

import { getWorkoutDays } from './plans.js';
import { unescapeHtml } from './html.js';

export function normalizeKey(value) {
  let text = unescapeHtml(String(value ?? '')).trim().toLowerCase();
  if (!text) return '';
  text = text.replace(/[–—]/g, '-').replace(/•/g, ' ');
  text = text.replace(/[^a-z0-9\s-]/g, ' ').replace(/-/g, ' ');
  return text.replace(/\s+/g, ' ').trim();
}

export function dayToken(category, dayId) {
  const cat = String(category || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return `${cat}:${Number(dayId)}`;
}

/** "Session 3 - Back & Triceps" from the plan's own "Session 3 – Back & Triceps" line, or "". */
export function extractSessionTitle(planText, dayId) {
  const text = String(planText || '');
  if (!text.trim() || !Number.isInteger(Number(dayId))) return '';
  const did = Number(dayId);
  const patterns = [
    new RegExp(`^\\s*Session\\s*${did}\\s*[–—-]\\s*(.+?)\\s*$`, 'i'),
    new RegExp(`^\\s*Session\\s*${did}\\s*[:]\\s*(.+?)\\s*$`, 'i'),
    new RegExp(`^\\s*Session\\s*${did}\\b\\s*(.+?)\\s*$`, 'i'),
  ];
  for (const line of text.split(/\r\n|\r|\n/)) {
    if (!line.trim()) continue;
    for (const pat of patterns) {
      const m = pat.exec(line.trim());
      if (!m) continue;
      let tail = (m[1] || '').trim().replace(/^[–—\-:]+/, '').trim();
      if (tail) {
        tail = tail.replace(/[–—]/g, '-').trim().replace(/\s*-\s*/g, ' - ').replace(/\s{2,}/g, ' ');
        return `Session ${did} - ${tail}`;
      }
      return `Session ${did}`;
    }
  }
  return '';
}

/** Every plan day: {category, day_id, label, token, aliases}. */
export function planDays(planText) {
  const data = getWorkoutDays(planText || '');
  const titles = data.session_titles || {};
  const out = [];
  for (const [category, days] of Object.entries(data.workout || {})) {
    const cat = String(category || '').trim();
    if (!cat || !days || typeof days !== 'object') continue;
    for (const dayName of Object.keys(days)) {
      const m = /\s+(\d+)\s*$/.exec(dayName);
      if (!m) continue;
      const dayId = Number(m[1]);
      let sessionTitle = '';
      if (cat.toLowerCase() === 'session') {
        sessionTitle = String(titles[String(dayId)] || '').trim();
        if (!sessionTitle) {
          const extracted = extractSessionTitle(planText, dayId);
          if (extracted.toLowerCase().startsWith('session ')) {
            sessionTitle = extracted.replace(new RegExp(`^\\s*session\\s*${dayId}\\s*[-:–—]?\\s*`, 'i'), '').trim();
          }
        }
      }
      const label = cat.toLowerCase() === 'session' && sessionTitle ? `Session ${dayId} - ${sessionTitle}` : `${cat} ${dayId}`;
      const aliases = new Set([dayName, `${cat} ${dayId}`, `${cat}:${dayId}`, `${cat}-${dayId}`,
        // The day's number alone ("1" is Session 1, not every session with a 1 in it).
        String(dayId)]);
      if (cat.toLowerCase() === 'session') {
        aliases.add(`session ${dayId}`);
        aliases.add(`s${dayId}`);
        if (sessionTitle) {
          aliases.add(sessionTitle);
          aliases.add(`session ${dayId} ${sessionTitle}`);
          aliases.add(`session ${dayId} - ${sessionTitle}`);
        }
      }
      out.push({ category: cat, day_id: dayId, label, token: dayToken(cat, dayId), aliases: [...aliases] });
    }
  }
  return out;
}

/** The Get Workout list: every day's label, in category then day order. */
export function sessionLabels(planText) {
  return planDays(planText)
    .sort((a, b) => (a.category.toLowerCase() < b.category.toLowerCase() ? -1 : a.category.toLowerCase() > b.category.toLowerCase() ? 1 : a.day_id - b.day_id))
    .map((d) => d.label);
}

/** The person's own words for days, kept as JSON {token: word} (user_texts "shortcut_keys"). */
export function customKeys(text) {
  let data;
  try {
    data = JSON.parse(String(text || '').trim() || 'null');
  } catch {
    return {};
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return {};
  const out = {};
  for (const [k, v] of Object.entries(data)) {
    const token = String(k ?? '').trim();
    const val = String(v ?? '').trim();
    if (token && val) out[token] = val.slice(0, 120);
  }
  return out;
}

const pyLess = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

/** The day a key means: {day} or {error}. */
export function resolveDay(planText, rawKey, customText = '') {
  const days = planDays(planText);
  if (!days.length) return { error: 'No workout plan found.' };
  const key = normalizeKey(rawKey);
  if (!key) return { error: 'Missing key.' };

  const aliasMap = new Map();
  const byToken = new Map();
  for (const d of days) {
    byToken.set(d.token, d);
    for (const alias of d.aliases) {
      const norm = normalizeKey(alias);
      if (!norm) continue;
      if (!aliasMap.has(norm)) aliasMap.set(norm, []);
      aliasMap.get(norm).push(d);
    }
  }
  const customMap = new Map();
  for (const [token, word] of Object.entries(customKeys(customText))) {
    const d = byToken.get(token);
    const norm = normalizeKey(word);
    if (!d || !norm) continue;
    if (!customMap.has(norm)) customMap.set(norm, []);
    customMap.get(norm).push(d);
  }
  const unique = (entries) => {
    const out = new Map();
    for (const d of entries) if (d.category && d.day_id > 0) out.set(`${d.category}\u0000${d.day_id}`, d);
    return [...out.values()];
  };
  const pick = (entries) => {
    if (entries.length === 1) return { day: entries[0] };
    if (entries.length > 1) {
      const labels = [...new Set(entries.map((d) => d.label))].sort(pyLess);
      return { error: `Ambiguous key '${rawKey}'. Matches: ${labels.slice(0, 8).join(', ')}` };
    }
    return null;
  };

  const found = pick(unique(customMap.get(key) || [])) || pick(unique(aliasMap.get(key) || []));
  if (found) return found;
  const partial = [];
  const isDigits = (s) => /^\d+$/.test(s);
  for (const [alias, items] of aliasMap) {
    // A number only ever matches a day's own number (above): "0" isn't part of Session 10.
    if (isDigits(key) || isDigits(alias)) continue;
    if (alias.includes(key) || key.includes(alias)) partial.push(...items);
  }
  const partly = pick(unique(partial));
  if (partly) return partly;
  const sample = [...new Set(days.map((d) => d.label))].sort(pyLess).slice(0, 8).join(', ');
  return { error: `No workout day matched '${rawKey}'. Try one of: ${sample}` };
}

/**
 * The person's words for days, from the Session names screen ({token: word}), checked as the old
 * app's /shortcut/mapping did: only days in the plan, empty boxes dropped, each word used once.
 * Returns {text} (to save as user_texts "shortcut_keys") or {error}.
 */
export function nicknamesText(planText, words) {
  const allowed = new Set(planDays(planText).map((d) => d.token));
  const mapping = {};
  const seen = new Map();
  for (const [token, raw] of Object.entries(words || {})) {
    const tok = String(token ?? '').trim();
    if (!tok || !allowed.has(tok)) continue;
    const val = String(raw ?? '').trim().slice(0, 120);
    const norm = normalizeKey(val);
    if (!val || !norm) continue;
    const prev = seen.get(norm);
    if (prev && prev !== tok) return { error: 'Each name can only be used for one session.' };
    seen.set(norm, tok);
    mapping[tok] = val;
  }
  return { text: JSON.stringify(mapping) };
}
