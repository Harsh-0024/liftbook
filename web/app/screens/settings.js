// Settings: profile, plan and rep ranges, exercises (timed, bodyweight, renames), feedback,
// sync and the account.

import { h, icon, rowItem, pageHead, toast, busy, ago, formatDay, fmtNum, copyText, ask } from '../ui.js';
import { avatar } from './home.js';
import { Online } from '../online.js';
import { FEEDBACK_KINDS } from '../data.js';
import { defaultRepRangesText } from '../../core/plans.js';
import { DEFAULT_PLAN } from '../../core/plans.js';
import { deviceDay } from '../../core/dates.js';
import { planDays, customKeys, nicknamesText } from '../../core/sessions.js';
import { isNative, pickPhoto, saveFile, linkBackUrl } from '../native.js';

const SECTIONS = [
  ['profile', 'Profile', 'Name, username, bodyweight, photo'],
  ['plan', 'Workout plan', 'Your cycles, sessions and exercises, written as plain text, and the rep ranges for each.'],
  ['exercises', 'Exercises', 'Timed, bodyweight, renames'],
  ['shortcuts', 'Apple Shortcuts', 'Log and get workouts from Notes on your iPhone'],
  ['feedback', 'Feedback', 'Tell the developer what works for you, what doesn’t, and what you’d like next.'],
  ['sync', 'Sync and data', 'Devices, backup file'],
  ['account', 'Account', 'Password, theme, sign out, delete'],
];

// Pages inside a section: [key, title, back to]. The admin page shows only to admins.
const SUBPAGES = [['session-names', 'Session names', 'shortcuts'], ['admin', 'Admin', '']];

export function settingsScreen(ctx, section) {
  const sub = SUBPAGES.find(([k]) => k === section);
  if (sub) {
    const [key, title, back] = sub;
    return h('div', {},
      pageHead(title, '', { back: back ? `#/settings/${back}` : '#/settings' }),
      { 'session-names': sessionNames, admin }[key](ctx));
  }
  const found = SECTIONS.find(([k]) => k === section);
  if (!found) return index(ctx);
  const [key, title] = found;
  const body = { profile, plan, exercises, shortcuts, feedback, sync, account }[key](ctx);
  return h('div', {}, pageHead(title, found[2], { back: '#/settings' }), body);
}

/** The theme picked here (auto follows the device), kept on this device. */
export function themeChoice() {
  try {
    return localStorage.getItem('liftbook-theme') || 'auto';
  } catch {
    return 'auto';
  }
}

