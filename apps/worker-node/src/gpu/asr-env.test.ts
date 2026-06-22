import { expect, test } from 'vitest';

import {
  AsrEnvError,
  ENGINE_GIGAAM_V3,
  WEBHOOK_CALLBACK_PATH,
  isGpuAsrEnabled,
  resolveAsrEnv,
  webhookCallbackUrl,
} from './asr-env.js';

const FULL = {
  GPU_ASR_ENABLED: 'true',
  GIGAAM_ENDPOINT: 'https://gpu.example.com',
  GIGAAM_WEBHOOK_SECRET: 's3cr3t',
  WEBHOOK_PUBLIC_URL: 'https://hook.example.com',
};

// ── isGpuAsrEnabled ─────────────────────────────────────────────────────────

test('isGpuAsrEnabled is true ONLY for the exact string "true"', () => {
  expect(isGpuAsrEnabled({ GPU_ASR_ENABLED: 'true' })).toBe(true);
  expect(isGpuAsrEnabled({ GPU_ASR_ENABLED: 'TRUE' })).toBe(false);
  expect(isGpuAsrEnabled({ GPU_ASR_ENABLED: '1' })).toBe(false);
  expect(isGpuAsrEnabled({ GPU_ASR_ENABLED: '' })).toBe(false);
  expect(isGpuAsrEnabled({})).toBe(false);
});

// ── resolveAsrEnv: disabled ─────────────────────────────────────────────────

test('resolveAsrEnv returns a disabled config when the flag is off (no other vars needed)', () => {
  expect(resolveAsrEnv({})).toEqual({ enabled: false });
  expect(resolveAsrEnv({ GPU_ASR_ENABLED: 'false' })).toEqual({ enabled: false });
});

// ── resolveAsrEnv: enabled ──────────────────────────────────────────────────

test('resolveAsrEnv returns a fully-typed enabled config when every var is present', () => {
  expect(resolveAsrEnv(FULL)).toEqual({
    enabled: true,
    endpoint: 'https://gpu.example.com',
    webhookSecret: 's3cr3t',
    webhookPublicUrl: 'https://hook.example.com',
  });
});

test.each([
  ['GIGAAM_ENDPOINT'],
  ['GIGAAM_WEBHOOK_SECRET'],
  ['WEBHOOK_PUBLIC_URL'],
])('resolveAsrEnv throws AsrEnvError naming a missing %s at boot when enabled', (missing) => {
  const env = { ...FULL, [missing]: '' };
  expect(() => resolveAsrEnv(env)).toThrow(AsrEnvError);
  expect(() => resolveAsrEnv(env)).toThrow(new RegExp(missing));
});

// ── webhookCallbackUrl ──────────────────────────────────────────────────────

test('webhookCallbackUrl joins the base with the /gpu/callback path, trimming a trailing slash', () => {
  expect(webhookCallbackUrl('https://hook.example.com')).toBe(
    `https://hook.example.com${WEBHOOK_CALLBACK_PATH}`,
  );
  expect(webhookCallbackUrl('https://hook.example.com/')).toBe(
    `https://hook.example.com${WEBHOOK_CALLBACK_PATH}`,
  );
});

test('ENGINE_GIGAAM_V3 is the gigaam-v3 engine tag', () => {
  expect(ENGINE_GIGAAM_V3).toBe('gigaam-v3');
});
