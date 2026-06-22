import { createEnv } from '@t3-oss/env-nextjs';
import * as z from 'zod';

export const Env = createEnv({
  server: {
    CLERK_SECRET_KEY: z.string().min(1),
    DATABASE_URL: z.string().min(1),
    REDIS_PRIVATE_URL: z.string().url(),
    // Crypto billing (P1.12). `mock` (deterministic, no network) is the dev/test
    // default; production sets `tron` once the on-chain provider lands (P1.13/F).
    PAYMENT_PROVIDER: z.enum(['tron', 'mock']).default('mock'),
    // Optional JSON override of the plan grid (prices/minute caps).
    BILLING_PLAN_ENV: z.string().optional(),
    // TRON on-chain deposit watcher (P1.13). USDT TRC-20 contract a transfer must
    // match; confirmations before a deposit is credited; testnet (Nile/Shasta) for
    // checkpoint F. TRONGRID_API_KEY (secret) lives only in .env.local. The real
    // poller reads these at checkpoint F; the watcher core takes them as args.
    USDT_CONTRACT: z.string().min(1).default('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'),
    TRON_CONFIRMATIONS: z.coerce.number().int().min(1).default(19),
    TRON_NETWORK: z.enum(['mainnet', 'nile', 'shasta']).default('nile'),
    TRONGRID_API_KEY: z.string().optional(),
    // Master BIP39 mnemonic for HD deposit-address derivation (P1.13.1). SECRET —
    // lives only in .env.local / KMS, never committed, never logged. Optional so a
    // mock-provider dev/CI run boots without it; the tron provider fails loudly at
    // use-time if it is missing.
    TRON_HD_MNEMONIC: z.string().optional(),
    // TronGrid / own-node RPC base for the deposit watcher (Nile testnet default).
    TRON_RPC_URL: z.string().url().default('https://nile.trongrid.io'),
  },
  client: {
    NEXT_PUBLIC_APP_URL: z.string().optional(),
    // tusd resumable-upload endpoint the browser PATCHes video bytes to (P2.2).
    // The /api/uploads/grant route hands this to the client so the tus endpoint
    // is configured in one place. tusd itself is founder-gated (not in repo).
    NEXT_PUBLIC_TUS_ENDPOINT: z.string().url(),
    // Public base URL of the R2 bucket that serves finished clips (P2.3). The
    // dashboard builds a clip's playback/download URL as `${base}/${key}` behind
    // the toClipUrl seam. A presigned-URL route (for private buckets) is a
    // FOUNDER-GATED follow-up; for the MVP the bucket is public-read.
    NEXT_PUBLIC_R2_PUBLIC_BASE: z.string().url(),
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: z.string().min(1),
    NEXT_PUBLIC_LOGGING_LEVEL: z.enum(['error', 'info', 'debug', 'warning', 'trace', 'fatal']).default('info'),
    NEXT_PUBLIC_BETTER_STACK_SOURCE_TOKEN: z.string().optional(),
    NEXT_PUBLIC_BETTER_STACK_INGESTING_HOST: z.string().optional(),
  },
  shared: {
    NODE_ENV: z.enum(['test', 'development', 'production']).optional(),
  },
  // You need to destructure all the keys manually
  runtimeEnv: {
    CLERK_SECRET_KEY: process.env.CLERK_SECRET_KEY,
    DATABASE_URL: process.env.DATABASE_URL,
    NEXT_PUBLIC_APP_URL: process.env.NEXT_PUBLIC_APP_URL,
    NEXT_PUBLIC_TUS_ENDPOINT: process.env.NEXT_PUBLIC_TUS_ENDPOINT,
    NEXT_PUBLIC_R2_PUBLIC_BASE: process.env.NEXT_PUBLIC_R2_PUBLIC_BASE,
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY:
      process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
    NEXT_PUBLIC_LOGGING_LEVEL: process.env.NEXT_PUBLIC_LOGGING_LEVEL,
    NEXT_PUBLIC_BETTER_STACK_SOURCE_TOKEN: process.env.NEXT_PUBLIC_BETTER_STACK_SOURCE_TOKEN,
    NEXT_PUBLIC_BETTER_STACK_INGESTING_HOST: process.env.NEXT_PUBLIC_BETTER_STACK_INGESTING_HOST,
    NODE_ENV: process.env.NODE_ENV,
    REDIS_PRIVATE_URL: process.env.REDIS_PRIVATE_URL,
    PAYMENT_PROVIDER: process.env.PAYMENT_PROVIDER,
    BILLING_PLAN_ENV: process.env.BILLING_PLAN_ENV,
    USDT_CONTRACT: process.env.USDT_CONTRACT,
    TRON_CONFIRMATIONS: process.env.TRON_CONFIRMATIONS,
    TRON_NETWORK: process.env.TRON_NETWORK,
    TRONGRID_API_KEY: process.env.TRONGRID_API_KEY,
    TRON_HD_MNEMONIC: process.env.TRON_HD_MNEMONIC,
    TRON_RPC_URL: process.env.TRON_RPC_URL,
  },
  // Fail fast with the offending variable names: the t3-env default throws a
  // generic "Invalid environment variables" without naming what is missing.
  onValidationError: (issues) => {
    const names = issues
      .map((issue) => {
        const segment = issue.path?.[0];
        if (segment == null) {
          return null;
        }
        return typeof segment === 'object' ? String(segment.key) : String(segment);
      })
      .filter((name): name is string => name != null);
    const detail = names.length > 0 ? names.join(', ') : 'unknown';
    throw new Error(`❌ Invalid environment variables: ${detail}`);
  },
});