export function setTheme(value) {
  try {
    if (value === 'auto') localStorage.removeItem('liftbook-theme');
    else localStorage.setItem('liftbook-theme', value);
  } catch {
    // only this visit
  }
  if (value === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = value;
}

function themeSeg() {
  const seg = h('div', { class: 'seg', role: 'radiogroup', 'aria-label': 'Appearance' });
  const paint = () => {
    const now = themeChoice();
    seg.replaceChildren(...[['dark', 'Dark', 'moon'], ['light', 'Light', 'sun'], ['auto', 'Auto', 'monitor']].map(([v, l, ic]) =>
      h('button', { type: 'button', role: 'radio', 'aria-checked': String(now === v), class: now === v ? 'on' : '', onclick: () => {
        setTheme(v);
        paint();
      } }, icon(ic), l)));
  };
  paint();
  return seg;
}

function bodyweightInput(ctx) {
  const { lb } = ctx;
  const bw = h('input', { id: 'bw-inline', type: 'number', step: '0.1', min: '1', max: '500', inputmode: 'decimal',
    value: lb.profile()?.bodyweight ?? '', placeholder: '—', 'aria-label': 'Bodyweight in kg', class: 'inline-num' });
  bw.addEventListener('change', async () => {
    const v = bw.value.trim() === '' ? null : Number(bw.value);
    if (v !== null && !(v >= 1 && v <= 500)) {
      toast('Bodyweight should be between 1 and 500.');
      bw.value = lb.profile()?.bodyweight ?? '';
      return;
    }
    await lb.saveProfile({ bodyweight: v });
    toast(v === null ? 'Bodyweight cleared.' : `Bodyweight saved: ${fmtNum(v)} kg.`);
  });
  return h('span', { class: 'value inline-unit' }, bw, h('small', {}, 'kg'));
}

function index(ctx) {
  const p = ctx.lb.profile() || {};
  const st = ctx.sync.status();
  return h('div', {},
    pageHead('Settings', '', { back: '#/' }),
    h('a', { class: 'group rowi profile-row', href: '#/settings/profile' },
      avatar(ctx, 'small'),
      h('span', { class: 'main' }, h('span', { class: 'title' }, p.full_name || p.username || 'Your profile'),
        h('span', { class: 'desc' }, p.username ? `@${p.username}` : ''), h('span', { class: 'desc' }, ctx.user.email)),
      h('span', { class: 'value', style: 'color:var(--gold-text);font-weight:600' }, 'Edit'), h('span', { class: 'chev-i' }, icon('chev'))),

    h('section', { class: 'section' }, h('div', { class: 'label' }, 'Preferences'),
      h('div', { class: 'group' },
        h('div', { class: 'rowi' }, h('span', { class: 'ico' }, icon('scale')),
          h('label', { class: 'main', for: 'bw-inline', style: 'margin:0;color:inherit' }, h('span', { class: 'title' }, 'Bodyweight'), h('span', { class: 'desc' }, 'Used for bodyweight exercises')),
          bodyweightInput(ctx)),
        h('div', { class: 'blk' },
          h('div', { class: 'row', style: 'gap:14px;margin-bottom:12px' }, h('span', { class: 'ico', style: 'color:var(--gold-text)' }, icon('moon')), h('b', { style: 'font-size:.95rem' }, 'Appearance')),
          themeSeg()))),

    h('section', { class: 'section' }, h('div', { class: 'label' }, 'Training'),
      h('div', { class: 'group' },
        rowItem({ href: '#/settings/plan', ico: 'plan', title: 'Workout plan and rep ranges', desc: 'Your days, the exercises in them, target reps' }),
        rowItem({ href: '#/settings/exercises', ico: 'dumbbell', title: 'Exercises', desc: 'Timed, bodyweight, renames' }),
        rowItem({ href: '#/coach', ico: 'coach', title: 'AI coach', desc: 'Ask about your training' }))),

    h('section', { class: 'section' }, h('div', { class: 'label' }, 'Data and connections'),
      h('div', { class: 'group' },
        rowItem({ href: '#/settings/sync', ico: 'sync', title: 'Sync and data', desc: 'Devices, backup file, export',
          value: st.pending ? `${st.pending} to sync` : st.last_sync ? `Synced ${ago(st.last_sync)}` : '' }),
        rowItem({ href: '#/settings/shortcuts', ico: 'phone', title: 'Apple Shortcuts', desc: 'Log and get workouts from Notes on your iPhone' }))),

    h('section', { class: 'section' }, h('div', { class: 'label' }, 'Account'),
      h('div', { class: 'group' },
        rowItem({ href: '#/settings/account', ico: 'lock', title: 'Account', desc: 'Email, password, sign out, delete' }),
        ctx.lb.isAdmin() ? rowItem({ href: '#/settings/admin', ico: 'shield', title: 'Admin', desc: 'Feedback, people, coach answers' }) : null)),

    h('section', { class: 'section' }, h('div', { class: 'label' }, 'Help make it better'),
      h('div', { class: 'group' }, rowItem({ href: '#/settings/feedback', ico: 'chat', title: 'Send feedback', desc: 'What you like, what you don’t, ideas' }))),

    h('div', { class: 'group', style: 'margin-top:30px' },
      rowItem({ onclick: (e) => busy(e.currentTarget, () => ctx.signOut())(e), ico: 'logout', title: 'Sign out of this device', chev: false })));
}

function field(label, input, hint) {
  return h('div', { class: 'field' }, h('label', { for: input.id }, label), input, hint ? h('div', { class: 'hint' }, hint) : null);
}

/* ---------------- profile ---------------- */

function profile(ctx) {
  const { lb } = ctx;
  const p = lb.profile() || {};
  const name = h('input', { id: 'full_name', type: 'text', value: p.full_name || '', maxlength: 100 });
  const username = h('input', { id: 'username', type: 'text', value: p.username || '', maxlength: 50, autocapitalize: 'off' });
  const bw = h('input', { id: 'bodyweight', type: 'number', step: '0.1', min: '1', max: '500', inputmode: 'decimal', value: p.bodyweight ?? '' });
  const avatar = h('div', { class: 'avatar' }, (p.full_name || p.username || '?').slice(0, 1).toUpperCase());
  lb.avatarUrl().then((url) => {
    if (url) avatar.replaceWith(h('img', { class: 'avatar', src: url, alt: 'Profile photo' }));
  });
  const file = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', hidden: true });
  const photoBtn = h('button', { class: 'btn small', type: 'button' }, 'Change photo');
  const upload = async (photo) => {
    if (!photo) return;
    await lb.uploadAvatar(photo);
    toast('Photo saved.');
    ctx.refresh();
  };
  // In the Android app: the camera or the gallery.
  if (isNative) photoBtn.addEventListener('click', busy(photoBtn, async () => upload(await pickPhoto())));
  else photoBtn.addEventListener('click', () => file.click());
  file.addEventListener('change', busy(photoBtn, () => upload(file.files[0])));

  const save = h('button', { class: 'btn primary', type: 'button' }, 'Save');
  save.addEventListener('click', busy(save, async () => {
    const u = username.value.trim();
    if (!/^[A-Za-z0-9_.-]{3,50}$/.test(u)) throw new Error('Choose a username of 3 or more letters, numbers, dots, dashes or underscores.');
    if (u.toLowerCase() !== String(p.username || '').toLowerCase()) {
      let free;
      try {
        free = await lb.usernameAvailable(u);
      } catch {
        throw new Error('Connect to the internet to change your username (it has to be checked).');
      }
      if (!free) throw new Error('That username is taken.');
    }
    const weight = bw.value.trim() === '' ? null : Number(bw.value);
    if (weight !== null && !(weight >= 1 && weight <= 500)) throw new Error('Bodyweight should be between 1 and 500.');
    await lb.saveProfile({ full_name: name.value.trim(), username: u, bodyweight: weight });
    toast('Profile saved.');
  }));
  return h('div', {},
    h('div', { class: 'group' },
      h('div', { class: 'rowi profile-photo' }, avatar,
        h('span', { class: 'main' }, h('span', { class: 'title' }, 'Photo'), h('span', { class: 'desc' }, 'Shown at the top of Settings')),
        photoBtn, file)),
    h('section', { class: 'section' }, h('div', { class: 'label' }, 'About you'),
      h('div', { class: 'group' }, h('div', { class: 'blk' },
        field('Name', name), field('Username', username), field('Bodyweight (kg)', bw, 'Used for bodyweight exercises like pull-ups and dips.')),
        h('div', { class: 'editor-bar static' }, h('span', { class: 'editor-meta' }, 'Kept on this device and synced'), save))));
}

/* ---------------- plan ---------------- */

function plan(ctx) {
  const { lb } = ctx;
  const s = lb.settings();
  const admin = lb.isAdmin();
  const shared = lb.sharedPlan();
  const followPlan = h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: Boolean(s.follow_shared_plan), 'aria-label': 'Follow the shared plan' });
  const followReps = h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: Boolean(s.follow_shared_exercises), 'aria-label': 'Follow the shared rep ranges' });
  followPlan.addEventListener('change', async () => {
    await lb.setSetting('follow_shared_plan', followPlan.checked);
    toast(followPlan.checked ? 'Following the shared plan.' : 'Using your own plan.');
  });
  followReps.addEventListener('change', async () => {
    await lb.setSetting('follow_shared_exercises', followReps.checked);
    toast(followReps.checked ? 'Following the shared rep ranges.' : 'Using your own rep ranges.');
  });

  const planText = h('textarea', { id: 'plan', class: 'editor mono', spellcheck: 'false', 'aria-label': 'Your plan', placeholder: DEFAULT_PLAN.trim() }, lb.text('plan'));
  const repText = h('textarea', { id: 'rep_ranges', class: 'editor mono', spellcheck: 'false', 'aria-label': 'Your rep ranges', placeholder: defaultRepRangesText().trim() }, lb.text('rep_ranges'));
  // Each editor says whether what's in it is saved, as the old plan page did.
  const editorGroup = (area, kind, label, done) => {
    const meta = h('span', { class: 'editor-meta' });
    const btn = h('button', { class: 'btn primary small', type: 'button' }, label);
    const mark = () => {
      const saved = area.value === lb.text(kind);
      meta.textContent = saved ? (area.value.trim() ? 'Saved' : 'Using the built-in one') : 'Not saved yet';
      btn.disabled = saved;
    };
    area.addEventListener('input', mark);
    btn.addEventListener('click', busy(btn, async () => {
      await lb.setText(kind, area.value);
      toast(done);
      mark();
    }));
    mark();
    return h('div', { class: 'group' }, area, h('div', { class: 'editor-bar' }, meta, btn));
  };
  const refresh = h('button', { class: 'btn small', type: 'button' }, 'Check for updates');
  refresh.addEventListener('click', busy(refresh, async () => {
    toast((await lb.refreshShared()) ? 'Shared plan is up to date.' : 'Couldn’t reach the server.');
  }));

  // As the old "Copy and edit": the shared plan and rep ranges become your own, and following stops.
  const copy = h('button', { class: 'btn small', type: 'button' }, 'Copy');
  copy.addEventListener('click', busy(copy, async () => {
    const nextPlan = (shared.plan || DEFAULT_PLAN).trim();
    const nextReps = (shared.rep_ranges || defaultRepRangesText()).trim();
    const mine = [lb.text('plan'), lb.text('rep_ranges')].some((t) => String(t || '').trim());
    if (mine && !(await ask('Your own plan and rep ranges are replaced by a copy of the shared ones.', { title: 'Replace your plan?', yes: 'Replace', danger: true }))) return;
    await lb.setText('plan', nextPlan);
    await lb.setText('rep_ranges', nextReps);
    await lb.setSetting('follow_shared_plan', false);
    await lb.setSetting('follow_shared_exercises', false);
    followPlan.checked = false;
    followReps.checked = false;
    for (const [area, text] of [[planText, nextPlan], [repText, nextReps]]) {
      area.value = text;
      area.dispatchEvent(new Event('input'));
    }
    toast('Copied. The plan is yours to edit now.');
  }));

  return h('div', {},
    admin ? h('div', { class: 'notice' }, icon('shield'), h('span', {}, 'You’re an admin: your plan and rep ranges are the shared ones others can follow.')) :
      h('section', { class: 'section' },
        h('div', { class: 'label' }, 'Shared plan'),
        h('div', { class: 'group' },
          h('label', { class: 'rowi' }, h('span', { class: 'ico' }, icon('person')),
            h('span', { class: 'main' }, h('span', { class: 'title' }, 'Follow the shared plan'), h('span', { class: 'desc' }, 'Retrieve uses it instead of yours')), followPlan),
          h('label', { class: 'rowi' }, h('span', { class: 'ico' }, icon('sliders')),
            h('span', { class: 'main' }, h('span', { class: 'title' }, 'Follow the shared rep ranges'), h('span', { class: 'desc' }, 'Targets come from the shared plan')), followReps),
          h('div', { class: 'rowi' }, h('span', { class: 'ico' }, icon('sync')),
            h('span', { class: 'main' }, h('span', { class: 'title' }, 'Shared plan'),
              h('span', { class: 'desc' }, shared.updated_at ? `Updated ${formatDay(shared.updated_at)}` : 'Not downloaded yet')), refresh),
          h('div', { class: 'rowi' }, h('span', { class: 'ico' }, icon('edit')),
            h('span', { class: 'main' }, h('span', { class: 'title' }, 'Copy and edit'), h('span', { class: 'desc' }, 'Make the shared plan and rep ranges your own to change')), copy))),
    h('section', { class: 'section' },
      h('div', { class: 'label' }, 'Plan'),
      editorGroup(planText, 'plan', 'Save plan', 'Plan saved.'),
      h('p', { class: 'foot' }, 'A day header ("Session 1 - Legs"), then one exercise per line, with targets like "Squat - [3, 5-8]". Leave it empty for the built-in plan.')),
    h('section', { class: 'section' },
      h('div', { class: 'label' }, 'Rep ranges'),
      editorGroup(repText, 'rep_ranges', 'Save rep ranges', 'Rep ranges saved.'),
      h('p', { class: 'foot' }, 'One exercise per line: "Squat: 3, 5-8" (sets, then reps) or "Plank: 30-60s". Leave it empty for the built-in ranges.')));
}

