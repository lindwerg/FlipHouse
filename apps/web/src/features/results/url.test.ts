import { describe, expect, it } from 'vitest';
import { toClipUrl } from './url';

// NEXT_PUBLIC_R2_PUBLIC_BASE is 'https://clips.example.com' in TEST_ENV_DEFAULTS.
describe('toClipUrl', () => {
  it('joins the public base and the object key with a single slash', () => {
    expect(toClipUrl('clips/abc/clip_00.mp4')).toBe(
      'https://clips.example.com/clips/abc/clip_00.mp4',
    );
  });

  it('normalises a leading slash on the key so it never doubles //', () => {
    expect(toClipUrl('/clips/abc/clip_00.mp4')).toBe(
      'https://clips.example.com/clips/abc/clip_00.mp4',
    );
  });
});
