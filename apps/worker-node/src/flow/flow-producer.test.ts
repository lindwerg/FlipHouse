import type { FlowJob, JobNode } from 'bullmq';
import { expect, test } from 'vitest';
import { flowJobId } from '@fliphouse/shared';

import { enqueueFlow } from './flow-producer.js';
import type { FlowEnqueuer } from './flow-producer.js';

const HASH = 'a'.repeat(64);

test('enqueueFlow builds the flow tree and submits it to the producer', async () => {
  let received: FlowJob | undefined;
  const producer: FlowEnqueuer = {
    add: async (flow) => {
      received = flow;
      return { job: { id: flow.opts?.jobId } } as unknown as JobNode;
    },
  };

  await enqueueFlow(producer, { contentHash: HASH, ownerId: 'user_1', source: 'uploads/a.mp4' });

  expect(received?.name).toBe('publish');
  expect(received?.opts?.jobId).toBe(flowJobId(HASH));
  expect(received?.children?.[0]?.name).toBe('store');
});
