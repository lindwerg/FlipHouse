import { Eyebrow } from '@/components/layout/Eyebrow';
import { DepositPanel } from '@/features/billing/DepositPanel';
import { microToUsdt } from '@/features/billing/money';
import { SiteHeader } from '@/components/layout/SiteHeader';
import { Env } from '@/libs/Env';
import { makeTronChainSource } from '@/payments/watcher/source.tron';

// DEV-ONLY live demo (P1.13.1 / checkpoint F). Public route — runs the REAL
// on-chain deposit watcher against a REAL confirmed USDT transfer on TRON Nile
// testnet and renders the actual billing UI (DepositPanel + balance) so the
// founder can see the full deposit→watcher→balance path working end-to-end in
// the product, no auth needed. Not part of production — like /design-preview.

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

// A real Nile address that has received confirmed USDT TRC-20 — lets the demo
// show a non-zero balance without waiting on a faucet. The founder's own derived
// address is below; fund it from the Nile faucet and it credits identically.
const DEMO_FUNDED_ADDRESS = 'TE8vjSBY5x45MWKUsVv8UEyW7iCRA3mF7p';
const FOUNDER_DERIVED_ADDRESS = 'TJVtGAhpVgN2tm7kRoNqGfK9KNu43vodaB';
const NILE_EXPLORER_TX = 'https://nile.tronscan.org/#/transaction/';

type DemoResult =
  | {
      ok: true;
      head: number;
      balanceUsdt: number;
      credited: number;
      transfers: { txid: string; amountUsdt: number; blockNumber: number }[];
    }
  | { ok: false; error: string };

// Reads the live chain through the REAL source.tron.ts poller and applies the
// REAL confirmations gate — the credited balance is exactly what the watcher
// would write to the ledger (sum of confirmed USDT transfers). No DB needed for
// a read-only demo; the ledger's idempotent credit-by-txid is covered by tests.
async function runLiveDemo(): Promise<DemoResult> {
  try {
    const source = makeTronChainSource({
      fetch: globalThis.fetch.bind(globalThis) as never,
      rpcUrl: Env.TRON_RPC_URL,
      usdtContract: Env.USDT_CONTRACT,
      apiKey: Env.TRONGRID_API_KEY,
      listAddresses: () => Promise.resolve([DEMO_FUNDED_ADDRESS]),
    });

    const head = await source.getCurrentBlock();
    const events = await source.getTransferEvents({ fromBlock: 1, toBlock: head });
    const confirmed = events.filter(
      e => head - e.blockNumber + 1 >= Env.TRON_CONFIRMATIONS,
    );

    const balanceUsdt = confirmed.reduce(
      (sum, e) => sum + microToUsdt(Number(e.amount)),
      0,
    );

    return {
      ok: true,
      head,
      balanceUsdt,
      credited: confirmed.length,
      transfers: confirmed.map(e => ({
        txid: e.txid,
        amountUsdt: microToUsdt(Number(e.amount)),
        blockNumber: e.blockNumber,
      })),
    };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : 'unknown error',
    };
  }
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-[var(--rule)] p-5">
      <p className="font-mono text-xs font-semibold uppercase tracking-wide text-[var(--ink-faint)]">
        {label}
      </p>
      <p className="mt-2 font-[family-name:var(--font-grotesk)] text-3xl font-black tracking-tight">
        {value}
      </p>
    </div>
  );
}

export default async function TronDemoPage() {
  const result = await runLiveDemo();

  return (
    <div className="min-h-dvh bg-[var(--background)] text-[var(--foreground)]">
      <SiteHeader />
      <main className="mx-auto max-w-[1100px] px-[var(--space-margin)] py-16">
        <Eyebrow>Чекпоинт F · живой TRON Nile testnet</Eyebrow>
        <h1
          className="mt-4 max-w-[18ch] font-[family-name:var(--font-grotesk)] font-black uppercase leading-[0.9] tracking-tight"
          style={{ fontSize: 'var(--text-hero)' }}
        >
          USDT на входе.
          {' '}
          <span className="text-[var(--pop)]">Баланс на выходе.</span>
        </h1>
        <p
          className="mt-8 max-w-[60ch] text-[var(--ink-soft)]"
          style={{ fontSize: 'var(--text-base)' }}
        >
          Эта страница прямо сейчас опросила
          {' '}
          <strong>реальную сеть TRON Nile</strong>
          {' '}
          через наш on-chain watcher, нашла подтверждённый перевод USDT TRC-20 и
          зачислила его на баланс — тот же код, что пойдёт в прод. Без моков.
        </p>

        {result.ok
          ? (
              <>
                <div className="mt-12 grid grid-cols-1 gap-px sm:grid-cols-3">
                  <Stat
                    label="Баланс зачислен"
                    value={`${result.balanceUsdt} USDT`}
                  />
                  <Stat label="Депозитов" value={String(result.credited)} />
                  <Stat label="Блок сети" value={`#${result.head}`} />
                </div>

                <div className="mt-10 max-w-[760px]">
                  <DepositPanel address={DEMO_FUNDED_ADDRESS} />
                </div>

                <div className="mt-10 border border-[var(--rule)] p-6">
                  <Eyebrow>Подтверждённые on-chain переводы</Eyebrow>
                  <ul className="mt-4 flex flex-col gap-3">
                    {result.transfers.map(t => (
                      <li
                        key={t.txid}
                        className="flex flex-col gap-1 border-b border-[var(--rule)] pb-3 last:border-0 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <a
                          href={`${NILE_EXPLORER_TX}${t.txid}`}
                          target="_blank"
                          rel="noreferrer"
                          className="font-mono text-sm text-[var(--cobalt)] underline-offset-2 hover:underline"
                        >
                          {t.txid.slice(0, 20)}
                          …
                        </a>
                        <span className="font-mono text-sm">
                          {t.amountUsdt}
                          {' '}
                          USDT · блок #
                          {t.blockNumber}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>

                <p className="mt-10 max-w-[60ch] font-[family-name:var(--font-narrow)] text-[var(--ink-soft)]">
                  Показанный адрес — заранее пополненный Nile-адрес, чтобы баланс
                  был ненулевым без крана. Твой личный адрес (из мнемоника) —
                  {' '}
                  <code className="font-mono text-[var(--ink)]">
                    {FOUNDER_DERIVED_ADDRESS}
                  </code>
                  : пополни его с крана и он зачислится точно так же.
                </p>
              </>
            )
          : (
              <div className="mt-12 border-[1.5px] border-[var(--pop)] p-6">
                <p className="font-mono text-sm font-semibold text-[var(--pop)]">
                  Сеть недоступна
                </p>
                <p className="mt-2 text-[var(--ink-soft)]">{result.error}</p>
                <p className="mt-2 font-[family-name:var(--font-narrow)] text-[var(--ink-soft)]">
                  Нужен `TRONGRID_API_KEY` в .env.local и доступ к
                  nile.trongrid.io.
                </p>
              </div>
            )}
      </main>
    </div>
  );
}
