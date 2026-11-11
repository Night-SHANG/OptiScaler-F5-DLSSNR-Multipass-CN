# F5 upstream integration audit, 2026-11-11

Candidate: `janblade/OptiScaler-F5-DLSSNR-Multipass` main `f10dedf93a2d5412c753c751c120d52b223800f6`.
Previous pin: `4d72d53e521b34a5cda9dd4f63ee7f4cd0438035`.

## Scope and immutable evidence

The upstream diff contains 190 files (49,485 additions and 28,697 removals), mostly renderer/source, generated shader headers, new smoke tests, and UI changes. Main additions include F5Low integration, LUT chaining/colour spaces and DX11/Vulkan LUT shaders, depth fade, native blend, secondary contexts/retirement, notification history, frame timing and frame-generation status rules. This review accepts that implementation as upstream code, not as proof of rendering correctness or a security audit of GPU algorithms. Localization must not change renderer producers, persisted configuration names or values.

The previous exact contract and pin are retained under `audit/2026-10-31/`. The new contract has 1,261 C/C++ paths and 1,607 exact-byte protected files. Only 24 byte-identical previously audited files retain their existing structured records. Every changed structured source moved into exact-byte protection. All mutable literal allowlists remain empty; the normalizer and verification implementation are unchanged. There is no automatic regeneration command or compatibility bypass.

## Dependencies, licenses and installers

- `.gitmodules` and all ten gitlinks are unchanged. Recursive dependency worktrees still need the independent Windows build gate; this review does not claim they are initialized.
- All four installer inputs, `get_hybrid_assets.ps1`, NVIDIA Streamline manifest, existing legal notices/licenses, original font and ImGui core anchors are unchanged. Installer translation pairs and fingerprints require no renewal. `ImGuiNotify.hpp` did change for notification integration and is now exact-byte protected.
- The new `external/f5low/README.md` is dependency documentation and remains protected, not exempted as ordinary documentation. It describes an external GPL-3.0 F5Low kit and Intel XeSS-FG 1.3.4.95. No kit binaries are in this upstream tree, and none were downloaded, accepted or redistributed for this audit.
- The kit path is git-ignored except its README. Existing XeSS gitlink remains unchanged and the MSBuild output still uses its 1.3.1.78 library.

## Packaging and build review

`package_release.ps1` now requires an external F5Low kit by default. Its kit branch checks archive/manifest hashes, the exact Intel version/hash/signature, export strings and binary path hygiene; stages F5Low plus the replacement Intel DLL and license notices. It also changes forwarder selection to the newest output, checks its version against OptiScaler, and requires shipped `FGOutput=auto` and `FrameGenerator=auto`.

The CN wrapper explicitly supplies upstream's supported `-NoF5Low` switch. This preserves the existing downloader-only, pinned-dependency package without silently adding a new external runtime. It rejects `f5low.dll` in both build/public payload checks and records `f5low_kit_included: false` in metadata. Existing dependency byte comparisons, prohibited NVIDIA runtime checks, exact build-evidence hashes, archive validation and installer-output checks remain intact. F5Low UI/source support is present, but the optional kit is not bundled; this is a deliberate release-content limitation, not full F5Low distribution support.

New audited packager SHA256: `08eedbba9154b2f09685c7eddbd40b1c6cb3b24156a4bc58f43419de383600c8`.
New main project SHA256: `fd4c54668bb3ebc5f0e6bd6e43c33193c7c565bce6ac4f109592be1597ac05ac`.
The hybrid helper hash is unchanged.

The main `.vcxproj` diff adds source/header entries for F5Low, notifications, LUTs, timing and contexts; pre/postbuild commands are unchanged. The forwarder now includes a version resource through both MSVC and CMake (MSVC only), using the shared release resource header. Its existing separately verified build remains necessary. Filters mirror source additions.

Upstream's package workflow additionally downloads user-supplied kit URLs and can attach a rewritten package to a draft release using `--clobber`. Its new `tools/finish_release_zip.py` changes automatic FG defaults to F5Low/XeFG Tensor. Neither workflow nor finishing script is adopted or executed by CN packaging. Both are exact-byte protected inputs. CN does not gain remote publishing permission from these upstream files. Other upstream workflow/test runner changes add host smoke cases and path triggers, not CN publication changes.

## Verification and limits

- Exact immutable-object, HEAD, index and pristine worktree verification passed: 1,261 sources, ten gitlinks, no changed structured sources.
- A new packaging regression failed before implementation on the missing `-NoF5Low`, then passed after the wrapper change. It also checks optional-kit rejection, metadata and absence of upstream finishing-script invocation.
- Build/packaging contract suite: 25 tests passed, with six PowerShell-only tests skipped because PowerShell is unavailable in this Linux cloud workspace.
- Upstream compatibility suite: 31 tests passed, including historical contract retention, unchanged dependency/installer evidence and no expanded mutable slots, alongside real-Git hostile-input rejection tests.
- Installer suite: 19 tests passed, with two platform-specific tests skipped; no installer adapter implementation or fingerprint change was necessary.
- Targeted Python compilation and whitespace checks passed; pristine upstream `git status --short` remained empty.
- Windows PowerShell execution, MSVC Release x64 compilation, final package/runtime dependency checks, and game/GPU/Chinese pixel layout remain separate gates. No local-computer operation, remote write, publication, license acceptance or optional-runtime download was performed by this build audit.

Localization source coverage and translation results are maintained separately by the integration work; a zero pending count alone is not proof of every visible runtime path.

## Display and translation integration

Independent source traversal added missing transitive F5Low/FG status, module details/signatures, notification type, LUT space/chain and shader error producers. New templates preserve raw module names while translating absent version metadata. Input and post-stack LUT filename previews use raw UTF-8 paths, preserving stored path bytes and control IDs. A previous 1D-only rejection probe was retired explicitly because upstream now supports 1D LUTs, with its exact evidence archived.

Final catalog: 2,967 active candidates = 2,735 changed display translations + 232 explained technical retentions; missing/stale zero. Compared with the previous candidate, 295 added and 24 removed (7 new sources match rewritten old wording). 241 inherited reviewed states and 2,726 machine_translated states remain; AI additions are not human-reviewed.

The post-LUT loaded-chain string is already flattened upstream and contains arbitrary filenames. The status snapshot lacks historical per-layer names/sizes, so re-parsing separators or current settings cannot safely reconstruct it. It intentionally remains raw, including English connective prose; its outer label is translated. A complete solution requires a structured upstream display snapshot. Unknown external DLL diagnostics also retain fallback. Neither limitation is counted as proof of full runtime coverage.

## Final portable integration checks

Against the committed candidate, full unittest discovery ran 284 tests: 276 passed and eight Windows/PowerShell-only tests skipped. compileall, strict source/placeholder translation checks and reviewed-memory consistency passed. The fresh localized copy adapted 1,132 calls in 14 files; actual ImGui wrapper syntax and 173 boundary assertions passed. Representative probes checked 208 visible sources and three excluded persisted keys. Actual rendered samples passed all 65 cases in each of C++17 and C++20. The original upstream checkout remained pristine throughout.

Independent review found and fixed the module-version raw-field omission, then found no further blocking issues; the raw loaded-chain limitation was retained after confirming the missing structured upstream interface. Tests validate source and display adaptation, not real GPU rendering. Windows and package checks are executed by the draft PR's workflow and must be read for the exact final candidate.

A second same-pin source scan produced zero additions/removals and no changes under `Localization/`; the original 295-added/24-removed transition statistics remain stable.
