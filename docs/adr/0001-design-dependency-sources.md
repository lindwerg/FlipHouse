# ADR-0001 — Design dependency sources (npm/CLI vs vendored)

- **Status:** Accepted · 2026-06-15
- **Context:** `docs/02-ДИЗАЙН-И-МОУШЕН.md` (§2–§3, §6), `docs/04` §1.4 (PWA)
- **Scope:** P1+ design/motion/PWA phases

## Decision

Design libraries fall into **two source channels**. This ADR pins which channel
each comes from so later phases never re-derive the source or pull from an
unvetted mirror.

1. **Vendored via `git clone` into `/vendor`** (pinned in `vendor/PINS.lock`,
   Шаг 0.9): repos we lift/patch source from — `ai-elements`, `kibo`,
   `shadergradient`, `launch-ui`. These are also installable via CLI below; we
   vendor them so the lifted source is reproducible and reviewable.
2. **Installed via npm / shadcn-style CLI** (NOT cloned into `/vendor`): runtime
   packages and shadcn "copy-owned" generators. Commands below are the single
   source of truth.

> Permissive licenses verified against upstream `LICENSE` files in `vendor/PINS.lock`:
> `ai-elements` = Apache-2.0, `kibo`/`shadergradient`/`launch-ui` = MIT.

## How we install (exact commands)

From `docs/02 §3.1` — hero / atmosphere:

```bash
npx ai-elements add prompt-input      # hero prompt-input shell (Apache-2.0)
npx kibo-ui add dropzone              # drop surface (MIT)
npm i @shadergradient/react @react-three/fiber three   # WebGL mesh-gradient bg (MIT), code-split ssr:false
npm i motion                          # motion engine (MIT), import from 'motion/react'
```

From `docs/02 §6` — motion / scroll / tokens:

```bash
npm i lenis gsap                      # smooth scroll (MIT) + GSAP (no-charge, all plugins free)
npm i -D style-dictionary             # design tokens source-of-truth (Apache-2.0) → tokens.css
```

From `docs/04 §1.4` — PWA:

```bash
npm i @serwist/next web-push && npm i -D serwist @types/web-push
```

## Source channel per dependency

| dependency | channel | license | role |
|---|---|---|---|
| `ai-elements` (PromptInput) | CLI `npx ai-elements` + vendored | Apache-2.0 | hero input shell |
| `kibo` (Dropzone) | CLI `npx kibo-ui` + vendored | MIT | drop surface |
| `shadergradient` | npm `@shadergradient/react` + vendored | MIT | animated mesh-gradient bg |
| `motion` | npm `motion` | MIT | motion engine (Magic UI / motion-primitives base) |
| `lenis` | npm `lenis` | MIT | smooth scroll |
| `gsap` + ScrollTrigger | npm `gsap` | GSAP no-charge | scroll timelines / pin / scrub |
| `style-dictionary` | npm (dev) | Apache-2.0 | token build → `tokens.css` |
| `@serwist/next` / `web-push` | npm | MIT | PWA service worker + web-push |
| `launch-ui` | vendored (`/vendor`) | MIT | landing sections |

## Avoided dependencies (do NOT use / vendor)

Marked **avoided** per `docs/02 §2.4` / §3 — license or competitive-scope risk:

| dependency | reason | avoid |
|---|---|---|
| `paper-design/shaders` (`@paper-design/shaders-react`) | **PolyForm Shield 1.0.0, not OSI** — banned for a product competing with Paper (design/gradient/shader tools). | **avoid** if FlipHouse is itself a design tool; legally vet otherwise. Use `shadergradient` instead. |
| `whatamesh` (`jordienr/whatamesh`) | **No license (all-rights-reserved)** on GitHub and npm. | **avoid** — use `shadergradient` for the same Stripe-style gradient. |
| `origin-space/originui` | **AGPL-3.0** copyleft (redirects to `cosscom/coss`). | **avoid** for vendoring — use `kibo` (MIT) for the same aesthetic. |

## Consequences

- P-phase design steps reference this ADR for the install command and never
  guess a source. New design deps are added here first.
- `magicui` / `motion-primitives` / `aceternity` are shadcn "copy-owned"
  components pulled through their own CLIs on top of `motion`; they are not
  cloned into `/vendor` (consistent with channel 2).
