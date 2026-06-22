// Client-side mirror of the content-hash identity used across the pipeline. A
// content hash is a 64-char lowercase hex SHA-256 digest — the same shape the
// tusd post-finish hook (apps/hook-receiver) and packages/shared validate. Kept
// local so the web app does not pull the shared package's build into its bundle.

/** True when `value` is a 64-char lowercase hex SHA-256 digest. */
export function isValidContentHash(value: string): boolean {
  return /^[0-9a-f]{64}$/.test(value);
}
