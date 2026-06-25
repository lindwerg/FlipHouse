/**
 * Lost-callback backstop sweep (P2 step #1, TRACK C). The happy path resumes a
 * parked ASR job via the webhook; if that callback is permanently lost (GPU
 * crash, network black hole), the parked job would sit `delayed` until its
 * deadline and then re-enter the asr lane with neither `_COMPLETE` nor `_FAILED`
 * — re-submitting forever. This sweep closes that hole:
 *
 *   for each request whose park deadline has passed (`listExpired`):
 *     • poll the GPU `${endpoint}/status/<request_id>`:
 *         – terminal (succeeded/failed) → ATOMIC `claim` (GETDEL park:<id>). The
 *           sweep is a LEGIT second claimer: the atomic GETDEL guarantees it and
 *           a late webhook can never both win. On a won success → write the raw
 *           payload to R2 + enqueue `asr-resume`; on a won failure → enqueue
 *           `asr-fail`. A lost claim (null) is a no-op (the webhook got there).
 *         – still processing & under {@link MAX_PARK_CYCLES} → re-arm the
 *           deadline (give the GPU another window) WITHOUT claiming.
 *         – still processing & past the cap → claim + enqueue `asr-fail` (the
 *           prediction is wedged; fail the job rather than park it forever).
 *
 * Pure and fully injected — `runParkSweep(deps)` is the entry the existing
 * sweep/cron calls; the real ioredis/fetch/R2/Queue construction lives behind
 * the deps it is handed (built in worker/run-resume-asr.ts).
 */

import { classifyAsrFailReason } from '@fliphouse/shared';

/** Max sweep re-arm cycles before a still-processing prediction is force-failed. */
export const MAX_PARK_CYCLES = 4;

/** How long each re-arm extends the park deadline (one more sweep window). */
export const REARM_MS = 5 * 60 * 1000;

/** The decoded `park:<id>` value (jobId + reconstruction context). */
export interface ParkValue {
  readonly jobId: string;
  readonly contentHash: string;
  readonly outputPrefix: string;
}

/** Terminal/non-terminal status the GPU reports for a prediction. */
export type GpuStatus =
  | { readonly state: 'succeeded'; readonly payload: unknown }
  | { readonly state: 'failed'; readonly error: string }
  | { readonly state: 'processing' };

/** The `asr-resume` success job (matches the webhook-receiver shape). */
export interface AsrResumeJob {
  readonly jobId: string;
  readonly requestId: string;
  readonly rawPayloadKey: string;
  readonly contentHash: string;
  readonly outputPrefix: string;
}

/** The `asr-fail` failure job (matches the webhook-receiver shape). */
export interface AsrFailJob {
  readonly jobId: string;
  readonly error: string;
}

export interface ParkSweepDeps {
  readonly nowMs: () => number;
  /** Request ids whose park deadline has already passed (ZRANGEBYSCORE -inf now). */
  listExpired(): Promise<readonly string[]>;
  /** Poll the GPU for this prediction's terminal/processing status. */
  pollStatus(requestId: string): Promise<GpuStatus>;
  /** ATOMIC GETDEL of `park:<id>` → the decoded value once, `null` if a late webhook won. */
  claim(requestId: string): Promise<ParkValue | null>;
  /** Re-arm the park deadline for a still-processing request; returns the new cycle count. */
  bumpDeadline(requestId: string, newDeadlineMs: number): Promise<number>;
  /** Persist the raw GigaAM payload verbatim to R2 (same key the webhook would use). */
  writeRaw(rawPayloadKey: string, payload: unknown): Promise<void>;
  /** Enqueue the `asr-resume` success job onto the asr-resume queue. */
  enqueueResume(job: AsrResumeJob): Promise<void>;
  /** Enqueue the `asr-fail` failure job onto the asr-resume queue. */
  enqueueFail(job: AsrFailJob): Promise<void>;
}

/** Aggregate counters returned by one sweep pass (for logging/metrics). */
export interface ParkSweepSummary {
  scanned: number;
  resumed: number;
  failed: number;
  rearmed: number;
  lostRace: number;
}

/** R2 key the raw GigaAM payload lands at — identical to the webhook's rawPayloadKeyFor. */
function rawPayloadKeyFor(contentHash: string): string {
  return `intermediate/${contentHash}/asr/_raw_gigaam.json`;
}

