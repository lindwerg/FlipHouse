import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';

/**
 * Stream the SHA-256 of a local file as a 64-char lowercase hex digest — the SAME
 * content identity the browser computes for a File upload (sha256Hex over the
 * bytes), so a video ingested by URL and the same bytes uploaded as a file
 * collapse onto ONE `upload_ledger` row (content-addressed dedup). Streamed (not
 * read-into-memory) so a multi-GB source never buffers fully.
 */
export function hashFile(localPath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256');
    const stream = createReadStream(localPath);
    stream.on('error', reject);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}
