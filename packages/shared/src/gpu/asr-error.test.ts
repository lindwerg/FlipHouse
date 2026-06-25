import { describe, expect, it } from 'vitest';

import {
  GIGAAM_AUTH_ERROR_PREFIX,
  GIGAAM_AUTH_FAIL_REASON,
  classifyAsrFailReason,
  isGigaamAuthError,
} from './asr-error.js';

describe('isGigaamAuthError', () => {
  it('is true for the auth-prefixed error', () => {
    expect(isGigaamAuthError(`${GIGAAM_AUTH_ERROR_PREFIX} 403 gated`)).toBe(true);
  });

  it('is false for a plain transcription fault', () => {
    expect(isGigaamAuthError('cuda oom')).toBe(false);
  });
});

describe('classifyAsrFailReason', () => {
  it('maps an auth-class fault to the distinct operator reason and keeps the detail', () => {
    const out = classifyAsrFailReason(`${GIGAAM_AUTH_ERROR_PREFIX} 401 unauthorized`);
    expect(out).toContain(GIGAAM_AUTH_FAIL_REASON);
    expect(out).toContain('401 unauthorized');
  });

  it('uses the bare reason when no detail trails the prefix', () => {
    const out = classifyAsrFailReason(GIGAAM_AUTH_ERROR_PREFIX);
    expect(out).toBe(GIGAAM_AUTH_FAIL_REASON);
  });

  it('passes a non-auth fault through verbatim', () => {
    expect(classifyAsrFailReason('ffmpeg decode failed')).toBe('ffmpeg decode failed');
  });
});
