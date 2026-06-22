import { finishUpload, upsertClips } from '@fliphouse/db';
import type { Db } from '@fliphouse/db';

import { runPythonStage } from '../python/spawn.js';
import { buildR2ArtifactStore } from '../r2/build-r2-client.js';
import type { StageProcessorDeps } from '../stages/stage-processor.js';

/**
 * Wire the production {@link StageProcessorDeps} from an injected Db handle + env:
 * the R2 artifact store (sentinels + manifest read), the Python subprocess runner,
 * and the publish DB writers. The Db/Pool lifecycle is owned by the caller
 * ({@link runWorkers}), so this stays a thin, side-effect-light factory.
 */
export function buildStageProcessorDeps(
  db: Db,
  env: Record<string, string | undefined> = process.env,
): StageProcessorDeps {
  const r2 = buildR2ArtifactStore(env);
  return {
    r2,
    runStage: (request, signal) => runPythonStage(request, { signal }),
    publish: {
      readJson: (key) => r2.getJson(key),
      copyObject: (fromKey, toKey) => r2.copyObject(fromKey, toKey),
      upsertClips: (contentHash, rows) => upsertClips(db, contentHash, rows),
      finishUpload: (contentHash, input) => finishUpload(db, contentHash, input),
    },
  };
}
