import { FlowProducer } from 'bullmq';
import type { ConnectionOptions, FlowJob, JobNode } from 'bullmq';

import { buildFlowTree } from './build-flow-tree.js';
import type { BuildFlowArgs } from './build-flow-tree.js';

/** The slice of {@link FlowProducer} the orchestrator depends on (injectable). */
export interface FlowEnqueuer {
  add(flow: FlowJob): Promise<JobNode>;
}

/** Build and enqueue the render flow for one upload. Re-adding the same content is a no-op. */
export function enqueueFlow(producer: FlowEnqueuer, args: BuildFlowArgs): Promise<JobNode> {
  return producer.add(buildFlowTree(args));
}

/* v8 ignore start -- real Redis connection; exercised in integration, not unit tests */
export function createFlowProducer(connection: ConnectionOptions): FlowProducer {
  return new FlowProducer({ connection });
}
/* v8 ignore stop */
