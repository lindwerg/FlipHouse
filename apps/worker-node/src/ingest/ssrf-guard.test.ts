import { expect, test, vi } from 'vitest';

import { assertPublicUrl } from './ssrf-guard.js';
import { IngestDownloadError } from './ytdlp-download.js';

/** A lookup that should never be reached (the literal-host gate fires first). */
const unreachableLookup = vi.fn();

test('assertPublicUrl rejects a blocked literal host before any DNS lookup', async () => {
  await expect(
    assertPublicUrl('http://169.254.169.254/x.mp4', unreachableLookup),
  ).rejects.toMatchObject({ kind: 'private' });
  expect(unreachableLookup).not.toHaveBeenCalled();
});

test('assertPublicUrl unbrackets and rejects an IPv6-literal loopback host', async () => {
  // `new URL('http://[::1]/').hostname` is `[::1]`; the guard strips the brackets
  // before classifying, so the loopback is caught at the literal-host gate.
  await expect(assertPublicUrl('http://[::1]/x.mp4', unreachableLookup)).rejects.toMatchObject({
    kind: 'private',
  });
  expect(unreachableLookup).not.toHaveBeenCalled();
});

test('assertPublicUrl rejects when a public-looking host resolves to a private IP', async () => {
  // DNS-rebinding: the name is public, but it resolves to a private address.
  const lookup = vi.fn().mockResolvedValue([{ address: '10.0.0.5' }]);
  await expect(assertPublicUrl('https://evil.example.com/x.mp4', lookup)).rejects.toMatchObject({
    kind: 'private',
  });
});

test('assertPublicUrl rejects when ANY resolved address is private (mixed result)', async () => {
  const lookup = vi
    .fn()
    .mockResolvedValue([{ address: '93.184.216.34' }, { address: '169.254.169.254' }]);
  await expect(assertPublicUrl('https://mixed.example.com/x.mp4', lookup)).rejects.toBeInstanceOf(
    IngestDownloadError,
  );
});

test('assertPublicUrl resolves when every resolved address is public', async () => {
  const lookup = vi.fn().mockResolvedValue([{ address: '93.184.216.34' }]);
  await expect(assertPublicUrl('https://cdn.example.com/x.mp4', lookup)).resolves.toBeUndefined();
  expect(lookup).toHaveBeenCalledWith('cdn.example.com');
});

test('assertPublicUrl tolerates a DNS-resolution failure (not proof of private)', async () => {
  const lookup = vi.fn().mockRejectedValue(new Error('ENOTFOUND'));
  // A DNS error is not a positive private match — yt-dlp will surface a real error.
  await expect(assertPublicUrl('https://cdn.example.com/x.mp4', lookup)).resolves.toBeUndefined();
});

test('assertPublicUrl throws on an unparseable url', async () => {
  await expect(assertPublicUrl('not a url', unreachableLookup)).rejects.toMatchObject({
    kind: 'unknown',
  });
});
