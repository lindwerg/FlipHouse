import type { FlowJob } from 'bullmq';
import { expect, test } from 'vitest';
import { flowJobId, stageJobId } from '@fliphouse/shared';

import { buildFlowTree } from './build-flow-tree.js';

const HASH = 'a'.repeat(64);
const ARGS = { contentHash: HASH, ownerId: 'user_1', source: 'uploads/a.mp4' };

/** Flatten the single-child chain from root to leaf into an ordered array. */
function chainFromRoot(root: FlowJob): FlowJob[] {
  const out: FlowJob[] = [];
  let node: FlowJob | undefined = root;
  while (node) {
    out.push(node);
    node = node.children?.[0];
  }
  return out;
}

test('buildFlowTree roots at publish, runs transcode last (deepest leaf)', () => {
  const root = buildFlowTree(ARGS);
  const names = chainFromRoot(root).map((n) => n.name);

  expect(names).toEqual([
    'publish',
    'store',
    'banner',
    'caption',
    'reframe',
    'score',
    'asr',
    'transcode',
  ]);
});

test('root publish carries the flow jobId and is never auto-removed', () => {
  const root = buildFlowTree(ARGS);

  expect(root.opts?.jobId).toBe(flowJobId(HASH));
  expect(root.opts?.removeOnComplete).toBe(false);
  // Root has no parent, so neither failure flag applies.
  expect(root.opts?.failParentOnFailure).toBeUndefined();
  expect(root.opts?.ignoreDependencyOnFailure).toBeUndefined();
});

test('each non-root node carries its deterministic stage jobId', () => {
  const nodes = chainFromRoot(buildFlowTree(ARGS));

  for (const node of nodes) {
    if (node.name === 'publish') continue;
    expect(node.opts?.jobId).toBe(stageJobId(node.name, HASH));
  }
});

test('every non-root stage fails the parent — no middle node swallows a failure', () => {
  const byName = new Map(chainFromRoot(buildFlowTree(ARGS)).map((n) => [n.name, n]));

  for (const stage of ['store', 'banner', 'caption', 'reframe', 'score', 'asr', 'transcode']) {
    expect(byName.get(stage)?.opts?.failParentOnFailure).toBe(true);
    // ignoreDependencyOnFailure on a middle node would swallow an upstream
    // critical failure in a linear chain — it must never be set in P2.
    expect(byName.get(stage)?.opts?.ignoreDependencyOnFailure).toBeUndefined();
  }
});

test('stages route to their docs/01 §5 queues', () => {
  const byName = new Map(chainFromRoot(buildFlowTree(ARGS)).map((n) => [n.name, n.queueName]));

  expect(byName.get('transcode')).toBe('transcode');
  expect(byName.get('asr')).toBe('gpu-asr');
  expect(byName.get('score')).toBe('gpu-score');
  expect(byName.get('reframe')).toBe('cpu');
  expect(byName.get('store')).toBe('cpu');
  expect(byName.get('publish')).toBe('publish');
});

test('the leaf transcode has no children and carries flow data', () => {
  const nodes = chainFromRoot(buildFlowTree(ARGS));
  const leaf = nodes[nodes.length - 1];

  expect(leaf?.name).toBe('transcode');
  expect(leaf?.children).toBeUndefined();
  expect(leaf?.data).toMatchObject({
    contentHash: HASH,
    ownerId: 'user_1',
    source: 'uploads/a.mp4',
    stage: 'transcode',
    outputPrefix: `intermediate/${HASH}/transcode`,
  });
});
