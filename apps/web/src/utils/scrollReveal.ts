// Declarative reveal configs for the landing scroll-storytelling (P1.9).
//
// Single source of truth for the GSAP/ScrollTrigger tweens in useSmoothScroll.
// Each config only animates compositor-friendly CSS properties (transform,
// opacity, clip-path) per web/coding-style.md — never layout-bound properties
// like width/height/top/left/margin/padding/border/font-size. scrollReveal.test
// statically asserts this so a future config touching a banned property is RED.

export const ALLOWED_REVEAL_PROPERTIES = [
  'transform',
  'opacity',
  'clip-path',
] as const;

export const BANNED_ANIMATION_PROPERTIES = [
  'width',
  'height',
  'top',
  'left',
  'margin',
  'padding',
  'border',
  'font-size',
] as const;

export type RevealKeyframe = {
  opacity?: number;
  /** GSAP transform shorthand: y/x (translate), scaleX/scaleY (scale). */
  y?: number;
  x?: number;
  scaleX?: number;
  scaleY?: number;
  clipPath?: string;
};

export type RevealConfig = {
  /** Selector matched against `[data-reveal="<name>"]` in the document. */
  name: string;
  from: RevealKeyframe;
  to: RevealKeyframe;
  /** Tween duration in seconds. */
  duration: number;
  /** GSAP ease name. */
  ease: string;
  /** Per-element stagger in seconds when a group of targets reveals together. */
  stagger: number;
};

// Maps a GSAP keyframe to the underlying CSS properties it actually animates.
// y/x/scaleX/scaleY all compile to `transform`; opacity → `opacity`; clipPath →
// `clip-path`. This is the surface scrollReveal.test inspects.
const KEYFRAME_TO_CSS: Record<keyof RevealKeyframe, (typeof ALLOWED_REVEAL_PROPERTIES)[number]> = {
  opacity: 'opacity',
  y: 'transform',
  x: 'transform',
  scaleX: 'transform',
  scaleY: 'transform',
  clipPath: 'clip-path',
};

export function revealProperties(config: RevealConfig): string[] {
  const keys = new Set<keyof RevealKeyframe>([
    ...(Object.keys(config.from) as Array<keyof RevealKeyframe>),
    ...(Object.keys(config.to) as Array<keyof RevealKeyframe>),
  ]);
  const css = new Set<string>();
  for (const key of keys) {
    css.add(KEYFRAME_TO_CSS[key]);
  }
  return [...css];
}

export const REVEAL_CONFIGS: Record<string, RevealConfig> = {
  // Default section/row reveal: fade up. Mirrors the swiss-pop.html `.reveal`
  // (opacity 0 + translateY 14px → 0) at 600ms with the expo-out ease.
  rise: {
    name: 'rise',
    from: { opacity: 0, y: 14 },
    to: { opacity: 1, y: 0 },
    duration: 0.6,
    ease: 'expo.out',
    stagger: 0.07,
  },
  // Per-word reveal for AnimatedHeading: a tighter, staggered fade up.
  words: {
    name: 'words',
    from: { opacity: 0, y: 18 },
    to: { opacity: 1, y: 0 },
    duration: 0.5,
    ease: 'expo.out',
    stagger: 0.045,
  },
  // Score bars / progress fills: grow horizontally (scaleX), matching the
  // reference `.score__fill` animation.
  growX: {
    name: 'growX',
    from: { scaleX: 0 },
    to: { scaleX: 1 },
    duration: 0.9,
    ease: 'expo.out',
    stagger: 0.07,
  },
} as const;
