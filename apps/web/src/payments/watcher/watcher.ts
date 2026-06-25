import type { BillingDatabase } from '@/features/billing/balance';
import { credit } from '@/features/billing/balance';
import { microToUsdt } from '@/features/billing/money';
import type { CursorStore } from './cursor';
import type { TransferEvent, TronChainSource } from './source';

// Own on-chain TRON deposit watcher. The source of truth is the chain itself —
// no third-party PSP/webhook. A USDT TRC-20 transfer to a user's deposit address
// is credited only once it has ≥ N confirmations, idempotently by txid.

export type ProcessSummary = {
  credited: number;
  skippedPending: number;
  skippedWrongToken: number;
  skippedUnknownAddress: number;
  skippedDuplicate: number;
};

export type ProcessTransfersArgs = {
  events: TransferEvent[];
  currentBlock: number;
  usdtContract: string;
  confirmations: number;
  /** Maps a deposit address to its userId (null = unknown address → skip). */
  resolveUserId: (toAddress: string) => Promise<string | null>;
};

const REASON = 'usdt-trc20 deposit';

/**
 * Processes a batch of transfer events: filters to confirmed USDT transfers to
 * known users and credits each one. Credits the actual on-chain amount, never an
 * invoiced amount. Returns a per-outcome summary.
 */
export async function processTransfers(
  db: BillingDatabase,
  args: ProcessTransfersArgs,
): Promise<ProcessSummary> {
  const summary: ProcessSummary = {
    credited: 0,
    skippedPending: 0,
    skippedWrongToken: 0,
    skippedUnknownAddress: 0,
    skippedDuplicate: 0,
  };

  for (const event of args.events) {
    if (event.tokenContract !== args.usdtContract) {
      summary.skippedWrongToken += 1;
      continue;
    }

    const confirmations = args.currentBlock - event.blockNumber + 1;
    if (confirmations < args.confirmations) {
      summary.skippedPending += 1;
      continue;
    }

    const userId = await args.resolveUserId(event.toAddress);
    if (!userId) {
      summary.skippedUnknownAddress += 1;
      continue;
    }

    const amountUsdt = microToUsdt(event.amount);
    const { credited } = await credit(db, {
      userId,
      amountUsdt,
      txid: event.txid,
      reason: REASON,
    });

    if (credited) {
      summary.credited += 1;
    } else {
      summary.skippedDuplicate += 1;
    }
  }

  return summary;
}

export type RunWatcherTickArgs = {
  source: TronChainSource;
  cursor: CursorStore;
  usdtContract: string;
  confirmations: number;
  resolveUserId: (toAddress: string) => Promise<string | null>;
};

const EMPTY_SUMMARY: ProcessSummary = {
  credited: 0,
  skippedPending: 0,
  skippedWrongToken: 0,
  skippedUnknownAddress: 0,
  skippedDuplicate: 0,
};

/**
 * One watcher tick: scans new blocks since the cursor, processes their transfers,
 * and advances the cursor only past now-final blocks (currentBlock - N) so
 * still-pending blocks are re-scanned next tick — safe because credit is
 * idempotent by txid.
 */
export async function runWatcherTick(
  db: BillingDatabase,
  args: RunWatcherTickArgs,
): Promise<ProcessSummary> {
  const currentBlock = await args.source.getCurrentBlock();
  const last = await args.cursor.getLastBlock();
  const fromBlock = last != null ? last + 1 : 1;

  if (fromBlock > currentBlock) {
    return { ...EMPTY_SUMMARY };
  }

  const events = await args.source.getTransferEvents({
    fromBlock,
    toBlock: currentBlock,
  });
  const summary = await processTransfers(db, {
    events,
    currentBlock,
    usdtContract: args.usdtContract,
    confirmations: args.confirmations,
    resolveUserId: args.resolveUserId,
  });

  const finalBlock = currentBlock - args.confirmations;
  await args.cursor.setLastBlock(Math.max(last ?? 0, finalBlock));

  return summary;
}
