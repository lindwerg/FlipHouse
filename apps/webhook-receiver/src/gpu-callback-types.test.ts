import { expect, test } from 'vitest';

import { gpuCallbackSchema } from './gpu-callback-types.js';

const REQUEST_ID = '11111111-2222-4333-8444-555555555555';

function succeededBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    request_id: REQUEST_ID,
    status: 'succeeded',
    engine: 'gigaam-v3',
    payload: {
      duration: 12.5,
      language: 'ru',
      segments: [
        {
          start: 0,
          end: 1.2,
          words: [{ word: 'привет', start: 0, end: 0.6 }],
        },
      ],
    },
    ...overrides,
  };
}

test('accepts a well-formed succeeded callback', () => {
  const parsed = gpuCallbackSchema.parse(succeededBody());
  expect(parsed.status).toBe('succeeded');
  if (parsed.status === 'succeeded') {
    expect(parsed.payload.language).toBe('ru');
    expect(parsed.payload.segments[0]?.words[0]?.word).toBe('привет');
  }
});

test('retains the optional punctuated segment text (TRANS-1)', () => {
  // Zod strips unknown keys, so `text` MUST be in the schema or it is dropped on
  // the verbatim R2 persist — discarding the native sentence-boundary signal.
  const body = succeededBody({
    payload: {
      duration: 1.2,
      language: 'ru',
      segments: [
        {
          start: 0,
          end: 1.2,
          text: 'Привет, мир.',
          words: [{ word: 'привет', start: 0, end: 0.6 }],
        },
      ],
    },
  });
  const parsed = gpuCallbackSchema.parse(body);
  if (parsed.status === 'succeeded') {
    expect(parsed.payload.segments[0]?.text).toBe('Привет, мир.');
  }
});

test('accepts a legacy segment without text (additive/backward-compatible)', () => {
  const parsed = gpuCallbackSchema.parse(succeededBody());
  if (parsed.status === 'succeeded') {
    expect(parsed.payload.segments[0]?.text).toBeUndefined();
  }
});

test('accepts a well-formed failed callback', () => {
  const parsed = gpuCallbackSchema.parse({
    request_id: REQUEST_ID,
    status: 'failed',
    error: 'gpu OOM',
  });
  expect(parsed.status).toBe('failed');
  if (parsed.status === 'failed') {
    expect(parsed.error).toBe('gpu OOM');
  }
});

test('rejects a non-uuid request_id', () => {
  expect(() => gpuCallbackSchema.parse(succeededBody({ request_id: 'not-a-uuid' }))).toThrow();
});

test('rejects an unknown status', () => {
  expect(() =>
    gpuCallbackSchema.parse({ request_id: REQUEST_ID, status: 'canceled', error: 'x' }),
  ).toThrow();
});

test('rejects a wrong engine on a succeeded callback', () => {
  expect(() => gpuCallbackSchema.parse(succeededBody({ engine: 'whisper' }))).toThrow();
});

test('rejects a non-ru language', () => {
  expect(() =>
    gpuCallbackSchema.parse(
      succeededBody({
        payload: { duration: 1, language: 'en', segments: [] },
      }),
    ),
  ).toThrow();
});

test('rejects a segment word missing its timestamps', () => {
  expect(() =>
    gpuCallbackSchema.parse(
      succeededBody({
        payload: {
          duration: 1,
          language: 'ru',
          segments: [{ start: 0, end: 1, words: [{ word: 'x', start: 0 }] }],
        },
      }),
    ),
  ).toThrow();
});

test('rejects a failed callback missing its error', () => {
  expect(() => gpuCallbackSchema.parse({ request_id: REQUEST_ID, status: 'failed' })).toThrow();
});
