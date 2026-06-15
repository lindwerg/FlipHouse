import { redis } from '@/libs/Redis';

// The watcher tracks the last block height it has processed so each tick scans
// only new blocks. Injectable so integration tests use an in-memory store and
// production uses Redis — the watcher core never reads a singleton directly.

export type CursorStore = {
  getLastBlock: () => Promise<number | null>;
  setLastBlock: (block: number) => Promise<void>;
};

/** In-memory cursor for tests. Not shared across instances. */
export function inMemoryCursorStore(initial?: number): CursorStore {
  let lastBlock: number | null = initial ?? null;
  return {
    getLastBlock: () => Promise.resolve(lastBlock),
    setLastBlock: (block) => {
      lastBlock = block;
      return Promise.resolve();
    },
  };
}

/** Redis-backed cursor for production (a single string key). */
export function redisCursorStore(
  key = 'payments:watcher:tron:lastBlock',
): CursorStore {
  return {
    async getLastBlock() {
      const raw = await redis.get(key);
      return raw == null ? null : Number(raw);
    },
    async setLastBlock(block) {
      await redis.set(key, String(block));
    },
  };
}
