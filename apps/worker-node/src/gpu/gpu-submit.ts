/**
 * GigaAM-v3 GPU submit seam (P2 step #1, TRACK C). Fires the SUBMIT half of the
 * submit-and-park contract: `POST ${endpoint}/transcribe` with the presigned
 * audio URL + the webhook callback URL the GPU posts its result to. The GPU
 * replies synchronously with `{ request_id, status: "accepted" }`; the real
 * transcription lands later via the webhook (TRACK B).
 *
 * The single network seam is an injected `fetch`-like function, so the whole
 * module is unit-tested with a mock and needs no coverage-ignore. Any non-2xx,
 * non-JSON, or schema-violating response becomes a named {@link GpuSubmitError}.
 */
import { z } from 'zod';

/** Fixed transcription language for the FlipHouse ASR lane. */
const ASR_LANGUAGE = 'ru';

/** Named error for every GPU-submit failure (transport, status, or contract). */
export class GpuSubmitError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GpuSubmitError';
  }
}

/** Inputs needed to assemble + send one submit request. */
export interface GpuSubmitArgs {
  readonly endpoint: string;
  readonly requestId: string;
  readonly audioUrl: string;
  readonly webhookUrl: string;
  readonly outputPrefix: string;
}

/** The submit body matching the shared SUBMIT contract exactly. */
export interface GpuSubmitBody {
  readonly request_id: string;
  readonly audio_url: string;
  readonly language: typeof ASR_LANGUAGE;
  readonly webhook_url: string;
  readonly output_prefix: string;
}

/** The minimal `fetch` surface this seam needs (injectable). */
export type FetchFn = (url: string, init: RequestInit) => Promise<Response>;

/** The sync response the GPU returns: a request id and an `accepted` ack. */
export const submitResponseSchema = z.object({
  request_id: z.string().min(1),
  status: z.literal('accepted'),
});

/** Build the SUBMIT body from validated args (pure — no I/O). */
export function buildSubmitBody(args: GpuSubmitArgs): GpuSubmitBody {
  return {
    request_id: args.requestId,
    audio_url: args.audioUrl,
    language: ASR_LANGUAGE,
    webhook_url: args.webhookUrl,
    output_prefix: args.outputPrefix,
  };
}

export interface GpuSubmitDeps {
  readonly fetchFn: FetchFn;
}

/** Strip a single trailing slash so `${endpoint}/transcribe` is never doubled. */
function transcribeUrl(endpoint: string): string {
  return `${endpoint.replace(/\/$/, '')}/transcribe`;
}

/**
 * Submit one transcription request to the GPU and return the accepted
 * `request_id`. Throws {@link GpuSubmitError} on any transport failure, non-2xx
 * status, unparseable body, or schema mismatch — the caller treats a submit
 * failure as a retryable stage error (BullMQ re-runs the asr lane).
 */
export async function gpuSubmit(args: GpuSubmitArgs, deps: GpuSubmitDeps): Promise<string> {
  const url = transcribeUrl(args.endpoint);
  let res: Response;
  try {
    res = await deps.fetchFn(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(buildSubmitBody(args)),
    });
  } catch (err: unknown) {
    const reason = err instanceof Error ? err.message : String(err);
    throw new GpuSubmitError(`gpu submit transport failure: ${reason}`);
  }

  if (!res.ok) {
    throw new GpuSubmitError(`gpu submit returned non-2xx status ${res.status}`);
  }

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new GpuSubmitError('gpu submit response body is not valid JSON');
  }

  const parsed = submitResponseSchema.safeParse(body);
  if (!parsed.success) {
    throw new GpuSubmitError('gpu submit response failed schema validation');
  }
  return parsed.data.request_id;
}
