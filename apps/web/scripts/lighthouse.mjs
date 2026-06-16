// Lighthouse CWV budget gate for the landing (P1.16, docs/02 §5.3 / web/performance.md).
// Founder runs this locally against a production build and on the staging domain at
// checkpoint G — NOT in the CI job (founder decision 2026-06-16: keep CI fast).
//
// Usage:
//   node scripts/lighthouse.mjs https://web-staging-….up.railway.app   # staging
//   pnpm --filter web build && node scripts/lighthouse.mjs              # local prod build
//
// With an explicit URL it audits that origin. Without one it spawns `next start`
// against the existing .next build, audits it, and tears the server down.
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { gzipSync } from 'node:zlib';
import * as chromeLauncher from 'chrome-launcher';
import lighthouse from 'lighthouse';
import desktopConfig from 'lighthouse/core/config/desktop-config.js';

const BUDGETS = {
  lcpMs: 2500, // LCP < 2.5s
  cls: 0.1, // CLS < 0.1
  tbtMs: 200, // TBT < 200ms
  jsGzBytes: 150 * 1024, // First-load JS < 150kb gzipped
};

const PORT = process.env.LIGHTHOUSE_PORT ?? '3009';
const externalUrl = process.argv[2] ?? process.env.LIGHTHOUSE_URL;
const targetUrl = externalUrl ?? `http://localhost:${PORT}`;

async function waitForServer(url, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { redirect: 'manual' });
      if (res.status > 0) {
        return;
      }
    } catch {
      // not up yet
    }
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(`server at ${url} did not become ready in ${timeoutMs}ms`);
}

async function runLighthouse(url) {
  const chrome = await chromeLauncher.launch({
    chromeFlags: ['--headless=new', '--no-sandbox', '--disable-gpu'],
  });
  try {
    const result = await lighthouse(
      url,
      { port: chrome.port, onlyCategories: ['performance'], output: 'json' },
      desktopConfig,
    );
    return result.lhr;
  } finally {
    await chrome.kill();
  }
}

/**
 * First-Load JS (gzipped): the JS the initial document pulls — the chunks named in
 * the served HTML's <script> tags. Dynamically-imported heavy libs (GSAP/Lenis on
 * the landing) are NOT counted: they are fetched later, which is exactly the
 * "dynamically import heavy libraries" pattern web/performance.md prescribes, so
 * the 150kb budget is about the initial bundle. Each chunk is gzipped from disk
 * (.next/static) for an exact, deterministic transfer size. Local build only —
 * returns null when auditing an external (staging) URL.
 */
async function firstLoadJsBytes(url, isExternal) {
  if (isExternal) {
    return null;
  }
  const html = await (await fetch(url)).text();
  const srcs = [...html.matchAll(/src="(\/_next\/static\/[^"]+?\.js)"/g)].map(m => m[1]);
  const unique = [...new Set(srcs)];

  let total = 0;
  for (const src of unique) {
    // /_next/static/chunks/x.js → <pkgRoot>/.next/static/chunks/x.js
    const file = path.join(process.cwd(), '.next', src.replace(/^\/_next\//, ''));
    total += gzipSync(readFileSync(file)).length;
  }
  return total;
}

function evaluate(lhr, jsBytes) {
  const lcp = lhr.audits['largest-contentful-paint'].numericValue;
  const cls = lhr.audits['cumulative-layout-shift'].numericValue;
  const tbt = lhr.audits['total-blocking-time'].numericValue;

  const checks = [
    { name: 'LCP', value: `${Math.round(lcp)}ms`, ok: lcp < BUDGETS.lcpMs, budget: `<${BUDGETS.lcpMs}ms` },
    { name: 'CLS', value: cls.toFixed(3), ok: cls < BUDGETS.cls, budget: `<${BUDGETS.cls}` },
    { name: 'TBT', value: `${Math.round(tbt)}ms`, ok: tbt < BUDGETS.tbtMs, budget: `<${BUDGETS.tbtMs}ms` },
  ];

  if (jsBytes != null) {
    checks.push({
      name: 'JS (gz)',
      value: `${(jsBytes / 1024).toFixed(1)}kb`,
      ok: jsBytes < BUDGETS.jsGzBytes,
      budget: `<${BUDGETS.jsGzBytes / 1024}kb first-load`,
    });
  }

  for (const c of checks) {
    console.warn(`${c.ok ? '✓' : '✗'} ${c.name.padEnd(8)} ${c.value.padEnd(10)} budget ${c.budget}`);
  }
  if (jsBytes == null) {
    console.warn('· JS (gz)  skipped    (first-load JS measured only against a local build)');
  }
  return checks.every(c => c.ok);
}

async function main() {
  let server;
  if (!externalUrl) {
    console.warn(`Starting next start on :${PORT} (audits the existing .next build)…`);
    server = spawn('npx', ['next', 'start', '-p', PORT], { stdio: 'inherit' });
    await waitForServer(targetUrl);
  }

  try {
    console.warn(`Running Lighthouse against ${targetUrl} …`);
    const lhr = await runLighthouse(targetUrl);
    const jsBytes = await firstLoadJsBytes(targetUrl, !!externalUrl);
    const passed = evaluate(lhr, jsBytes);

    if (!passed) {
      console.error('\n❌ Lighthouse budget exceeded.');
      process.exitCode = 1;
    } else {
      console.warn('\n✅ Lighthouse budget met.');
    }
  } finally {
    server?.kill('SIGTERM');
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
