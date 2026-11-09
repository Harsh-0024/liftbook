// Pasting a workout, as the old Log page did it: some copies (Notes on some phones) put a blank
// line between every line; those are put back as one blank line above each exercise, its sets
// straight under it. After pasting a whole workout the box goes back to the top, so the title shows.

const NUMBERS_LINE = /^\s*(?:bw\b|[+-]?\d)/i;

/** The text with doubled blank lines undone, or the same text when it isn't spaced that way. */
export function tidyPaste(text) {
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  const filled = lines.map((line) => line.trim() !== '');
  const touching = filled.some((f, i) => f && filled[i + 1]);
  if (touching || filled.filter(Boolean).length < 4) return text;
  const out = [];
  lines.filter((_, i) => filled[i]).forEach((line, i) => {
    if (i > 0 && !NUMBERS_LINE.test(line)) out.push('');
    out.push(line);
  });
  return out.join('\n') + (/\n\s*$/.test(text) ? '\n' : '');
}

/** Puts text in at the cursor (over any selection) and tells the page it changed. */
export function insertAtCursor(ta, text) {
  const start = ta.selectionStart ?? ta.value.length;
  ta.setRangeText(text, start, ta.selectionEnd ?? start, 'end');
  ta.dispatchEvent(new Event('input', { bubbles: true }));
}

/** Let the paste show for a moment, then glide back up to the title. */
export function showFromTop(ta) {
  setTimeout(() => ta.scrollTo({ top: 0, behavior: 'smooth' }), 220);
}

export function attachPasteTidy(ta) {
  ta.addEventListener('paste', (e) => {
    const text = e.clipboardData?.getData('text/plain');
    if (!text) return;
    // The whole workout: an empty box, or everything selected. A line pasted mid-text stays put.
    const whole = !ta.value.trim() || (ta.selectionStart === 0 && ta.selectionEnd === ta.value.length);
    const tidy = tidyPaste(text);
    if (tidy !== text) {
      e.preventDefault();
      insertAtCursor(ta, tidy);
    }
    if (whole) showFromTop(ta);
  });
}
