import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

// Config-as-code contract for the Railway `web` service (P1.14). Reading the
// committed railway.json keeps the deploy declarative (docs/01 §7): the same
// file Railway consumes is the file these tests assert against, so a drift
// between intent and deployed config fails CI rather than surfacing in prod.
const here = dirname(fileURLToPath(import.meta.url));
const railwayConfigPath = resolve(here, '../../railway.json');

type RailwayConfig = {
  deploy: {
    startCommand: string;
    healthcheckPath: string;
    preDeployCommand: string;
    numReplicas: number;
    restartPolicyType: string;
  };
};

function readRailwayConfig(): RailwayConfig {
  return JSON.parse(readFileSync(railwayConfigPath, 'utf8')) as RailwayConfig;
}

describe('railway.json web service config', () => {
  it('railway.json sets healthcheckPath to /api/health', () => {
    expect(readRailwayConfig().deploy.healthcheckPath).toBe('/api/health');
  });

  it('railway.json runs drizzle migrate in preDeployCommand', () => {
    expect(readRailwayConfig().deploy.preDeployCommand).toContain('db:migrate');
  });

  it('web service requests 2 replicas', () => {
    expect(readRailwayConfig().deploy.numReplicas).toBe(2);
  });

  it('start command binds to dual-stack (::)', () => {
    expect(readRailwayConfig().deploy.startCommand).toContain('::');
  });
});
