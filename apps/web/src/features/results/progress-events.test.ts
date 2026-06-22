import { describe, expect, it } from 'vitest';
import { buildProgressEvent } from './progress-events';

describe('buildProgressEvent', () => {
  it('builds a progress event for an in-flight status with the monotonic ordinal id', () => {
    const event = buildProgressEvent('scoring');

    expect(event.ordinal).toBe(4);
    expect(event.isTerminal).toBe(false);
    expect(event.payload.status).toBe('scoring');
    expect(event.payload.percent).toBeGreaterThan(0);
    expect(event.frame).toContain('id: 4');
    expect(event.frame).toContain('event: progress');
    expect(event.frame.endsWith('\n\n')).toBe(true);
  });

  it('builds a terminal done event with the done event name and 100%', () => {
    const event = buildProgressEvent('done');

    expect(event.isTerminal).toBe(true);
    expect(event.ordinal).toBe(10);
    expect(event.payload.percent).toBe(100);
    expect(event.frame).toContain('event: done');
  });

  it('marks failed and duplicate as terminal done events', () => {
    expect(buildProgressEvent('failed').isTerminal).toBe(true);
    expect(buildProgressEvent('failed').frame).toContain('event: done');
    expect(buildProgressEvent('duplicate').isTerminal).toBe(true);
  });
});