/* ---------------- exercises ---------------- */

function exercises(ctx) {
  const { lb } = ctx;
  const counts = new Map();
  for (const l of lb.history()) counts.set(l.exercise, (counts.get(l.exercise) || 0) + 1);
  const names = [...counts.keys()].sort((a, b) => a.localeCompare(b));
  const search = h('input', { id: 'ex-search', type: 'search', placeholder: 'Search your exercises', autocapitalize: 'off', 'aria-label': 'Search your exercises' });
  const group = h('div', { class: 'group pick-group' });
  const kind = (s) => [s.is_timed ? 'Timed' : null, s.is_bodyweight ? 'Bodyweight added' : null].filter(Boolean).join(' · ') || 'Weight and reps';
  // The switch shows what the app does now, built-in bodyweight exercises included.
  const state = (n) => ({ ...(lb.exerciseSetting(n) || {}), is_bodyweight: lb.bodyweightOn(n) });
  let open = null;

  // One row per exercise; tap it to set timed or bodyweight, or rename it, in place.
  const row = (n) => {
    const s = state(n);
    const desc = h('span', { class: 'desc' }, kind(s));
    const head = h('button', { class: `rowi${open === n ? ' open' : ''}`, type: 'button', 'aria-expanded': String(open === n) },
      h('span', { class: 'ico' }, icon('dumbbell')),
      h('span', { class: 'main' }, h('span', { class: 'title' }, n), desc),
      h('span', { class: 'value' }, `${counts.get(n)} logged`),
      h('span', { class: 'chev-i' }, icon('chev')));
    head.addEventListener('click', () => { open = open === n ? null : n; paint(); });
    if (open !== n) return [head];
    const sw = (key, label, hint, extra = {}) => {
      const input = h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: s[key] === true, 'aria-label': `${n}: ${label}` });
      input.addEventListener('change', async () => {
        await lb.setExerciseSetting(n, { [key]: input.checked, ...extra });
        s[key] = input.checked;
        desc.textContent = kind(s);
      });
      return h('label', { class: 'rowi sub' }, h('span', { class: 'main' }, h('span', { class: 'title' }, label), h('span', { class: 'desc' }, hint)), input);
    };
    const to = h('input', { type: 'text', value: n, maxlength: 100, 'aria-label': `New name for ${n}` });
    const info = h('div', { class: 'hint' }, 'Its history comes along.');
    const go = h('button', { class: 'btn small primary', type: 'button' }, 'Rename');
    to.addEventListener('input', () => {
      const pr = lb.renamePreview(n, to.value);
      info.textContent = pr.error || `Moves ${pr.logs} logged session${pr.logs === 1 ? '' : 's'}, and the name in your plan and rep ranges.`;
    });
    go.addEventListener('click', busy(go, async () => {
      const r = await lb.rename(n, to.value);
      toast(`Renamed. ${r.logs} session${r.logs === 1 ? '' : 's'} moved.`);
      ctx.refresh();
    }));
    return [head,
      sw('is_timed', 'Timed', 'Sets are seconds, not reps'),
      sw('is_bodyweight', 'Bodyweight', 'Your bodyweight is added to the weight', { bodyweight_source: 'manual' }),
      h('div', { class: 'blk sub' }, h('label', { class: 'sub-label' }, 'Rename'), h('div', { class: 'row rename-row' }, to, go), info)];
  };
  const paint = () => {
    const q = search.value.trim().toLowerCase();
    const shown = names.filter((n) => !q || n.toLowerCase().includes(q)).slice(0, 100);
    group.replaceChildren(...(shown.length ? shown.flatMap(row)
      : [h('div', { class: 'empty' }, icon('search'), names.length ? `Nothing matches “${search.value.trim()}”.` : 'Exercises show up here once you log them.')]));
  };
  search.addEventListener('input', paint);
  paint();

  const renames = lb.renames();
  return h('div', {},
    h('div', { class: 'search' }, icon('search'), search),
    h('section', { class: 'section' }, h('div', { class: 'label' }, 'Your exercises', h('span', {}, `${names.length} exercise${names.length === 1 ? '' : 's'}`)), group),
    renames.length ? h('section', { class: 'section' }, h('div', { class: 'label' }, 'Renamed'),
      h('div', { class: 'group' }, renames.map((r) => {
        const undo = h('button', { class: 'btn small', type: 'button' }, 'Undo');
        undo.addEventListener('click', busy(undo, async () => {
          if (!(await ask(`Its logged workouts move back to ${r.old_name}.`, { title: `Put ${r.new_name} back to ${r.old_name}?`, yes: 'Undo rename' }))) return;
          await lb.undoRename(r.id);
          toast('Rename undone.');
          ctx.refresh();
        }));
        return h('div', { class: 'rowi' }, h('span', { class: 'ico' }, icon('edit')),
          h('span', { class: 'main' }, h('span', { class: 'title' }, `${r.old_name} → ${r.new_name}`), h('span', { class: 'desc' }, 'Logs typed with the old name are saved under the new one')), undo);
      })),
      ) : null);
}

