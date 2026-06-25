import type { StageRequest, StageResult } from '@fliphouse/shared';

import { runPythonStage } from './spawn.js';

/** Context tags attached to each forwarded Python stderr line (OBS-2). */
export interface StageLineContext {
  readonly stage: string;
  readonly contentHash: string;
}

/** Sink for a single Python stderr line, tagged with its originating stage. */
export type StageLineSink = (line: string, ctx: StageLineContext) => void;

/** The runStage signature {@link StageProcessorDeps} expects. */
export type StageRunner = (request: StageRequest, signal?: AbortSignal) => Promise<StageResult>;

/**
 * Build the production `runStage` that wires {@link runPythonStage}'s
 * `onStderrLine` to a sink (OBS-2). Each stderr line is forwarded with its
 * `{stage, contentHash}` so the Python sidecar's diagnostics surface in the Node
 * logs on a SUCCESSFUL run, not only on failure. The `_run` seam injects the
 * stage runner so the forwarding wiring is unit-tested without a real subprocess.
 */
export function makeStageRunner(sink: StageLineSink, _run: typeof runPythonStage = runPythonStage): StageRunner {
  return (request, signal) =>
    _run(request, {
      ...(signal ? { signal } : {}),
      onStderrLine: (line) => sink(line, { stage: request.stage, contentHash: request.contentHash }),
    });
}
