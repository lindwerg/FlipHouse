import { describe, expect, it } from 'vitest';
import { mmss, rankLabel, scoreBarWidth } from './format';

describe('mmss', () => {
  it('formats seconds as m:ss with a zero-padded seconds field', () => {
    expect(mmss(41.5)).toBe('0:41');
    expect(mmss(5)).toBe('0:05');
    expect(mmss(754)).toBe('12:34');
  });

  it('clamps negative input to 0:00', () => {
    expect(mmss(-3)).toBe('0:00');
  });
});

describe('rankLabel', () => {
  it('renders a zero-based rank as a two-digit one-based label', () => {
    expect(rankLabel(0)).toBe('01');
    expect(rankLabel(9)).toBe('10');
  });
});

describe('scoreBarWidth', () => {
  it('rounds and clamps a score to a 0-100 width', () => {
    expect(scoreBarWidth(87.5)).toBe(88);
    expect(scoreBarWidth(-5)).toBe(0);
    expect(scoreBarWidth(140)).toBe(100);
  });
});
