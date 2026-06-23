'use client';

import { useEffect, useState } from 'react';
import type { OwnerUploadView } from './api-schemas';
import { uploadsResponseSchema } from './api-schemas';
import { RankedBatchView } from './RankedBatchView';
import { uploadBadge } from './upload-badge';

// Persistent "Мои клипы" history for the creator dashboard (P2). Fetches the
// owner-wide GET /api/uploads on mount — NOT gated on an in-session contentHash —
// so finished clips survive a page refresh (the founder's complaint). Each upload
// is an editorial group: a status badge (готово / обрабатывается / ошибка), a
// date, then its ranked clips reused from RankedBatchView (presigned, playable).
// `deps.fetch` is injectable so the load/empty/error branches are unit-testable
// with a fake fetch (no network).

const LOAD_ERROR = 'Не удалось загрузить ваши клипы. Обновите страницу.';

type LoadPhase = 'loading' | 'ready' | 'error';

export interface MyClipsDeps {
  fetch?: typeof fetch;
}

interface MyClipsState {
  phase: LoadPhase;
  uploads: readonly OwnerUploadView[];
}

const INITIAL: MyClipsState = { phase: 'loading', uploads: [] };

/** Stable "DD.MM.YYYY" for the upload date — locale-independent, no hydration drift. */
function formatUploadDate(iso: string): string {
  const date = new Date(iso);
  const dd = date.getUTCDate().toString().padStart(2, '0');
  const mm = (date.getUTCMonth() + 1).toString().padStart(2, '0');
  const yyyy = date.getUTCFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

export function MyClips({ deps }: { deps?: MyClipsDeps } = {}) {
  const fetchImpl = deps?.fetch ?? fetch;
  const [state, setState] = useState<MyClipsState>(INITIAL);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetchImpl('/api/uploads', { headers: { accept: 'application/json' } });
        if (!res.ok) {
          throw new Error(`uploads request failed: ${res.status}`);
        }
        const parsed = uploadsResponseSchema.parse(await res.json());
        if (!cancelled) {
          setState({ phase: 'ready', uploads: parsed.uploads });
        }
      } catch {
        if (!cancelled) {
          setState({ phase: 'error', uploads: [] });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchImpl]);

  return (
    <section
      data-slot="my-clips"
      aria-labelledby="my-clips-heading"
      className="mt-16 border-t-[1.5px] border-[var(--rule-strong)] pt-8"
    >
      <h2
        id="my-clips-heading"
        className="font-[family-name:var(--font-grotesk)] text-[var(--text-base)] font-extrabold tracking-tight text-[var(--foreground)]"
      >
        Мои клипы
      </h2>

      {state.phase === 'loading'
        ? (
            <p className="mt-4 font-mono text-sm text-[var(--ink-soft)]">Загружаем вашу историю…</p>
          )
        : null}

      {state.phase === 'error'
        ? (
            <p className="mt-4 font-mono text-sm text-[var(--pop)]">{LOAD_ERROR}</p>
          )
        : null}

      {state.phase === 'ready' && state.uploads.length === 0
        ? (
            <p className="mt-4 max-w-[52ch] font-[family-name:var(--font-narrow)] leading-snug text-[var(--ink-soft)]">
              Здесь появятся ваши готовые клипы. Загрузите первое видео выше.
            </p>
          )
        : null}

      {state.phase === 'ready' && state.uploads.length > 0
        ? (
            <ol className="mt-6 list-none space-y-12">
              {state.uploads.map((upload) => {
                const badge = uploadBadge(upload.status);
                return (
                  <li key={upload.contentHash} data-slot="my-clips-upload">
                    <div className="flex flex-wrap items-center gap-3">
                      <span
                        className="inline-flex items-center border border-[var(--rule-strong)] px-2 py-0.5 font-mono text-[0.66rem] uppercase tracking-[0.14em]"
                        style={{ color: badge.color }}
                        data-badge={upload.status}
                      >
                        {badge.label}
                      </span>
                      <time
                        dateTime={upload.createdAt}
                        className="font-mono text-[0.72rem] tracking-wide text-[var(--ink-faint)]"
                      >
                        {formatUploadDate(upload.createdAt)}
                      </time>
                    </div>
                    <div className="mt-4">
                      <RankedBatchView clips={upload.clips} />
                    </div>
                  </li>
                );
              })}
            </ol>
          )
        : null}
    </section>
  );
}
