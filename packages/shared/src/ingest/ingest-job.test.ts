import { expect, test } from 'vitest';

import { INGEST_QUEUE_NAME, ingestJobDataSchema, isIngestableUrl } from './ingest-job.js';

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
