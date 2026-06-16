import * as z from 'zod';
import type { TransferEvent, TronChainSource } from './source';

// Real on-chain TRON source (P1.13.1): polls TronGrid / our own node for USDT
// TRC-20 Transfer events to our deposit addresses. The network is injected as a
// `fetch`-like client so the watcher core and unit tests never touch the chain.
//
// The TronGrid trc20 account-endpoint returns only a block_timestamp, so the
// blockNumber that drives the confirmations gate is resolved with a second call
// (gettransactioninfobyid) per transfer. Over-fetching is safe — the credit is
// idempotent by txid — so we keep only transfers whose resolved block falls in
// the requested range.

type FetchLike = (
  url: string,
  init?: { method?: string; headers?: Record<string, string>; body?: string },
) => Promise<{ ok: boolean; json: () => Promise<unknown> }>;

export type TronChainSourceDeps = {
  fetch: FetchLike;
  rpcUrl: string;
  usdtContract: string;
  /** Returns the deposit addresses we watch (a DB query in prod). */
  listAddresses: () => Promise<string[]>;
  /** Optional TronGrid API key (sent as the TRON-PRO-API-KEY header). */
  apiKey?: string;
};

// TronGrid response shapes — validated at the boundary; external data is untrusted.
const nowBlockSchema = z.object({
  block_header: z.object({ raw_data: z.object({ number: z.number() }) }),
});

const trc20PageSchema = z.object({
  data: z.array(
    z.object({
      transaction_id: z.string(),
      token_info: z.object({ address: z.string() }),
      from: z.string(),
      to: z.string(),
      value: z.string(),
      type: z.string().optional(),
    }),
  ),
});

const txInfoSchema = z.object({ blockNumber: z.number().optional() });

const TRC20_PAGE_LIMIT = 200;

// USDT TRC-20 amounts are non-negative integer strings in the token's smallest
// unit. Never trust the node: a negative value would *drain* a balance on credit
// and a non-integer would crash BigInt(), so we parse defensively and skip
// anything that is not a positive integer.
function parsePositiveAmount(value: string): bigint | null {
  if (!/^\d+$/.test(value)) {
    return null;
  }
  const amount = BigInt(value);
  return amount > BigInt(0) ? amount : null;
}

function headers(apiKey?: string): Record<string, string> {
  const base: Record<string, string> = { 'Content-Type': 'application/json' };
  return apiKey ? { ...base, 'TRON-PRO-API-KEY': apiKey } : base;
}

async function readJson(
  res: { ok: boolean; json: () => Promise<unknown> },
  context: string,
): Promise<unknown> {
  if (!res.ok) {
    throw new Error(`TronGrid request failed: ${context}`);
  }
  return res.json();
}

export function makeTronChainSource(
  deps: TronChainSourceDeps,
): TronChainSource {
  const { fetch, rpcUrl, usdtContract, listAddresses, apiKey } = deps;

  async function getCurrentBlock(): Promise<number> {
    const res = await fetch(`${rpcUrl}/wallet/getnowblock`, {
      method: 'POST',
      headers: headers(apiKey),
      body: JSON.stringify({}),
    });
    const parsed = nowBlockSchema.parse(await readJson(res, 'getnowblock'));
    return parsed.block_header.raw_data.number;
  }

  async function resolveBlockNumber(txid: string): Promise<number | null> {
    const res = await fetch(`${rpcUrl}/wallet/gettransactioninfobyid`, {
      method: 'POST',
      headers: headers(apiKey),
      body: JSON.stringify({ value: txid }),
    });
    const parsed = txInfoSchema.parse(await readJson(res, 'gettransactioninfobyid'));
    return parsed.blockNumber ?? null;
  }

  async function fetchAddressTransfers(address: string): Promise<TransferEvent[]> {
    const url =
      `${rpcUrl}/v1/accounts/${address}/transactions/trc20` +
      `?only_to=true&limit=${TRC20_PAGE_LIMIT}&contract_address=${usdtContract}`;
    const res = await fetch(url, { headers: headers(apiKey) });
    const page = trc20PageSchema.parse(await readJson(res, 'trc20 page'));

    const events: TransferEvent[] = [];
    for (const row of page.data) {
      // Defensive: the contract_address + only_to query params already narrow,
      // but never trust the endpoint — re-filter to our USDT contract + address.
      if (row.token_info.address !== usdtContract || row.to !== address) {
        continue;
      }
      const amount = parsePositiveAmount(row.value);
      if (amount == null) {
        continue;
      }
      const blockNumber = await resolveBlockNumber(row.transaction_id);
      if (blockNumber == null) {
        continue;
      }
      events.push({
        txid: row.transaction_id,
        blockNumber,
        toAddress: row.to,
        fromAddress: row.from,
        tokenContract: row.token_info.address,
        amount,
      });
    }
    return events;
  }

  async function getTransferEvents(range: {
    fromBlock: number;
    toBlock: number;
  }): Promise<TransferEvent[]> {
    const addresses = await listAddresses();
    const events: TransferEvent[] = [];
    for (const address of addresses) {
      for (const event of await fetchAddressTransfers(address)) {
        if (event.blockNumber >= range.fromBlock && event.blockNumber <= range.toBlock) {
          events.push(event);
        }
      }
    }
    return events;
  }

  return { getCurrentBlock, getTransferEvents };
}
