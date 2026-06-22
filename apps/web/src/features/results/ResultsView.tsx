'use client';

import { ProgressTracker } from './ProgressTracker';
import { RankedBatchView } from './RankedBatchView';
import type { UseUploadProgressDeps } from './useUploadProgress';
import { useUploadProgress } from './useUploadProgress';

// Container for the live creator results surface (P2.3). Mounts useUploadProgress
// for one upload (by content hash) and branches on its phase: done → the ranked
// clips; failed → a Russian error panel with a retry affordance; duplicate → an
// info panel ("это видео уже обрабатывалось") plus any clips that already exist
// for the hash; otherwise → the live ProgressTracker. `deps` is injectable so the
// branch logic is tested with a fake fetch + timers (no network).

interface ResultsViewProps {
  contentHash: string;
  deps?: UseUploadProgressDeps;
}

export function ResultsView({ contentHash, deps }: ResultsViewProps) {
  const progress = useUploadProgress(contentHash, deps);

  if (progress.phase === 'done') {
    return (
      <div data-slot="results-done" className="mt-8">
        <h2 className="mb-4 text-[var(--text-base)] font-bold tracking-tight text-[var(--foreground)]">
          Готовые клипы
        </h2>
        <RankedBatchView clips={progress.clips} />
      </div>
    );
  }

  if (progress.phase === 'failed') {
    return (
      <section
        data-slot="results-failed"
        aria-labelledby="results-failed-h"
        className="mt-8 max-w-[640px] border-l-2 border-[var(--pop)] pl-4"
      >
        <h2 id="results-failed-h" className="text-[var(--text-base)] font-bold text-[var(--pop)]">
          Не удалось обработать видео
        </h2>
        <p className="mt-2 text-sm text-[var(--ink-soft)]">
          {progress.error ?? 'Произошла ошибка во время обработки.'}
          {' '}
          Попробуйте загрузить видео ещё раз.
        </p>
      </section>
    );
  }

  if (progress.phase === 'duplicate') {
    return (
      <section
        data-slot="results-duplicate"
        aria-labelledby="results-dup-h"
        className="mt-8"
      >
        <h2 id="results-dup-h" className="text-[var(--text-base)] font-bold text-[var(--foreground)]">
          Это видео уже обрабатывалось
        </h2>
        <p className="mt-2 max-w-[640px] text-sm text-[var(--ink-soft)]">
          Мы нашли результаты предыдущей обработки этого видео.
        </p>
        {progress.clips.length > 0
          ? (
              <div className="mt-4">
                <RankedBatchView clips={progress.clips} />
              </div>
            )
          : null}
      </section>
    );
  }

  return (
    <div data-slot="results-progress" className="mt-8">
      <ProgressTracker
        phase={progress.phase}
        percent={progress.percent}
        phaseLabel={progress.phaseLabel}
        error={progress.error}
      />
    </div>
  );
}
