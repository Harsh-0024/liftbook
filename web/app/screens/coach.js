// The AI coach: ask about your training and get answers from your own history. It runs as a
// Supabase Edge Function (supabase/functions/coach) with the person's own Gemini or Groq key,
// so it needs a connection; the keys are managed here too. Offline, the built-in answers
// (web/core/history_qa.js) still answer the questions they know. The chat stays while the app is open.

import { h, toast, busy, ago, formatDay, ask } from '../ui.js';
import { Online, KEY_LINKS } from '../online.js';
import { coachData, suggestions } from '../../core/coach_tools.js';
import { rulesReply } from '../../core/history_qa.js';

const chat = { messages: [] }; // [{role: user|assistant, text, steps?, links?, answer_id?, model?, rating?, error?}]

const PROVIDERS = { gemini: 'Gemini', groq: 'Groq' };

/** The coach's answer as text with **bold**, "- " bullets and dates linked to that day's workout. */
export function formatAnswer(text, hasWorkout = () => true) {
  const inline = (line) => {
    const out = [];
    for (const part of line.split(/(\*\*[^*]+\*\*)/g)) {
      if (!part) continue;
      if (/^\*\*[^*]+\*\*$/.test(part)) {
        out.push(h('strong', {}, ...dated(part.slice(2, -2))));
      } else {
        out.push(...dated(part));
      }
    }
    return out;
  };
  const dated = (s) => s.split(/(\b20\d{2}-\d{2}-\d{2}\b)/g).filter(Boolean)
    .map((p) => (/^20\d{2}-\d{2}-\d{2}$/.test(p) && hasWorkout(p) ? h('a', { href: `#/workout/${p}` }, p) : p));

  const blocks = [];
  let list = null;
  for (const raw of String(text || '').split('\n')) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    if (bullet) {
      list ??= h('ul', {});
      list.append(h('li', {}, ...inline(bullet[1])));
      continue;
    }
    if (list) {
      blocks.push(list);
      list = null;
    }
    if (line.trim()) blocks.push(h('p', {}, ...inline(line.replace(/^#+\s*/, ''))));
  }
  if (list) blocks.push(list);
  return h('div', { class: 'answer' }, blocks);
}

export function coachScreen(ctx) {
  const { lb } = ctx;
  const online = new Online(ctx.client);
  const page = h('div', {});
  const keysCard = h('div', {});
  const thread = h('div', { class: 'chat', 'aria-live': 'polite' });
  const starters = h('div', { class: 'tabs starters' });
  const input = h('textarea', {
    class: 'chat-input', rows: 2, maxlength: 1500, placeholder: 'Ask about your training…', 'aria-label': 'Your question',
  });
  const ask = h('button', { class: 'btn primary', type: 'button' }, 'Ask');
  const fresh = h('button', { class: 'btn small', type: 'button', onclick: () => {
    chat.messages = [];
    paintThread();
  } }, 'New chat');
  const askArea = h('div', { class: 'card ask' }, input, h('div', { class: 'row spread', style: 'margin-top:10px' },
    h('span', { class: 'subtle' }, 'Answers come from your synced workouts.'), ask));
  let keys = null;
  let showKeys = false;
  let working = false;

  const todayLocal = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };
  const days = new Set(lb.workouts().map((w) => w.day));
  const builtIn = (question, note) => rulesReply({
    history: lb.history(), settings: lb.exerciseSettings(), ownRepRanges: lb.text('rep_ranges'), today: todayLocal(),
  }, question, { page: 'coach' }, note);

  function paintStarters() {
    if (chat.messages.length) {
      starters.replaceChildren();
      return;
    }
    const list = suggestions(coachData({
      history: lb.history(), settings: lb.exerciseSettings(), planText: lb.planText(), repRangesText: lb.repRangesText(), today: todayLocal(),
    }));
    starters.replaceChildren(...list.map((q) => h('button', { type: 'button', onclick: () => send(q) }, q)));
  }

  function bubble(m) {
    if (m.role === 'user') return h('div', { class: 'msg me' }, m.text);
    const body = [];
    if (m.pending) {
      body.push(h('div', { class: 'subtle' }, 'Thinking…'));
    }
    if (m.steps?.length) {
      body.push(h('ul', { class: 'steps' }, m.steps.map((s) => h('li', { class: s.ok ? '' : 'error' },
        `${s.label}${Object.values(s.args || {}).length ? ` · ${Object.values(s.args).join(', ')}` : ''}`))));
    }
    if (m.error) body.push(h('p', { class: 'error' }, m.error));
    if (m.note) body.push(h('p', { class: 'subtle' }, m.note));
    if (m.text) body.push(formatAnswer(m.text, (d) => days.has(d)));
    if (m.answer_id) {
      const rate = (value) => async () => {
        const next = m.rating === value ? 0 : value;
        try {
          await online.rate(m.answer_id, next);
          m.rating = next || null;
          paintThread();
          if (next) toast('Thanks, that helps improve the coach.');
        } catch (err) {
          toast(err.message, 5000);
        }
      };
      body.push(h('div', { class: 'row spread msg-foot' },
        h('span', { class: 'subtle' }, m.model || (m.source === 'rules' ? 'Built-in answer' : '')),
        h('div', { class: 'row' },
          h('button', { class: `btn small${m.rating === 1 ? ' on' : ''}`, type: 'button', 'aria-label': 'Helpful', 'aria-pressed': String(m.rating === 1), onclick: rate(1) }, '👍'),
          h('button', { class: `btn small${m.rating === -1 ? ' on' : ''}`, type: 'button', 'aria-label': 'Not helpful', 'aria-pressed': String(m.rating === -1), onclick: rate(-1) }, '👎'))));
    }
    return h('div', { class: 'msg coach card' }, body);
  }

  function paintThread() {
    thread.replaceChildren(...chat.messages.map(bubble));
    fresh.hidden = !chat.messages.length || working;
    paintStarters();
  }

  async function send(question) {
    const q = String(question || '').trim();
    if (!q || working) return;
    if (!navigator.onLine) {
      const local = builtIn(q, 'You’re offline, so this is the built-in answer.');
      if (!local.ok) {
        toast('The coach needs a connection for that. Try again when you’re online.', 4000);
        return;
      }
      input.value = '';
      chat.messages.push({ role: 'user', text: q }, { role: 'assistant', text: local.answer, note: local.note, source: 'rules' });
      paintThread();
      thread.lastElementChild?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      return;
    }
    working = true;
    ask.disabled = true;
    input.value = '';
    const history = chat.messages.filter((m) => m.text && !m.error).map((m) => ({ role: m.role, text: m.text }));
    chat.messages.push({ role: 'user', text: q });
    const reply = { role: 'assistant', pending: true, steps: [] };
    chat.messages.push(reply);
    paintThread();
    reply.el = thread.lastElementChild;
    reply.el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    try {
      const r = await online.ask([...history, { role: 'user', text: q }], {
        context: { page: 'coach' },
        onStep: (s) => {
          reply.steps.push(s);
          paintThread();
        },
      });
      if (r.ok) {
        Object.assign(reply, { text: r.answer, steps: r.steps || reply.steps, answer_id: r.answer_id, model: r.model, note: r.note, source: r.source });
      }
      else reply.error = r.error || 'The coach couldn’t answer.';
      if (r.no_key) {
        keys = [];
        paintKeys();
      }
      // The coach marks keys used (or refused): show that in the key list.
      if (!r.no_key) loadKeys();
    } catch (err) {
      // Lost the connection on the way: answer here if the built-in answers know this one.
      const local = err.offline ? builtIn(q, 'No connection, so this is the built-in answer.') : null;
      if (local?.ok) Object.assign(reply, { text: local.answer, note: local.note, source: 'rules' });
      else reply.error = err.message || 'The coach couldn’t answer.';
    } finally {
      reply.pending = false;
      working = false;
      ask.disabled = false;
      paintThread();
      thread.lastElementChild?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  ask.addEventListener('click', () => send(input.value));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(input.value);
  });

  /* ---------------- keys ---------------- */

  function keyForm({ first }) {
    const label = h('input', { id: 'key_label', type: 'text', maxlength: 100, placeholder: 'e.g. My Gemini key', autocomplete: 'off' });
    const key = h('input', {
      id: 'key_value', type: 'password', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', placeholder: 'AIza… or gsk_…',
    });
    const save = h('button', { class: 'btn primary', type: 'button' }, 'Save key');
    save.addEventListener('click', busy(save, async () => {
      await online.addKey(label.value, key.value);
      key.value = '';
      label.value = '';
      toast('Key saved. Ask away.');
      showKeys = !first && showKeys;
      await loadKeys();
    }));
    return h('div', { class: 'stack' },
      h('div', { class: 'field' }, h('label', { for: 'key_value' }, 'Your key'), key,
        h('div', { class: 'hint' }, 'It is kept on Liftbook’s server and only used for your questions. Nobody can read it back, not even you.')),
      h('div', { class: 'field' }, h('label', { for: 'key_label' }, 'Name (optional)'), label),
      save);
  }

  function keyRow(k) {
    const toggle = h('button', { class: 'btn small', type: 'button' }, k.is_active ? 'Turn off' : 'Turn on');
    toggle.addEventListener('click', busy(toggle, async () => {
      await online.setKey(k.id, { is_active: !k.is_active });
      await loadKeys();
    }));
    const del = h('button', { class: 'btn small danger', type: 'button' }, 'Delete');
    del.addEventListener('click', busy(del, async () => {
      if (!(await ask('The coach stops using it. You can add it again any time.', { title: `Delete the ${PROVIDERS[k.provider] || ''} key ending ${k.key_hint}?`, yes: 'Delete', danger: true }))) return;
      await online.deleteKey(k.id);
      toast('Key deleted.');
      await loadKeys();
    }));
    return h('li', {}, h('div', { class: 'item key-row' },
      h('div', {},
        h('div', { style: 'font-weight:600' }, k.label || `${PROVIDERS[k.provider] || 'AI'} key`),
        h('div', { class: 'meta' }, `${PROVIDERS[k.provider] || ''} · ends ${k.key_hint} · ${k.is_active ? (k.last_used_at ? `used ${ago(k.last_used_at)}` : 'not used yet') : 'off'}`)),
      h('div', { class: 'row' }, toggle, del)));
  }

  const howTo = () => h('p', { class: 'subtle' },
    'Get a free key from ', h('a', { href: KEY_LINKS.gemini, target: '_blank', rel: 'noopener' }, 'Google AI Studio'),
    ' (Gemini) or ', h('a', { href: KEY_LINKS.groq, target: '_blank', rel: 'noopener' }, 'Groq'),
    ', copy it, and paste it here. Add both and the coach uses whichever is free.');

  function paintKeys() {
    if (keys === null) {
      keysCard.replaceChildren(h('div', { class: 'card subtle' }, navigator.onLine ? 'Loading your keys…' : 'You’re offline. The coach needs a connection.'));
      askArea.hidden = true;
      return;
    }
    const active = keys.filter((k) => k.is_active);
    askArea.hidden = !active.length;
    if (!active.length) {
      keysCard.replaceChildren(h('div', { class: 'card gold' },
        h('h2', {}, keys.length ? 'Turn a key on' : 'Add your AI key'),
        h('p', { class: 'muted' }, 'The coach answers with your own Gemini or Groq key, so it costs Liftbook nothing and your questions stay yours.'),
        howTo(),
        keys.length ? h('ul', { class: 'list' }, keys.map(keyRow)) : null,
        keyForm({ first: true })));
      return;
    }
    if (!showKeys) {
      keysCard.replaceChildren();
      return;
    }
    keysCard.replaceChildren(h('div', { class: 'card' },
      h('div', { class: 'row spread' }, h('h2', { style: 'margin:0' }, 'AI keys'),
        h('button', { class: 'btn small', type: 'button', onclick: () => {
          showKeys = false;
          paintKeys();
        } }, 'Done')),
      h('ul', { class: 'list' }, keys.map(keyRow)),
      h('details', {}, h('summary', { class: 'linkish' }, 'Add another key'), howTo(), keyForm({ first: false }))));
  }

  async function loadKeys() {
    try {
      keys = (await online.keys()) || [];
    } catch (err) {
      keys = null;
      keysCard.replaceChildren(h('div', { class: 'card' }, h('p', { class: 'error' }, err.offline
        ? 'You’re offline. The coach needs a connection.' : err.message)));
      askArea.hidden = true;
      return;
    }
    paintKeys();
  }

  /* ---------------- earlier answers ---------------- */

  const past = h('details', { class: 'card past' }, h('summary', {}, 'Earlier answers'));
  past.addEventListener('toggle', async () => {
    if (!past.open || past.dataset.loaded) return;
    past.dataset.loaded = '1';
    const body = h('div', { class: 'subtle' }, 'Loading…');
    past.append(body);
    try {
      const rows = await online.recentAnswers();
      body.replaceWith(rows.length ? h('ul', { class: 'list' }, rows.map((r) => h('li', {},
        h('details', {}, h('summary', { class: 'item' }, h('span', {}, r.question), h('span', { class: 'meta' }, formatDay(r.created_at, { weekday: false }))),
          formatAnswer(r.answer, (d) => days.has(d)))))) : h('p', { class: 'subtle' }, 'No answers yet.'));
    } catch (err) {
      body.replaceWith(h('p', { class: 'error' }, err.message));
      delete past.dataset.loaded;
    }
  });

  const keysButton = h('button', { class: 'btn small', type: 'button', onclick: () => {
    showKeys = !showKeys;
    paintKeys();
  } }, 'AI keys');

  page.append(
    h('div', { class: 'page-head' }, h('h1', {}, 'AI coach'), h('div', { class: 'row' }, fresh, keysButton)),
    keysCard, thread, starters, askArea, past,
  );
  paintThread();
  paintKeys();
  loadKeys();
  return page;
}
