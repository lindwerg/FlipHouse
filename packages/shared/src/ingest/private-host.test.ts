import { describe, expect, test } from 'vitest';

import { isBlockedHost } from './private-host.js';

describe('isBlockedHost — blocked hostnames', () => {
  test('blocks localhost and the GCP metadata name (case-insensitive)', () => {
    expect(isBlockedHost('localhost')).toBe(true);
    expect(isBlockedHost('LOCALHOST')).toBe(true);
    expect(isBlockedHost('metadata.google.internal')).toBe(true);
  });

  test('blocks internal/link-local hostname suffixes', () => {
    expect(isBlockedHost('db.internal')).toBe(true);
    expect(isBlockedHost('printer.local')).toBe(true);
    expect(isBlockedHost('app.localhost')).toBe(true);
    expect(isBlockedHost('host.localdomain')).toBe(true);
  });
});

describe('isBlockedHost — blocked IPv4', () => {
  test('blocks loopback, RFC1918, link-local/metadata, CGNAT, and 0/8', () => {
    expect(isBlockedHost('127.0.0.1')).toBe(true);
    expect(isBlockedHost('10.0.0.5')).toBe(true);
    expect(isBlockedHost('172.16.0.1')).toBe(true);
    expect(isBlockedHost('172.31.255.255')).toBe(true);
    expect(isBlockedHost('192.168.1.1')).toBe(true);
    expect(isBlockedHost('169.254.169.254')).toBe(true); // cloud IMDS
    expect(isBlockedHost('100.64.0.1')).toBe(true); // CGNAT
    expect(isBlockedHost('0.0.0.0')).toBe(true);
    expect(isBlockedHost('224.0.0.1')).toBe(true); // multicast
    expect(isBlockedHost('255.255.255.255')).toBe(true); // broadcast
  });

  test('allows public IPv4 just outside the blocked ranges', () => {
    expect(isBlockedHost('1.2.3.4')).toBe(false);
    expect(isBlockedHost('8.8.8.8')).toBe(false);
    expect(isBlockedHost('172.15.0.1')).toBe(false); // just below 172.16
    expect(isBlockedHost('172.32.0.1')).toBe(false); // just above 172.31
    expect(isBlockedHost('100.63.0.1')).toBe(false); // just below CGNAT
    expect(isBlockedHost('100.128.0.1')).toBe(false); // just above CGNAT
    expect(isBlockedHost('192.167.1.1')).toBe(false);
  });

  test('does not treat an out-of-range-octet string as IPv4', () => {
    // 256 is not a valid octet → not parsed as IPv4, falls through to hostname rules.
    expect(isBlockedHost('256.1.1.1')).toBe(false);
  });
});

describe('isBlockedHost — blocked IPv6', () => {
  test('blocks loopback, unspecified, link-local, and unique-local', () => {
    expect(isBlockedHost('::1')).toBe(true);
    expect(isBlockedHost('[::1]')).toBe(true);
    expect(isBlockedHost('::')).toBe(true);
    expect(isBlockedHost('fe80::1')).toBe(true);
    expect(isBlockedHost('fec0::1')).toBe(false); // not link-local prefix fe8/fe9/fea/feb — site-local deprecated, allowed
    expect(isBlockedHost('fc00::1')).toBe(true);
    expect(isBlockedHost('fd12:3456::1')).toBe(true);
  });

  test('blocks IPv4-mapped/compat IPv6 whose embedded IPv4 is private', () => {
    expect(isBlockedHost('::ffff:169.254.169.254')).toBe(true);
    expect(isBlockedHost('::ffff:10.0.0.5')).toBe(true);
  });

  test('strips an IPv6 zone id before classifying', () => {
    expect(isBlockedHost('fe80::1%eth0')).toBe(true);
  });

  test('allows a public IPv6 and a public IPv4-mapped address', () => {
    expect(isBlockedHost('2606:4700:4700::1111')).toBe(false);
    expect(isBlockedHost('::ffff:8.8.8.8')).toBe(false);
  });
});

describe('isBlockedHost — public hosts pass through', () => {
  test('allows normal video hosts and CDNs', () => {
    expect(isBlockedHost('www.youtube.com')).toBe(false);
    expect(isBlockedHost('cdn.example.com')).toBe(false);
    expect(isBlockedHost('vimeo.com')).toBe(false);
  });
});
