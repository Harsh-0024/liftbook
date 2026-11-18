// A chart's side scale: gridlines on round numbers (70, 80, 90… or 2.5, 5, 7.5…), not on
// whatever quarters of the range fall out (67, 77, 88…).

/**
 * values: the numbers the chart shows (and any line drawn with them, like a "start" line).
 * Returns {lo, hi, step, places, ticks}: the scale's ends, the step between gridlines (1, 2, 2.5
 * or 5 times a power of ten), how many decimals its labels need, and the gridline values, four
 * or five of them, always covering every value with a little room above and below.
 */
export function chartScale(values) {
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const span = hi - lo;
  lo -= span * 0.1;
  hi += span * 0.1;
  const rough = (hi - lo) / 4;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const tries = [1, 2, 2.5, 5, 10, 20, 25, 50].map((m) => m * mag).filter((st) => st >= rough);
  // At most five lines: rounding both ends out can add one, so take the next round step then.
  const step = tries.find((st) => Math.ceil(hi / st) - Math.floor(lo / st) <= 4) || tries[tries.length - 1];
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const count = Math.round((hi - lo) / step);
  const ticks = [];
  for (let k = 0; k <= count; k++) ticks.push(Number((lo + step * k).toFixed(6)) + 0); // no 0.30000000000000004, no "-0"
  const places = Number.isInteger(step) ? 0 : Number.isInteger(step * 10) ? 1 : 2;
  return { lo, hi, step, places, ticks };
}
