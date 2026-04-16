# Maintainer Reality Check and Rewritten Issue Backlog

## Step 1 — Code analysis

### Existing modules and features
- **GTK3 desktop application (`src/Auryn.py` + `src/Auryn.ui`)**: URL input, quality selection, destination folder chooser, setup dialog, log view, metadata panel, and lyrics tab are wired and functional.
- **Download orchestration through `streamrip` CLI**: the app resolves `rip`, runs `rip url <url>` in a PTY, parses live output, updates progress, and supports stop/terminate.
- **Service-specific metadata fetchers**:
  - Qobuz album lookup (`fetch_qobuz_meta`)
  - Deezer album lookup (`fetch_deezer_album`) and track→album bridge (`fetch_deezer_track_album`)
  - Cover art retrieval and scaling
- **Preflight/setup checks**: verifies `rip` availability, presence of `~/.config/streamrip/config.toml`, and destination writability.
- **Credential application flow**: reads `~/.config/Auryn/accounts.json` and writes relevant values into streamrip TOML via regex replacements.
- **Basic CI**: linting and tests job exists, but tests are allowed to fail (`pytest || true`).

### Incomplete or fragile parts
- **No automated tests for runtime behavior**: project has no test files; CI is mostly syntactic confidence.
- **Fragile config editing**: `_update_config` uses regex replacement against TOML text; missing keys/section context can silently skip updates.
- **Secrets handling risk**: plaintext credentials in `~/.config/Auryn/accounts.json`; no permission hardening or warning UX.
- **Service support messaging vs runtime reality**:
  - URL detector recognizes tidal/soundcloud URLs, but metadata fetch is only implemented for qobuz/deezer.
  - README claims “does not directly interact with any online services”, but app performs multiple direct API calls (Qobuz, Deezer, lrclib).
- **Rebrand is partial**: repo name/README uses Auryn, while app file names, About dialog, desktop file, and UI title still use Auryn.
- **No packaging sources in repo for claims**: README references `.deb`/Docker/Flatpak status but repository contains no Dockerfile, compose file, or flatpak manifests.

### Missing components (based on repository contents)
- No unit/integration test suite.
- No issue templates, contribution guide, or roadmap doc in-repo.
- No build/packaging automation artifacts for Debian, Docker image, or Flatpak.
- No structured logging or crash-report persistence beyond GTK log pane.

## Step 2 — Reality check

### What actually works
- Desktop GUI launches from GTK Builder and exposes a complete end-to-end interaction path for entering URL, running preflight, starting/stopping download, and viewing log/progress.
- Qobuz/Deezer metadata + cover loading works as best-effort pre-download enrichment.
- Streamrip invocation and live output parsing are implemented and integrated with UI state.

### What is misleading in current issue framing (common examples to avoid)
- “Implement auth system” is misleading: there is already credential storage + apply flow; the real work is **hardening and validation**.
- “Add Docker support” is misleading: README says image exists, but this repo has no Docker assets; issue should be “add in-repo Docker build files matching README claims.”
- “Build service abstraction layer for all providers” is too broad for current maturity; current code needs incremental metadata/fallback consistency first.
- “Improve CI” should not imply quality gates exist today; tests are currently non-blocking in CI.

### What is too ambitious right now
- Full architecture rewrite (plugin system, async refactor, multi-process service layer).
- Comprehensive cross-platform installer matrix.
- Full secure vault/keyring integration in one shot.

## Step 3 — Rewritten issues

### Issue 1: Add smoke tests for URL parsing and preflight helpers
**Labels:** `good first issue`

## Overview
Core logic in `src/Auryn.py` (URL/service detection and setup checks) has no tests. This creates regression risk when adding providers or changing validation behavior.

## What needs to be done
- [ ] Create a `tests/` folder and add `test_detect_service_and_id.py`.
- [ ] Add table-driven tests for supported URL patterns (qobuz/deezer/deezer_track/tidal/soundcloud/invalid).
- [ ] Add unit tests for `toml_escape` edge cases.
- [ ] Add a lightweight preflight test that mocks `_find_rip_path` and writability checks.

## Goal
Catch regressions in parsing and setup logic before release.

## Notes
Keep tests pure-Python with mocks; do not require GTK display in CI.

---

### Issue 2: Make CI fail on real test failures
**Labels:** `good first issue`

