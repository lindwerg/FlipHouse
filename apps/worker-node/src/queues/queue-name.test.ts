import { describe, expect, test } from 'vitest';

import { resolveQueue } from './queue-name.js';

// Queue mapping is the BullMQ contract from docs/01 §5 (stage → queue name).
// Founder decision (P0.8): follow the authoritative §5 table, not the roadmap's
// loosely-worded example (transcode→cpu was wrong).
describe('resolveQueue', () => {
  test('resolveQueue maps transcode stage to transcode queue', () => {
    expect(resolveQueue('transcode')).toBe('transcode');
  });

  test('resolveQueue maps asr stage to gpu-asr queue', () => {
    expect(resolveQueue('asr')).toBe('gpu-asr');
  });

  test('resolveQueue maps score stage to gpu-score queue', () => {
    expect(resolveQueue('score')).toBe('gpu-score');
  });

  test('resolveQueue maps cpu-tier stages (fanout,reframe,caption,banner,store) to cpu queue', () => {
    expect(resolveQueue('fanout')).toBe('cpu');
    expect(resolveQueue('reframe')).toBe('cpu');
    expect(resolveQueue('caption')).toBe('cpu');
    expect(resolveQueue('banner')).toBe('cpu');
    expect(resolveQueue('store')).toBe('cpu');
  });

  test('resolveQueue maps publish stage to publish queue', () => {
    expect(resolveQueue('publish')).toBe('publish');
  });

  test('resolveQueue throws on unknown stage', () => {
    // @ts-expect-error — unknown stage is rejected at runtime (boundary validation).
    expect(() => resolveQueue('nonsense')).toThrow(/unknown stage/i);
  });
});
