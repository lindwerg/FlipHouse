/**
 * The single upload's flow-enqueue args, kept local to the ingest module to avoid
 * coupling it to the FlowProducer's full signature (mirrors the hook-receiver's
 * EnqueueArgs). `source` is the R2 key of the ingested source video.
 */
export interface EnqueueArgs {
  readonly contentHash: string;
  readonly ownerId: string;
  readonly source: string;
}
