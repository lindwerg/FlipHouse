/**
 * Healthcheck payload for the web service (docs/01 §7 — Railway HC `/api/health`).
 * Pure builder so the contract is unit-tested independently of the route handler.
 */
export interface HealthPayload {
  status: 'ok';
  service: 'web';
}

export function buildHealthPayload(): HealthPayload {
  return { status: 'ok', service: 'web' };
}
