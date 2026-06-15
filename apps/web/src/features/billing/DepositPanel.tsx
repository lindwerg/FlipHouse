'use client';

import { useState } from 'react';

// Swiss-styled "Пополнить" panel: shows the user's personal TRC-20 deposit
// address and a copy control. The address is derived server-side and passed in;
// this client component only handles the copy interaction.

type DepositPanelProps = {
  address: string;
};

export function DepositPanel({ address }: DepositPanelProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(address);
    setCopied(true);
  };

  return (
    <section
      aria-labelledby="deposit-heading"
      className="mt-10 border-[1.5px] border-[var(--rule-strong)] p-6 md:p-8"
    >
      <p className="font-mono text-sm font-semibold tracking-wide text-[var(--pop)]">
        Баланс · USDT
      </p>
      <h2
        id="deposit-heading"
        className="mt-2 font-[family-name:var(--font-grotesk)] text-2xl font-extrabold tracking-tight"
      >
        Пополнить
      </h2>
      <p className="mt-2 max-w-[48ch] font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
        Переведите USDT в сети TRC-20 на ваш персональный адрес — баланс
        зачислится после подтверждения сети.
      </p>

      <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <code
          data-slot="deposit-address"
          className="block flex-1 overflow-x-auto border border-[var(--rule)] bg-[var(--background)] px-3 py-2 font-mono text-sm"
        >
          {address}
        </code>
        <button
          type="button"
          onClick={copy}
          className="shrink-0 border-[1.5px] border-[var(--pop)] px-4 py-2 font-mono text-sm font-semibold text-[var(--pop)] transition-colors duration-300 hover:bg-[var(--pop)] hover:text-[var(--on-pop-solid)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--pop)]"
        >
          {copied ? 'Скопировано' : 'Скопировать'}
        </button>
      </div>
    </section>
  );
}
