import type { UploadStatus } from '@fliphouse/db';

// Pure status → progress mapping for the creator results dashboard (P2.3). The
// upload_ledger `status` is the single shared truth; these helpers turn it into
// the % / Russian label the UI renders and the monotonic event id the SSE stream
// uses for forward-only resume. All pure — unit-tested at 100%, no I/O.

/**
 * Canonical forward-only status order. The INDEX of a status here is its
 * `statusOrdinal` — a monotonic, wall-clock-free cursor the SSE stream emits as
 * the event `id:` so a reconnecting client can resume forward-only. MUST mirror
 * `uploadStatusEnum` in @fliphouse/db (and worker-node transitions.ts).
 */
export const UPLOAD_STATUSES: readonly UploadStatus[] = [
  'queued',
  'hashing',
  'transcoding',
  'transcribing',
  'scoring',
  'reframing',
  'captioning',
  'rendering',
  'storing',
  'publishing',
  'done',
  'failed',
  'duplicate',
];

const TERMINAL_STATUSES: readonly UploadStatus[] = ['done', 'failed', 'duplicate'];

/** Russian phase labels keyed by status (brand "FlipHouse" stays latin elsewhere). */
const STATUS_LABELS: Readonly<Record<UploadStatus, string>> = {
  queued: 'В очереди',
  hashing: 'Считаем отпечаток',
  transcoding: 'Перекодируем видео',
  transcribing: 'Расшифровываем речь',
  scoring: 'Оцениваем виральность',
  reframing: 'Кадрируем 9:16',
  captioning: 'Накладываем субтитры',
  rendering: 'Рендерим клипы',
  storing: 'Сохраняем результат',
  publishing: 'Публикуем',
  done: 'Готово',
  failed: 'Ошибка обработки',
  duplicate: 'Это видео уже обрабатывалось',
};

export interface StatusProgress {
  readonly percent: number;
  readonly label: string;
  readonly isTerminal: boolean;
}

/** Index of a status in the canonical order — the monotonic SSE event id. */
export function statusOrdinal(status: UploadStatus): number {
  return UPLOAD_STATUSES.indexOf(status);
}

/**
 * Maps a status to a 0–100 percent, a Russian label, and whether it is terminal.
 * `done` is 100; `failed`/`duplicate` report the percent of the last in-flight
 * stage (`publishing`-60%-ish position) is irrelevant — terminal failures are
 * shown as their own panel — so they report 100 to stop the bar from lying about
 * "still working". Non-terminal stages are spread evenly across 0–95 so the bar
 * never claims 100% before the run is actually done.
 */
export function statusToProgress(status: UploadStatus): StatusProgress {
  const isTerminal = TERMINAL_STATUSES.includes(status);
  const label = STATUS_LABELS[status];
  if (isTerminal) {
    return { percent: 100, label, isTerminal: true };
  }
  // 'publishing' is the last pre-terminal stage; cap its bar at 95% so 100%
  // is reserved for an actually-terminal status.
  const lastPreTerminal = statusOrdinal('publishing');
  const ordinal = statusOrdinal(status);
  const percent = Math.round((ordinal / lastPreTerminal) * 95);
  return { percent, label, isTerminal: false };
}
