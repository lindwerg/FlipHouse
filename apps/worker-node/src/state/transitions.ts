/**
 * Forward-only upload status state machine (docs blueprint §5). The DAG only
 * ever moves a job forward through the pipeline; the sole backward move is to
 * `failed`, and `duplicate` is reachable only from `queued` (the ON CONFLICT
 * claim-skip). Terminal states have no exit. The `guarded setStatus` in the
 * ledger repo uses this to reject out-of-order writes from re-delivered jobs.
 */
export const UPLOAD_STATUSES = [
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
] as const;

export type UploadStatus = (typeof UPLOAD_STATUSES)[number];

/** Linear forward progression; `failed`/`duplicate` sit outside it by design. */
const FORWARD_ORDER: readonly UploadStatus[] = [
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
];

const TERMINAL: ReadonlySet<UploadStatus> = new Set<UploadStatus>(['done', 'failed', 'duplicate']);

/** Whether moving `from → to` is a legal status transition. */
export function validTransition(from: UploadStatus, to: UploadStatus): boolean {
  if (TERMINAL.has(from)) return false; // terminal states never transition out
  if (to === 'failed') return true; // any in-flight job may fail
  if (to === 'duplicate') return from === 'queued'; // only at the claim-skip
  return FORWARD_ORDER.indexOf(to) > FORWARD_ORDER.indexOf(from); // strictly forward
}
