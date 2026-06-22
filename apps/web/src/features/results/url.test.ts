import { describe, expect, it, vi } from 'vitest';
import { toClipUrl } from './url';

// toClipUrl now delegates to the presign seam; assert the delegation rather than
// a concat (the presign LOGIC itself is covered in r2-presign.test.ts).
vi.mock('./r2-presign', () => ({
  presignClipUrl: vi.fn(async (key: string) => `signed:${key}`),
}));

describe('toClipUrl', () => {
  it('delegates the object key to presignClipUrl and returns its presigned URL', async () => {
    await expect(toClipUrl('clips/abc/clip_00.mp4')).resolves.toBe(
      'signed:clips/abc/clip_00.mp4',
    );
  });
});
