/**
 * ASR park-lane env resolution + boot-assert (P2 step #1, TRACK C). When
 * `GPU_ASR_ENABLED==="true"` the submit-and-park lane needs three more vars
 * (`GIGAAM_ENDPOINT`, `GIGAAM_WEBHOOK_SECRET`, `WEBHOOK_PUBLIC_URL`); a missing
 * one must fail the DEPLOY, not every claimed asr job one-by-one. This pure
 * resolver is the single boundary that enforces that, so it is unit-tested to
 * 100% (the real worker boot just calls it).
 */

/** Engine tag stamped through the submit/finalize contract. */
export const ENGINE_GIGAAM_V3 = 'gigaam-v3';

/** Path the GPU posts its callback to, appended to `WEBHOOK_PUBLIC_URL`. */
export const WEBHOOK_CALLBACK_PATH = '/gpu/callback';

/** Named error for a misconfigured park lane — thrown at boot, never per-job. */
export class AsrEnvError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AsrEnvError';
  }
}

/** The park lane is armed ONLY for the exact opt-in string `"true"`. */
export function isGpuAsrEnabled(env: Record<string, string | undefined>): boolean {
  return env.GPU_ASR_ENABLED === 'true';
}

/** Resolved park-lane config: disabled (inline path) or a fully-typed enabled set. */
export type AsrEnvConfig =
  | { readonly enabled: false }
  | {
      readonly enabled: true;
      readonly endpoint: string;
      readonly webhookSecret: string;
      readonly webhookPublicUrl: string;
    };

/** The three vars the park lane requires when enabled. */
const REQUIRED_WHEN_ENABLED = [
  'GIGAAM_ENDPOINT',
  'GIGAAM_WEBHOOK_SECRET',
  'WEBHOOK_PUBLIC_URL',
] as const;

/**
 * Resolve the park-lane env. Disabled → `{ enabled: false }` with no further
 * checks (the inline CPU path needs nothing). Enabled → assert every required
 * var is a non-empty string (an empty string counts as missing) and return the
 * typed config; the FIRST missing var names itself in a thrown {@link AsrEnvError}.
 */
export function resolveAsrEnv(env: Record<string, string | undefined>): AsrEnvConfig {
  if (!isGpuAsrEnabled(env)) return { enabled: false };

  for (const name of REQUIRED_WHEN_ENABLED) {
    if (!env[name]) {
      throw new AsrEnvError(
        `GPU_ASR_ENABLED=true but required env var "${name}" is missing — failing the deploy`,
      );
    }
  }
  return {
    enabled: true,
    endpoint: env.GIGAAM_ENDPOINT as string,
    webhookSecret: env.GIGAAM_WEBHOOK_SECRET as string,
    webhookPublicUrl: env.WEBHOOK_PUBLIC_URL as string,
  };
}

/** Build the full GPU callback URL from the public base (trimming a trailing slash). */
export function webhookCallbackUrl(webhookPublicUrl: string): string {
  return `${webhookPublicUrl.replace(/\/$/, '')}${WEBHOOK_CALLBACK_PATH}`;
}
