import { describe, expect, it } from 'vitest';
import { buildSseFrame, sseResume } from './progress-stream';

describe('buildSseFrame', () => {
  it('serialises a monotonic id, event name and JSON data with a blank-line terminator', () => {
    const frame = buildSseFrame({ id: 4, event: 'progress', data: { percent: 50 } });
    expect(frame).toBe('id: 4\nevent: progress\ndata: {"percent":50}\n\n');
  });

  it('JSON-encodes nested data on a single data line', () => {
    const frame = buildSseFrame({ id: 10, event: 'done', data: { status: 'done', clips: 3 } });
    expect(frame).toContain('data: {"status":"done","clips":3}');
    expect(frame.endsWith('\n\n')).toBe(true);
  });
});

describe('sseResume', () => {
  it('emits when the current ordinal is strictly greater than Last-Event-ID', () => {
    expect(sseResume('2', 3)).toBe(true);
  });

  it('does not emit when the client already saw this or a later ordinal', () => {
    expect(sseResume('3', 3)).toBe(false);
    expect(sseResume('5', 3)).toBe(false);
  });

  it('treats a missing/blank/non-numeric header as "seen nothing" (always emits)', () => {
    expect(sseResume(null, 0)).toBe(true);
    expect(sseResume(undefined, 0)).toBe(true);
    expect(sseResume('', 0)).toBe(true);
    expect(sseResume('not-a-number', 0)).toBe(true);
  });
});
