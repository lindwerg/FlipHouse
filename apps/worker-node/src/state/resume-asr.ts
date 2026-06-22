/**
 * `asr-resume` queue consumer (P2 step #1, TRACK C) — the worker-node half of
 * the GigaAM resume/fail state machine. The webhook-receiver (TRACK B) enqueues
 * exactly two job NAMES onto the `asr-resume` BullMQ queue; this pure processor
 * branches on the name and drives the parked `gpu-asr` job forward:
 *
 *   • name `asr-resume` (success): spawn the `asr-finalize` CLI (downloads the
 *     raw GigaAM payload, normalizes, uploads `cascade_transcript.json` +
 *     `word_segments.json`, writes the `_COMPLETE` sentinel LAST — idempotent),
 *     THEN `changeDelay(0)` the parked parent so the asr lane re-runs and hits
 *     its `_COMPLETE` branch (success, no re-submit).
 *
 *   • name `asr-fail` (failure): write the `_FAILED` marker (carrying the GPU
 *     error) under the parked job's `outputPrefix`, THEN `changeDelay(0)` to
 *     promote — re-entry sees `_FAILED` and throws an UnrecoverableError.
 *
 * The webhook process lacks the parked job's lock token, so cross-process
 * moveToFailed is impossible; it delegates the failure here, where we own the
 * job. Every effect (loadJob, runFinalize, writeFailedMarker) is injected, so
 * the full branch matrix is unit-tested to 100% with no real I/O.
 */
import type { StageResult } from '@fliphouse/shared';
import { z } from 'zod';

import { stageErrorFrom } from '../errors/classify.js';

/** Engine tag the finalize CLI stamps into the normalized transcript outputs. */
export const ENGINE_GIGAAM = 'gigaam-v3';

/** Job name for a normal (success) resume — must match the webhook-receiver. */
export const ASR_RESUME_JOB_NAME = 'asr-resume';

/** Job name for a delegated failure — must match the webhook-receiver. */
export const ASR_FAIL_JOB_NAME = 'asr-fail';

/** Success-resume payload (the webhook-receiver's `AsrResumeJob`). */
export const asrResumeJobSchema = z.object({
  jobId: z.string().min(1),
  requestId: z.string().min(1),
  rawPayloadKey: z.string().min(1),
  contentHash: z.string().min(1),
  outputPrefix: z.string().min(1),
});

/** Failure payload (the webhook-receiver's `AsrFailJob`): jobId + provider error. */
export const asrFailJobSchema = z.object({
  jobId: z.string().min(1),
  error: z.string(),
});

/** The slice of the parked `gpu-asr` job the resume consumer drives. */
export interface ResumableParkedJob {
  /** Re-arm the delayed job to run immediately (promote it to waiting). */
  changeDelay(delay: number): Promise<void>;
  /** The parked job's R2 output prefix (where markers/artifacts live). */
  readonly outputPrefix: string;
}

/** Input the finalize CLI consumes on stdin. */
export interface FinalizeInput {
  readonly rawPayloadKey: string;
  readonly outputPrefix: string;
  readonly engine: typeof ENGINE_GIGAAM;
}

export interface ResumeAsrDeps {
  /** Load the parked `gpu-asr` job by id, or `undefined` if it is gone. */
  loadJob(jobId: string): Promise<ResumableParkedJob | undefined>;
  /** Spawn `asr-finalize`; resolves a {@link StageResult} (never rejects on stage failure). */
  runFinalize(input: FinalizeInput): Promise<StageResult>;
  /** Write the `_FAILED` marker under the parked outputPrefix. */
  writeFailedMarker(outputPrefix: string, error: string): Promise<void>;
}

/** The minimal BullMQ job shape this processor reads: a name + opaque data. */
export interface ResumeQueueJob {
  readonly name: string;
  readonly data: unknown;
}

/** Promote a parked job to run now (changeDelay(0)), tolerating an already-gone job. */
async function promote(job: ResumableParkedJob | undefined): Promise<void> {
  if (job) await job.changeDelay(0);
}

async function handleSuccess(data: unknown, deps: ResumeAsrDeps): Promise<void> {
  const payload = asrResumeJobSchema.parse(data);
  const result = await deps.runFinalize({
    rawPayloadKey: payload.rawPayloadKey,
    outputPrefix: payload.outputPrefix,
    engine: ENGINE_GIGAAM,
  });
  if (!result.ok) {
    throw stageErrorFrom(result);
  }
  const job = await deps.loadJob(payload.jobId);
  await promote(job);
}

async function handleFail(data: unknown, deps: ResumeAsrDeps): Promise<void> {
  const payload = asrFailJobSchema.parse(data);
  const job = await deps.loadJob(payload.jobId);
  // No job → nothing to fail (the park key/job already cleared); a late fail is a no-op.
  if (!job) return;
  await deps.writeFailedMarker(job.outputPrefix, payload.error);
  await promote(job);
}

/**
 * Process one `asr-resume` queue job. Routes on the job name; an unknown name is
 * a contract breach and throws (BullMQ fails it loudly rather than silently
 * dropping). Schema-validates each payload at the boundary.
 */
export async function resumeAsrProcessor(job: ResumeQueueJob, deps: ResumeAsrDeps): Promise<void> {
  if (job.name === ASR_RESUME_JOB_NAME) {
    return handleSuccess(job.data, deps);
  }
  if (job.name === ASR_FAIL_JOB_NAME) {
    return handleFail(job.data, deps);
  }
  throw new Error(`resume-asr: unknown job name "${job.name}"`);
}
