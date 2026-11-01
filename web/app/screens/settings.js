// Settings: profile, plan and rep ranges, exercises (timed, bodyweight, renames), feedback,
// sync and the account.

import { h, toast, busy, ago, formatDay, fmtNum, copyText } from '../ui.js';
import { Online } from '../online.js';
import { FEEDBACK_KINDS } from '../data.js';
import { defaultRepRangesText } from '../../core/plans.js';
import { DEFAULT_PLAN } from '../../core/plans.js';

const SECTIONS = [
  ['profile', 'Profile', 'Name, username, bodyweight, photo'],
  ['plan', 'Plan and rep ranges', 'Your training days and targets'],
  ['exercises', 'Exercises', 'Timed, bodyweight, renames'],
  ['shortcuts', 'Apple Shortcuts', 'Log and get workouts from Notes on your iPhone'],
  ['feedback', 'Feedback', 'Tell us what to improve'],
  ['sync', 'Sync and data', 'Devices, backup file'],
  ['account', 'Account', 'Password, theme, sign out, delete'],
];

export function settingsScreen(ctx, section) {
  const found = SECTIONS.find(([k]) => k === section);
  if (!found) return index(ctx);
  const [key, title] = found;
  const body = { profile, plan, exercises, shortcuts, feedback, sync, account }[key](ctx);
  return h('div', {},
    h('div', { class: 'page-head' }, h('h1', {}, title), h('a', { class: 'btn small', href: '#/settings' }, 'Settings')),
    body);
}

function index(ctx) {
  const p = ctx.lb.profile();
  return h('div', {},
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Settings'),
      h('p', { class: 'muted', style: 'margin:0' }, p ? `Signed in as ${p.username} (${ctx.user.email})` : ctx.user.email))),
    h('div', { class: 'card' }, h('ul', { class: 'list' }, SECTIONS.map(([k, t, sub]) => h('li', {},
      h('a', { class: 'item chev', href: `#/settings/${k}` }, h('div', {}, h('div', { style: 'font-weight:600' }, t), h('div', { class: 'meta' }, sub))))))),
    h('a', { class: 'btn block', href: '#/coach' }, 'AI coach'));
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
  const photoBtn = h('button', { class: 'btn small', type: 'button', onclick: () => file.click() }, 'Change photo');
  file.addEventListener('change', busy(photoBtn, async () => {
    if (!file.files[0]) return;
    await lb.uploadAvatar(file.files[0]);
    toast('Photo saved.');
    ctx.refresh();
  }));

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
  return h('div', { class: 'card' },
    h('div', { class: 'row', style: 'margin-bottom:16px' }, avatar, photoBtn, file),
    field('Name', name), field('Username', username), field('Bodyweight', bw, 'Used for bodyweight exercises like pull-ups and dips.'),
    save);
}

/* ---------------- plan ---------------- */

