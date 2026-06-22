import { STAGE_REQUEST_VERSION, isStage } from '@fliphouse/shared';
import type { Stage, StageRequest, StageResult } from '@fliphouse/shared';
import type { Job, Processor } from 'bullmq';
import { z } from 'zod';

import { STAGE_TIMEOUT_MS } from '../queues/queue-config.js';

import { executeAsr } from './execute-asr.js';
import type { AsrLaneDeps, AsrMarkerStore } from './execute-asr.js';
import { executeStage } from './execute-stage.js';
import { publishUpload } from './publish.js';
import type { PublishDeps } from './publish.js';

/**
 * Output filenames each Python stage writes, mirrored from the Python handlers so
 * the Node side can wire one stage's output as the next stage's input. These are
 * a cross-language contract; a rename on the Python side surfaces as a FATAL
 * `download_inputs` ValueError (loud flow failure), never silent corruption:
 *  - transcode → `proxy.mp4`             (stages/transcode.py)
 *  - asr       → `cascade_transcript.json` (stages/asr.py; the scorer's transcript)
 *              + `word_segments.json`     (stages/asr.py; per-word timings for captions)
 *  - score     → `clips.json`            (stages/score.py)
 *  - reframe   → `manifest.json` + `clip_NN.mp4` (stages/reframe.py)
 */
const PROXY_NAME = 'proxy.mp4';
const CASCADE_TRANSCRIPT_NAME = 'cascade_transcript.json';
const WORD_SEGMENTS_NAME = 'word_segments.json';
const CLIPS_NAME = 'clips.json';
const MANIFEST_NAME = 'manifest.json';

/** The R2 prefix a stage writes its outputs under (matches build-flow-tree). */
function stagePrefix(stage: Stage, contentHash: string): string {
  return `intermediate/${contentHash}/${stage}`;
}

/**
 * The logical inputs a Python stage downloads, each wired to the upstream key
 * that produced it. `transcode` reads the original upload; every later CPU stage
 * reads the transcode proxy plus its specific upstream artifact. `caption` (the
 * real burn-in, P2 step 5) reads the reframe `manifest.json`, the asr
 * `word_segments.json`, and `clips_prefix` — the reframe stage's R2 prefix it
 * lists the `clip_NN.mp4` files under. `banner` is still a P2 passthrough no-op
 * with nothing to forward (publish reads the caption prefix directly), so it
 * gets no inputs.
 */
export function buildStageInputs(
  stage: Stage,
  contentHash: string,
  source: string,
): Record<string, string> {
  const proxy = `${stagePrefix('transcode', contentHash)}/${PROXY_NAME}`;
  switch (stage) {
    case 'transcode':
      return { source };
    case 'asr':
      return { source: proxy };
    case 'score':
      return { source: proxy, transcript: `${stagePrefix('asr', contentHash)}/${CASCADE_TRANSCRIPT_NAME}` };
    case 'reframe':
      return { source: proxy, clips: `${stagePrefix('score', contentHash)}/${CLIPS_NAME}` };
    case 'caption':
      return {
        manifest: `${stagePrefix('reframe', contentHash)}/${MANIFEST_NAME}`,
        word_segments: `${stagePrefix('asr', contentHash)}/${WORD_SEGMENTS_NAME}`,
        // A bare R2 prefix (NOT a downloadable key): the caption handler reads each
        // clip's `path` from the manifest and downloads `${clips_prefix}/${path}`.
        clips_prefix: stagePrefix('reframe', contentHash),
      };
    default:
      return {};
  }
}

/** Job payload the FlowProducer attaches to every stage node (build-flow-tree). */
const stageJobDataSchema = z
  .object({
    contentHash: z.string().min(1),
    ownerId: z.string().min(1),
    stage: z.string().min(1),
    source: z.string().min(1),
    outputPrefix: z.string().min(1),
    // Present only on the publish root (the caption prefix it reads the
    // manifest + captioned clips from).
    clipsPrefix: z.string().min(1).optional(),
  })
  .passthrough();

export type StageJobData = z.infer<typeof stageJobDataSchema>;

/** Assemble the Python wire request (StageRequest) from validated job data. */
export function buildStageRequest(data: StageJobData, stage: Stage): StageRequest {
  return {
    version: STAGE_REQUEST_VERSION,
    stage,
    contentHash: data.contentHash,
    ownerId: data.ownerId,
    inputs: buildStageInputs(stage, data.contentHash, data.source),
    outputPrefix: data.outputPrefix,
    params: {},
  };
}

/** Everything the processor needs, all injectable so the routing is unit-testable. */
export interface StageProcessorDeps {
  readonly r2: AsrMarkerStore;
  readonly runStage: (request: StageRequest, signal?: AbortSignal) => Promise<StageResult>;
  readonly publish: PublishDeps;
  /**
   * ASR submit-and-park lane deps. When present and `gpuParkEnabled`, the `asr`
   * stage routes through {@link executeAsr} (submit + park + DelayedError);
   * otherwise asr runs inline like every other Python stage.
   */
  readonly asr: AsrLaneDeps;
}

/**
 * Combine BullMQ's own cancellation signal (3rd processor arg) with a per-stage
 * `AbortSignal.timeout`, so a wedged subprocess is aborted at `STAGE_TIMEOUT_MS`
 * — strictly below `LOCK_DURATION_MS` (see {@link assertTimeoutsBelowLock}), so
 * the stage is killed and retried BEFORE BullMQ's stall recovery can double-run
 * it. The timeout timer is `unref`'d by `AbortSignal.timeout`, so a job that
 * finishes first leaves no lingering handle keeping the process alive.
 */
export function stageAbortSignal(bull: AbortSignal | undefined, timeoutMs: number): AbortSignal {
  const timeout = AbortSignal.timeout(timeoutMs);
  return bull ? AbortSignal.any([bull, timeout]) : timeout;
}

/**
 * Build the BullMQ {@link Processor} for every queue: validate the job, route
 * `publish` to the Node finalizer and every Python stage through the generic
 * `executeStage` body (skip-if-cached → spawn → sentinel-last). A fatal stage
 * result propagates as a thrown UnrecoverableError so BullMQ fails the flow
 * instead of retrying.
 */
export function makeStageProcessor(deps: StageProcessorDeps): Processor {
  return async (job: Job, token?: string, signal?: AbortSignal): Promise<unknown> => {
    const data = stageJobDataSchema.parse(job.data);
    if (!isStage(data.stage)) {
      throw new Error(`stage-processor: unknown stage "${data.stage}"`);
    }
    const stage = data.stage;

    if (stage === 'publish') {
      if (!data.clipsPrefix) {
        throw new Error('stage-processor: publish job is missing clipsPrefix');
      }
      return publishUpload({ contentHash: data.contentHash, clipsPrefix: data.clipsPrefix }, deps.publish);
    }

    const ctx = {
      stage,
      contentHash: data.contentHash,
      ownerId: data.ownerId,
      request: buildStageRequest(data, stage),
      r2: deps.r2,
      runStage: deps.runStage,
      signal: stageAbortSignal(signal, STAGE_TIMEOUT_MS[stage]),
    };

    // The asr stage owns the GPU submit-and-park lane: it threads the BullMQ
    // token (captured here) + the parkable job so it can moveToDelayed on a
    // first-entry park, and re-enters via changeDelay(0) on resume.
    if (stage === 'asr') {
      return executeAsr({ ...ctx, token, job }, deps.asr);
    }

    return executeStage(ctx);
  };
}
