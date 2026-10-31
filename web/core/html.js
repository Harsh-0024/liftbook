// html.unescape() as Python does it (HTML5 rules), for workout titles.
import { HTML5, INVALID_CHARREFS, INVALID_CODEPOINTS } from './html_entities.js';

const INVALID = new Set(INVALID_CODEPOINTS);
const CHARREF = /&(#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\t\n\f <&#;]{1,32};?)/gu;

function replaceCharref(s) {
  if (s[0] === '#') {
    const num = s[1] === 'x' || s[1] === 'X'
      ? parseInt(s.slice(2).replace(/;+$/, ''), 16)
      : parseInt(s.slice(1).replace(/;+$/, ''), 10);
    if (Object.hasOwn(INVALID_CHARREFS, String(num))) return INVALID_CHARREFS[String(num)];
    if ((num >= 0xd800 && num <= 0xdfff) || num > 0x10ffff) return '�';
    if (INVALID.has(num)) return '';
    return String.fromCodePoint(num);
  }
  if (Object.hasOwn(HTML5, s)) return HTML5[s];
  const chars = [...s];
  for (let x = chars.length - 1; x > 1; x--) {
    const prefix = chars.slice(0, x).join('');
    if (Object.hasOwn(HTML5, prefix)) return HTML5[prefix] + chars.slice(x).join('');
  }
  return '&' + s;
}

export function unescapeHtml(s) {
  if (!s.includes('&')) return s;
  return s.replace(CHARREF, (_, ref) => replaceCharref(ref));
}
