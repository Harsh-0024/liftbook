// The Android app (Capacitor, android/): the few things that differ from the website. The app
// carries this same web app inside it; Capacitor's plugins are reached through
// window.Capacitor.Plugins, so the website needs nothing extra and every function here falls
// back to what the website does.

import { WEB_APP_URL } from '../config.js';

const cap = globalThis.Capacitor;
export const isNative = Boolean(cap?.isNativePlatform?.());
const plugins = cap?.Plugins || {};

/** The app's own address scheme: an emailed link comes back to the app as "in.liftbook.app://auth#...". */
export const APP_LINK = 'in.liftbook.app://auth';

/**
 * Where an emailed link (confirming an account or a new email, resetting a password) should land.
 * The app can't receive https links of its own, so it sends them to the website with "?app=android";
 * the website then hands the sign-in to the app (appHandOff) or, on a computer, carries on itself.
 */
export function linkBackUrl() {
  if (isNative) return `${WEB_APP_URL}?app=android`;
  return `${location.origin}${location.pathname}`;
}

/** On the website: an emailed link that was asked for in the Android app. */
export function wantsApp() {
  return !isNative && new URLSearchParams(location.search).get('app') === 'android';
}

/** The page that sends an emailed link's sign-in on to the app (on the website only). */
export function appHandOff(h, hash, carryOn) {
  const open = `${APP_LINK}${hash}`;
  const isAndroid = /Android/i.test(navigator.userAgent);
  // On an Android phone, try to open the app straight away; the button is there if that's blocked.
  if (isAndroid) setTimeout(() => { location.href = open; }, 50);
  return h('div', { class: 'auth' },
    h('img', { class: 'logo', src: 'icons/icon-192.png', alt: '', width: 72, height: 72 }),
    h('h1', {}, 'Open Liftbook'),
    h('p', { class: 'sub' }, isAndroid ? 'Finish in the Liftbook app on this phone.' : 'This link was asked for in the Liftbook app.'),
    h('div', { class: 'card stack' },
      h('a', { class: 'btn primary block', href: open }, 'Open the app'),
      h('button', { class: 'btn block', type: 'button', onclick: carryOn }, 'Continue in this browser')));
}

/**
 * Wires the app to Android: links back from emails, the back button, coming back to the front,
 * the network returning, the keyboard and the status bar colours. Does nothing on the website.
 */
export function startNative({ onLink, onResume, onOnline, onBack }) {
  if (!isNative) return;
  const { App, Network, Keyboard, SystemBars } = plugins;

  App?.addListener('appUrlOpen', ({ url }) => onLink(url));
  App?.getLaunchUrl?.().then((r) => r?.url && onLink(r.url)).catch(() => {});
  App?.addListener('resume', onResume);
  App?.addListener('backButton', ({ canGoBack }) => {
    if (!onBack(canGoBack)) App.minimizeApp();
  });
  Network?.addListener('networkStatusChange', (s) => s.connected && onOnline());

  // The log box stays in sight above the keyboard.
  Keyboard?.addListener('keyboardDidShow', () => {
    const el = document.activeElement;
    if (el && /^(TEXTAREA|INPUT|SELECT)$/.test(el.tagName)) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  });

  // Status bar icons light on the dark theme and dark on the light one (the app draws behind the bar).
  if (SystemBars) {
    const media = matchMedia('(prefers-color-scheme: light)');
    const paint = () => {
      const theme = document.documentElement.dataset.theme || (media.matches ? 'light' : 'dark');
      SystemBars.setStyle({ style: theme === 'light' ? 'LIGHT' : 'DARK' }).catch(() => {});
    };
    paint();
    media.addEventListener('change', paint);
    new MutationObserver(paint).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  }
}

/** A photo from the camera or the gallery (the app asks which); null when cancelled. */
export async function pickPhoto() {
  const { Camera } = plugins;
  try {
    const photo = await Camera.getPhoto({ source: 'PROMPT', resultType: 'uri', quality: 85, width: 1200, correctOrientation: true });
    const blob = await (await fetch(photo.webPath)).blob();
    return new File([blob], `photo.${photo.format || 'jpeg'}`, { type: blob.type || `image/${photo.format || 'jpeg'}` });
  } catch (err) {
    if (/cancel/i.test(String(err?.message || err))) return null;
    throw err;
  }
}

/** Saves a file the person asked for: a download on the website, the share sheet in the app. */
export async function saveFile(name, blob) {
  const { Filesystem, Share } = plugins;
  if (!isNative || !Filesystem || !Share) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    return;
  }
  const data = await new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1]);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
  const { uri } = await Filesystem.writeFile({ path: name, data, directory: 'CACHE' });
  try {
    await Share.share({ title: name, files: [uri] });
  } catch (err) {
    if (!/cancel/i.test(String(err?.message || err))) throw err;
  }
}
