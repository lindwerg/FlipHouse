import type { TransferEvent, TronChainSource } from './source';

// Test fixtures for the watcher: build TRC-20 transfer events and a fake chain
// source. Production code never imports this — the real source is source.tron.ts.

const DEFAULT_FROM = 'TsenderFakeAddress00000000000000000';

/** Builds a TRC-20 transfer event; fromAddress defaults to a fixed sender. */
export function makeTransfer(e: {
  txid: string;
  blockNumber: number;
  toAddress: string;
  tokenContract: string;
  amount: bigint;
  fromAddress?: string;
}): TransferEvent {
  return {
    txid: e.txid,
    blockNumber: e.blockNumber,
    toAddress: e.toAddress,
    fromAddress: e.fromAddress ?? DEFAULT_FROM,
    tokenContract: e.tokenContract,
    amount: e.amount,
  };
}

/** A chain source that replays fixed events and reports a fixed head block. */
export function fakeChainSource(
  events: TransferEvent[],
  currentBlock: number,
): TronChainSource {
  return {
    getCurrentBlock: () => Promise.resolve(currentBlock),
    getTransferEvents: ({ fromBlock, toBlock }) =>
      Promise.resolve(
        events.filter(
          e => e.blockNumber >= fromBlock && e.blockNumber <= toBlock,
        ),
      ),
  };
}
