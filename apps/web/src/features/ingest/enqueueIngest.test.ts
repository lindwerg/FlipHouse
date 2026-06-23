import { afterEach, describe, expect, it, vi } from 'vitest';

// enqueueIngest is exercised with an INJECTED queue, so its default factory (which
// reads the Redis URL from Env and opens a BullMQ connection) never runs — no
// Redis socket, no env beyond the vitest defaults.
const { enqueueIngest } = await import('./enqueueIngest');

afterEach(() => {
  vi.clearAllMocks();
});

describe('enqueueIngest', () => {
  it('adds a job carrying the url + ownerId with a per-(owner,url) dedup jobId', async () => {
    const add = vi.fn().mockResolvedValue(undefined);

    await enqueueIngest({ url: 'https://youtu.be/abc', ownerId: 'user_1' }, { queue: { add } });

    expect(add).toHaveBeenCalledTimes(1);
    const [name, data, opts] = add.mock.calls[0]!;
    expect(name).toBe('ingest');
    expect(data).toEqual({ url: 'https://youtu.be/abc', ownerId: 'user_1' });
    expect(opts.jobId).toBe(`ingest-user_1-${encodeURIComponent('https://youtu.be/abc')}`);
    expect(opts.removeOnComplete).toBeDefined();
    expect(opts.removeOnFail).toBeDefined();
  });

  it('propagates an add failure to the caller (the route maps it to 502)', async () => {
    const add = vi.fn().mockRejectedValue(new Error('redis down'));

    await expect(
      enqueueIngest({ url: 'https://youtu.be/abc', ownerId: 'user_1' }, { queue: { add } }),
    ).rejects.toThrow('redis down');
  });
});
