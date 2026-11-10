// Readability check: opens every screen of the app (light or dark), lists any text below the
// WCAG contrast guideline (4.5:1, or 3:1 for large text), and saves a screenshot of each screen.
// It signs in to a stand-in for Supabase inside the browser, with made-up workouts: no real
// account or data is touched.
//
//   python3 web/tools/serve.py            (in one terminal)
//   node web/tools/contrast_check.cjs /tmp/shots light     (or dark; add "noshots" to skip pictures)
//
// Needs Playwright with Chromium (npm install --no-save playwright && npx playwright install chromium).
// Disabled buttons and hidden text are skipped: the guideline doesn't cover them.
const { chromium } = require('playwright');
const fs = require('fs');
const [outDir, theme = 'light', shots = 'shots'] = process.argv.slice(2);
const BASE = 'http://localhost:8765/';
const SUPA = 'https://qjlmxlnmfowqsunpzvac.supabase.co';
const USER = { id: '00000000-0000-4000-8000-000000000001', email: 'demo@example.test', user_metadata: { username: 'demo' } };

// Made-up training: three sessions in rotation, every other day for six weeks.
function seed() {
  const days = [['Session 1 - Push', [['Flat Barbell Press', 80, 8], ['Incline Dumbbell Press', 30, 10], ['Tricep Pushdown', 30, 12]]],
    ['Session 2 - Pull', [['Pull Ups', 0, 8], ['Barbell Row', 70, 8], ['Barbell Curl', 30, 10]]],
    ['Session 3 - Legs', [['Back Squat', 120, 5], ['Leg Press', 200, 10]]]];
  const rows = []; let n = 0;
  const now = new Date();
  for (let i = 21; i >= 1; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i * 2);
    const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const [title, exs] = days[i % 3];
    for (const [ex, w, r] of exs) {
      const weight = w ? w + (21 - i) * 1.25 : 0;
      n++;
      rows.push({ user_id: USER.id, id: `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`, legacy_id: null,
        date: `${day}T00:00:00`, workout_name: title, exercise: ex, exercise_string: `${ex}\n${weight || 'BW'} x ${r}, ${r}`,
        sets: { weights: [weight, weight], reps: [r, r] }, bodyweight: 75, uses_bodyweight: ex === 'Pull Ups',
        top_weight: weight, top_reps: r, estimated_1rm: Math.round(weight * (1 + r / 30) * 10) / 10,
        created_at: `${day}T10:00:00Z`, updated_at: `${day}T10:00:00Z`, deleted_at: null, server_updated_at: `${day}T10:00:00.000001+00:00` });
    }
  }
  return rows;
}
const DATA = {
  profiles: [{ user_id: USER.id, username: 'demo', full_name: 'Demo', bodyweight: 75, avatar_path: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', deleted_at: null, server_updated_at: '2026-01-01T00:00:00.000001+00:00' }],
  workout_logs: seed(),
};

const ALL_PAGES = ['', 'log', 'history', 'WORKOUT', 'retrieve', 'retrieve/custom', 'stats', 'coach', 'settings',
  'settings/profile', 'settings/plan', 'settings/exercises', 'settings/shortcuts', 'settings/feedback', 'settings/sync',
  'settings/account', 'settings/session-names', 'signin'];
const PAGES = process.env.PAGES ? process.env.PAGES.split(',') : ALL_PAGES;

function auditInPage() {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const over = (t, b) => ({ r: t.r * t.a + b.r * (1 - t.a), g: t.g * t.a + b.g * (1 - t.a), b: t.b * t.a + b.b * (1 - t.a), a: 1 });
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = (c) => '#' + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const bgOf = (el) => { const layers = []; let grad = false;
    for (let n = el; n; n = n.parentElement) { const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage.includes('gradient') && n !== document.body && n !== document.documentElement) {
        const g = [...cs.backgroundImage.matchAll(/rgba?\([^)]+\)/g)].map((x) => parse(x[0])).filter((x) => x.a > 0.5);
        if (g.length) { // the lighter stop is the worst case for dark text, the darker for light text
          layers.push(g.reduce((a, b) => (lum(a) > lum(b) ? a : b))); layers[layers.length - 1].alt = g.reduce((a, b) => (lum(a) < lum(b) ? a : b)); grad = true; } }
      const c = parse(cs.backgroundColor); if (c && c.a > 0) layers.push(c);
      if (layers.length && layers[layers.length - 1].a >= 1) break; }
    let base = { r: 255, g: 255, b: 255, a: 1 }; const bodyBg = parse(getComputedStyle(document.body).backgroundColor);
    if (bodyBg && bodyBg.a > 0) base = bodyBg;
    let alt = null;
    for (let i = layers.length - 1; i >= 0; i--) { if (layers[i].alt) alt = over(layers[i].alt, base); base = over(layers[i], base); }
    return { bg: base, alt, grad }; };
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (!r.width || !r.height || cs.visibility === 'hidden') continue;
    if (el.closest('[hidden], [aria-hidden="true"], template, script, style, noscript, :disabled, [disabled]')) continue;
    const fg = parse(cs.color); if (!fg) continue;
    let op = 1; for (let n = el; n; n = n.parentElement) op *= +getComputedStyle(n).opacity;
    if (op === 0) continue;
    const { bg, alt, grad } = bgOf(el);
    const size = parseFloat(cs.fontSize), bold = +cs.fontWeight >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    let got = ratio(over({ ...fg, a: fg.a * op }, bg), bg);
    if (alt) got = Math.min(got, ratio(over({ ...fg, a: fg.a * op }, alt), alt));
    if (got + 0.005 < need) out.push({ text: el.textContent.trim().replace(/\s+/g, ' ').slice(0, 40),
      tag: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''),
      fg: hex(over({ ...fg, a: fg.a * op }, bg)), bg: hex(bg), ratio: +got.toFixed(2), need, grad });
  }
  return out;
}

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 393, height: 852 }, deviceScaleFactor: 1, colorScheme: theme, hasTouch: true, isMobile: true });
  await ctx.addInitScript(([user]) => {
    try {
      if (!localStorage.getItem('liftbook-session')) localStorage.setItem('liftbook-session', JSON.stringify({ access_token: 't', refresh_token: 'r', expires_at: Math.floor(Date.now() / 1000) + 86400, user }));
    } catch (e) {}
  }, [USER]);
  await ctx.route(`${SUPA}/**`, async (route) => {
    const req = route.request(); const u = new URL(req.url()); const p = u.pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (p.startsWith('/auth/v1/token')) return json({ access_token: 't', refresh_token: 'r', expires_in: 86400, user: USER });
    if (p.startsWith('/auth/v1/user')) return json(USER);
    if (p.startsWith('/rest/v1/rpc/')) return json(p.endsWith('is_admin') ? true : []);
    if (p.startsWith('/rest/v1/')) {
      if (req.method() !== 'GET') return route.fulfill({ status: 201, body: '' });
      const t = p.slice('/rest/v1/'.length); const off = Number(u.searchParams.get('offset') || 0);
      return json(off ? [] : (DATA[t] || []));
    }
    return route.fulfill({ status: 404, body: '' });
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message.slice(0, 160)));
  await page.goto(BASE + '#/'); await page.waitForTimeout(1500);
  const day = await page.evaluate(() => (document.querySelector('a[href^="#/workout/"]') || {}).getAttribute?.('href')?.split('/').pop());
  const report = {};
  for (let p of PAGES) {
    const name = p === 'WORKOUT' ? `workout/${day}` : p;
    if (p === 'signin') { await page.evaluate(() => localStorage.removeItem('liftbook-session')); }
    await page.goto(BASE + '#/' + name); if (p === 'signin') await page.reload();
    await page.waitForTimeout(700);
    report[name] = await page.evaluate(auditInPage);
    if (shots !== 'noshots') await page.screenshot({ path: `${outDir}/${(name || 'home').replace(/\W+/g, '_')}.png` });
  }
  fs.writeFileSync(`${outDir}/report.json`, JSON.stringify(report, null, 1));
  const seen = new Set(); let total = 0;
  for (const [p, list] of Object.entries(report)) for (const i of list) {
    const k = i.tag + i.fg + i.bg; if (seen.has(k)) continue; seen.add(k); total++;
    console.log(`${(p || 'home').padEnd(22)} ${i.ratio}/${i.need} ${i.fg} on ${i.bg}${i.grad ? ' G' : ''} ${i.tag.slice(0, 34)} "${i.text.slice(0, 26)}"`);
  }
  console.log(`DISTINCT low-contrast items: ${total}`);
  if (errors.length) console.log('PAGE ERRORS:', [...new Set(errors)].join(' | '));
  await browser.close();
})();
