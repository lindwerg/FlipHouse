import { Redis } from 'ioredis';
import { Env } from './Env';
import { logger } from './Logger';

// Lazy singleton mirroring src/libs/DB.ts: one client per process, cached on
// globalThis in dev so HMR reloads reuse the connection instead of leaking one
// per reload. In production we keep a fresh module-scoped instance.
declare global {
  // eslint-disable-next-line vars-on-top, no-var
  var cachedRedis: Redis | undefined;
}

const createRedisConnection = (): Redis => {
  const client = new Redis(Env.REDIS_PRIVATE_URL, {
    // BullMQ (P2) requires this; also avoids commands erroring out mid-retry.
    maxRetriesPerRequest: null,
    // Defer the socket until the first command so importing this module never
    // blocks boot or the landing LCP.
    lazyConnect: true,
  });

  // Without an error listener ioredis re-throws connection errors as an
  // "Unhandled error event" and crashes the process.
  client.on('error', (error) => {
    logger.error(`Redis error: ${error.message}`);
  });

  return client;
};

const redis = globalThis.cachedRedis ?? createRedisConnection();

if (Env.NODE_ENV !== 'production') {
  globalThis.cachedRedis = redis;
}

export { redis };
