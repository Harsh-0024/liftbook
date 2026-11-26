// Searching exercise names the way people type them at the gym: "rdl" finds Romanian Deadlift,
// "db row" finds Dumbbell Row, "row barbell" finds Barbell Row. Each word typed has to appear in
// the name (in any order), either as itself or as the longer word it stands for.

/** Short names for a whole lift. */
const LIFTS = {
  rdl: ['romanian deadlift'],
  sldl: ['stiff leg deadlift', 'stiff-leg deadlift', 'stiff legged deadlift', 'stiff-legged deadlift'],
  ohp: ['overhead press'],
  bp: ['bench press'],
  dl: ['deadlift'],
  bss: ['bulgarian split squat'],
  lpd: ['lat pulldown', 'lat pull-down', 'lat pull down'],
  pullup: ['pull-up', 'pull up'],
  pullups: ['pull-ups', 'pull ups'],
  chinup: ['chin-up', 'chin up'],
  chinups: ['chin-ups', 'chin ups'],
  pushup: ['push-up', 'push up'],
  pushups: ['push-ups', 'push ups'],
};

/** Short names for one word of a name. */
const WORDS = {
  db: ['dumbbell'],
  dbs: ['dumbbells', 'dumbbell'],
  bb: ['barbell'],
  kb: ['kettlebell'],
  ez: ['ez-bar', 'ez bar'],
  bw: ['bodyweight', 'body weight'],
  ext: ['extension'],
  tri: ['tricep', 'triceps'],
  bi: ['bicep', 'biceps'],
  incl: ['incline'],
  decl: ['decline'],
};

const clean = (s) => String(s || '').toLowerCase().replace(/[’']/g, '').replace(/\s+/g, ' ').trim();

/** True when every word typed is in the name, as itself or as what it is short for. */
export function exerciseMatches(name, query) {
  const n = clean(name);
  const q = clean(query);
  if (!q) return true;
  if (n.includes(q)) return true;
  if (LIFTS[q]?.some((full) => n.includes(full))) return true;
  // A word typed matches from the start of a word in the name ("bb" is not the "bb" in "dumbbell").
  const words = n.split(/[\s-]+/);
  return q.split(' ').every((word) => words.some((w) => w.startsWith(word))
    || (LIFTS[word] || []).some((full) => n.includes(full))
    || (WORDS[word] || []).some((full) => n.includes(full)));
}
