import type { UploadStatus } from '@fliphouse/db';

// Pure status → compact badge mapping for the "Мои клипы" history (P2). Collapses
// the 13-state forward-only ledger status into the three states a creator cares
// about at a glance — готово / обрабатывается / ошибка — each carrying a design
// token colour (Swiss-Pop / OLED-black). Pure, no I/O — unit-tested.

const TERMINAL_DONE: UploadStatus = 'done';
const FAILED: UploadStatus = 'failed';
const DUPLICATE: UploadStatus = 'duplicate';

export interface UploadBadge {
  /** Short Russian label shown in the badge pill. */
  readonly label: string;
  /** CSS colour for the badge text — a design token, not a hardcoded hex. */
  readonly color: string;
}

const DONE_BADGE: UploadBadge = { label: 'готово', color: 'var(--foreground)' };
const PROCESSING_BADGE: UploadBadge = { label: 'обрабатывается', color: 'var(--cobalt)' };
const ERROR_BADGE: UploadBadge = { label: 'ошибка', color: 'var(--pop)' };
const DUPLICATE_BADGE: UploadBadge = { label: 'дубликат', color: 'var(--ink-soft)' };

/**
 * Map an upload's ledger status to its dashboard badge. `done` → готово,
 * `failed` → ошибка, `duplicate` → дубликат; every non-terminal stage collapses
 * to обрабатывается so an in-flight upload reads as one clear state.
 */
export function uploadBadge(status: UploadStatus): UploadBadge {
  switch (status) {
    case TERMINAL_DONE:
      return DONE_BADGE;
    case FAILED:
      return ERROR_BADGE;
    case DUPLICATE:
      return DUPLICATE_BADGE;
    default:
      return PROCESSING_BADGE;
  }
}
