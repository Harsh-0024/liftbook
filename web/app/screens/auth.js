// Signing in, creating an account, resetting a password, and choosing a username.

import { h, toast, busy } from '../ui.js';

const USERNAME_RE = /^[A-Za-z0-9_.-]{3,50}$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PASSWORD_MIN = 8;

const appUrl = () => `${location.origin}${location.pathname}`;

function shell(title, sub, ...body) {
  return h('div', { class: 'auth' },
    h('img', { class: 'logo', src: 'icons/icon-192.png', alt: '', width: 72, height: 72 }),
    h('h1', {}, title),
    h('p', { class: 'sub' }, sub),
    h('div', { class: 'card' }, ...body));
}

function field(label, input, hint) {
  return h('div', { class: 'field' }, h('label', { for: input.id }, label), input, hint ? h('div', { class: 'hint' }, hint) : null);
}

function passwordProblem(password) {
  if (password.length < PASSWORD_MIN) return `Use at least ${PASSWORD_MIN} characters.`;
  if (new TextEncoder().encode(password).length > 72) return 'Use at most 72 characters.';
  return null;
}

export function authScreens({ client, onSignedIn, go }, which) {
  if (which === 'signup') return signUp(client, onSignedIn);
  if (which === 'forgot') return forgot(client);
  return signIn(client, onSignedIn, go);
}

function signIn(client, onSignedIn) {
  const email = h('input', { id: 'email', type: 'email', autocomplete: 'username', required: true, autocapitalize: 'off' });
  const password = h('input', { id: 'password', type: 'password', autocomplete: 'current-password', required: true });
  const err = h('p', { class: 'error', role: 'alert' });
  const btn = h('button', { class: 'btn primary block', type: 'submit' }, 'Sign in');
  const form = h('form', { novalidate: true },
    field('Email', email),
    field('Password', password),
    err, btn,
    h('p', { class: 'center subtle', style: 'margin-top:14px' },
      h('a', { href: '#/forgot' }, 'Forgot your password?')),
  );
  form.addEventListener('submit', busy(btn, async () => {
    err.textContent = '';
    if (!EMAIL_RE.test(email.value.trim())) {
      err.textContent = 'Type the email you signed up with.';
      return;
    }
    try {
      await client.auth.signIn(email.value.trim(), password.value);
    } catch (e) {
      err.textContent = e.message;
      return;
    }
    await onSignedIn();
  }));
  return shell('Welcome back', 'Sign in to your workout log.', form,
    h('p', { class: 'center subtle', style: 'margin:14px 0 0' }, 'New here? ', h('a', { href: '#/signup' }, 'Create an account')));
}

function signUp(client, onSignedIn) {
  const name = h('input', { id: 'full_name', type: 'text', autocomplete: 'name', maxlength: 100 });
  const username = h('input', { id: 'username', type: 'text', autocomplete: 'username', autocapitalize: 'off', maxlength: 50 });
  const email = h('input', { id: 'email', type: 'email', autocomplete: 'email', autocapitalize: 'off' });
  const password = h('input', { id: 'password', type: 'password', autocomplete: 'new-password' });
  const err = h('p', { class: 'error', role: 'alert' });
  const btn = h('button', { class: 'btn primary block', type: 'submit' }, 'Create account');
  const form = h('form', { novalidate: true },
    field('Your name', name),
    field('Username', username, 'Letters, numbers, dots, dashes and underscores; 3 or more.'),
    field('Email', email),
    field('Password', password, `At least ${PASSWORD_MIN} characters.`),
    err, btn);
  form.addEventListener('submit', busy(btn, async () => {
    err.textContent = '';
    const u = username.value.trim();
    const problem = !USERNAME_RE.test(u) ? 'Choose a username of 3 or more letters, numbers, dots, dashes or underscores.'
      : !EMAIL_RE.test(email.value.trim()) ? 'Type a valid email.'
        : passwordProblem(password.value);
    if (problem) {
      err.textContent = problem;
      return;
    }
    try {
      if (!(await client.db.rpcAnon('username_available', { name: u }))) {
        err.textContent = 'That username is taken. Choose another.';
        return;
      }
      const session = await client.auth.signUp(email.value.trim(), password.value, { username: u, full_name: name.value.trim() }, appUrl());
      if (session) {
        await onSignedIn();
        return;
      }
    } catch (e) {
      err.textContent = e.message;
      return;
    }
    form.replaceWith(h('div', {},
      h('h2', {}, 'Check your email'),
      h('p', { class: 'muted' }, `We sent a link to ${email.value.trim()}. Open it on this device to finish creating your account.`)));
  }));
  return shell('Create your account', 'Your workouts, on every device, even offline.', form,
    h('p', { class: 'center subtle', style: 'margin:14px 0 0' }, 'Already have one? ', h('a', { href: '#/signin' }, 'Sign in')));
}