function plan(ctx) {
  const { lb } = ctx;
  const s = lb.settings();
  const admin = lb.isAdmin();
  const shared = lb.sharedPlan();
  const followPlan = h('input', { type: 'checkbox', checked: Boolean(s.follow_shared_plan) });
  const followReps = h('input', { type: 'checkbox', checked: Boolean(s.follow_shared_exercises) });
  followPlan.addEventListener('change', async () => {
    await lb.setSetting('follow_shared_plan', followPlan.checked);
    toast(followPlan.checked ? 'Following the shared plan.' : 'Using your own plan.');
  });
  followReps.addEventListener('change', async () => {
    await lb.setSetting('follow_shared_exercises', followReps.checked);
    toast(followReps.checked ? 'Following the shared rep ranges.' : 'Using your own rep ranges.');
  });

  const planText = h('textarea', { id: 'plan', spellcheck: 'false', placeholder: DEFAULT_PLAN.slice(0, 400) }, lb.text('plan'));
  const repText = h('textarea', { id: 'rep_ranges', spellcheck: 'false', placeholder: defaultRepRangesText().slice(0, 300) }, lb.text('rep_ranges'));
  const savePlan = h('button', { class: 'btn primary', type: 'button' }, 'Save plan');
  savePlan.addEventListener('click', busy(savePlan, async () => {
    await lb.setText('plan', planText.value);
    toast('Plan saved.');
  }));
  const saveReps = h('button', { class: 'btn primary', type: 'button' }, 'Save rep ranges');
  saveReps.addEventListener('click', busy(saveReps, async () => {
    await lb.setText('rep_ranges', repText.value);
    toast('Rep ranges saved.');
  }));
  const refresh = h('button', { class: 'btn small', type: 'button' }, 'Check for updates');
  refresh.addEventListener('click', busy(refresh, async () => {
    toast((await lb.refreshShared()) ? 'Shared plan is up to date.' : 'Couldn’t reach the server.');
  }));

  return h('div', {},
    admin ? h('div', { class: 'card gold' }, h('p', { style: 'margin:0' }, 'You’re an admin: your plan and rep ranges are the shared ones others can follow.')) :
      h('div', { class: 'card' },
        h('h2', {}, 'Shared plan'),
        h('label', { class: 'check' }, followPlan, h('span', {}, 'Follow the shared plan', h('div', { class: 'hint' }, 'Retrieve uses it instead of yours.'))),
        h('label', { class: 'check', style: 'margin-top:10px' }, followReps, h('span', {}, 'Follow the shared rep ranges')),
        h('div', { class: 'row spread', style: 'margin-top:12px' },
          h('span', { class: 'subtle' }, shared.updated_at ? `Shared plan updated ${formatDay(shared.updated_at)}` : 'Shared plan not downloaded yet'),
          refresh)),
    h('div', { class: 'card' },
      h('h2', {}, 'Your plan'),
      h('p', { class: 'subtle' }, 'A day header ("Session 1 - Legs"), then one exercise per line, with targets like "Squat - [3, 5-8]". Leave empty for the built-in plan.'),
      planText, h('div', { class: 'row', style: 'margin-top:12px' }, savePlan)),
    h('div', { class: 'card' },
      h('h2', {}, 'Rep ranges'),
      h('p', { class: 'subtle' }, 'One exercise per line: "Squat: 3, 5-8" (sets, then reps) or "Plank: 30-60s". Leave empty for the built-in ranges.'),
      repText, h('div', { class: 'row', style: 'margin-top:12px' }, saveReps)));
}

/* ---------------- exercises ---------------- */

