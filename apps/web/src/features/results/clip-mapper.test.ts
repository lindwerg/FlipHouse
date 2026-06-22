import type { ClipDashboardRow } from '@fliphouse/db';
import { describe, expect, it, vi } from 'vitest';
import { toClipView } from './clip-mapper';

// The clip URL is a server-side presign; mock the seam so this test asserts the
// row→view projection (numeric coercions + awaited URL), not AWS behaviour.
vi.mock('./url', () => ({
  toClipUrl: vi.fn(async (key: string) => `https://signed.example.com/${key}`),
}));

const ROW: ClipDashboardRow = {
  rank: 0,
  score: '87.5000',
  startTime: '12.000',
  endTime: '41.500',
  durationS: '29.500',
  width: 1080,
  height: 1920,
  clipUrl: 'clips/abc/clip_00.mp4',
  title: 'best',
};

describe('toClipView', () => {
  it('coerces numeric-string columns to numbers and resolves the presigned URL', async () => {
    const view = await toClipView(ROW);

    expect(view.score).toBe(87.5);
    expect(view.startTime).toBe(12);
    expect(view.endTime).toBe(41.5);
    expect(view.durationS).toBe(29.5);
    expect(view.width).toBe(1080);
    expect(view.height).toBe(1920);
    expect(view.rank).toBe(0);
    expect(view.title).toBe('best');
    expect(view.clipUrl).toBe('https://signed.example.com/clips/abc/clip_00.mp4');
  });
});