function forgot(client) {
  const email = h('input', { id: 'email', type: 'email', autocomplete: 'email', autocapitalize: 'off' });
  const err = h('p', { class: 'error', role: 'alert' });
  const btn = h('button', { class: 'btn primary block', type: 'submit' }, 'Send reset link');
  const form = h('form', { novalidate: true }, field('Email', email), err, btn);
  form.addEventListener('submit', busy(btn, async () => {
    err.textContent = '';
    if (!EMAIL_RE.test(email.value.trim())) {
      err.textContent = 'Type the email you signed up with.';
      return;
    }
    try {
      await client.auth.sendPasswordReset(email.value.trim(), appUrl());
    } catch (e) {
      err.textContent = e.message;
      return;
    }
    form.replaceWith(h('p', { class: 'muted' }, 'If there is an account with that email, a link to choose a new password is on its way.'));
  }));
  return shell('Reset your password', 'We’ll email you a link.', form,
    h('p', { class: 'center subtle', style: 'margin:14px 0 0' }, h('a', { href: '#/signin' }, 'Back to sign in')));
}

/** After a reset link: choose the new password (signed in by the link). */
export function resetScreen(ctx) {
  const password = h('input', { id: 'password', type: 'password', autocomplete: 'new-password' });
  const again = h('input', { id: 'password2', type: 'password', autocomplete: 'new-password' });
  const err = h('p', { class: 'error', role: 'alert' });
  const btn = h('button', { class: 'btn primary block', type: 'submit' }, 'Save new password');
  const form = h('form', { novalidate: true }, field('New password', password), field('Type it again', again), err, btn);
  form.addEventListener('submit', busy(btn, async () => {
    err.textContent = passwordProblem(password.value) || (password.value !== again.value ? 'The two don’t match.' : '');
    if (err.textContent) return;
    try {
      await ctx.client.auth.updatePassword(password.value);
    } catch (e) {
      err.textContent = e.message;
      return;
    }
    toast('Password changed.');
    ctx.go('');
  }));
  return shell('Choose a new password', 'You’re signed in from the link.', form);
}

/** An account with no profile yet (made here, or by an older app): pick a username. */
export function welcomeScreen(ctx) {
  const meta = ctx.user.user_metadata || {};
  if (ctx.lb.profile()) {
    queueMicrotask(() => ctx.go(''));
    return h('p', {});
  }
  const name = h('input', { id: 'full_name', type: 'text', value: meta.full_name || '', maxlength: 100 });
  const username = h('input', { id: 'username', type: 'text', value: meta.username || '', autocapitalize: 'off', maxlength: 50 });
  const err = h('p', { class: 'error', role: 'alert' });
  const btn = h('button', { class: 'btn primary block', type: 'submit' }, 'Start logging');
  const form = h('form', { novalidate: true }, field('Your name', name), field('Username', username), err, btn);
  form.addEventListener('submit', busy(btn, async () => {
    const u = username.value.trim();
    if (!USERNAME_RE.test(u)) {
      err.textContent = 'Choose a username of 3 or more letters, numbers, dots, dashes or underscores.';
      return;
    }
    // The profile may have arrived from another device meanwhile.
    const r = await ctx.sync.runOnce();
    if (r.error) {
      err.textContent = r.error === 'offline' ? 'Connect to the internet to finish setting up.' : r.error;
      return;
    }
    if (!ctx.lb.profile()) {
      if (!(await ctx.lb.usernameAvailable(u))) {
        err.textContent = 'That username is taken. Choose another.';
        return;
      }
      await ctx.lb.saveProfile({ username: u, full_name: name.value.trim() });
      await ctx.sync.runOnce();
    }
    ctx.go('');
  }));
  return shell('One more step', 'Choose how you appear in Liftbook.', form);
}
