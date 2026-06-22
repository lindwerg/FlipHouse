import { expect, test, vi } from 'vitest';

import {
  GpuSubmitError,
  buildSubmitBody,
  gpuSubmit,
  submitResponseSchema,
} from './gpu-submit.js';

const ARGS = {
  endpoint: 'https://gpu.example.com',
  requestId: '11111111-1111-1111-1111-111111111111',
  audioUrl: 'https://r2.example.com/presigned?sig=abc',
  webhookUrl: 'https://hook.example.com/gpu/callback',
  outputPrefix: 'intermediate/h/asr',
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

// ── buildSubmitBody ─────────────────────────────────────────────────────────

test('buildSubmitBody assembles the exact SUBMIT contract body', () => {
  expect(buildSubmitBody(ARGS)).toEqual({
    request_id: ARGS.requestId,
    audio_url: ARGS.audioUrl,
    language: 'ru',
    webhook_url: ARGS.webhookUrl,
    output_prefix: ARGS.outputPrefix,
  });
});

// ── submitResponseSchema ────────────────────────────────────────────────────

test('submitResponseSchema accepts an accepted sync response', () => {
  const body = { request_id: ARGS.requestId, status: 'accepted' };
  expect(submitResponseSchema.parse(body)).toEqual(body);
});

test('submitResponseSchema rejects a non-accepted status', () => {
  expect(submitResponseSchema.safeParse({ request_id: ARGS.requestId, status: 'queued' }).success).toBe(false);
});

// ── gpuSubmit ───────────────────────────────────────────────────────────────

test('gpuSubmit POSTs to <endpoint>/transcribe with the JSON body and returns the request_id', async () => {
  const fetchFn = vi.fn(async () => jsonResponse(200, { request_id: ARGS.requestId, status: 'accepted' }));

  const result = await gpuSubmit(ARGS, { fetchFn });

  expect(result).toBe(ARGS.requestId);
  expect(fetchFn).toHaveBeenCalledTimes(1);
  const [url, init] = fetchFn.mock.calls[0] as [string, RequestInit];
  expect(url).toBe('https://gpu.example.com/transcribe');
  expect(init.method).toBe('POST');
  expect(init.headers).toMatchObject({ 'content-type': 'application/json' });
  expect(JSON.parse(init.body as string)).toEqual(buildSubmitBody(ARGS));
});

test('gpuSubmit trims a trailing slash off the endpoint so the path is well-formed', async () => {
  const fetchFn = vi.fn(async () => jsonResponse(200, { request_id: ARGS.requestId, status: 'accepted' }));

  await gpuSubmit({ ...ARGS, endpoint: 'https://gpu.example.com/' }, { fetchFn });

  expect((fetchFn.mock.calls[0] as [string, RequestInit])[0]).toBe('https://gpu.example.com/transcribe');
});

test('gpuSubmit throws GpuSubmitError on a non-2xx response', async () => {
  const fetchFn = vi.fn(async () => jsonResponse(503, { error: 'overloaded' }));

  await expect(gpuSubmit(ARGS, { fetchFn })).rejects.toBeInstanceOf(GpuSubmitError);
  await expect(gpuSubmit(ARGS, { fetchFn })).rejects.toThrow(/503/);
});

test('gpuSubmit throws GpuSubmitError when the body fails the schema', async () => {
  const fetchFn = vi.fn(async () => jsonResponse(200, { request_id: ARGS.requestId, status: 'queued' }));

  await expect(gpuSubmit(ARGS, { fetchFn })).rejects.toBeInstanceOf(GpuSubmitError);
});

test('gpuSubmit throws GpuSubmitError when the response body is not JSON', async () => {
  const fetchFn = vi.fn(
    async () =>
      ({
        ok: true,
        status: 200,
        json: async () => {
          throw new Error('invalid json');
        },
        text: async () => 'not json',
      }) as unknown as Response,
  );

  await expect(gpuSubmit(ARGS, { fetchFn })).rejects.toBeInstanceOf(GpuSubmitError);
});

test('gpuSubmit wraps a transport-level fetch rejection in GpuSubmitError', async () => {
  const fetchFn = vi.fn(async () => {
    throw new Error('ECONNREFUSED');
  });

  await expect(gpuSubmit(ARGS, { fetchFn })).rejects.toThrow(/ECONNREFUSED/);
});

test('gpuSubmit stringifies a non-Error transport rejection', async () => {
  const fetchFn = vi.fn(async () => Promise.reject('socket hang up'));

  await expect(gpuSubmit(ARGS, { fetchFn })).rejects.toThrow(/socket hang up/);
});
