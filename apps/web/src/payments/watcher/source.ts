// On-chain source abstraction so the watcher core never touches the network.
// The real TronGrid/own-node poller (source.tron.ts) lands at checkpoint F; unit
// tests inject a fixture source (fixtures.ts).

export type TransferEvent = {
  /** On-chain transaction hash — globally unique, used as the credit idempotency key. */
  txid: string;
  /** Block the transfer was included in (drives the confirmations gate). */
  blockNumber: number;
  /** TRC-20 recipient (a per-user deposit address). */
  toAddress: string;
  fromAddress: string;
  /** Token contract address — must equal the USDT contract to count. */
  tokenContract: string;
  /** Amount in the token's smallest unit (USDT TRC-20 = 6 decimals = micro-USDT). */
  amount: bigint;
};

export type TronChainSource = {
  /** Current chain head, used to compute confirmations. */
  getCurrentBlock: () => Promise<number>;
  /** TRC-20 Transfer events to our deposit addresses within an inclusive block range. */
  getTransferEvents: (range: {
    fromBlock: number;
    toBlock: number;
  }) => Promise<TransferEvent[]>;
};
