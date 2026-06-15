// @vitest-environment jsdom
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ScrollProvider } from './ScrollProvider';

// Mock the hook so this stays a deterministic unit test — no GSAP/Lenis dynamic
// imports or rAF loop. The hook itself is covered by useSmoothScroll.test.tsx.
const useSmoothScroll = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/useSmoothScroll', () => ({ useSmoothScroll }));

describe('ScrollProvider', () => {
  it('runs the smooth-scroll hook and renders nothing', () => {
    const { container } = render(<ScrollProvider />);

    expect(useSmoothScroll).toHaveBeenCalledTimes(1);
    expect(container).toBeEmptyDOMElement();
  });
});
