import type { ProgressPhase } from './useUploadProgress';

// Accessible live progress UI for the creator dashboard (P2.3). An aria-live
// polite region announces each phase label to assistive tech without stealing
// focus; the percent bar animates on the compositor (transform: scaleX only). No
// data fetching — pure props from the ResultsView container.

interface ProgressTrackerProps {
  percent: number;
  phaseLabel: string;
  error: string | null;
  phase: ProgressPhase;
}

export function ProgressTracker({ percent, phaseLabel, error, phase }: ProgressTrackerProps) {
  const clamped = Math.min(100, Math.max(0, percent));
  return (
    <section aria-labelledby="progress-h" className="max-w-[640px]">
      <h3
        id="progress-h"
        className="font-mono text-[0.72rem] uppercase tracking-[0.14em] text-[var(--ink-faint)]"
      >
        Обработка видео
      </h3>

      <div
        aria-live="polite"
        aria-atomic="true"
        className="mt-2 text-[var(--text-base)] font-semibold leading-tight text-[var(--foreground)]"
      >
        {phaseLabel}
      </div>

      <div
        role="progressbar"
        aria-label="Прогресс обработки"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        className="mt-4 h-1.5 w-full overflow-hidden bg-[var(--rule)]"
      >
        <span
          className="block h-full origin-left bg-[var(--pop)] transition-transform duration-[var(--duration-normal)] ease-[var(--ease-out-expo)]"
          style={{ transform: `scaleX(${clamped / 100})` }}
        />
      </div>

      <p className="mt-2 font-mono text-[0.72rem] tabular-nums text-[var(--ink-soft)]">
        {clamped}%
      </p>

      {error !== null && phase === 'failed'
        ? (
            <p role="alert" className="mt-3 text-sm text-[var(--pop)]">
              {error}
            </p>
          )
        : null}
    </section>
  );
}
