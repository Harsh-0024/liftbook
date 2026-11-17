// Reduce Motion (iPhone: Settings > Accessibility > Motion; computers have the same switch): a
// script's smooth scroll ignores it unless asked, so it jumps instead when that's on.
export const scrollBehavior = () =>
  (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth');
