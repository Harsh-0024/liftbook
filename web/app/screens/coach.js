// The AI coach: a later phase, as a Supabase Edge Function (it needs the person's AI key, which
// the app can never read back, and the coach_answers table). This page holds its place.
//
// When it lands: POST the question to /functions/v1/coach with the access token; the function
// reads the history with the service key, answers, and stores the answer in coach_answers,
// which this page lists (select on coach_answers is already granted) with the 👍/👎 rating.

import { h } from '../ui.js';

export function coachScreen() {
  return h('div', {},
    h('div', { class: 'page-head' }, h('h1', {}, 'AI coach')),
    h('div', { class: 'card coach-empty' },
      h('div', { class: 'big', 'aria-hidden': 'true' }, '✨'),
      h('h2', {}, 'Coming soon'),
      h('p', { class: 'muted' }, 'Ask about your training and get answers from your own history. The coach is moving to the new app next.'),
      h('p', { class: 'subtle' }, 'Until then it’s on the current site, app.liftbook.in.')));
}
