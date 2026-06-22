import type { ClipView } from './api-schemas';
import { mmss, rankLabel, scoreBarWidth } from './format';

// Presentational ranked-clips view for REAL pipeline output (P2.3). Swiss-Pop:
// rank #1 carries the --pop accent; every row is a ranked editorial entry with a
// 9:16 preview, mmss range + dimensions, and a virality bar. Pure props in, no
// data fetching — the container (ResultsView) supplies clips. The hardcoded demo
// (components/sections/RankedBatch) is unchanged so its page/tests stay green.

interface RankedBatchViewProps {
  clips: readonly ClipView[];
}

const ROW =
  'grid grid-cols-[2.5rem_1fr] items-start gap-3 md:grid-cols-[3.5rem_1fr_minmax(7.5rem,9rem)] md:gap-[var(--space-gutter)]';

// 9:16 vertical preview — explicit dimensions keep CLS at 0; the element scales
// down via CSS but the intrinsic ratio is fixed at the source 1080×1920.
const VIDEO_WIDTH = 1080;
const VIDEO_HEIGHT = 1920;

// Only the top few clips are above the fold; below-fold videos use preload="none"
// (no bytes fetched until the user interacts) instead of preload="metadata", which
// is the <video> equivalent of lazy loading.
const ABOVE_FOLD_COUNT = 2;

export function RankedBatchView({ clips }: RankedBatchViewProps) {
  if (clips.length === 0) {
    return (
      <p className="font-mono text-sm text-[var(--ink-soft)]">
        Готовых клипов пока нет.
      </p>
    );
  }

  return (
    <ol
      aria-label="Ранжированные клипы из вашего видео"
      className="list-none border-t-[1.5px] border-[var(--rule-strong)]"
    >
      {clips.map((clip, index) => {
        const isTop = index === 0;
        const belowFold = index >= ABOVE_FOLD_COUNT;
        const accent = isTop ? 'text-[var(--pop)]' : 'text-[var(--foreground)]';
        return (
          <li
            key={clip.rank}
            className={`${ROW} border-b border-[var(--rule)] py-5`}
          >
            <span
              className={`font-mono text-2xl font-semibold tabular-nums ${accent}`}
            >
              {rankLabel(clip.rank)}
            </span>

            <div className="min-w-0">
              <h3 className="font-bold leading-tight tracking-tight text-[var(--foreground)]">
                {clip.title}
              </h3>
              <p className="mt-1 font-mono text-[0.72rem] tracking-wide text-[var(--ink-faint)]">
                {mmss(clip.startTime)}
                {' — '}
                {mmss(clip.endTime)}
                {' · '}
                {clip.width}×{clip.height}
                {' · '}
                {mmss(clip.durationS)}
              </p>

              <div className="mt-3 flex flex-wrap items-end gap-4">
                <video
                  className="w-[clamp(7rem,30vw,11rem)] border border-[var(--rule)] bg-black"
                  controls
                  preload={belowFold ? 'none' : 'metadata'}
                  width={VIDEO_WIDTH}
                  height={VIDEO_HEIGHT}
                  style={{ aspectRatio: '9 / 16' }}
                >
                  <source src={clip.clipUrl} type="video/mp4" />
                  <track kind="captions" />
                </video>

                <a
                  href={clip.clipUrl}
                  download
                  className="inline-flex items-center border border-[var(--rule-strong)] px-3 py-1.5 font-mono text-[0.72rem] uppercase tracking-[0.12em] text-[var(--foreground)] transition-[transform,opacity] duration-[var(--duration-fast)] ease-[var(--ease-out-expo)] hover:-translate-y-0.5 hover:opacity-80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--pop)] active:translate-y-0"
                >
                  Скачать
                </a>
              </div>
            </div>

            <div className="text-right tabular-nums md:pt-1">
              <span className="font-mono text-xl font-semibold text-[var(--foreground)]">
                {Math.round(clip.score)}
              </span>
              <span className="mt-1 block h-1.5 w-full overflow-hidden bg-[var(--rule)]">
                <span
                  className={`block h-full origin-left ${isTop ? 'bg-[var(--pop)]' : 'bg-[var(--foreground)]'}`}
                  style={{ transform: `scaleX(${scoreBarWidth(clip.score) / 100})` }}
                />
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
