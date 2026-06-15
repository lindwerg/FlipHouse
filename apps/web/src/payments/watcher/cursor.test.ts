import { beforeEach, describe, expect, it, vi } from 'vitest';

const redisGet = vi.fn<(key: string) => Promise<string | null>>();
const redisSet = vi.fn<(key: string, value: string) => Promise<unknown>>();

vi.mock('@/libs/Redis', () => ({
  redis: {
    get: (key: string) => redisGet(key),
    set: (key: string, value: string) => redisSet(key, value),
  },
}));

const { inMemoryCursorStore, redisCursorStore } = await import('./cursor');

// The cursor tracks the last block the watcher has processed. The in-memory
// store backs the integration tests; production uses a Redis-backed store.
describe('in-memory cursor store', () => {
  it('returns null before any block is set, then round-trips the last block', async () => {
    const cursor = inMemoryCursorStore();

    expect(await cursor.getLastBlock()).toBeNull();

    await cursor.setLastBlock(42);
    expect(await cursor.getLastBlock()).toBe(42);
  });

  it('accepts an initial block', async () => {
    const cursor = inMemoryCursorStore(100);

    expect(await cursor.getLastBlock()).toBe(100);
  });
});

describe('redis cursor store', () => {
  beforeEach(() => {
    redisGet.mockReset();
    redisSet.mockReset();
    redisSet.mockResolvedValue('OK');
  });

  it('returns null when the key is unset, and parses the stored block', async () => {
    const cursor = redisCursorStore();

    redisGet.mockResolvedValueOnce(null);
    expect(await cursor.getLastBlock()).toBeNull();

    redisGet.mockResolvedValueOnce('50');
    expect(await cursor.getLastBlock()).toBe(50);
  });

  it('persists the block as a string under the cursor key', async () => {
    const cursor = redisCursorStore('payments:watcher:tron:lastBlock');

    await cursor.setLastBlock(73);

    expect(redisSet).toHaveBeenCalledWith(
      'payments:watcher:tron:lastBlock',
      '73',
    );
  });
});
