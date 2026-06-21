import { flowJobId, stageJobId } from '@fliphouse/shared';
import type { Stage } from '@fliphouse/shared';
import type { FlowJob } from 'bullmq';

import { RETENTION, STAGE_RETRY } from '../queues/queue-config.js';
import { resolveQueue } from '../queues/queue-name.js';

export interface BuildFlowArgs {
  readonly contentHash: string;
  readonly ownerId: string;
  /** R2 key of the uploaded source video. */
  readonly source: string;
}

/**
 * Stages in children-run-first order (leaf → root). A BullMQ Flow is a TREE
 * (one parent per job), so the post-score arms run as a LEGAL LINEAR chain, not
 * the spec's illegal shared-`score` diamond. caption/banner are passthrough
 * stubs in P2; true parallel fan-out is a P3 two-phase flow. See stage.ts.
 */
const CHAIN: readonly Stage[] = [
  'transcode',
  'asr',
  'score',
  'reframe',
  'caption',
  'banner',
  'publish',
];

const ROOT_STAGE: Stage = 'publish';

function outputPrefix(stage: Stage, contentHash: string): string {
  return `intermediate/${contentHash}/${stage}`;
}

function nodeFor(stage: Stage, args: BuildFlowArgs, child: FlowJob | undefined): FlowJob {
  const isRoot = stage === ROOT_STAGE;
  const retry = STAGE_RETRY[stage];

  // In the P2 LINEAR chain every stage is load-bearing: any failure must fail the
  // whole flow (publish never runs on a partial result). `ignoreDependencyOnFailure`
  // cannot be used on a middle node — it would swallow an upstream critical failure.
  // Cosmetic-optional caption/banner return as failure-isolated SIBLINGS in the P3
  // two-phase fan-out, not here.
  const failureOpts = isRoot ? {} : { failParentOnFailure: true };

  return {
    name: stage,
    queueName: resolveQueue(stage),
    data: {
      contentHash: args.contentHash,
      ownerId: args.ownerId,
      stage,
      source: args.source,
      outputPrefix: outputPrefix(stage, args.contentHash),
      // The publish finalizer reads the render manifest + clips straight from the
      // reframe stage's prefix (the producer's actual keys), so it needs that
      // prefix in its job data — there is no separate `store` artifact anymore.
      ...(isRoot ? { reframePrefix: outputPrefix('reframe', args.contentHash) } : {}),
    },
    opts: {
      // Root keeps a durable dedup id (GC'd via the ledger, not Redis eviction);
      // children may be evicted — the ledger is the idempotency authority.
      jobId: isRoot ? flowJobId(args.contentHash) : stageJobId(stage, args.contentHash),
      attempts: retry.attempts,
      backoff: retry.backoff,
      removeOnComplete: isRoot ? false : RETENTION.complete,
      removeOnFail: RETENTION.fail,
      ...failureOpts,
    },
    ...(child ? { children: [child] } : {}),
  };
}

/**
 * Build the FlowProducer tree for one upload. Pure (no Redis): folds the chain
 * from the `transcode` leaf up to the `publish` root, nesting each stage as the
 * single child of the next.
 */
export function buildFlowTree(args: BuildFlowArgs): FlowJob {
  let node: FlowJob | undefined;
  for (const stage of CHAIN) {
    node = nodeFor(stage, args, node);
  }
  // CHAIN is non-empty, so `node` is the root after the loop.
  return node as FlowJob;
}