/* ---------------- feedback ---------------- */

function feedback(ctx) {
  const { lb } = ctx;
  const labels = { like: 'Something I like', dislike: 'Something I don’t like', improve: 'Could be better', idea: 'A feature idea' };
  const icons = { like: 'heart', dislike: 'thumbdown', improve: 'wrench', idea: 'bulb' };
  const prompts = { like: 'What do you like about it?', dislike: 'What gets in your way?', improve: 'What could work better, and how?', idea: 'What would you like the app to do?' };
  let kind = 'idea';
  const msg = h('textarea', { id: 'message', class: 'editor', maxlength: 2000, 'aria-label': 'Your feedback', style: 'min-height:140px;font-family:var(--font)' });
  const tiles = FEEDBACK_KINDS.map((k) => h('button', { type: 'button', class: 'kind', dataset: { kind: k }, 'aria-pressed': 'false',
    onclick: () => pick(k) }, icon(icons[k]), h('span', {}, labels[k])));
  const pick = (k) => {
    kind = k;
    for (const t of tiles) t.setAttribute('aria-pressed', String(t.dataset.kind === k));
    msg.placeholder = prompts[k];
  };
  pick(kind);
  const send = h('button', { class: 'btn primary small', type: 'button' }, icon('send'), 'Send');
  const mine = h('div', {}, h('p', { class: 'subtle', style: 'padding:16px 20px;margin:0' }, 'Loading what you sent…'));
  const load = async () => {
    try {
      const rows = await lb.myFeedback();
      mine.replaceChildren(rows.length ? h('div', { class: 'group' }, rows.map((r) => h('div', { class: 'rowi', style: 'align-items:flex-start' },
        h('span', { class: 'ico' }, icon(icons[r.kind] || 'chat')),
        h('span', { class: 'main' }, h('span', { class: 'title', style: 'font-weight:500;white-space:pre-wrap' }, r.message),
          h('span', { class: 'desc' }, `${labels[r.kind] || r.kind} · ${formatDay(r.created_at)}`)),
        h('span', { class: `pill ${r.status === 'done' ? 'improved' : r.status === 'seen' ? 'new' : ''}` }, r.status === 'new' ? 'sent' : r.status)))) :
        h('div', { class: 'group' }, h('p', { class: 'subtle', style: 'padding:16px 20px;margin:0' }, 'Nothing sent yet.')));
    } catch {
      mine.replaceChildren(h('div', { class: 'group' }, h('p', { class: 'subtle', style: 'padding:16px 20px;margin:0' }, 'Connect to the internet to see what you sent.')));
    }
  };
  send.addEventListener('click', busy(send, async () => {
    try {
      await lb.sendFeedback(kind, msg.value, location.hash);
    } catch (err) {
      if (err.status === 0) throw new Error('No connection. Feedback needs the internet; try again when online.');
      throw err;
    }
    msg.value = '';
    toast('Thank you. Sent.');
    load();
  }));
  load();
  return h('div', {},
    h('section', { class: 'section' },
      h('div', { class: 'label' }, 'What is it about?'),
      h('div', { class: 'kinds' }, tiles),
      h('div', { class: 'group' }, msg, h('div', { class: 'editor-bar' }, h('span', { class: 'editor-meta' }, 'Every note is read'), send)),
      h('p', { class: 'foot', style: 'margin-top:10px' }, 'Sent with your name and email, so the developer can follow up if needed.')),
    h('section', { class: 'section' }, h('div', { class: 'label' }, 'What you sent'), mine));
}

