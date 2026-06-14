# CI branch protection — make the gate blocking

The `.github/workflows/ci.yml` job runs the full pipeline (`scripts/ci-local.sh`)
on every PR and push to `main`. To make it **block merges on red** (the final
ZERO-bugs gate, P0 ЧП F), the `ci` job must be marked **required** on `main`.

## One-time setup (repo admin)

GitHub UI: **Settings → Branches → Branch protection rules → Add rule**

- **Branch name pattern:** `main`
- ✅ **Require a pull request before merging**
- ✅ **Require status checks to pass before merging**
  - ✅ **Require branches to be up to date before merging**
  - Search and select the required check: **`ci`** (the job id in `ci.yml`)
- ✅ **Do not allow bypassing the above settings** (applies to admins too)

## Or via GitHub CLI

```bash
gh api -X PUT repos/:owner/:repo/branches/main/protection \
  -H 'Accept: application/vnd.github+json' \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[contexts][]=ci' \
  -f 'enforce_admins=true' \
  -f 'required_pull_request_reviews[required_approving_review_count]=1' \
  -f 'restrictions='
```

## Verifying it blocks

A red pipeline must block merge. Proven locally by the fail-fast test
(`scripts/__tests__/ci-pipeline.test.mjs::ci fails fast when a TS test is red`):
a broken unit test makes `scripts/ci-local.sh` exit non-zero **before** the e2e
step. The same script runs in CI, so the `ci` job goes red and — once required —
the merge button is disabled until fixed.

> From this point nothing red merges into `main`.
