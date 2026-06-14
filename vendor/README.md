# /vendor — pinned upstream sources

This directory holds shallow clones of the upstream repositories FlipHouse lifts
from. The clones themselves are **git-ignored** (we do not fork their history);
only `PINS.lock` and this `README.md` are tracked. `PINS.lock` records, per repo,
the pinned commit (`git clone --depth 1` HEAD at vendoring time), the verified
license, and the usage mode. Regenerate with:

```bash
node scripts/write-vendor-pins.mjs > vendor/PINS.lock
```

To (re)materialize the clones on a fresh checkout, run the clone commands in
`roadmap/P0-bootstrap-test-harness.md` Шаг 0.9 (or `scripts/setup.sh`, Шаг 0.12).

## Legal discipline

Licenses below are verified against each clone's actual `LICENSE` file, not just
the roadmap intent. The mode column governs what later phases may do.

| name | license | mode | what we may lift |
|---|---|---|---|
| `openshorts` | MIT | lift+edit | clipping/render engine (`main.py`, hooks, fonts, Dockerfile) |
| `samuraigpt-shorts` | **NONE** | **reference-only** | design of the 8-signal virality framework only — **no code** |
| `captacity` | MIT | lift+patch | word-timestamp karaoke caption burn-in |
| `lr-asd` | MIT | wrap | active-speaker detection, run on GPU provider (not lifted verbatim) |
| `tusd` | MIT | lift-verbatim | resumable upload edge (deployed as a container) |
| `saas-boilerplate` | MIT | lift+extend | Clerk auth / multi-tenant / RBAC / i18n skeleton |
| `launch-ui` | MIT | lift-sections | landing sections (hero, pricing, stats, cta, faq, footer, navbar) |
| `ai-elements` | Apache-2.0 | lift-promptinput | hero prompt-input shell |
| `kibo` | MIT | lift-dropzone | dropzone surface |
| `shadergradient` | MIT | lift/ref | animated WebGL mesh-gradient hero background |
| `cliq` | **NONE** | **reference-only** | Link→Conversion→Commission model only — **no code** |

### Hard rules

- **`samuraigpt-shorts` and `cliq` have no license.** They are vendored as a
  reference for clean-room reimplementation **only**. Never copy their code into
  production. Anything we ship that overlaps must be written from scratch.
- **`lr-asd` is MIT but used by wrapping** (CUDA → GPU provider), not by copying
  source into our tree; re-confirm license terms before any redistribution.
- Permissive repos (MIT / Apache-2.0) may be lifted/edited within their license
  terms (attribution preserved where required).
