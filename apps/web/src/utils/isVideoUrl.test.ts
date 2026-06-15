import { describe, expect, it } from 'vitest';
import { isVideoUrl } from './isVideoUrl';

describe('isVideoUrl', () => {
  it('returns true for youtube, youtu.be, vimeo and a direct .mp4 url', () => {
    expect(isVideoUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ')).toBe(true);
    expect(isVideoUrl('https://youtu.be/dQw4w9WgXcQ')).toBe(true);
    expect(isVideoUrl('https://vimeo.com/76979871')).toBe(true);
    expect(isVideoUrl('https://cdn.example.com/clips/raw.mp4')).toBe(true);
  });

  it('returns false for a non-url string', () => {
    expect(isVideoUrl('just some text')).toBe(false);
    expect(isVideoUrl('')).toBe(false);
  });

  it('returns false for non-video urls and non-http schemes', () => {
    expect(isVideoUrl('https://example.com/article')).toBe(false);
    expect(isVideoUrl('ftp://files.example.com/clip.mp4')).toBe(false);
  });
});
