# P2 Node E2E-wiring — Blueprint (ultracode army, 2026-06-22)

{
  "decisions": [
    {
      "fork": "Fork 1 — store↔publish bridge: which artifact publish consumes (FINAL, with resultUrl + reframePrefix wire contract resolved)",
      "decision": "Eliminate result.json. Remove the 'store' stage from the Node CHAIN/STAGES union and from all four Stage-keyed maps. Publish reads reframe's manifest.json directly. RESOLVED WIRE CONTRACT (was ambiguous in the original): publish job data carries exactly ONE new field — reframePrefix: outputPrefix('reframe', contentHash) (= 'intermediate/{hash}/reframe'). Inside publishUpload, derive manifestKey = `${args.reframePrefix}/manifest.json`, read it, and compute each clip URL as resolveClipKey(args.reframePrefix, clip.path) = `${args.reframePrefix}/${clip.path}` — the exact key Python wrote (Python upload_outputs uses content_key(prefix, name) = '{prefix}/{filename}', confirmed in stages/store.py + artifacts.py). deriveClipKey is NO LONGER called on the hot path; its import is dropped from publish.ts. RESOLVED resultUrl (was dangling): remove resultUrl from PublishArgs entirely; inside publishUpload set finishUpload's resultUrl = manifestKey (the manifest IS the canonical result artifact now that result.json is gone). DB column uploads.result_url is nullable (schema.ts:48 `text('result_url')`, no .notNull()), so a wrong/missing value never crashed the DB — but writing the manifestKey gives the row a meaningful, non-undefined URL. CHAIN drops to 7: transcode→asr→score→reframe→caption→banner→publish.",
      "rationale": "Verified against source: result.json (stages/store.py) carries only 7 fields {rank,key,title,score,duration_s,width,height} while clips schema (schema.ts:61-89) needs 17 incl. sub_scores/confidence/start_time/end_time/used_video/model_used/modalities_used/manifest_schema_version/engine — expanding result.json duplicates the manifest (dual-source-of-truth anti-pattern). publish.ts already ignores result.json and parses manifest.json, so store is pure cost. The original blueprint left TWO holes the adversarial review flagged as critical/high and I confirmed: (a) reframePrefix was referenced in publish.ts changes but only manifestKey was passed by the flow builder — fixed by passing reframePrefix as the single named field and deriving manifestKey from it (no fragile '/manifest.json' string-stripping); (b) resultUrl had no producer after store removal — fixed by aliasing it to manifestKey. I reject the reviewer's framing that a missing resultUrl is a DB-crash 'critical': schema.ts:48 proves the column is nullable. It is nonetheless a real dangling-field bug worth fixing, so adopted at HIGH.",
      "filesToChange": [
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/packages/shared/src/flow/stage.ts",
          "change": "Remove 'store' from the STAGES tuple. Stage union narrows to 7. Update the topology NOTE comment to list the 7-stage chain."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/queues/queue-config.ts",
          "change": "REQUIRED to avoid TS compile break: remove the 'store' entry from STAGE_RETRY (line 46) and from STAGE_TIMEOUT_MS (line 58). Both are Readonly<Record<Stage,...>>; once Stage drops 'store' the keysets must drop it too."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/progress/flow-progress.ts",
          "change": "REQUIRED to avoid TS compile break + progress drift: remove 'store: 1' from STAGE_WEIGHT (Readonly<Record<Stage,number>>). TOTAL_WEIGHT recomputes over STAGES automatically. Update the '8-node DAG' comment to '7-node DAG'."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/flow/build-flow-tree.ts",
          "change": "Remove 'store' from CHAIN (now 7 stages). In nodeFor(), when stage === 'publish', add reframePrefix: outputPrefix('reframe', args.contentHash) to the job data object so the publish processor receives it."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/stages/publish.ts",
          "change": "PublishArgs: replace { contentHash, manifestKey, resultUrl } with { contentHash, reframePrefix }. In publishUpload: const manifestKey = `${args.reframePrefix}/manifest.json`; parse it; map clipUrl via new local helper resolveClipKey(reframePrefix, clipPath) = `${reframePrefix}/${clipPath}`. Drop the deriveClipKey import (keep renderManifestSchema). finishUpload call: resultUrl: manifestKey, manifestUrl: manifestKey, engine: manifest.engine."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/stages/registry.ts",
          "change": "Remove 'store' from the PYTHON_STAGES set (now 6 Python stages)."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/stages/_registry.py",
          "change": "PHASE 2 ONLY (see risks/deploy ordering): remove the 'store' lambda + the store_handler import. Do NOT land this in the same deploy as the Node CHAIN change — keep store_handler registered until the store queue is drained."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/stages/publish.test.ts",
          "change": "Update args from {contentHash,manifestKey,resultUrl} to {contentHash, reframePrefix: `intermediate/${HASH}/reframe`}. Fixture clip paths → 'clip_00.mp4'/'clip_01.mp4'. Assert clipUrl === `intermediate/${HASH}/reframe/clip_00.mp4`. Assert finishUpload received resultUrl === manifestUrl === `intermediate/${HASH}/reframe/manifest.json`. Add a test asserting publishUpload does NOT import/call deriveClipKey (assert the resolved key has NO 'clips/' prefix). Add fixture fields segment_count:1, caption_band:null, schema_version:2 (Fork 4)."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/flow/build-flow-tree.test.ts",
          "change": "Remove 'store' from the failParentOnFailure list (line 59) and from the queue-routing map assertion (line 74). Assert chain length is 7 and excludes 'store'. Add assertion: publish node data contains reframePrefix === `intermediate/${ARGS.contentHash}/reframe`."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/worker/worker-order.itest.ts",
          "change": "Update the expected order array (lines 59-67) to the 7-stage list, dropping 'store'."
        }
      ],
      "testPlan": [
        "RED: publish.test.ts — assert clipUrl for rank 0 === `intermediate/${HASH}/reframe/clip_00.mp4`; fails (current code calls deriveClipKey → 'clips/{hash}/clip_000.mp4')",
        "GREEN: implement resolveClipKey + reframePrefix-derived manifestKey in publishUpload; drop deriveClipKey import",
        "RED: publish.test.ts — assert finishUpload.resultUrl === manifestUrl (the manifest key); fails (current passes args.resultUrl='r')",
        "GREEN: set resultUrl=manifestKey in finishUpload call; remove resultUrl from PublishArgs",
        "RED: build-flow-tree.test.ts — assert chain length 7 and publish data.reframePrefix set; fails currently",
        "GREEN: remove 'store' from CHAIN; inject reframePrefix in nodeFor for publish",
        "RED (compile): tsc fails on queue-config.ts + flow-progress.ts incomplete Record<Stage>; fix by removing 'store' keys",
        "Verify worker-order.itest.ts expects 7-stage order against real Redis",
        "Verify registry.test.ts: isPythonStage('store') === false",
        "Verify flow-progress.test.ts: progress still reaches 100 at publish (TOTAL_WEIGHT recomputed)"
      ],
      "risks": [
        "DEPLOY-ORDER RACE (adopted from reliability review, was under-specified): Railway restarts Node and Python independently. If Python's registry loses 'store' before old Node workers stop enqueuing it, in-flight 'store' jobs hit UNKNOWN_STAGE → UnrecoverableError → failParentOnFailure kills the whole flow and orphans rendered clips. MITIGATION (two-phase): Phase 1 deploy = Node CHAIN without 'store' + leave Python store_handler registered. Drain the cpu/store queue to zero (observe BullMQ). Phase 2 deploy = remove store_handler from Python _registry.py. _registry.py change is explicitly Phase-2-only above.",
        "Existing R2 store sentinels (intermediate/{hash}/store/_COMPLETE.json) from old uploads are orphaned harmlessly — no migration; no new upload writes them.",
        "Any external reader of result.json by convention gets a 404 — none exist in-repo (grep clean); audit before deploy.",
        "ffmpeg H.264 encoding is not byte-deterministic, so a retry after OOM may write different bytes to the same reframe clip key — harmless: R2 PUT is last-writer-wins and clips rows store no sha256. Noted, not blocking."
      ]
    },
    {
      "fork": "Fork 2 — clip-naming 404: canonicalize TS padding to Python's 2 digits + harden path against traversal",
      "decision": "Align TS to Python (the file producer). Change clipFileName in manifest-schema.ts from padStart(3,'0') to padStart(2,'0') → 'clip_00.mp4', matching crop_geometry.clip_filename (`f\"clip_{rank:02d}.mp4\"`, confirmed line 146). Python stays unchanged (ground truth). ADOPTED from security review: tighten clipEntrySchema.path from z.string().min(1) to z.string().regex(/^clip_\\d{2}\\.mp4$/) so a malformed/compromised manifest.json cannot inject a path-traversal value (e.g. '../uploads/secret.mp4') into resolveClipKey. This is also a contract assertion pinning the exact filename format the producer emits. Update all TS fixtures from 3-digit to 2-digit.",
      "rationale": "Verified: Python crop_geometry.py:146 = clip_{rank:02d}.mp4 and golden test_manifest.py:79 = 'clip_00.mp4'. TS currently produces 'clip_000.mp4' — the literal 404 root cause. Consumer-driven contract: the consumer must read the producer's key. 2-digit padding is sufficient for top-N (N small, <100). Changing TS (4 files) is less blast radius than changing Python (crop_geometry, render, 2 test goldens). Fork 1 removes deriveClipKey from the hot path, but the constant must stay correct for the Fork 4 golden contract test to be meaningful. The regex hardening is genuinely valuable: Fork 1 makes publish read clip.path from an R2 object (previously deriveClipKey was pure and un-traversable), so validating the path at the zod boundary restores that safety property before resolveClipKey concatenates it.",
      "filesToChange": [
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/packages/shared/src/manifest/manifest-schema.ts",
          "change": "clipFileName: String(rank).padStart(2,'0') → 'clip_00.mp4'. Update JSDoc to '2-digit zero-pad to match Python crop_geometry.clip_filename (clip_{rank:02d})'. clipEntrySchema.path: z.string().regex(/^clip_\\d{2}\\.mp4$/,'clip path must be a bare 2-digit filename'). Keep deriveClipKey signature (still exported for any future use)."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/packages/shared/src/manifest/manifest-schema.test.ts",
          "change": "clipFileName(0)==='clip_00.mp4', clipFileName(12)==='clip_12.mp4'. deriveClipKey ends with '/clip_03.mp4'. validClip.path → 'clip_00.mp4'. Add test: renderManifestSchema.safeParse({...validManifest, clips:[{...validClip, path:'../evil.mp4'}]}).success === false."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/packages/db/src/ledger-repo.test.ts",
          "change": "Update the fixture clipUrl literal 'clips/x/clip_000.mp4' (line 99) to a 2-digit form for consistency — cosmetic, but keeps the repo free of the stale 3-digit pattern. Verify test still green."
        }
      ],
      "testPlan": [
        "RED: manifest-schema.test.ts clipFileName(0) expects 'clip_00.mp4'; fails (returns 'clip_000.mp4')",
        "GREEN: padStart(3)→padStart(2)",
        "RED: safeParse with path '../evil.mp4' expects success===false; fails (current min(1) accepts it)",
        "GREEN: add regex /^clip_\\d{2}\\.mp4$/ to path",
        "Verify Fork 4 golden assertion clipFileName(0) === golden.clips[0].path ('clip_00.mp4') passes",
        "Verify publish.test.ts 2-digit clipUrl assertions pass"
      ],
      "risks": [
        "No existing R2 objects are named clip_000.mp4: no E2E ever ran (ArtifactStore was missing), so the bucket has no buggy 3-digit clips — safe.",
        "deriveClipKey remains exported in @fliphouse/shared public surface; any out-of-repo caller hardcoding 3 digits would break — grep shows only in-repo callers; audit before release.",
        "The regex hard-codes 2-digit width; if N ever exceeds 99 clips the producer's :02d and this regex both need widening together — acceptable, N is capped well below 100."
      ]
    },
    {
      "fork": "Fork 3 — ArtifactStore R2 impl (E2E BLOCKER): create apps/worker-node/src/r2/artifact-store.ts",
      "decision": "Implement R2ArtifactStore (implements the existing ArtifactStore interface in handler-contract.ts) using @aws-sdk/client-s3 v3. Pure exported helpers buildS3Config, isNotFound, isPreconditionFailed get 100% unit coverage; only the two s3Client.send() calls are /* v8 ignore */-gated, mirroring Python r2.py's seam. Export a module-level const SENTINEL_SCHEMA_VERSION = 1 (ADOPTED from speed review: no inline literal) and SENTINEL_MAX_BYTES = 1024 (ADOPTED from reliability review: an asserted size invariant guaranteeing the sentinel body stays single-part so IfNoneMatch conditional-write atomicity holds). hasSentinel HEADs prefix+'/_COMPLETE.json': true on success, false ONLY on isNotFound, rethrow all else (403/5xx/network → BullMQ retry, never silently 'not found'). writeSentinel PUTs with IfNoneMatch='*' and body JSON.stringify({...marker, completedAt, schemaVersion:SENTINEL_SCHEMA_VERSION}); swallow 412 (PreconditionFailed) AND 409 (Conflict, concurrent delete+rewrite race) as idempotent no-ops; rethrow all else. buildS3Config sets requestChecksumCalculation:'WHEN_REQUIRED' + responseChecksumValidation:'WHEN_REQUIRED' to neutralize the aws-sdk-v3 CRC32 trailer bug R2 rejects (mirror of the boto3-1.36 fix already in stages/r2.py). Add @aws-sdk/client-s3 to apps/worker-node/package.json. Thin factory build-r2-client.ts constructs the singleton S3Client + R2ArtifactStore from env.",
      "rationale": "Verified: executeStage (execute-stage.ts:17) calls ctx.r2.hasSentinel and ctx.r2.writeSentinel — handler-contract.ts:8 defines the interface but NO concrete impl exists in the repo, so executeStage throws before runStage and Python never spawns. This is the true E2E blocker. The WHEN_REQUIRED knob is the exact mirror of the documented boto3-1.36 fix on the Python side. IfNoneMatch='*' makes concurrent duplicate workers idempotent (second writer gets 412). Checking both httpStatusCode AND err.name guards the documented v3 head-404 naming variance. SENTINEL_MAX_BYTES converts the prose 'sentinel is tiny so never multipart' note into a test-enforced invariant so a future dev adding fields gets a failing test, not a silent atomicity regression.",
      "filesToChange": [
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/r2/artifact-store.ts",
          "change": "CREATE. Export const SENTINEL_SCHEMA_VERSION=1, SENTINEL_MAX_BYTES=1024. Export pure: buildS3Config(env) → {region:'auto', endpoint:`https://${env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`, credentials:{accessKeyId,secretAccessKey}, requestChecksumCalculation:'WHEN_REQUIRED', responseChecksumValidation:'WHEN_REQUIRED'}; isNotFound(err) = err?.$metadata?.httpStatusCode===404 || err?.name==='NotFound'; isPreconditionFailed(err) = err?.$metadata?.httpStatusCode===412 || err?.name==='PreconditionFailed'. Export class R2ArtifactStore implements ArtifactStore; constructor({bucket,s3Client}). hasSentinel: HeadObjectCommand(prefix+'/_COMPLETE.json'); return true; catch→ if isNotFound return false; throw. writeSentinel: const body=JSON.stringify({...marker, completedAt:new Date().toISOString(), schemaVersion:SENTINEL_SCHEMA_VERSION}); assert body byte length<=SENTINEL_MAX_BYTES; PutObjectCommand({Body:body, ContentType:'application/json', IfNoneMatch:'*'}); catch→ if isPreconditionFailed return; if err?.$metadata?.httpStatusCode===409 return; throw. The two .send() calls inside /* v8 ignore */ blocks."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/r2/artifact-store.test.ts",
          "change": "CREATE. buildS3Config: endpoint from R2_ACCOUNT_ID, both checksum knobs WHEN_REQUIRED. isNotFound: true for {$metadata:{httpStatusCode:404}}, true for {name:'NotFound'}, false for 403/500. isPreconditionFailed: true for 412 / {name:'PreconditionFailed'}, false for 200. R2ArtifactStore.hasSentinel via vi.fn() send: resolves→true; throws 404→false; throws 403→rethrow. writeSentinel: resolves→no throw; throws 412→no throw; throws 409→no throw; throws 500→rethrow. ADOPTED: explicit 409 case. SENTINEL_MAX_BYTES: a marker that overflows 1024 bytes makes writeSentinel throw the size-invariant error."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/r2/build-r2-client.ts",
          "change": "CREATE. buildR2ArtifactStore(env): reads R2_ACCOUNT_ID/R2_BUCKET/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY, throws a clear Error naming the missing var, returns new R2ArtifactStore({bucket, s3Client:new S3Client(buildS3Config(env))}). Construct S3Client ONCE here (shared pool). Thin glue — covered by integration, no unit test required."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/package.json",
          "change": "Add '@aws-sdk/client-s3':'^3.700.0' (or current stable) to dependencies."
        }
      ],
      "testPlan": [
        "RED: artifact-store.test.ts isNotFound({$metadata:{httpStatusCode:404}})===true; fails (file absent)",
        "GREEN: create artifact-store.ts pure helpers + constants",
        "RED: hasSentinel mock expects false when send throws 404; fails (class absent)",
        "GREEN: implement R2ArtifactStore.hasSentinel",
        "RED: writeSentinel expects no throw on 412 and on 409; fails",
        "GREEN: implement writeSentinel with IfNoneMatch + 412/409 swallow",
        "RED: writeSentinel with >1024-byte marker expects throw; fails",
        "GREEN: add SENTINEL_MAX_BYTES assertion",
        "Verify 100% branch coverage (only the two send() calls v8-ignored)",
        "Integration (Step 11): worker-order.itest.ts injects a real R2ArtifactStore against MinIO/R2 dev bucket to round-trip hasSentinel/writeSentinel"
      ],
      "risks": [
        "@aws-sdk/client-s3 adds ~6MB to the worker bundle — fine server-side.",
        "R2 404 error naming varies by endpoint — guarded by checking httpStatusCode AND err.name.",
        "403 must NEVER map to 'not found' or the stage silently re-runs forever on a broken R2 config — covered by an explicit 403-rethrow test.",
        "buildR2ArtifactStore throws at startup on missing env (fail-fast on Railway) — desired."
      ]
    },
    {
      "fork": "Fork 4 — manifest version mirror lie: real cross-language golden + reconcile TS schema to Python v2",
      "decision": "(1) MANIFEST_SCHEMA_VERSION → 2. (2) Add to clipEntrySchema: segment_count: z.number().int().positive().default(1) and caption_band: z.record(z.string(), z.number()).nullable().default(null). REVISED from original z.unknown(): verified caption_band values in Python are numeric ({\"y_top\":900,\"y_bottom\":940,\"confidence\":0.8} — mixed int/float, all numbers), so z.number() (NOT z.number().int()) is the correct, strict-but-accurate value type; this surfaces future non-numeric additions as TS contract failures instead of silent passthrough. (3) ADOPTED (correctness + speed reviews, both flagged): add .passthrough() to BOTH renderManifestSchema (top-level) AND clipEntrySchema (nested) — zod strips unknown nested fields even when the parent passes through, so without nested .passthrough() a future Python ClipEntry field silently breaks the round-trip golden instead of signaling drift. (4) Create manifest-contract.golden.json from the Python byte-shape golden (test_manifest.py:54-88, schema_version:2, one clip, segment_count:1, caption_band:null, path:'clip_00.mp4'). TS contract test loads it, renderManifestSchema.parse(golden) deep-equals golden (round-trip), asserts MANIFEST_SCHEMA_VERSION === golden.schema_version, and clipFileName(0) === golden.clips[0].path. ADOPTED (both reviews): add a pytest that serializes the live Python golden and asserts byte-equality with the checked-in JSON, so the golden cannot drift silently when ClipEntry.to_dict() changes.",
      "rationale": "Verified the existing test is tautological: manifest-schema.test.ts:38-41 asserts MANIFEST_SCHEMA_VERSION===1 against a literal, never touching Python. Python is already at v2 (manifest.py MANIFEST_SCHEMA_VERSION=2) with segment_count + caption_band in to_dict() — three invisible drifts. The golden-JSON approach is lowest-friction: Python's to_dict() golden already exists at test_manifest.py:54. .default() on the new fields keeps old v1 manifests parseable. The nested .passthrough() fix is essential — the original blueprint only passed-through at top level, which the correctness review correctly identified would still silently drop future ClipEntry fields. The Python-side byte-equality pytest (adopted over a prose 'keep in sync' comment) turns drift into a failing CI test rather than a human reminder — directly satisfies the founder's CI-gate-against-drift intent.",
      "filesToChange": [
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/packages/shared/src/manifest/manifest-schema.ts",
          "change": "MANIFEST_SCHEMA_VERSION=2. clipEntrySchema: add segment_count: z.number().int().positive().default(1), caption_band: z.record(z.string(), z.number()).nullable().default(null); add .passthrough(). renderManifestSchema: add .passthrough(). Replace the file-top comment's contract claim with an accurate description of the golden round-trip test."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/packages/shared/src/manifest/manifest-contract.golden.json",
          "change": "CREATE. Exact copy of test_manifest.py:54-88 to_dict() output (schema_version:2; one clip with segment_count:1, caption_band:null, path:'clip_00.mp4', all 17 fields). Header note: 'Generated from Python RenderManifest.to_dict(); kept in lock-step by tests/clipping/test_golden_matches_shared.py — do not hand-edit.'"
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/packages/shared/src/manifest/manifest-schema.test.ts",
          "change": "Replace the tautological version test (lines 38-41) with: load golden; assert renderManifestSchema.parse(golden) deep-equals golden (round-trip catches dropped fields); assert MANIFEST_SCHEMA_VERSION === golden.schema_version; assert clipFileName(0) === golden.clips[0].path. Update validClip to include segment_count:1, caption_band:null. validManifest.schema_version already binds to MANIFEST_SCHEMA_VERSION (now 2). Add a test that a v1-shaped manifest (no segment_count/caption_band) still parses via defaults."
        },
        {
          "path": "/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/tests/clipping/test_golden_matches_shared.py",
          "change": "CREATE. Build the same RenderManifest as test_manifest.py, json.dumps(to_dict()), load packages/shared/src/manifest/manifest-contract.golden.json, assert the two parse to equal dicts. Fails CI if a dev changes to_dict() without regenerating the shared golden."
        }
      ],
      "testPlan": [
        "RED: manifest-schema.test.ts asserts MANIFEST_SCHEMA_VERSION===golden.schema_version; fails (1 vs 2) — note: do Steps 2+3 as ONE commit (ADOPTED from speed review) so the suite goes red→green atomically and the bisect boundary is clean",
        "GREEN: bump to 2",
        "RED: round-trip deep-equal fails (zod strips segment_count/caption_band)",
        "GREEN: add the two fields + .passthrough() on both schemas",
        "RED: clipFileName(0)===golden.clips[0].path fails until Fork 2 padding lands",
        "GREEN: Fork 2 padding makes it pass",
        "Verify a v1 manifest (no new fields) still parses via .default()",
        "Python: test_golden_matches_shared.py asserts live to_dict() byte-equals the checked-in golden — green",
        "NOTE: segment_count/caption_band are manifest-only — NOT persisted to the clips table (see decision below); publishUpload's rows.map does NOT read them, so no schema.ts/migration change and no ClipInput type error"
      ],
      "risks": [
        "DB-PERSISTENCE SCOPE (correctness review raised as 'critical' — RESOLVED by explicit non-persistence): I reject adding segment_count/caption_band columns to the clips table for P2. ClipInput = Omit<clips.$inferInsert,...> (ledger-repo.ts:66), so a field reaches the DB ONLY if publishUpload's rows.map writes it. The current rows.map (publish.ts:30-47) does NOT write them and will NOT after this fork — therefore NO TS type error and NO migration is needed. They remain manifest-only fields. Documented here so no one claims the dashboard reads them from clip rows. Adding columns is a deliberate future decision, not a P2 blocker.",
        "nested+top .passthrough() means unknown Python fields reach publishUpload's manifest object; rows.map reads only named fields, so extras are harmlessly ignored.",
        "If apps/web hard-asserts MANIFEST_SCHEMA_VERSION===1 anywhere, bumping to 2 breaks it — grep before deploy (none found in worker-node/shared/db).",
        "The shared golden must track to_dict(); enforced by the new pytest (drift = red CI), not prose."
      ]
    }
  ],
  "artifactStoreDesign": {
    "interface": "export interface ArtifactStore { hasSentinel(outputPrefix: string): Promise<boolean>; writeSentinel(outputPrefix: string, marker: Record<string, unknown>): Promise<void>; } — already defined in apps/worker-node/src/stages/handler-contract.ts (verified). Concrete class R2ArtifactStore lives at apps/worker-node/src/r2/artifact-store.ts and implements it. Constructor: constructor({ bucket, s3Client }: { bucket: string; s3Client: S3Client }). Pure helpers buildS3Config / isNotFound / isPreconditionFailed and constants SENTINEL_SCHEMA_VERSION / SENTINEL_MAX_BYTES are exported named members, directly importable by tests without instantiating the class.",
    "r2Operations": "hasSentinel(outputPrefix): send HeadObjectCommand({ Bucket: this.bucket, Key: `${outputPrefix}/_COMPLETE.json` }). success → true. catch → if (isNotFound(err)) return false; throw err (403/5xx/network become BullMQ retries, NEVER false). writeSentinel(outputPrefix, marker): const body = JSON.stringify({ ...marker, completedAt: new Date().toISOString(), schemaVersion: SENTINEL_SCHEMA_VERSION }); if (Buffer.byteLength(body,'utf8') > SENTINEL_MAX_BYTES) throw new Error('sentinel body exceeds SENTINEL_MAX_BYTES'); send PutObjectCommand({ Bucket: this.bucket, Key: `${outputPrefix}/_COMPLETE.json`, Body: body, ContentType: 'application/json', IfNoneMatch: '*' }). catch → if (isPreconditionFailed(err)) return; if (err?.$metadata?.httpStatusCode === 409) return; throw err. buildS3Config(env): { region:'auto', endpoint:`https://${env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`, credentials:{ accessKeyId: env.R2_ACCESS_KEY_ID, secretAccessKey: env.R2_SECRET_ACCESS_KEY }, requestChecksumCalculation:'WHEN_REQUIRED', responseChecksumValidation:'WHEN_REQUIRED' }. isNotFound(err): err?.$metadata?.httpStatusCode === 404 || err?.name === 'NotFound'. isPreconditionFailed(err): err?.$metadata?.httpStatusCode === 412 || err?.name === 'PreconditionFailed'.",
    "crashSafety": "Sentinel is written LAST, after runStage() returns ok — ordering enforced by execute-stage.ts:20-24 (verified) and must not change. Crash after artifacts but before sentinel → next BullMQ attempt re-downloads, re-computes, re-uploads (S3 PUT is last-writer-wins idempotent; ffmpeg non-determinism only changes bytes, not validity, and no sha256 is stored), then writes the sentinel. Crash after sentinel → next attempt hasSentinel()→true → short-circuit with cached result (execute-stage.ts:17-19). Two concurrent workers on the same job: first PUT wins (200), second gets 412 (PreconditionFailed)→no-op; a delete+rewrite race surfaces as 409→also no-op. R2 gives read-after-write consistency on a single object, so the winner's sentinel is visible to all subsequent HEADs immediately. hasSentinel HEADs ONLY '_COMPLETE.json', never a data artifact (a bare data HEAD could be a truncated partial). Sentinel body records completedAt + stage + contentHash (from marker) for operator audit without scanning data objects.",
    "reliabilityNotes": "S3Client constructed ONCE in build-r2-client.ts and shared across all calls in the worker process (SDK pools connections internally) — never per-call. requestChecksumCalculation:'WHEN_REQUIRED' + responseChecksumValidation:'WHEN_REQUIRED' is MANDATORY: aws-sdk-js v3 recent default WHEN_SUPPORTED emits a CRC32 streaming trailer that R2 rejects with SignatureDoesNotMatch — identical to the boto3-1.36 bug already fixed in stages/r2.py. HEAD is a cheap R2 Class B op (no egress). SENTINEL_MAX_BYTES (1024) is a test-enforced invariant guaranteeing the body stays single-part so the IfNoneMatch conditional-write atomicity (which does NOT hold for multipart) is always valid; a future dev adding sentinel fields hits a failing test, not a silent atomicity regression. On HeadObject, v3 throws rather than returning null for a missing object and the error shape varies by endpoint, so check httpStatusCode===404 as primary and err.name==='NotFound' as secondary. A 403 means an R2 permissions misconfig and MUST rethrow — mapping it to 'not found' would make the stage silently re-run forever on a broken config (covered by an explicit 403-rethrow unit test)."
  },
  "buildOrder": [
    "Step 1 — Fork 2 padding (shared, zero deps). RED: in manifest-schema.test.ts change clipFileName(0) to expect 'clip_00.mp4' and clipFileName(12)→'clip_12.mp4'; deriveClipKey→'/clip_03.mp4'; validClip.path→'clip_00.mp4'. Run vitest (shared): RED on clipFileName. IMPL: padStart(3)→padStart(2) in manifest-schema.ts. GREEN on padding (version test still red — fixed Step 2).",
    "Step 2 — Fork 2 path hardening (shared). RED: add manifest-schema.test.ts case asserting safeParse({...validManifest, clips:[{...validClip, path:'../evil.mp4'}]}).success===false. Run vitest: RED. IMPL: change clipEntrySchema.path to z.string().regex(/^clip_\\d{2}\\.mp4$/). GREEN.",
    "Step 3 — Fork 4 schema + golden + Python guard, as ONE atomic commit (avoids a double-red bisect boundary). RED: (a) create manifest-contract.golden.json from test_manifest.py:54-88 (v2, segment_count:1, caption_band:null, path:'clip_00.mp4'); (b) replace the tautological version test with golden round-trip + MANIFEST_SCHEMA_VERSION===golden.schema_version + clipFileName(0)===golden.clips[0].path; add validClip segment_count/caption_band; add a v1-manifest-still-parses test. Run vitest: RED (version 1≠2; fields stripped). IMPL: MANIFEST_SCHEMA_VERSION=2; add segment_count + caption_band(z.record(z.string(),z.number())) with defaults; add .passthrough() to clipEntrySchema AND renderManifestSchema; fix the file-top comment. Run vitest (shared): GREEN, shared coverage 100%. Then create services/ai-worker-python/tests/clipping/test_golden_matches_shared.py asserting live to_dict() byte-equals the checked-in golden; run pytest: GREEN.",
    "Step 4 — Fork 3 pure helpers (worker-node). RED: create artifact-store.test.ts testing buildS3Config (endpoint + both WHEN_REQUIRED knobs), isNotFound (404/NotFound true; 403/500 false), isPreconditionFailed (412/PreconditionFailed true; 200 false). Run vitest (worker-node): RED (file absent). IMPL: create artifact-store.ts with SENTINEL_SCHEMA_VERSION, SENTINEL_MAX_BYTES, and the three pure helpers. GREEN, 100% on helpers.",
    "Step 5 — Fork 3 class (worker-node). RED: extend artifact-store.test.ts — hasSentinel via vi.fn() send (resolves→true; 404→false; 403→rethrow); writeSentinel (resolves→ok; 412→ok; 409→ok; 500→rethrow; >1024-byte marker→throws size invariant). Run vitest: RED (class absent). IMPL: add R2ArtifactStore with injected s3Client.send, the two send() calls inside /* v8 ignore */. GREEN, 100% branch (send calls excluded).",
    "Step 6 — Fork 3 env factory + dep (worker-node). Add '@aws-sdk/client-s3' to apps/worker-node/package.json; install. Create build-r2-client.ts (buildR2ArtifactStore(env), single shared S3Client, fail-fast on missing env). No unit test (thin glue; covered by Step 11 integration). Run tsc: GREEN.",
    "Step 7 — Fork 1 Stage-union removal + all Stage-keyed maps (compile-driven). RED: build-flow-tree.test.ts — assert chain length 7, remove 'store' from the failParentOnFailure list (line 59) and queue map (line 74), add assertion publish data.reframePrefix===`intermediate/${ARGS.contentHash}/reframe`. Run vitest: RED. IMPL (one commit): remove 'store' from stage.ts STAGES; remove 'store' from queue-config.ts STAGE_RETRY+STAGE_TIMEOUT_MS; remove 'store' from flow-progress.ts STAGE_WEIGHT; remove 'store' from build-flow-tree.ts CHAIN and inject reframePrefix for the publish node; remove 'store' from registry.ts PYTHON_STAGES. Run tsc + vitest (worker-node): GREEN (verify flow-progress.test.ts still reaches 100, registry.test.ts isPythonStage('store')===false).",
    "Step 8 — Fork 1 publish rewire (worker-node). RED: publish.test.ts — args→{contentHash, reframePrefix:`intermediate/${HASH}/reframe`}; fixtures path 'clip_00.mp4'/'clip_01.mp4', schema_version:2, segment_count:1, caption_band:null; assert clipUrl===`intermediate/${HASH}/reframe/clip_00.mp4`; assert finishUpload resultUrl===manifestUrl===`intermediate/${HASH}/reframe/manifest.json`; add assertion the resolved key has NO 'clips/' prefix (deriveClipKey not used). Run vitest: RED. IMPL: PublishArgs→{contentHash, reframePrefix}; derive manifestKey; add local resolveClipKey; drop deriveClipKey import; finishUpload resultUrl=manifestKey. GREEN.",
    "Step 9 — Fork 2 cleanup (db). Update the stale 'clips/x/clip_000.mp4' fixture literal in packages/db/src/ledger-repo.test.ts to a 2-digit form. Run vitest (db): GREEN.",
    "Step 10 — Fork 1 integration order (worker-node, real Redis). RED: update worker-order.itest.ts expected order (lines 59-67) to the 7-stage list dropping 'store'. Run itest: GREEN.",
    "Step 11 — E2E wire (worker-node). Create apps/worker-node/src/worker/stage-processor.ts: the BullMQ Processor that, for a Python stage, assembles StageContext { stage, contentHash, ownerId, request, r2: buildR2ArtifactStore(process.env), runStage: runPythonStage } and calls executeStage; for 'publish' calls publishUpload with PublishDeps wired to readJson/upsertClips/finishUpload. Add an itest extending worker-order.itest.ts that injects a real R2ArtifactStore against a MinIO/R2 dev bucket and round-trips hasSentinel/writeSentinel. This is the concrete landing spot for the ArtifactStore injection. Run itest: GREEN.",
    "Step 12 — Two-phase deploy + Python store removal (PHASE 2). Deploy Steps 1-11 (Node CHAIN already store-less; Python store_handler STILL registered). Drain the cpu/store BullMQ queue to zero (observe). THEN remove the 'store' lambda + store_handler import from services/ai-worker-python/fliphouse_worker/stages/_registry.py and redeploy Python. Run pytest (test_store.py still green — it calls store_handler directly, not via registry).",
    "Step 13 — Docs. Update the manifest-schema.ts file-top comment to describe the golden round-trip contract accurately (remove the false claim). Confirm the golden JSON header note points at test_golden_matches_shared.py as the drift gate."
  ],
  "openQuestions": [
    "P2 deliberately does NOT persist segment_count/caption_band to the clips table (manifest-only). Confirm this is acceptable for the dashboard DoD, or schedule a follow-up migration (jsonb caption_band, int segment_count) + rows.map + ClipInput update if the dashboard must display reframe-segment detail.",
    "Step 11 integration test needs a real S3-compatible target (MinIO container or an R2 dev bucket with throwaway creds). Confirm which is available in CI; if neither, the hasSentinel/writeSentinel round-trip stays a gated live test (like the existing P2-2.5 live R2 harness) rather than a default-CI itest."
  ]
}