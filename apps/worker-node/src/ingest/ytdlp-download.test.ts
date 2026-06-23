import { expect, test, vi } from 'vitest';

import {
  classifyYtdlpError,
  DOWNLOAD_TIMEOUT_MS,
  downloadVideo,
  IngestDownloadError,
  ingestErrorFromStderr,
  ytdlpArgs,
} from './ytdlp-download.js';

// A lookup seam resolving every host to a public IP, so the SSRF pre-flight in
// downloadVideo never makes a real DNS call in these unit tests.
const publicLookup = vi.fn().mockResolvedValue([{ address: '93.184.216.34' }]);

test('ytdlpArgs builds a robust best-mp4 download command for the url + outPath', () => {
  const args = ytdlpArgs('https://youtu.be/abc', '/tmp/out.mp4');
  expect(args).toContain('https://youtu.be/abc');
  expect(args).toContain('/tmp/out.mp4');
  // Format fallback chain + mp4 merge.
  expect(args).toContain('best[ext=mp4][height<=1080]/best[ext=mp4]/best');
  expect(args).toContain('--merge-output-format');
  expect(args).toContain('mp4');
  // Robustness knobs.
  expect(args).toContain('--retries');
  expect(args).toContain('--fragment-retries');
  expect(args).toContain('--no-playlist');
  // SSRF/DoS size ceiling.
  expect(args).toContain('--max-filesize');
});

test('DOWNLOAD_TIMEOUT_MS stays below the 30-min worker lock', () => {
  expect(DOWNLOAD_TIMEOUT_MS).toBeLessThan(30 * 60 * 1000);
});

test('classifyYtdlpError maps YouTube datacenter-IP wall to ip-blocked', () => {
  expect(classifyYtdlpError('ERROR: Sign in to confirm you are not a bot')).toBe('ip-blocked');
  expect(classifyYtdlpError('HTTP Error 429: Too Many Requests')).toBe('ip-blocked');
  expect(classifyYtdlpError('Failed to extract any player response')).toBe('ip-blocked');
});

test('classifyYtdlpError maps age / private / geo / unavailable distinctly', () => {
  expect(classifyYtdlpError('This video may be inappropriate; age restricted')).toBe('age-restricted');
  expect(classifyYtdlpError('Private video. Sign in if you have been granted access')).toBe('private');
  expect(classifyYtdlpError('This video is not available in your country')).toBe('geo-restricted');
  expect(classifyYtdlpError('ERROR: Video unavailable')).toBe('unavailable');
  expect(classifyYtdlpError('HTTP Error 404: Not Found')).toBe('unavailable');
  expect(classifyYtdlpError('Unsupported URL: https://example.com/page')).toBe('unavailable');
});

test('classifyYtdlpError maps transient transport failures to network', () => {
  expect(classifyYtdlpError('Unable to download webpage: connection reset')).toBe('network');
  expect(classifyYtdlpError('Read operation timed out')).toBe('network');
  expect(classifyYtdlpError('Temporary failure in name resolution')).toBe('network');
});

test('classifyYtdlpError falls back to unknown for an unrecognized blob', () => {
  expect(classifyYtdlpError('some weird internal panic')).toBe('unknown');
});

test('ingestErrorFromStderr carries a kind + a Russian user message + clipped detail', () => {
  const err = ingestErrorFromStderr('ERROR: Private video');
  expect(err).toBeInstanceOf(IngestDownloadError);
  expect(err.kind).toBe('private');
  expect(err.userMessage).toMatch(/приватн/i);
  expect(err.message).toContain('private');
});

test('ingestErrorFromStderr handles an empty stderr without throwing', () => {
  const err = ingestErrorFromStderr('');
  expect(err.kind).toBe('unknown');
  expect(err.message).toContain('no stderr');
});

test('downloadVideo resolves when the injected execFile succeeds', async () => {
  const execFile = vi.fn().mockResolvedValue({ stdout: '', stderr: '' });
  await expect(
    downloadVideo('https://youtu.be/abc', '/tmp/out.mp4', {
      execFile,
      bin: 'yt-dlp',
      timeoutMs: 1000,
      lookup: publicLookup,
    }),
  ).resolves.toBeUndefined();
  expect(execFile).toHaveBeenCalledWith('yt-dlp', ytdlpArgs('https://youtu.be/abc', '/tmp/out.mp4'), {
    timeout: 1000,
    maxBuffer: expect.any(Number),
  });
});

test('downloadVideo throws a classified IngestDownloadError from execFile stderr', async () => {
  const err = Object.assign(new Error('exit 1'), { stderr: 'ERROR: Sign in to confirm you are not a bot' });
  const execFile = vi.fn().mockRejectedValue(err);
  await expect(
    downloadVideo('https://youtu.be/abc', '/tmp/out.mp4', { execFile, lookup: publicLookup }),
  ).rejects.toMatchObject({ kind: 'ip-blocked' });
});

test('downloadVideo falls back to the error message when no stderr is attached', async () => {
  const execFile = vi.fn().mockRejectedValue(new Error('Read operation timed out'));
  await expect(
    downloadVideo('https://youtu.be/abc', '/tmp/out.mp4', { execFile, lookup: publicLookup }),
  ).rejects.toMatchObject({ kind: 'network' });
});

test('downloadVideo stringifies a non-Error rejection', async () => {
  const execFile = vi.fn().mockRejectedValue('plain string boom');
  await expect(
    downloadVideo('https://youtu.be/abc', '/tmp/out.mp4', { execFile, lookup: publicLookup }),
  ).rejects.toBeInstanceOf(IngestDownloadError);
});

test('downloadVideo rejects a private/metadata host BEFORE spawning yt-dlp', async () => {
  const execFile = vi.fn();
  await expect(
    downloadVideo('http://169.254.169.254/x.mp4', '/tmp/out.mp4', { execFile, lookup: publicLookup }),
  ).rejects.toMatchObject({ kind: 'private' });
  // The SSRF guard short-circuits — yt-dlp never runs against an internal target.
  expect(execFile).not.toHaveBeenCalled();
});

test('downloadVideo falls back to the default execFile when none is injected', async () => {
  // `true` (the POSIX no-op binary) exits 0 instantly with no network, exercising
  // the `?? defaultExecFile` fallback branch without invoking real yt-dlp.
  await expect(
    downloadVideo('https://youtu.be/abc', '/tmp/out.mp4', {
      bin: 'true',
      timeoutMs: 5000,
      lookup: publicLookup,
    }),
  ).resolves.toBeUndefined();
});
