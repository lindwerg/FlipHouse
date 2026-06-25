import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

/**
 * Guard the OBS-1 runtime-env contract: the worker image MUST set
 * `PYTHONUNBUFFERED=1`, otherwise the Python sidecar's stderr is block-buffered
 * and Railway's log pipeline (which only ingests unbuffered lines) shows nothing
 * but "Starting Container" — the exact diagnosability gap OBS-1 fixes. A static
 * grep of the Dockerfile catches an accidental removal in review, not in prod.
 */
test('Dockerfile pins PYTHONUNBUFFERED=1 in the runtime stage', () => {
  const dockerfile = fileURLToPath(new URL('../Dockerfile', import.meta.url));
  const content = readFileSync(dockerfile, 'utf8');
  expect(content).toMatch(/^ENV PYTHONUNBUFFERED=1$/m);
});