/* ---------------- admin ---------------- */

const FEEDBACK_LABELS = { like: 'Likes', dislike: 'Dislikes', improve: 'Improve', idea: 'Idea' };

function admin(ctx) {
  const { lb } = ctx;
  if (!lb.isAdmin()) return h('div', { class: 'card' }, h('p', { class: 'muted' }, 'Only admins can see this page.'));
  const tabs = [['feedback', 'Feedback'], ['people', 'People'], ['coach', 'Coach answers']];
  let tab = 'feedback';
  const bar = h('div', { class: 'tabs' });
  const box = h('div', {});
  const offline = (err) => h('div', { class: 'card' }, h('p', { class: 'error' }, err.status === 0 ? 'You’re offline. The admin pages need a connection.' : err.message));
  const when = (t) => (t ? `${formatDay(t)} (${ago(t)})` : 'never');

  async function feedbackTab() {
    const rows = await lb.adminFeedback();
    const counts = { new: 0, seen: 0, done: 0 };
    for (const r of rows) counts[r.status] = (counts[r.status] || 0) + 1;
    const item = (r) => {
      const status = h('select', { 'aria-label': 'Status' }, ['new', 'seen', 'done'].map((v) => h('option', { value: v, selected: v === r.status }, v)));
      status.addEventListener('change', async () => {
        try {
          await lb.setFeedbackStatus(r.id, status.value);
          r.status = status.value;
          toast(`Marked ${status.value}.`);
        } catch (err) {
          status.value = r.status;
          toast(err.message, 5000);
        }
      });
      return h('li', {}, h('div', { class: 'item', style: 'align-items:flex-start;gap:12px' },
        h('div', { style: 'min-width:0' }, h('div', { style: 'white-space:pre-wrap' }, r.message),
          h('div', { class: 'meta' }, `${FEEDBACK_LABELS[r.kind] || r.kind} · ${r.username || r.email} · ${formatDay(r.created_at)}${r.page ? ` · ${r.page}` : ''}`)),
        status));
    };
    const shown = h('div', { class: 'card' }, rows.length ? h('ul', { class: 'list' }, rows.map(item)) : h('p', { class: 'subtle' }, 'No feedback yet.'));
    // Shown once as new; from now on the sender sees it was read (as in the old app).
    for (const r of rows.filter((x) => x.status === 'new')) {
      lb.setFeedbackStatus(r.id, 'seen').catch(() => {});
    }
    return [h('p', { class: 'subtle' }, `${rows.length} in all · ${counts.new} new · ${counts.done} done`), shown];
  }

  async function peopleTab() {
    const rows = await lb.adminUsers();
    const active = rows.filter((r) => r.last_workout && (Date.now() - Date.parse(r.last_workout)) < 30 * 86400000).length;
    return [h('p', { class: 'subtle' }, `${rows.length} accounts · ${active} logged in the last 30 days`),
      h('div', { class: 'card' }, h('ul', { class: 'list' }, rows.map((r) => h('li', {}, h('div', { class: 'item', style: 'align-items:flex-start' },
        h('div', { style: 'min-width:0' },
          h('div', { style: 'font-weight:600' }, `${r.username || '(no username yet)'}${r.full_name ? ` · ${r.full_name}` : ''}${r.is_admin ? ' · admin' : ''}`),
          h('div', { class: 'meta' }, `${r.email || 'no email'}${r.confirmed ? '' : ' (not confirmed)'}`),
          h('div', { class: 'meta' }, `${r.workouts} workout${r.workouts === 1 ? '' : 's'} · last ${r.last_workout ? formatDay(r.last_workout) : 'never'} · joined ${formatDay(r.created_at)} · signed in ${when(r.last_sign_in_at)}`)))))))];
  }

  async function coachTab() {
    const { totals = {}, answers = [] } = await lb.adminCoach(100);
    return [h('p', { class: 'subtle' }, `${totals.answers || 0} answers · ${totals.helpful || 0} 👍 · ${totals.not_helpful || 0} 👎 · ${totals.built_in || 0} built-in`),
      h('div', { class: 'stack' }, answers.length ? answers.map((a) => h('details', { class: 'card' },
        h('summary', {}, h('span', { style: 'font-weight:600' }, a.question),
          h('div', { class: 'meta' }, `${a.username} · ${formatDay(a.created_at)} · ${a.source === 'rules' ? 'built-in' : a.model || 'ai'}${a.rating === 1 ? ' · 👍' : a.rating === -1 ? ' · 👎' : ''}${a.ms ? ` · ${(a.ms / 1000).toFixed(1)} s` : ''}`)),
        h('p', { style: 'white-space:pre-wrap' }, a.answer),
        a.comment ? h('p', { class: 'subtle' }, `Comment: ${a.comment}`) : null,
        a.failed ? h('p', { class: 'subtle' }, `Failed first: ${a.failed}`) : null)) : h('div', { class: 'card subtle' }, 'No answers yet.'))];
  }

  async function paint() {
    bar.replaceChildren(...tabs.map(([k, label]) => h('button', { type: 'button', class: k === tab ? 'on' : '', 'aria-pressed': String(k === tab), onclick: () => { tab = k; paint(); } }, label)));
    box.replaceChildren(h('div', { class: 'card subtle' }, 'Loading…'));
    try {
      box.replaceChildren(...await { feedback: feedbackTab, people: peopleTab, coach: coachTab }[tab]());
    } catch (err) {
      box.replaceChildren(offline(err));
    }
  }
  paint();
  return h('div', {}, bar, box);
}

