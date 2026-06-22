/* v8 ignore start -- Web Worker entry. Runs only in a real Worker context (not
   jsdom/node), so it is covered by E2E rather than unit tests. It delegates the
   actual hashing to the unit-tested streaming-hash.ts. */
import { hashStream } from './streaming-hash';

// Off-main-thread content hashing: the dashboard posts the selected File here,
// we stream its bytes through SHA-256 without blocking the UI, and post back the
// 64-char hex digest. A failure is reported as an `error` string so the caller
// rejects cleanly instead of hanging.
self.addEventListener('message', async (event: MessageEvent<File>) => {
  try {
    const digest = await hashStream(event.data.stream());
    self.postMessage({ digest });
  } catch (error) {
    self.postMessage({
      error: error instanceof Error ? error.message : 'hash worker failed',
    });
  }
});
/* v8 ignore stop */
