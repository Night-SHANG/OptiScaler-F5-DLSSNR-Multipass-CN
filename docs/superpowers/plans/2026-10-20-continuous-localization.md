# F5 Continuous Localization Implementation Plan

> **For agentic workers:** Use test-first implementation and independent whole-change review. Steps use checkbox tracking.

**Goal:** Add an accurate coverage section to the existing test Release and safely keep the F5 localization current with compatible upstream changes.

**Architecture:** A scheduled discovery/preflight workflow resolves a full upstream commit, checks immutable build/license/dependency contracts and audited display structures, and scans candidate text. Only a candidate with zero missing/stale translations and passing integration/runtime checks may update the tracked pin. Existing full Windows and portable jobs remain mandatory before any new test Pre-release. Existing release tags and assets are immutable.

**Tech Stack:** Python standard library, PowerShell, GitHub Actions, MSVC v143 and g++.

**Spec:** User-approved scope on 2026-10-20: add this Release's progress explanation and continuous synchronization like the prior CN repositories; untranslated additions or compatibility failure block publication. Translation credentials require separate authorization.

## Global Constraints

- Work only in `Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN`, on dot cloud Linux and GitHub-hosted runners.
- Preserve existing `v0.1.32-cn-test.1` tag, assets, and published target `6c9128d67a8fb5a21303fabb8affd032806ab862`.
- Coverage is static catalog accounting, not exhaustive runtime/visual acceptance.
- No new translation API configuration or reading/copying old secrets.
- No force-push, history removal, permission changes, license acceptance, or stable/Latest publication.
- Future compatible updates may produce distinct test Pre-releases only after all existing gates.
- Build scripts, package inputs, licensing/dependency changes, installer fingerprints, and unreviewed display structure changes fail closed.

## Review Focus

- No-op upstream checks must not create commits, releases, or duplicate updates.
- Missing/stale/unsafe translations must block candidate promotion and release.
- Concurrent main changes, moved upstream tags, or incompatible source anchors must stop rather than overwrite.
- Release-description editing must preserve every other body segment and all tag/asset identities.
- Failed/uncertain publication must read existing state before a retry and never replace existing assets.

## Task 1: Accurate Release Coverage

- [x] Add failing tests for current counts, missing/stale/retained provenance, diff counts, marker conflicts and byte preservation.
- [x] Implement pure `tools/f5_release_notes.py` summary/render/update functions.
- [x] Add a narrowly scoped body-only workflow action for the existing release; validate exact target, type and asset digests before and after.
- [ ] Verify actual public Release body contains the requested section and unchanged assets/tag.

## Task 2: Safe Upstream Compatibility Contract

- [x] Add tests for full-SHA/repository/version validation, protected file drift, new protected inputs, submodule changes and changed display structures.
- [x] Record baseline contracts separately from mutable current upstream pin.
- [x] Allow only explicitly compatible candidate changes; do not automatically approve new contracts.
- [x] Use the current validated pin in materialization, installer identity, packaging and current-source fixtures while retaining historical audit evidence.

## Task 3: Continuous Synchronization and Publication

- [x] Add a scheduled and manually runnable upstream discovery/preflight workflow with serialized updates.
- [x] Resolve upstream main and latest release metadata from the fixed repository; compare full commit identities.
- [x] Scan candidates, reuse reliable translations, preserve provenance and emit pending diagnostics; do not call an unconfigured translation service.
- [x] Run strict checks, current-source display integration and existing portable regressions before promoting compatible pin/catalog changes.
- [ ] Run the unchanged-strength Windows/portable pipeline for the resulting exact CN commit.
- [x] Permit only distinct test Pre-release names tied to verified upstream/CN SHAs and same-run package hashes.
- [x] Preserve current published release; no ordinary commit, PR or failed check may trigger publication.

## Task 4: Verification and Documentation

- [x] Run all unit tests, current-source fixtures, workflow static validation and independent review.
- [ ] Upload normal history-preserving commits and verify the remote SHA.
- [ ] Observe one real synchronization run and exact-commit full CI; inspect artifacts and release-description readback.
- [ ] Update repository documentation and Notion with actual enabled behavior, credential gap and remaining runtime limits.
