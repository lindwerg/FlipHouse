import { claimUpload, createDb, findStuckFlows, setFlowJobId } from '@fliphouse/db';
import type { UploadRow } from '@fliphouse/db';
import { flowJobId } from '@fliphouse/shared';
import { enqueueFlow } from '@fliphouse/worker-node/flow';
import type { FlowEnqueuer } from '@fliphouse/worker-node/flow';
import type { Pool } from 'pg';

import type { PostFinishDeps } from './handle-post-finish.js';
import type { SweepDeps } from './reconcile-sweep.js';

/* v8 ignore start -- real pg + BullMQ wiring; exercised in integration, not unit tests */

/**
 * Bind the pure post-finish handler to production effects: the durable claim
 * goes through the drizzle ledger repo, the enqueue through the shared
 * FlowProducer (which dedups a re-add of a live flow). The handler stays storage-
 * and queue-agnostic; only this seam knows about pg and BullMQ.
 */
export function buildRealDeps(pool: Pool, producer: FlowEnqueuer): PostFinishDeps {
  const db = createDb(pool);
  return {
    claimUpload: (input) => claimUpload(db, input),
    enqueueFlow: async (args) => {
      await enqueueFlow(producer, args);
    },
    markEnqueued: (contentHash) => setFlowJobId(db, contentHash, flowJobId(contentHash)),
  };
}

/** The reconcile-sweep's effects, bound to the same pg ledger + FlowProducer. */
export function buildSweepDeps(pool: Pool, producer: FlowEnqueuer): SweepDeps {
  const db = createDb(pool);
  return {
    findStuck: (olderThan): Promise<readonly UploadRow[]> => findStuckFlows(db, olderThan),
    enqueue: async (args) => {
      await enqueueFlow(producer, args);
    },
  };
}

/* v8 ignore stop */