/* ---------------- Apple Shortcuts ---------------- */

const SHORTCUT_FILES = [
  ['Log Workout', 'Pick one of your newest workout notes and log it'],
  ['Get Workout', 'Pick a session and save its targets as a note'],
];

function shortcuts(ctx) {
  const online = new Online(ctx.client);
  const box = h('div', {}, h('div', { class: 'card subtle' }, 'Loading…'));

  const copyRow = (value, label) => h('div', { class: 'row', style: 'flex-wrap:nowrap' },
    h('input', { type: 'text', value, readonly: true, 'aria-label': label, onclick: (e) => e.target.select() }),
    h('button', { class: 'btn small', type: 'button', onclick: () => copyText(value) }, 'Copy'));

  async function paint() {
    let info;
    try {
      info = await online.shortcutKey();
    } catch (err) {
      box.replaceChildren(h('div', { class: 'card' }, h('p', { class: 'error' }, err.offline ? 'You’re offline. Setting up Shortcuts needs a connection.' : err.message)));
      return;
    }
    // The key itself is only known on the device that made it (the server keeps a hash).
    const kept = ctx.store.getMeta('shortcut_key');
    const key = info && kept && kept.endsWith(info.key_hint) ? kept : null;
    const make = h('button', { class: `btn${info ? '' : ' primary'}`, type: 'button' }, info ? 'Make a new key' : 'Make my Shortcut key');
    make.addEventListener('click', busy(make, async () => {
      if (info && !(await ask('Your Shortcuts stop working until you paste the new key into them.', { title: 'Make a new key?', yes: 'Make a new key', danger: true }))) return;
      const fresh = await online.newShortcutKey();
      await ctx.store.setMeta('shortcut_key', fresh);
      toast('New key made. Copy it into your Shortcuts.');
      await paint();
    }));
    const remove = h('button', { class: 'btn small danger', type: 'button' }, 'Switch Shortcuts off');
    remove.addEventListener('click', busy(remove, async () => {
      if (!(await ask('Your Shortcuts stop working until you make a new key.', { title: 'Switch Shortcuts off?', yes: 'Switch off', danger: true }))) return;
      await online.removeShortcutKey();
      await ctx.store.setMeta('shortcut_key', null);
      await paint();
    }));
    const urls = online.shortcutUrls(key || '<your key>');
    box.replaceChildren(
      h('div', { class: 'card' },
        h('h2', {}, '1. Your Shortcut key'),
        h('p', { class: 'subtle' }, 'Each shortcut asks for it once, when you add it. Keep it private: it can log workouts to your account.'),
        info ? h('div', { class: 'stack' },
          key ? copyRow(key, 'Shortcut key') : h('p', {}, `Your key ends in ${info.key_hint}. It was made on another device or before this one signed in, so it can’t be shown here; make a new key if you need it again.`),
          h('p', { class: 'subtle' }, `Made ${ago(info.created_at)} · ${info.last_used_at ? `last used ${ago(info.last_used_at)}` : 'not used yet'}`),
          h('div', { class: 'row' }, make, remove)) : make),
      h('div', { class: 'card' },
        h('h2', {}, '2. Add the shortcuts'),
        h('p', { class: 'subtle' }, 'Open this page on your iPhone, tap a shortcut to add it, and paste your key when asked.'),
        h('ul', { class: 'list' }, SHORTCUT_FILES.map(([name, sub]) => h('li', {},
          h('a', { class: 'item chev', href: `shortcuts/${encodeURIComponent(name)}.shortcut`, download: `${name}.shortcut` },
            h('div', {}, h('div', { style: 'font-weight:600' }, name), h('div', { class: 'meta' }, sub))))))),
      h('div', { class: 'card' }, h('ul', { class: 'list' }, h('li', {},
        h('a', { class: 'item chev', href: '#/settings/session-names' },
          h('div', {}, h('div', { style: 'font-weight:600' }, 'Session names'),
            h('div', { class: 'meta' }, 'Your own words for sessions, like “push”, to pick them quickly in Get Workout')))))),
      h('div', { class: 'card' },
        h('h2', {}, '3. Keep your workouts in the Workout Logs folder'),
        h('p', { class: 'subtle' }, 'The shortcuts use one folder in Apple Notes called Workout Logs, and make it the first time. Get Workout saves every workout there, and Log Workout only offers notes from there.')),
      h('details', { class: 'card' },
        h('summary', { class: 'linkish' }, 'Links for your own shortcut'),
        h('p', { class: 'subtle' }, 'Log: POST the note as workout_text. Get: add ?key= and a session name, or ?list=1 for the sessions.'),
        h('div', { class: 'field' }, h('label', {}, 'Log URL'), copyRow(urls.log, 'Log URL')),
        h('div', { class: 'field' }, h('label', {}, 'Get URL'), copyRow(urls.pick, 'Get URL'))),
    );
  }
  paint();
  return box;
}

