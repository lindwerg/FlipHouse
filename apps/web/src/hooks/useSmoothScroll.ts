'use client';

import { useEffect } from 'react';
import { REVEAL_CONFIGS } from '@/utils/scrollReveal';

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
const REVEAL_START = 'top 85%';

type GsapModule = typeof import('gsap')['gsap'];
type ScrollTriggerModule = typeof import('gsap/ScrollTrigger')['ScrollTrigger'];

type RevealGroup = {
  trigger: HTMLElement;
  targets: HTMLElement[];
  config: (typeof REVEAL_CONFIGS)[string];
};

function configFor(name: string | undefined) {
  return (name && REVEAL_CONFIGS[name]) || REVEAL_CONFIGS.rise!;
}

// Collects the reveal groups on the page. Three mechanisms, all
// compositor-only:
//   • per-word hero/closer headings — every [data-slot="word"] inside an
//     [data-slot="animated-heading"], staggered;
//   • staggered groups — a [data-reveal-group] container whose [data-reveal-item]
//     descendants reveal together (the container itself is never hidden);
//   • standalone — a self-revealing [data-reveal] element.
function collectGroups(): RevealGroup[] {
  const groups: RevealGroup[] = [];

  for (const heading of document.querySelectorAll<HTMLElement>(
    '[data-slot="animated-heading"]',
  )) {
    const words = heading.querySelectorAll<HTMLElement>('[data-slot="word"]');
    if (words.length > 0) {
      groups.push({ trigger: heading, targets: [...words], config: REVEAL_CONFIGS.words! });
    }
  }

  for (const group of document.querySelectorAll<HTMLElement>('[data-reveal-group]')) {
    const items = group.querySelectorAll<HTMLElement>('[data-reveal-item]');
    if (items.length > 0) {
      groups.push({ trigger: group, targets: [...items], config: configFor(group.dataset.revealGroup) });
    }
  }

  for (const el of document.querySelectorAll<HTMLElement>('[data-reveal]')) {
    groups.push({ trigger: el, targets: [el], config: configFor(el.dataset.reveal) });
  }

  return groups;
}

function buildReveals(gsap: GsapModule, ScrollTrigger: ScrollTriggerModule) {
  for (const { trigger, targets, config } of collectGroups()) {
    // Apply the hidden from-state up front (motion is allowed here, so this can
    // never strand content invisible for reduced-motion users).
    gsap.set(targets, { ...config.from, willChange: 'transform, opacity' });

    const tween = gsap.to(targets, {
      ...config.to,
      duration: config.duration,
      ease: config.ease,
      stagger: config.stagger,
      paused: true,
      onComplete: () => gsap.set(targets, { willChange: 'auto' }),
    });

    ScrollTrigger.create({
      trigger,
      start: REVEAL_START,
      once: true,
      onEnter: () => tween?.play?.(),
    });
  }
}

/**
 * Drives the landing scroll-storytelling: smooth scrolling via Lenis synced to
 * gsap.ticker, plus compositor-only reveal tweens (scrollReveal configs) wired
 * to ScrollTrigger. Honors `prefers-reduced-motion` — when reduced, nothing is
 * initialized and the page keeps native scrolling with all content visible.
 * GSAP/Lenis are loaded via dynamic import() so they stay out of the initial
 * bundle.
 */
export function useSmoothScroll(): void {
  useEffect(() => {
    if (window.matchMedia(REDUCED_MOTION_QUERY).matches) {
      return;
    }

    let cancelled = false;
    let lenis: import('lenis').default | undefined;
    let tickerFn: ((time: number) => void) | undefined;
    let gsapRef: GsapModule | undefined;
    let scrollTriggerRef: ScrollTriggerModule | undefined;

    (async () => {
      const [{ default: Lenis }, { gsap }, { ScrollTrigger }] = await Promise.all([
        import('lenis'),
        import('gsap'),
        import('gsap/ScrollTrigger'),
      ]);
      if (cancelled) {
        return;
      }

      gsapRef = gsap;
      scrollTriggerRef = ScrollTrigger;
      gsap.registerPlugin(ScrollTrigger);

      lenis = new Lenis();
      lenis.on('scroll', ScrollTrigger.update);
      tickerFn = (time: number) => lenis!.raf(time * 1000);
      gsap.ticker.add(tickerFn);
      gsap.ticker.lagSmoothing(0);

      buildReveals(gsap, ScrollTrigger);
    })();

    return () => {
      cancelled = true;
      if (gsapRef && tickerFn) {
        gsapRef.ticker.remove(tickerFn);
      }
      scrollTriggerRef?.getAll().forEach(trigger => trigger.kill());
      lenis?.destroy();
    };
  }, []);
}
