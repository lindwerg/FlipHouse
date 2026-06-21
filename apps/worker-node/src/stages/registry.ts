import type { Stage } from '@fliphouse/shared';

import { executeStage } from './execute-stage.js';
import type { StageHandler } from './handler-contract.js';

/** Stages driven by a Python subprocess via the generic executeStage body. */
const PYTHON_STAGES: ReadonlySet<Stage> = new Set<Stage>([
  'transcode',
  'asr',
  'score',
  'reframe',
  'caption',
  'banner',
]);

export function isPythonStage(stage: Stage): boolean {
  return PYTHON_STAGES.has(stage);
}

/**
 * Resolve the generic handler for a Python-backed stage. `publish` is a Node
 * finalizer (see publish.ts), not a subprocess stage, so it is routed
 * separately by the worker and rejected here.
 */
export function resolveStageHandler(stage: Stage): StageHandler {
  if (!isPythonStage(stage)) {
    throw new Error(`no generic stage handler for "${stage}"`);
  }
  return executeStage;
}
