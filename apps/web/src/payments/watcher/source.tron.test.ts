import { describe, expect, it, vi } from 'vitest';
import { makeTronChainSource } from './source.tron';

// Real TronGrid poller (P1.13.1) with the network injected as `fetch` — these
// tests never hit the chain. The TronGrid trc20 account-endpoint returns only a
// block_timestamp, so blockNumber (the confirmations driver) is resolved with a
// second call (gettransactioninfobyid). Nile testnet shapes.

const RPC = 'https://nile.trongrid.io';
const USDT = 'TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf';
const OUR = 'TUEZSdKsoDHQMeZwihtdoBiN46zxhGWYdH';
const OTHER = 'TSeJkUh4Qv67VNFwY8LaAxERygNdy6NQZK';
const SENDER = 'TWsm8HtU2A5eEzoT8ev8yaoFjHsXLLrckb';

function res(body: unknown) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
}

function trc20Row(over: {
  txid: string;
  to: string;
  value: string;
  contract?: string;
}) {
  return {
    transaction_id: over.txid,
    token_info: {
      address: over.contract ?? USDT,
      decimals: 6,
      symbol: 'USDT',
      name: 'Tether USD',
    },
    block_timestamp: 1_700_000_000_000,
    from: SENDER,
    to: over.to,
    value: over.value,
    type: 'Transfer',
  };
}

describe('tron chain source (TronGrid poller, network injected)', () => {
  it('tron source reports the current block height from the node', async () => {
    const fetchMock = vi.fn(() =>
      res({ block_header: { raw_data: { number: 5_000_000 } } }),
    );
    const source = makeTronChainSource({
      fetch: fetchMock,
      rpcUrl: RPC,
      usdtContract: USDT,
      listAddresses: () => Promise.resolve([]),
    });

    expect(await source.getCurrentBlock()).toBe(5_000_000);
    expect(fetchMock).toHaveBeenCalledWith(
      `${RPC}/wallet/getnowblock`,
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('tron source parses a TronGrid trc20 transfer page into TransferEvent[]', async () => {
    const txid = 'a'.repeat(64);
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/transactions/trc20')) {
        return res({ data: [trc20Row({ txid, to: OUR, value: '2500000' })] });
      }
      if (url.includes('/gettransactioninfobyid')) {
        return res({ id: txid, blockNumber: 100 });
      }
      return res({});
    });
    const source = makeTronChainSource({
      fetch: fetchMock,
      rpcUrl: RPC,
      usdtContract: USDT,
      listAddresses: () => Promise.resolve([OUR]),
    });

    const events = await source.getTransferEvents({ fromBlock: 1, toBlock: 200 });

    expect(events).toEqual([
      {
        txid,
        blockNumber: 100,
        toAddress: OUR,
        fromAddress: SENDER,
        tokenContract: USDT,
        amount: BigInt(2_500_000),
      },
    ]);
  });

  it('tron source filters to USDT contract + our addresses and resolves blockNumber for confirmations', async () => {
    const okTxid = 'b'.repeat(64);
    const wrongTokenTxid = 'c'.repeat(64);
    const otherAddrTxid = 'd'.repeat(64);
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/transactions/trc20')) {
        return res({
          data: [
            trc20Row({ txid: okTxid, to: OUR, value: '1000000' }),
            // Different token contract → must be filtered out.
            trc20Row({
              txid: wrongTokenTxid,
              to: OUR,
              value: '9000000',
              contract: 'TFakeTokenContract00000000000000000',
            }),
            // USDT but to a non-watched address → must be filtered out.
            trc20Row({ txid: otherAddrTxid, to: OTHER, value: '7000000' }),
          ],
        });
      }
      if (url.includes('/gettransactioninfobyid')) {
        return res({ id: okTxid, blockNumber: 42 });
      }
      return res({});
    });
    const source = makeTronChainSource({
      fetch: fetchMock,
      rpcUrl: RPC,
      usdtContract: USDT,
      listAddresses: () => Promise.resolve([OUR]),
    });

    const events = await source.getTransferEvents({ fromBlock: 1, toBlock: 100 });

    expect(events).toHaveLength(1);
    expect(events[0]!.txid).toBe(okTxid);
    expect(events[0]!.tokenContract).toBe(USDT);
    expect(events[0]!.toAddress).toBe(OUR);
    // blockNumber is NOT in the trc20 page — it must come from the info call.
    expect(events[0]!.blockNumber).toBe(42);
    expect(events[0]!.amount).toBe(BigInt(1_000_000));
  });

  it('skips a transfer whose block is not yet packed (no blockNumber)', async () => {
    const txid = 'e'.repeat(64);
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/transactions/trc20')) {
        return res({ data: [trc20Row({ txid, to: OUR, value: '1000000' })] });
      }
      // gettransactioninfobyid returns {} for a tx not yet in a block.
      return res({});
    });
    const source = makeTronChainSource({
      fetch: fetchMock,
      rpcUrl: RPC,
      usdtContract: USDT,
      listAddresses: () => Promise.resolve([OUR]),
    });

    expect(await source.getTransferEvents({ fromBlock: 1, toBlock: 200 })).toEqual(
      [],
    );
  });

  it('skips transfers with a non-positive or malformed amount (untrusted node)', async () => {
    const okTxid = 'f'.repeat(64);
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('/transactions/trc20')) {
        return res({
          data: [
            // A spoofed/compromised node must never drain a balance or crash the
            // tick: negative, zero, and non-integer amounts are all dropped.
            trc20Row({ txid: 'aa'.repeat(32), to: OUR, value: '-1000000' }),
            trc20Row({ txid: 'bb'.repeat(32), to: OUR, value: '0' }),
            trc20Row({ txid: 'cc'.repeat(32), to: OUR, value: '1.5' }),
            trc20Row({ txid: okTxid, to: OUR, value: '1000000' }),
          ],
        });
      }
      if (url.includes('/gettransactioninfobyid')) {
        return res({ id: okTxid, blockNumber: 7 });
      }
      return res({});
    });
    const source = makeTronChainSource({
      fetch: fetchMock,
      rpcUrl: RPC,
      usdtContract: USDT,
      listAddresses: () => Promise.resolve([OUR]),
    });

    const events = await source.getTransferEvents({ fromBlock: 1, toBlock: 100 });

    expect(events).toHaveLength(1);
    expect(events[0]!.txid).toBe(okTxid);
    expect(events[0]!.amount).toBe(BigInt(1_000_000));
  });

  it('throws on a failed TronGrid response', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({ ok: false, json: () => Promise.resolve({}) }),
    );
    const source = makeTronChainSource({
      fetch: fetchMock,
      rpcUrl: RPC,
      usdtContract: USDT,
      listAddresses: () => Promise.resolve([]),
    });

    await expect(source.getCurrentBlock()).rejects.toThrow(/TronGrid request failed/);
  });
});