/* ---------------- session names (Get Workout) ---------------- */

function sessionNames(ctx) {
  const { lb } = ctx;
  const planText = lb.planText();
  const days = planDays(planText).sort((a, b) => (a.category.toLowerCase() < b.category.toLowerCase() ? -1
    : a.category.toLowerCase() > b.category.toLowerCase() ? 1 : a.day_id - b.day_id));
  if (!days.length) {
    return h('div', { class: 'card' }, h('p', { class: 'muted' }, 'Your plan has no sessions yet.'),
      h('a', { class: 'btn', href: '#/settings/plan' }, 'Open your plan'));
  }
  const saved = customKeys(lb.text('shortcut_keys'));
  const inputs = days.map((d, i) => h('input', {
    id: `day-key-${i}`, type: 'text', maxlength: 120, value: saved[d.token] || '', placeholder: 'e.g. push',
    autocomplete: 'off', autocapitalize: 'off', 'data-token': d.token,
  }));
  const save = h('button', { class: 'btn primary', type: 'button' }, 'Save names');
  save.addEventListener('click', busy(save, async () => {
    const r = nicknamesText(planText, Object.fromEntries(inputs.map((el) => [el.dataset.token, el.value])));
    if (r.error) throw new Error(r.error);
    await lb.setText('shortcut_keys', r.text);
    toast('Session names saved.');
  }));
  return h('div', { class: 'card' },
    h('p', { class: 'subtle' }, 'Give a session your own word, like “push” or “legs”, and say or type it in Get Workout.'),
    days.map((d, i) => field(d.label, inputs[i], d.label.toLowerCase().startsWith(`${d.category} ${d.day_id}`.toLowerCase()) ? null : `${d.category} ${d.day_id}`)),
    h('p', { class: 'subtle' }, 'Leave a box empty to use the session’s own name. Capitals and punctuation don’t matter.'),
    save);
}

/* ---------------- sync and data ---------------- */

