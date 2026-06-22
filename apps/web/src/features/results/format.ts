// Pure display formatters for the results dashboard (P2.3). Unit-tested at 100%.

/** Seconds → `m:ss` (e.g. 41.5 → "0:41", 754 → "12:34"). Negatives clamp to 0. */
export function mmss(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

/** Two-digit rank label for display: 0 → "01", 9 → "10". */
export function rankLabel(rank: number): string {
  return (rank + 1).toString().padStart(2, '0');
}

/** Clamp a virality score to a 0–100 bar width percentage. */
export function scoreBarWidth(score: number): number {
  return Math.min(100, Math.max(0, Math.round(score)));
}
