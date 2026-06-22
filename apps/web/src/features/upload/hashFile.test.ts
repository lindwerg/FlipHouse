import { createHash } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import { HASH_INVALID_ERROR, hashFile } from './hashFile';

function sha256Hex(bytes: Uint8Array): string {
  return createHash('sha256').update(bytes).digest('hex');
}

// A File whose .stream() yields the given bytes — drives the in-process runner
// fallback without a browser File implementation.
function fakeFile(bytes: Uint8Array, name = 'clip.mp4', type = 'video/mp4'): File {
  return {
    name,
    type,
    size: bytes.length,
    stream(): ReadableStream<Uint8Array> {
      return new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(bytes);
          controller.close();
        },
      });
    },
  } as unknown as File;
}

describe('hashFile', () => {
  it('hashes a file via the in-process runner to the shared sha256', async () => {
    const bytes = Uint8Array.from([1, 2, 3, 4]);
    const file = fakeFile(bytes);

    const digest = await hashFile(file, { runInProcess: true });

    expect(digest).toBe(sha256Hex(bytes));
  });

  it('uses an injected runner and returns its 64-char hex digest', async () => {
    const expected = 'a'.repeat(64);
    const runner = vi.fn().mockResolvedValue(expected);
    const file = fakeFile(Uint8Array.from([9]));

    const digest = await hashFile(file, { runner });

    expect(runner).toHaveBeenCalledWith(file);
    expect(digest).toBe(expected);
  });

  it('throws HASH_INVALID_ERROR when the runner returns a non-hex digest', async () => {
    const runner = vi.fn().mockResolvedValue('not-a-valid-hash');
    const file = fakeFile(Uint8Array.from([1]));

    await expect(hashFile(file, { runner })).rejects.toThrow(HASH_INVALID_ERROR);
  });

  it('throws HASH_INVALID_ERROR when the runner returns an uppercase digest', async () => {
    const runner = vi.fn().mockResolvedValue('A'.repeat(64));
    const file = fakeFile(Uint8Array.from([1]));

    await expect(hashFile(file, { runner })).rejects.toThrow(HASH_INVALID_ERROR);
  });

  it('falls through to the default Worker runner when given no options', async () => {
    // Exercises the no-runner/no-runInProcess branch (the production default).
    // A fake global Worker posts back a valid digest so the round-trip resolves
    // without a real Worker thread.
    const expected = 'b'.repeat(64);
    class FakeWorker {
      private handler: ((event: MessageEvent) => void) | null = null;
      addEventListener(type: string, handler: (event: MessageEvent) => void): void {
        if (type === 'message') {
          this.handler = handler;
        }
      }

      postMessage(): void {
        this.handler?.({ data: { digest: expected } } as MessageEvent);
      }

      terminate(): void {}
    }
    const original = globalThis.Worker;
    (globalThis as { Worker?: unknown }).Worker = FakeWorker;
    try {
      const digest = await hashFile(fakeFile(Uint8Array.from([7])));

      expect(digest).toBe(expected);
    } finally {
      (globalThis as { Worker?: unknown }).Worker = original;
    }
  });
});