function exercises(ctx) {
  const { lb } = ctx;
  const names = [...new Set(lb.history().map((l) => l.exercise))].sort((a, b) => a.localeCompare(b));
  const search = h('input', { id: 'ex-search', type: 'search', placeholder: 'Search your exercises', autocapitalize: 'off' });
  const list = h('ul', { class: 'list' });
  const paint = () => {
    const q = search.value.trim().toLowerCase();
    list.replaceChildren(...names.filter((n) => !q || n.toLowerCase().includes(q)).slice(0, 100).map((n) => {
      const s = lb.exerciseSetting(n) || {};
      const timed = h('input', { type: 'checkbox', checked: s.is_timed === true, 'aria-label': `${n} is timed` });
      const bw = h('input', { type: 'checkbox', checked: s.is_bodyweight === true, 'aria-label': `${n} uses bodyweight` });
      timed.addEventListener('change', () => lb.setExerciseSetting(n, { is_timed: timed.checked }));
      bw.addEventListener('change', () => lb.setExerciseSetting(n, { is_bodyweight: bw.checked, bodyweight_source: 'manual' }));
      return h('li', {}, h('div', { class: 'item', style: 'flex-wrap:wrap' },
        h('span', { style: 'font-weight:600' }, n),
        h('span', { class: 'row', style: 'gap:14px' },
          h('label', { class: 'check', style: 'margin:0' }, timed, 'Timed'),
          h('label', { class: 'check', style: 'margin:0' }, bw, 'Bodyweight'),
          h('button', { class: 'linkish', type: 'button', onclick: () => renameForm(n) }, 'Rename'))));
    }));
  };
  search.addEventListener('input', paint);

  const renameBox = h('div', {});
  function renameForm(oldName) {
    const to = h('input', { id: 'new-name', type: 'text', value: oldName, maxlength: 100 });
    const info = h('p', { class: 'subtle' });
    const go = h('button', { class: 'btn primary', type: 'button' }, 'Rename');
    to.addEventListener('input', () => {
      const pr = lb.renamePreview(oldName, to.value);
      info.textContent = pr.error || `Moves ${pr.logs} logged session${pr.logs === 1 ? '' : 's'}, and the name in your plan and rep ranges.`;
    });
    go.addEventListener('click', busy(go, async () => {
      const r = await lb.rename(oldName, to.value);
      toast(`Renamed. ${r.logs} session${r.logs === 1 ? '' : 's'} moved.`);
      ctx.refresh();
    }));
    renameBox.replaceChildren(h('div', { class: 'card gold' }, h('h2', {}, `Rename ${oldName}`), field('New name', to), info,
      h('div', { class: 'row' }, go, h('button', { class: 'btn', type: 'button', onclick: () => renameBox.replaceChildren() }, 'Cancel'))));
    renameBox.scrollIntoView({ behavior: 'smooth' });
    to.focus();
  }

  const renames = lb.renames();
  paint();
  return h('div', {},
    renameBox,
    h('div', { class: 'card' },
      h('p', { class: 'subtle' }, 'Timed: sets are seconds, not reps. Bodyweight: your bodyweight is added to the weight.'),
      search, list),
    renames.length ? h('div', { class: 'card' }, h('h2', {}, 'Renamed exercises'),
      h('p', { class: 'subtle' }, 'Logs typed with the old name are saved under the new one.'),
      h('ul', { class: 'list' }, renames.map((r) => {
        const undo = h('button', { class: 'btn small', type: 'button' }, 'Undo');
        undo.addEventListener('click', busy(undo, async () => {
          if (!confirm(`Put ${r.new_name} back to ${r.old_name}?`)) return;
          await lb.undoRename(r.id);
          toast('Rename undone.');
          ctx.refresh();
        }));
        return h('li', {}, h('div', { class: 'item' }, h('span', {}, `${r.old_name} → ${r.new_name}`), undo));
      }))) : null);
}

/* ---------------- feedback ---------------- */

