// Whatever a note app sends (plain text, HTML, RTF) as plain workout text (utils/rich_text.py).
//
// Apple Notes rich text arrives with its own line breaks (U+2028), non-breaking spaces, bullet
// glyphs and sometimes as HTML or RTF. The parser only understands plain lines, so everything is
// flattened to that before parsing.

import { unescapeHtml } from './html.js';
import { strip } from './py.js';

const HTML_HINT = /<\s*(?:br|div|p|li|ul|ol|span|b|i|u|strong|em|h[1-6]|html|body|font|tt)\b[^>]*>/i;
const BLOCK_TAGS = new Set(['br', 'div', 'p', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'table']);
const SKIP_TAGS = new Set(['style', 'script', 'head', 'title']);
// Includes the emoji style selectors that ride along after marks like "✔\ufe0e".
const ZERO_WIDTH = /[\u200b\u200c\u200d\u2060\ufeff\ufffc\ufe0e\ufe0f]/g;
const SPACES = /[\u00a0\u2007\u202f\u2009\u200a\t]/g;
const LINE_BREAKS = /\r\n?|[\u2028\u2029\u0085\u000b\u000c]/g;
// List bullets and checklist boxes at the start of a line (plain "-" is left alone).
const BULLET = /^[ ]*(?:[•◦▪▫●○■□‣⁃∙·☐☑☒✓✔]\s*)+/gm;
// Markdown-style checklist items from other note apps: "- [ ] Squat", "- [x] Squat", "[x] Squat".
const CHECKBOX = /^[ ]*(?:[-*+][ ]+)?\[[ xX]\][ ]+/gm;

function htmlToText(text) {
  const parts = [];
  let skip = 0;
  const token = /<!--[\s\S]*?(?:-->|$)|<\/?([A-Za-z][^\s/>]*)[^>]*>|([^<]+|<)/g;
  for (const m of text.matchAll(token)) {
    if (m[1]) {
      const tag = m[1].toLowerCase();
      const closing = m[0][1] === '/';
      if (SKIP_TAGS.has(tag)) skip = closing ? Math.max(0, skip - 1) : skip + 1;
      else if (BLOCK_TAGS.has(tag)) parts.push('\n');
    } else if (m[2] !== undefined && !skip) {
      parts.push(unescapeHtml(m[2]));
    }
  }
  return parts.join('');
}

const RTF_TOKEN = /\\([a-z]+)(-?\d+)? ?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|(.)/gis;
const RTF_SKIP_DESTINATIONS = new Set([
  'fonttbl', 'colortbl', 'stylesheet', 'info', 'pict', 'header', 'footer',
  'expandedcolortbl', 'listtable', 'listoverridetable', 'generator', 'themedata',
]);
const CP1252 = new TextDecoder('windows-1252');
const CP1252_UNDEFINED = new Set([0x81, 0x8d, 0x8f, 0x90, 0x9d]);

function rtfToText(text) {
  const out = [];
  const stack = [];
  let skipping = false;
  let uc = 1;
  let pendingSkip = 0;
  for (const [, word0, arg, hexcode, symbol, brace, char] of text.matchAll(RTF_TOKEN)) {
    if (brace === '{') {
      stack.push([skipping, uc]);
    } else if (brace === '}') {
      [skipping, uc] = stack.length ? stack.pop() : [false, 1];
    } else if (symbol) {
      if (symbol === '*') skipping = true;
      else if ('\\{}'.includes(symbol) && !skipping) out.push(symbol);
      else if (symbol === '~' && !skipping) out.push(' ');
    } else if (word0) {
      const word = word0.toLowerCase();
      if (RTF_SKIP_DESTINATIONS.has(word)) skipping = true;
      else if (skipping) continue;
      else if (word === 'par' || word === 'line' || word === 'row') out.push('\n');
      else if (word === 'tab') out.push(' ');
      else if (word === 'uc') uc = Number(arg || 1);
      else if (word === 'u' && arg) {
        const code = Number(arg);
        out.push(String.fromCodePoint(code < 0 ? code + 65536 : code));
        pendingSkip = uc;
      }
    } else if (hexcode) {
      if (pendingSkip) pendingSkip--;
      else if (!skipping) {
        const byte = parseInt(hexcode, 16);
        out.push(CP1252_UNDEFINED.has(byte) ? '�' : CP1252.decode(new Uint8Array([byte])));
      }
    } else if (char) {
      if (pendingSkip) pendingSkip--;
      else if (!skipping) out.push(char);
    }
  }
  return out.join('');
}

function decode(bytes) {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    return CP1252.decode(bytes);
  }
}

/** Best-effort plain text from plain, HTML or RTF input (a string or bytes). */
export function toPlainText(raw) {
  let text = raw instanceof Uint8Array ? decode(raw) : String(raw ?? '');
  const stripped = text.replace(/^\s+/, '');
  if (stripped.startsWith('{\\rtf')) text = rtfToText(stripped);
  else if (HTML_HINT.test(text)) text = htmlToText(text);
  else if (/&(?:nbsp|amp|lt|gt|quot|#\d+);/.test(text)) text = unescapeHtml(text);

  text = text.replace(LINE_BREAKS, '\n').replace(ZERO_WIDTH, '').replace(SPACES, ' ');
  text = text.replace(BULLET, '').replace(CHECKBOX, '');
  const lines = text.split('\n').map((line) => strip(line.replace(/ {2,}/g, ' ')));
  return strip(lines.join('\n'));
}
