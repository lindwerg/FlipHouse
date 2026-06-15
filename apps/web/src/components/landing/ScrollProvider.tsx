'use client';

import { useSmoothScroll } from '@/hooks/useSmoothScroll';

// Headless controller for the landing scroll-storytelling. Mounted in the
// marketing route alongside <Landing/>; it runs useSmoothScroll (Lenis + GSAP
// reveals) against the rendered landing DOM and renders nothing.
export function ScrollProvider() {
  useSmoothScroll();
  return null;
}
