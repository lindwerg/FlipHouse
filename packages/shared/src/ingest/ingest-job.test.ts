import { expect, test } from 'vitest';

import {
  INGEST_QUEUE_NAME,
  ingestFailureKey,
  ingestJobDataSchema,
  isIngestableUrl,
} from './ingest-job.js';

test('INGEST_QUEUE_NAME is the dedicated ingest lane', () => {
  expect(INGEST_QUEUE_NAME).toBe('ingest');
});

test('isIngestableUrl accepts known video hosts', () => {
  expect(isIngestableUrl('https://www.youtube.com/watch?v=abc')).toBe(true);
  expect(isIngestableUrl('https://youtu.be/abc')).toBe(true);
  expect(isIngestableUrl('https://vimeo.com/123')).toBe(true);
  expect(isIngestableUrl('https://www.dailymotion.com/video/x')).toBe(true);
  expect(isIngestableUrl('https://www.twitch.tv/videos/1')).toBe(true);
});

test('isIngestableUrl accepts direct video files', () => {
  expect(isIngestableUrl('https://cdn.example.com/clip.mp4')).toBe(true);
  expect(isIngestableUrl('https://cdn.example.com/clip.MOV')).toBe(true);
  expect(isIngestableUrl('http://example.com/a/b/c.webm')).toBe(true);
  expect(isIngestableUrl('https://example.com/x.m4v')).toBe(true);
});

test('isIngestableUrl rejects non-video, non-http, and malformed inputs', () => {
  expect(isIngestableUrl('https://example.com/page.html')).toBe(false);
  expect(isIngestableUrl('ftp://example.com/clip.mp4')).toBe(false);
  expect(isIngestableUrl('not a url')).toBe(false);
  expect(isIngestableUrl('')).toBe(false);
});

test('isIngestableUrl rejects SSRF targets even when the path ends in a video ext', () => {
  // The exact cloud-metadata / private-network primitives from the security review.
  expect(isIngestableUrl('http://169.254.169.254/latest/meta-data/x.mp4')).toBe(false);
  expect(isIngestableUrl('http://metadata.google.internal/computeMetadata/v1/x.mp4')).toBe(false);
  expect(isIngestableUrl('http://10.0.0.5/internal.webm')).toBe(false);
  expect(isIngestableUrl('http://localhost:9000/secret.mp4')).toBe(false);
  expect(isIngestableUrl('http://[::1]/x.mov')).toBe(false);
  expect(isIngestableUrl('http://192.168.1.1/x.mp4')).toBe(false);
  expect(isIngestableUrl('http://172.16.5.5/x.mp4')).toBe(false);
});

test('ingestFailureKey is a stable `ingest:<64-hex>` derived from the url', () => {
  const key = ingestFailureKey('https://youtu.be/abc');
  expect(key).toMatch(/^ingest:[0-9a-f]{64}$/);
  // Deterministic: the same url always derives the same key (producer/consumer agree).
  expect(ingestFailureKey('https://youtu.be/abc')).toBe(key);
  // Distinct urls derive distinct keys.
  expect(ingestFailureKey('https://youtu.be/def')).not.toBe(key);
});

test('ingestJobDataSchema accepts a valid url + ownerId', () => {
  const parsed = ingestJobDataSchema.parse({
    url: 'https://youtu.be/abc',
    ownerId: 'user_1',
  });
  expect(parsed).toEqual({ url: 'https://youtu.be/abc', ownerId: 'user_1' });
});

test('ingestJobDataSchema rejects a non-ingestable url', () => {
  const result = ingestJobDataSchema.safeParse({
    url: 'https://example.com/page.html',
    ownerId: 'user_1',
  });
  expect(result.success).toBe(false);
});

test('ingestJobDataSchema rejects an empty ownerId', () => {
  const result = ingestJobDataSchema.safeParse({ url: 'https://youtu.be/abc', ownerId: '' });
  expect(result.success).toBe(false);
});
