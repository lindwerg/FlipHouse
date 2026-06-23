/**
 * SSRF host classification — the single source of truth for "is this host/IP one
 * a server-side fetch must NEVER reach". Shared by the web producer (rejects a
 * blocked literal host at submit time) and the worker consumer (re-checks the
 * literal host AND every DNS-resolved address before yt-dlp runs).
 *
 * The threat: an authenticated user pastes `http://169.254.169.254/x.mp4` (cloud
 * IMDS), `http://10.0.0.5/x.webm` (Railway private network), or `http://localhost`
 * — the worker has general outbound network access (it must reach googlevideo /
 * vimeo), so an un-filtered host is a read-exfiltration / credential-theft
 * primitive. Everything here is PURE so every branch is unit-tested.
 */

/** Hostnames that resolve to a node-local / metadata endpoint regardless of DNS. */
const BLOCKED_HOSTNAMES = new Set(['localhost', 'metadata.google.internal']);

/** Hostname suffixes that denote internal/link-local namespaces, never public. */
const BLOCKED_HOSTNAME_SUFFIXES = ['.localhost', '.internal', '.local', '.localdomain'];

/** Decimal-dotted IPv4 (no validation of octet range — callers pass real IPs). */
const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

/** Parse an IPv4 string into its four octets, or `null` when it is not IPv4. */
function parseIpv4(host: string): readonly [number, number, number, number] | null {
  const match = IPV4.exec(host);
  if (!match) {
    return null;
  }
  const octets = [Number(match[1]), Number(match[2]), Number(match[3]), Number(match[4])] as const;
  if (octets.some((o) => o > 255)) {
    return null;
  }
  return octets;
}

/**
 * True when an IPv4 address is private / loopback / link-local / metadata / other
 * non-public range (RFC 1918 + 127/8 loopback + 169.254/16 link-local incl. the
 * 169.254.169.254 cloud IMDS + 100.64/10 CGNAT + 0/8 + reserved/broadcast).
 */
function isBlockedIpv4(octets: readonly [number, number, number, number]): boolean {
  const [a, b] = octets;
  if (a === 0) return true; // "this" network / unspecified
  if (a === 10) return true; // RFC 1918
  if (a === 127) return true; // loopback
  if (a === 169 && b === 254) return true; // link-local incl. cloud metadata 169.254.169.254
  if (a === 172 && b >= 16 && b <= 31) return true; // RFC 1918
  if (a === 192 && b === 168) return true; // RFC 1918
  if (a === 100 && b >= 64 && b <= 127) return true; // CGNAT (carrier-grade NAT)
  if (a >= 224) return true; // multicast (224/4) + reserved/broadcast (240/4, 255.255.255.255)
  return false;
}

/** Strip an IPv6 zone id (`%eth0`) and surrounding brackets the URL host may carry. */
function normalizeIpv6(host: string): string {
  const unbracketed = host.startsWith('[') && host.endsWith(']') ? host.slice(1, -1) : host;
  const zoneAt = unbracketed.indexOf('%');
  return (zoneAt === -1 ? unbracketed : unbracketed.slice(0, zoneAt)).toLowerCase();
}

/**
 * True when an IPv6 literal is loopback (`::1`), unspecified (`::`), link-local
 * (`fe80::/10`), unique-local (`fc00::/7`), or an IPv4-mapped/compat address whose
 * embedded IPv4 is itself blocked (`::ffff:169.254.169.254`, `::ffff:10.0.0.5`).
 */
function isBlockedIpv6(host: string): boolean {
  const addr = normalizeIpv6(host);
  if (addr === '::1' || addr === '::') {
    return true;
  }
  // IPv4-mapped/compat: re-classify the embedded IPv4 (covers ::ffff:169.254.169.254).
  const lastColon = addr.lastIndexOf(':');
  if (lastColon !== -1 && addr.slice(lastColon + 1).includes('.')) {
    const embedded = parseIpv4(addr.slice(lastColon + 1));
    if (embedded && isBlockedIpv4(embedded)) {
      return true;
    }
  }
  if (addr.startsWith('fe8') || addr.startsWith('fe9') || addr.startsWith('fea') || addr.startsWith('feb')) {
    return true; // fe80::/10 link-local
  }
  if (addr.startsWith('fc') || addr.startsWith('fd')) {
    return true; // fc00::/7 unique-local
  }
  return false;
}

/**
 * True when `host` (a URL hostname OR a DNS-resolved IP) must be blocked from a
 * server-side fetch: a blocked hostname/suffix, or a private/loopback/link-local/
 * metadata IPv4/IPv6 literal. A normal public host (`cdn.example.com`, `1.2.3.4`)
 * returns false. Case-insensitive on hostnames.
 */
export function isBlockedHost(host: string): boolean {
  const lower = host.toLowerCase();
  if (BLOCKED_HOSTNAMES.has(lower)) {
    return true;
  }
  if (BLOCKED_HOSTNAME_SUFFIXES.some((suffix) => lower.endsWith(suffix))) {
    return true;
  }
  const ipv4 = parseIpv4(lower);
  if (ipv4) {
    return isBlockedIpv4(ipv4);
  }
  if (lower.includes(':')) {
    return isBlockedIpv6(host);
  }
  return false;
}
