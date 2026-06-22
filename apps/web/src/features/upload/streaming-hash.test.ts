import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { hashStream } from './streaming-hash';

// Reference digest computed exactly as packages/shared `sha256Hex` does
// (createHash('sha256').update(bytes).digest('hex')). Equality with that
// algorithm is the load-bearing contract: tusd's post-finish hook claims the
// ledger by this hash, so the client digest must match a server re-verify.
function sha256Hex(bytes: Uint8Array): string {
  return createHash('sha256').update(bytes).digest('hex');
}

// Build a ReadableStream<Uint8Array> that emits `chunks` in order, so the test
// can drive the pure streaming-hash path with no File/Worker/browser involved.
function streamOf(chunks: ReadonlyArray<Uint8Array>): ReadableStream<Uint8Array> {
  let index = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(chunks[index]!);
        index += 1;
      } else {
        controller.close();
      }
    },
  });
}

function bytes(...values: number[]): Uint8Array {
  return Uint8Array.from(values);
}

describe('hashStream', () => {
  it('hashes a single-chunk stream to the same digest as shared sha256Hex', async () => {
    const data = bytes(1, 2, 3, 4, 5);

    const digest = await hashStream(streamOf([data]));

    expect(digest).toBe(sha256Hex(data));
  });

  it('hashes a multi-chunk stream identically to the concatenated bytes', async () => {
    const a = bytes(10, 20, 30);
    const b = bytes(40, 50);
    const c = bytes(60, 70, 80, 90);
    const whole = bytes(10, 20, 30, 40, 50, 60, 70, 80, 90);

    const digest = await hashStream(streamOf([a, b, c]));

    expect(digest).toBe(sha256Hex(whole));
  });

  it('hashes an empty stream to the sha256 of zero bytes', async () => {
    const digest = await hashStream(streamOf([]));

    expect(digest).toBe(sha256Hex(new Uint8Array(0)));
  });

  it('returns a 64-char lowercase hex digest', async () => {
    const digest = await hashStream(streamOf([bytes(1, 2, 3)]));

    expect(digest).toMatch(/^[0-9a-f]{64}$/);
  });

  it('skips a chunk that reads as undefined (defensive boundary guard)', async () => {
    // A pathological reader that yields one `{done:false, value:undefined}` read
    // before closing — exercises the `value !== undefined` guard's false branch.
    let emitted = false;
    const stream = {
      getReader() {
        return {
          async read(): Promise<ReadableStreamReadResult<Uint8Array>> {
            if (!emitted) {
              emitted = true;
              return { done: false, value: undefined as unknown as Uint8Array };
            }
            return { done: true, value: undefined };
          },
          releaseLock() {},
        };
      },
    } as unknown as ReadableStream<Uint8Array>;

    const digest = await hashStream(stream);

    expect(digest).toBe(sha256Hex(new Uint8Array(0)));
  });

  it('releases the reader lock so the stream can be inspected after hashing', async () => {
    const stream = streamOf([bytes(9, 9, 9)]);

    await hashStream(stream);

    // A locked stream throws on getReader(); a released one does not.
    expect(() => stream.getReader()).not.toThrow();
  });
});
