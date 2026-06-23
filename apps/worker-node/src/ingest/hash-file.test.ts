import { createHash } from 'node:crypto';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, expect, test } from 'vitest';

import { hashFile } from './hash-file.js';

const created: string[] = [];

function tempFile(content: Buffer): string {
  const dir = mkdtempSync(join(tmpdir(), 'fh-hash-test-'));
  const path = join(dir, 'video.mp4');
  writeFileSync(path, content);
  created.push(path);
  return path;
}

afterEach(() => {
  created.length = 0;
});

test('hashFile streams the sha256 hex of the file bytes', async () => {
  const bytes = Buffer.from('the quick brown fox', 'utf8');
  const path = tempFile(bytes);
  const expected = createHash('sha256').update(bytes).digest('hex');

  await expect(hashFile(path)).resolves.toBe(expected);
});

test('hashFile hashes an empty file to the empty-input digest', async () => {
  const path = tempFile(Buffer.alloc(0));
  const expected = createHash('sha256').update(Buffer.alloc(0)).digest('hex');
  await expect(hashFile(path)).resolves.toBe(expected);
});

test('hashFile rejects when the path does not exist', async () => {
  await expect(hashFile('/nonexistent/path/video.mp4')).rejects.toBeInstanceOf(Error);
});