function sync(ctx) {
  const { lb, store } = ctx;
  const status = h('div', {});
  const paint = (st) => {
    status.replaceChildren(
      h('p', {}, st.running ? 'Syncing now…' : st.error === 'offline' ? 'Offline. Changes are kept on this device.' : st.error ? `Problem: ${st.error}` : 'Up to date.'),
      h('p', { class: 'subtle' }, `Last synced ${ago(st.last_sync)} · ${st.pending} change${st.pending === 1 ? '' : 's'} waiting to upload`));
  };
  paint(ctx.sync.status());
  const off = ctx.sync.onStatus((st) => (status.isConnected ? paint(st) : off()));
  const now = h('button', { class: 'btn primary', type: 'button' }, 'Sync now');
  now.addEventListener('click', busy(now, () => ctx.sync.runOnce()));
  const backup = () => {
    const blob = new Blob([JSON.stringify({ app: 'liftbook', exported_at: new Date().toISOString(), ...store.snapshot() }, null, 1)], { type: 'application/json' });
    saveFile(`liftbook-${lb.profile()?.username || 'backup'}-${deviceDay()}.json`, blob).catch((err) => toast(err.message || String(err)));
  };
  const from = h('input', { id: 'csv-from', type: 'date' });
  const to = h('input', { id: 'csv-to', type: 'date' });
  const spreadsheet = () => {
    if (from.value && to.value && from.value > to.value) return toast('The start date is after the end date.');
    const { count, text } = lb.csv({ from: from.value, to: to.value });
    if (!count) return toast('No workouts in those dates.');
    const range = from.value || to.value ? `${(from.value || 'start').replaceAll('-', '')}_${(to.value || 'today').replaceAll('-', '')}` : deviceDay().replaceAll('-', '');
    saveFile(`workout_history_${lb.profile()?.username || 'liftbook'}_${range}.csv`, new Blob([text], { type: 'text/csv' })).catch((err) => toast(err.message || String(err)));
  };
  const counts = lb.overview();
  return h('div', {},
    h('div', { class: 'card' }, h('h2', {}, 'Sync'), status, now,
      h('p', { class: 'subtle', style: 'margin-top:12px' }, 'Everything is kept on this device and works offline. Changes go to your account when you’re online, and your other devices pick them up when they open or come back online.')),
    h('div', { class: 'card' }, h('h2', {}, 'Your data'),
      h('p', {}, `${counts.total} workouts, ${lb.history().length} exercise logs, ${counts.exercises} exercises.`),
      h('button', { class: 'btn', type: 'button', onclick: backup }, 'Download a backup file')),
    h('div', { class: 'card' }, h('h2', {}, 'Spreadsheet'),
      h('p', { class: 'subtle' }, 'Every exercise you logged, one row each, for Excel, Numbers or Google Sheets. Leave the dates empty for all of it.'),
      h('div', { class: 'row' }, field('From', from), field('To', to)),
      h('button', { class: 'btn', type: 'button', onclick: spreadsheet }, 'Download a CSV file')),
    h('section', { class: 'section' }, h('div', { class: 'label' }, 'Clean up'),
      h('div', { class: 'group' },
        rowItem({ href: '#/settings/exercises', ico: 'edit', title: 'Rename an exercise', desc: 'Its history comes along' }),
        rowItem({ href: '#/history?select', ico: 'trash', title: 'Delete several workouts', desc: 'Opens your history so you can pick them' }))));
}

/* ---------------- account ---------------- */

function account(ctx) {
  const email = h('input', { id: 'new-email', type: 'email', autocomplete: 'email', autocapitalize: 'off', placeholder: 'new@example.com' });
  const moveEmail = h('button', { class: 'btn', type: 'button' }, 'Change email');
  moveEmail.addEventListener('click', busy(moveEmail, async () => {
    const next = email.value.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(next)) throw new Error('Type the new email address.');
    if (next === String(ctx.user.email || '').toLowerCase()) throw new Error('That’s already your email.');
    try {
      await ctx.client.auth.updateEmail(next, linkBackUrl());
    } catch (err) {
      if (err.status === 0) throw new Error('Changing your email needs the internet.');
      throw err;
    }
    email.value = '';
    toast('Check your inbox: open the link we sent to finish the change.', 7000);
  }));
  const pw = h('input', { id: 'new-password', type: 'password', autocomplete: 'new-password' });
  const change = h('button', { class: 'btn', type: 'button' }, 'Change password');
  change.addEventListener('click', busy(change, async () => {
    if (pw.value.length < 8) throw new Error('Use at least 8 characters.');
    await ctx.client.auth.updatePassword(pw.value);
    pw.value = '';
    toast('Password changed.');
  }));

  const out = h('button', { class: 'btn', type: 'button' }, 'Sign out of this device');
  out.addEventListener('click', busy(out, () => ctx.signOut()));
  // Delete: on the page, as the old app had it (no pop-up): what goes, a pointer to keep a copy,
  // and the username typed to unlock the button.
  const name = ctx.lb.profile()?.username || ctx.user.email;
  const confirmBox = h('input', { id: 'delete-confirm', type: 'text', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', placeholder: name });
  const del = h('button', { class: 'btn danger', type: 'button', disabled: true }, 'Delete my account');
  confirmBox.addEventListener('input', () => { del.disabled = confirmBox.value.trim() !== name; });
  del.addEventListener('click', busy(del, async () => {
    if (confirmBox.value.trim() !== name) throw new Error('That didn’t match, so nothing was deleted.');
    await ctx.lb.deleteAccount();
    toast('Your account has been deleted.');
    await ctx.signOut({ force: true });
  }));
  const deleteCard = h('div', { class: 'card danger-zone' },
    h('h2', {}, 'Delete my account'),
    h('p', { class: 'muted' }, 'This removes your account and everything in it: every workout, your plan, lifts, settings and photo, on all your devices. It can’t be undone. To keep a copy, ',
      h('a', { href: '#/settings/sync' }, 'download your data'), ' first.'),
    field(`To confirm, type your username: ${name}`, confirmBox),
    del);

  return h('div', {},
    h('div', { class: 'card' }, h('h2', {}, 'Email'), h('p', { class: 'muted' }, ctx.user.email),
      field('New email', email, 'We email a link to confirm it. Your sign-in changes once you open it.'), moveEmail),
    h('div', { class: 'card' }, h('h2', {}, 'Password'), field('New password', pw, 'At least 8 characters.'), change),
    h('div', { class: 'card' }, h('h2', {}, 'Appearance'), themeSeg()),
    h('div', { class: 'card' }, out),
    deleteCard);
}