## Overview
Current GitHub Actions workflow runs `pytest || true`, so broken tests do not block merges.

## What needs to be done
- [ ] Remove `|| true` from pytest step.
- [ ] Ensure at least one smoke test exists before enforcing failures.
- [ ] Document local test command in README.

## Goal
Turn CI from advisory into a real quality gate.

## Notes
Coordinate with Issue 1 to avoid immediately failing main branch without tests.

---

### Issue 3: Harden streamrip config updates (replace regex-only writes)
**Labels:** `help wanted`

## Overview
Credential and folder/quality updates rely on regex substitution on raw TOML text. If keys are absent or reordered, updates can silently fail.

## What needs to be done
- [ ] Introduce a small config writer helper that can insert missing keys when regex replacement finds no match.
- [ ] Add explicit logging when a key was not updated.
- [ ] Add backup file creation before write (e.g., `config.toml.bak`).
- [ ] Add tests for update behavior with missing keys.

## Goal
Make config mutation deterministic and safer across different streamrip config variants.

## Notes
Do not redesign full settings architecture; keep scope limited to current config fields.

---

### Issue 4: Add credential file safety checks and UX warnings
**Labels:** `help wanted`

## Overview
Credentials are read from `~/.config/Auryn/accounts.json` in plaintext. There is no permission check, warning, or guidance for safer usage.

## What needs to be done
- [ ] Check file permissions before loading credentials and log warning when overly permissive.
- [ ] Add Setup dialog note that credentials are local plaintext.
- [ ] Add README section documenting credential storage path and recommended permissions.

## Goal
Reduce accidental secret exposure while keeping current auth flow intact.

## Notes
Avoid keyring migration in this issue; this is a safety hardening pass only.

---

### Issue 5: Align README claims with actual runtime behavior
**Labels:** `good first issue`

## Overview
README legal/technical statements conflict with implementation details (the app does call external APIs for metadata/lyrics).

## What needs to be done
- [ ] Update README wording to accurately describe optional metadata/lyrics API calls.
- [ ] Keep legal disclaimer intent, but remove technically incorrect wording.
- [ ] Add short “What this app does/does not do” section grounded in current code.

## Goal
Ensure contributor/user expectations match real application behavior.

## Notes
Keep changes documentation-only; no feature work required.

---

### Issue 6: Complete Auryn rebrand in UI/runtime strings
**Labels:** `good first issue`

## Overview
Repository branding is “Auryn”, but runtime strings and file names still show “Auryn” in multiple places.

## What needs to be done
- [ ] Update window title, About dialog program name/comments/version text, and visible labels from Auryn to Auryn where appropriate.
- [ ] Update desktop entry metadata to match.
- [ ] Verify launch still works with existing file names (or rename in a separate scoped issue).

## Goal
Deliver a consistent project identity without risky file-structure churn.

## Notes
Do not combine with large rename/migration of module filenames unless separately planned.

---

### Issue 7: Add provider parity fallback for unsupported metadata fetch
**Labels:** `help wanted`

## Overview
Tidal/SoundCloud URLs are accepted by parser, but no metadata fetchers exist for them. User experience is uneven across providers.

## What needs to be done
- [ ] Add explicit UI status message when provider metadata enrichment is unavailable.
- [ ] Ensure download flow proceeds normally without metadata.
- [ ] Add tests for parser paths that intentionally skip metadata fetch.

## Goal
Provide predictable behavior instead of silent feature gaps.

## Notes
This issue is about user feedback/fallbacks, not implementing full provider API clients.

---

### Issue 8: Add in-repo packaging artifacts to match README promises
**Labels:** `help wanted`

## Overview
README references Docker/Flatpak/deb availability, but repo currently lacks Dockerfile/compose/flatpak manifests.

## What needs to be done
- [ ] Add a minimal, reproducible Dockerfile for GTK app runtime.
- [ ] Add a maintained `docker-compose.yml` example under version control.
- [ ] Either add Flatpak manifest scaffold or update README to mark status as external/not in repo.

## Goal
Bring documentation promises in sync with versioned build artifacts.

## Notes
Prefer a minimal first pass over a complex multi-stage packaging setup.

## Step 4 — Contributor focus summary
- `good first issue`: Issues 1, 2, 5, 6.
- `help wanted`: Issues 3, 4, 7, 8.
- Recommended onboarding order: **5 → 1 → 2 → 6**, then larger hardening tasks.
