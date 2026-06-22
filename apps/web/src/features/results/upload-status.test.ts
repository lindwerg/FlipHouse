import { describe, expect, it } from 'vitest';
import {
  statusOrdinal,
  statusToProgress,
  UPLOAD_STATUSES,
} from './upload-status';

describe('statusOrdinal', () => {
  it('returns the monotonic index of each status (queued first)', () => {
    expect(statusOrdinal('queued')).toBe(0);
    expect(statusOrdinal('hashing')).toBe(1);
    expect(statusOrdinal('publishing')).toBe(9);
    expect(statusOrdinal('done')).toBe(10);
  });

  it('increases monotonically across the forward-only order', () => {
    const ordinals = UPLOAD_STATUSES.map((s) => statusOrdinal(s));
    const sorted = [...ordinals].sort((a, b) => a - b);
    expect(ordinals).toEqual(sorted);
  });
});

describe('statusToProgress', () => {
  it('reports 0% for queued and a Russian label', () => {
    const p = statusToProgress('queued');
    expect(p.percent).toBe(0);
    expect(p.label).toBe('В очереди');
    expect(p.isTerminal).toBe(false);
  });

  it('caps the last pre-terminal stage (publishing) at 95%, never 100%', () => {
    const p = statusToProgress('publishing');
    expect(p.percent).toBe(95);
    expect(p.isTerminal).toBe(false);
  });

  it('spreads mid stages between 0 and 95', () => {
    const scoring = statusToProgress('scoring');
    expect(scoring.percent).toBeGreaterThan(0);
    expect(scoring.percent).toBeLessThan(95);
  });

  it('reports done as 100% terminal with the готово label', () => {
    const p = statusToProgress('done');
    expect(p.percent).toBe(100);
    expect(p.isTerminal).toBe(true);
    expect(p.label).toBe('Готово');
  });

  it('treats failed and duplicate as terminal at 100%', () => {
    expect(statusToProgress('failed')).toEqual({
      percent: 100,
      label: 'Ошибка обработки',
      isTerminal: true,
    });
    expect(statusToProgress('duplicate').isTerminal).toBe(true);
    expect(statusToProgress('duplicate').label).toBe('Это видео уже обрабатывалось');
  });
});
