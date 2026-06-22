import type { UploadRow } from '@fliphouse/db';

import type { EnqueueArgs } from './handle-post-finish.js';

/**
 * The two injected effects the sweep needs, kept abstract so the pure scheduling
 * logic is unit-testable without pg or Redis: `findStuck` reads pre-terminal
 * ledger rows untouched since a cutoff; `enqueue` re-adds one flow idempotently
 * (the FlowProducer dedup id makes a re-add of a live flow a no-op).
 */
export interface SweepDeps {
  findStuck(olderThan: Date): Promise<readonly UploadRow[]>;
  enqueue(args: EnqueueArgs): Promise<void>;
}

/** A ledger row carries everything an enqueue needs; `tusObjectKey` is the source key. */
function toEnqueueArgs(row: UploadRow): EnqueueArgs {
  return { contentHash: row.contentHash, ownerId: row.ownerId, source: row.tusObjectKey };
}

/**
 * Reconcile uploads that won their ledger claim but whose flow never reached
 * Redis (a crash in the gap between claim and enqueue in handlePostFinish).
 * Re-enqueues each stuck row idempotently and returns how many were placed. One
 * row's enqueue failing must NOT abort the others — failures are isolated so a
 * single bad row cannot starve the rest of the backlog; the next tick retries it.
 */
export async function sweepStuckFlows(deps: SweepDeps, graceTtlMs: number): Promise<number> {
  const olderThan = new Date(Date.now() - graceTtlMs);
  const stuck = await deps.findStuck(olderThan);

  let requeued = 0;
  for (const row of stuck) {
    try {
      await deps.enqueue(toEnqueueArgs(row));
      requeued += 1;
    } catch (error) {
      // Isolated: a transient enqueue failure on one row is retried next tick.
      // Logged (not silently swallowed) so a Redis outage starving the recovery
      // path is visible instead of dark — the loop still continues to the rest.
      process.stderr.write(`reconcile-sweep: enqueue failed for ${row.contentHash}: ${String(error)}\n`);
    }
  }
  return requeued;
}