function feedback(ctx) {
  const { lb } = ctx;
  const labels = { like: 'Something I like', dislike: 'Something I dislike', improve: 'Something to improve', idea: 'An idea' };
  const kind = h('select', { id: 'kind' }, FEEDBACK_KINDS.map((k) => h('option', { value: k }, labels[k])));
  const msg = h('textarea', { id: 'message', maxlength: 2000, style: 'min-height:120px;font-family:var(--font)' });
  const send = h('button', { class: 'btn primary', type: 'button' }, 'Send');
  const mine = h('div', {}, h('p', { class: 'subtle' }, 'Loading what you sent…'));
  const load = async () => {
    try {
      const rows = await lb.myFeedback();
      mine.replaceChildren(rows.length ? h('ul', { class: 'list' }, rows.map((r) => h('li', {}, h('div', { class: 'item', style: 'align-items:flex-start' },
        h('div', {}, h('div', {}, r.message), h('div', { class: 'meta' }, `${labels[r.kind]} · ${formatDay(r.created_at)}`)),
        h('span', { class: `pill ${r.status === 'done' ? 'improved' : r.status === 'seen' ? 'new' : ''}` }, r.status === 'new' ? 'sent' : r.status))))) :
        h('p', { class: 'subtle' }, 'Nothing sent yet.'));
    } catch {
      mine.replaceChildren(h('p', { class: 'subtle' }, 'Connect to the internet to see what you sent.'));
    }
  };
  send.addEventListener('click', busy(send, async () => {
    try {
      await lb.sendFeedback(kind.value, msg.value, location.hash);
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
    h('div', { class: 'card' }, field('What kind?', kind), field('Your feedback', msg), send),
    h('div', { class: 'card' }, h('h2', {}, 'What you sent'), mine));
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
      if (info && !confirm('Your Shortcuts stop working until you paste the new key into them. Make a new key?')) return;
      const fresh = await online.newShortcutKey();
      await ctx.store.setMeta('shortcut_key', fresh);
      toast('New key made. Copy it into your Shortcuts.');
      await paint();
    }));
    const remove = h('button', { class: 'btn small danger', type: 'button' }, 'Switch Shortcuts off');
    remove.addEventListener('click', busy(remove, async () => {
      if (!confirm('Your Shortcuts stop working. Switch them off?')) return;
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
    const a = h('a', { href: URL.createObjectURL(blob), download: `liftbook-${lb.profile()?.username || 'backup'}-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(a);
    a.click();
    a.remove();
  };
  const counts = lb.overview();
  return h('div', {},
    h('div', { class: 'card' }, h('h2', {}, 'Sync'), status, now,
      h('p', { class: 'subtle', style: 'margin-top:12px' }, 'Everything is kept on this device and works offline. Changes go to your account when you’re online, and your other devices pick them up when they open or come back online.')),
    h('div', { class: 'card' }, h('h2', {}, 'Your data'),
      h('p', {}, `${counts.total} workouts, ${lb.history().length} exercise logs, ${counts.exercises} exercises.`),
      h('button', { class: 'btn', type: 'button', onclick: backup }, 'Download a backup file')));
}

/* ---------------- account ---------------- */

function account(ctx) {
  const pw = h('input', { id: 'new-password', type: 'password', autocomplete: 'new-password' });
  const change = h('button', { class: 'btn', type: 'button' }, 'Change password');
  change.addEventListener('click', busy(change, async () => {
    if (pw.value.length < 8) throw new Error('Use at least 8 characters.');
    await ctx.client.auth.updatePassword(pw.value);
    pw.value = '';
    toast('Password changed.');
  }));

  let theme = 'auto';
  try {
    theme = localStorage.getItem('liftbook-theme') || 'auto';
  } catch {
    // default
  }
  const themeSel = h('select', { id: 'theme' }, [['auto', 'Match this device'], ['dark', 'Dark'], ['light', 'Light']].map(([v, l]) => h('option', { value: v, selected: v === theme }, l)));
  themeSel.addEventListener('change', () => {
    try {
      if (themeSel.value === 'auto') localStorage.removeItem('liftbook-theme');
      else localStorage.setItem('liftbook-theme', themeSel.value);
    } catch {
      // only this visit
    }
    if (themeSel.value === 'auto') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = themeSel.value;
  });

  const out = h('button', { class: 'btn', type: 'button' }, 'Sign out of this device');
  out.addEventListener('click', busy(out, () => ctx.signOut()));
  const del = h('button', { class: 'btn danger', type: 'button' }, 'Delete my account');
  del.addEventListener('click', busy(del, async () => {
    const name = ctx.lb.profile()?.username || ctx.user.email;
    const typed = prompt(`This deletes your account and every workout, on all devices, for good.\n\nType ${name} to confirm.`);
    if (typed === null) return;
    if (typed.trim() !== name) throw new Error('That didn’t match, so nothing was deleted.');
    await ctx.lb.deleteAccount();
    toast('Your account has been deleted.');
    await ctx.signOut({ force: true });
  }));

  return h('div', {},
    h('div', { class: 'card' }, h('h2', {}, 'Email'), h('p', { class: 'muted' }, ctx.user.email)),
    h('div', { class: 'card' }, h('h2', {}, 'Password'), field('New password', pw, 'At least 8 characters.'), change),
    h('div', { class: 'card' }, h('h2', {}, 'Theme'), themeSel),
    h('div', { class: 'card' }, h('div', { class: 'row' }, out, del)),
    h('p', { class: 'subtle' }, `Bodyweight on file: ${fmtNum(ctx.lb.profile()?.bodyweight)}`));
}
