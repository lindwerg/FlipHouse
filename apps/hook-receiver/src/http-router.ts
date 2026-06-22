import type { PostFinishOutcome } from './handle-post-finish.js';

/**
 * Cap on a tusd hook body. The envelope is tiny metadata (no file bytes flow
 * through this hook), so anything large is malformed or hostile — we refuse it
 * rather than buffer unbounded memory.
 */
export const MAX_BODY_BYTES = 65_536;

/**
 * Project a {@link PostFinishOutcome} onto the HTTP status tusd should see.
 * `enqueued` and `duplicate` are both SUCCESS — tusd must NOT retry a hook whose
 * work is already durably claimed (idempotency authority is the ledger, not the
 * delivery). Client-contract violations are distinct 4xx (never a transient 5xx
 * tusd would retry): `invalid-payload` (bad envelope) → 400; `missing-owner` and
 * `hash-required` (semantically unprocessable) → 422.
 */
export function mapOutcomeToStatus(outcome: PostFinishOutcome): number {
  switch (outcome.kind) {
    case 'enqueued':
    case 'duplicate':
      return 200;
    case 'invalid-payload':
      return 400;
    case 'missing-owner':
    case 'hash-required':
      return 422;
  }
}

/**
 * Buffer a readable request body and JSON.parse it, with a hard {@link
 * MAX_BODY_BYTES} ceiling. Rejects on overflow, malformed JSON, or a stream
 * error — every failure surfaces to the caller instead of being swallowed.
 */
export function parseRequestBody(stream: NodeJS.ReadableStream): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;

    stream.on('data', (chunk: Buffer) => {
      total += chunk.length;
      if (total > MAX_BODY_BYTES) {
        reject(new Error('request body too large'));
        return;
      }
      chunks.push(chunk);
    });

    stream.on('end', () => {
      // JSON.parse only ever throws a SyntaxError (an Error), so a thrown value
      // can be forwarded straight to reject without an instanceof narrowing.
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch (error) {
        reject(error as Error);
      }
    });

    stream.on('error', reject);
  });
}
