export { clips, costRecords, flowFailures, uploadLedger, uploadStatusEnum, usageRecords } from './schema.js';
export { createDb } from './client.js';
export type { Db } from './client.js';
export { PAYG_PER_MINUTE_MICROS, microsToNumericString, ratePaygMicros } from './rating.js';
export { BillingError, assertAffordable, resolveMinuteCap } from './billing-gate.js';
export type { BillingBlockReason, BillingGateEnv } from './billing-gate.js';
export {
  claimUpload,
  debitOnce,
  debitPayg,
  findIngestFailure,
  findStuckFlows,
  findStuckStatusUploads,
  finishUpload,
  incrementMinutesUsed,
  isPaygPlan,
  listClipsForOwner,
  listUploadsForOwner,
  loadUpload,
  OWNER_UPLOADS_DEFAULT_LIMIT,
  recordCogs,
  recordFailure,
  reconcileRows,
  reconcileStuckStatuses,
  setFlowJobId,
  setSourceDuration,
  setStatus,
  upsertClips,
} from './ledger-repo.js';
export type {
  BillingPlan,
  ClaimInput,
  ClaimResult,
  ClipDashboardRow,
  ClipInput,
  CogsInput,
  DebitInput,
  DebitPaygInput,
  FinishInput,
  IngestFailureRow,
  ListUploadsForOwnerOptions,
  OwnerClips,
  OwnerUpload,
  OwnerUploadsCursor,
  StuckStatusReconcileResult,
  UploadCharge,
  UploadRow,
  UploadStatus,
} from './ledger-repo.js';