/** Claim then route a terminal-success prediction; returns whether the claim was won. */
async function resolveSuccess(
  requestId: string,
  payload: unknown,
  deps: ParkSweepDeps,
  summary: ParkSweepSummary,
): Promise<void> {
  const park = await deps.claim(requestId);
  if (!park) {
    summary.lostRace += 1;
    return;
  }
  const rawPayloadKey = rawPayloadKeyFor(park.contentHash);
  await deps.writeRaw(rawPayloadKey, payload);
  await deps.enqueueResume({
    jobId: park.jobId,
    requestId,
    rawPayloadKey,
    contentHash: park.contentHash,
    outputPrefix: park.outputPrefix,
  });
  summary.resumed += 1;
}

/** Claim then route a terminal/timeout failure; returns whether the claim was won. */
async function resolveFailure(
  requestId: string,
  error: string,
  deps: ParkSweepDeps,
  summary: ParkSweepSummary,
): Promise<void> {
  const park = await deps.claim(requestId);
  if (!park) {
    summary.lostRace += 1;
    return;
  }
  await deps.enqueueFail({ jobId: park.jobId, error });
  summary.failed += 1;
}

/** Decide the fate of one expired request based on its polled GPU status. */
async function sweepOne(
  requestId: string,
  deps: ParkSweepDeps,
  summary: ParkSweepSummary,
): Promise<void> {
  const status = await deps.pollStatus(requestId);

  if (status.state === 'succeeded') {
    await resolveSuccess(requestId, status.payload, deps, summary);
    return;
  }
  if (status.state === 'failed') {
    // A lost-callback failure carries the GPU's own error; map an HF/pyannote
    // auth-class fault to a distinct, diagnosable reason (TRANS-4) just as the live
    // webhook path does, so an expired HF_TOKEN is identifiable from the asr-fail.
    await resolveFailure(requestId, classifyAsrFailReason(status.error), deps, summary);
    return;
  }

  // Still processing: re-arm under the cap, else force-fail (wedged prediction).
  const cycle = await deps.bumpDeadline(requestId, deps.nowMs() + REARM_MS);
  if (cycle >= MAX_PARK_CYCLES) {
    await resolveFailure(
      requestId,
      `asr prediction exceeded MAX_PARK_CYCLES (${MAX_PARK_CYCLES}) — timed out`,
      deps,
      summary,
    );
    return;
  }
  summary.rearmed += 1;
}

/**
 * The outcome of a GPU `/health` probe (TRANS-4 observability hook). `healthy`
 * iff the endpoint answered 200; otherwise `reason` carries an operator-actionable
 * description (non-200 status or a transport fault) so an outage is DETECTED before
 * ~20min of jobs silently fail — closing the STATE-noted observability hole where
 * Railway logs only show "Starting Container".
 */
export interface HealthProbeResult {
  readonly healthy: boolean;
  readonly status?: number;
  readonly reason?: string;
}

/** Inject only the probe transport so the classification logic is unit-tested. */
export interface HealthProbeDeps {
  /** GET `${endpoint}/health`; resolves `{ status }` or rejects on a transport fault. */
  fetchHealth(): Promise<{ readonly status: number }>;
}

/**
 * Probe the GigaAM GPU `/health` endpoint. Returns a structured result (never
 * throws) so the caller can alert on `!healthy` instead of an unhandled rejection.
 * A 200 is healthy; any other status or a transport fault is an outage signal.
 */
export async function probeGigaamHealth(deps: HealthProbeDeps): Promise<HealthProbeResult> {
  try {
    const res = await deps.fetchHealth();
    if (res.status === 200) {
      return { healthy: true, status: 200 };
    }
    return {
      healthy: false,
      status: res.status,
      reason: `gigaam /health returned ${res.status} (endpoint down or misconfigured)`,
    };
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    return { healthy: false, reason: `gigaam /health unreachable: ${detail}` };
  }
}

/**
 * Run one lost-callback sweep pass over every expired parked request. Each
 * request is handled independently; the returned summary aggregates the outcomes
 * for the caller to log or emit as metrics.
 */
export async function runParkSweep(deps: ParkSweepDeps): Promise<ParkSweepSummary> {
  const expired = await deps.listExpired();
  const summary: ParkSweepSummary = { scanned: 0, resumed: 0, failed: 0, rearmed: 0, lostRace: 0 };
  for (const requestId of expired) {
    summary.scanned += 1;
    await sweepOne(requestId, deps, summary);
  }
  return summary;
}
