// @vitest-environment jsdom
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSmoothScroll } from './useSmoothScroll';

// Shared mock instances captured via vi.hoisted so the (hoisted) vi.mock
// factories below can reference them. gsap/lenis are pulled in by the hook
// through dynamic import(); these mocks intercept those module specifiers so no
// real animation engine or rAF loop runs in jsdom.
const mocks = vi.hoisted(() => {
  const ticker = { add: vi.fn(), remove: vi.fn(), lagSmoothing: vi.fn() };
  const killable = { kill: vi.fn() };
  const tween = { play: vi.fn() };
  const scrollTrigger = {
    update: vi.fn(),
    // Typed params so the test can read back the ScrollTrigger config it built.
    create: vi.fn((_config: { trigger?: unknown; onEnter?: () => void }) => killable),
    getAll: vi.fn(() => [killable]),
  };
  const gsap = {
    ticker,
    registerPlugin: vi.fn(),
    to: vi.fn(
      (_targets: unknown, _vars: { onComplete?: () => void; [key: string]: unknown }) => tween,
    ),
    set: vi.fn(),
  };
  const lenisInstance = { on: vi.fn(), raf: vi.fn(), destroy: vi.fn() };
  // Lenis is `new`-ed by the hook; a constructable mock (a class returning the
  // shared instance) is required — an arrow vi.fn is not constructable (mirrors
  // the ioredis mock in src/libs/Redis.test.ts).
  class LenisMock {
    constructor() {
      return lenisInstance;
    }
  }
  const Lenis = vi.fn(LenisMock);
  return { gsap, scrollTrigger, lenisInstance, Lenis, tween, killable };
});

vi.mock('gsap', () => ({ gsap: mocks.gsap }));
vi.mock('gsap/ScrollTrigger', () => ({ ScrollTrigger: mocks.scrollTrigger }));
vi.mock('lenis', () => ({ default: mocks.Lenis }));

function setReducedMotion(reduced: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduced,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

beforeEach(() => {
  vi.clearAllMocks();
  setReducedMotion(false);
});

afterEach(() => {
  document.body.innerHTML = '';
});

describe('useSmoothScroll', () => {
  it('initializes Lenis and registers gsap ticker sync', async () => {
    renderHook(() => useSmoothScroll());

    await waitFor(() => expect(mocks.Lenis).toHaveBeenCalled());
    expect(mocks.gsap.ticker.add).toHaveBeenCalledWith(expect.any(Function));
    expect(mocks.lenisInstance.on).toHaveBeenCalledWith(
      'scroll',
      expect.any(Function),
    );
  });

  it('does not initialize Lenis when reduced motion preferred', async () => {
    setReducedMotion(true);

    renderHook(() => useSmoothScroll());

    // Give any (incorrectly scheduled) async init a chance to run.
    await Promise.resolve();
    expect(mocks.Lenis).not.toHaveBeenCalled();
    expect(mocks.gsap.ticker.add).not.toHaveBeenCalled();
  });

  it('cleans up ticker and lenis on unmount', async () => {
    const { unmount } = renderHook(() => useSmoothScroll());

    await waitFor(() => expect(mocks.Lenis).toHaveBeenCalled());
    unmount();

    await waitFor(() => {
      expect(mocks.gsap.ticker.remove).toHaveBeenCalled();
      expect(mocks.lenisInstance.destroy).toHaveBeenCalled();
    });
    // Every ScrollTrigger created by the hook is killed on teardown.
    expect(mocks.killable.kill).toHaveBeenCalled();
  });

  it('aborts init and skips Lenis when unmounted before modules load', async () => {
    const { unmount } = renderHook(() => useSmoothScroll());
    // Unmount synchronously — before the dynamic import()s resolve. The async
    // init must see the cancelled flag and never construct Lenis or add a ticker.
    unmount();

    await new Promise(resolve => setTimeout(resolve, 0));
    expect(mocks.Lenis).not.toHaveBeenCalled();
    expect(mocks.gsap.ticker.add).not.toHaveBeenCalled();
  });

  it('builds reveal tweens for [data-reveal] targets in the document', async () => {
    document.body.innerHTML = `
      <section data-reveal="rise"><p>one</p></section>
      <section data-reveal="rise"><p>two</p></section>
    `;

    renderHook(() => useSmoothScroll());

    await waitFor(() => expect(mocks.gsap.to).toHaveBeenCalled());
    expect(mocks.scrollTrigger.create).toHaveBeenCalled();
    expect(mocks.gsap.set).toHaveBeenCalled();

    // Drive the reveal callbacks the way ScrollTrigger/GSAP would at runtime:
    // entering the viewport plays the paused tween, and tween completion resets
    // will-change. Both run only compositor-only work.
    const createArg = mocks.scrollTrigger.create.mock.calls[0]![0];
    createArg.onEnter?.();
    expect(mocks.tween.play).toHaveBeenCalled();

    const toArg = mocks.gsap.to.mock.calls[0]![1];
    toArg.onComplete?.();
    expect(mocks.gsap.set).toHaveBeenCalledWith(expect.anything(), {
      willChange: 'auto',
    });
  });
});
