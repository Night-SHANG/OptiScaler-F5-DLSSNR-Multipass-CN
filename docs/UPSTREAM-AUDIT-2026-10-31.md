# F5 main integration audit, 2026-10-31

Candidate: `janblade/OptiScaler-F5-DLSSNR-Multipass` main `4d72d53e521b34a5cda9dd4f63ee7f4cd0438035` (one merge after v0.1.35.1). Previous: `fadc3bf67f6c8548e94914baec3f2e551ba8d8a4` v0.1.32. CN starting commit: `0af315ae0e3e7dd832aa75ca2b3db870e6b501bf`.

## Explicit review, not automatic contract renewal

The old automatic gate correctly rejected the changed source path set. 596 changed files include renderer additions, generated shaders and upstream tests. This review accepts upstream implementation as upstream code, not a claim of GPU behavioral equivalence or a security audit of its algorithms. No rendering producer logic is translated. Historical contract, pin, installer metadata and coverage evidence are preserved under `audit/v0.1.32/`; old Git history remains intact.

The new contract freezes every changed non-documentation input to exact bytes. Only unchanged historically audited sources retain the structured bucket, with **no mutable literal slots**. This tightens, not broadens, automatic authority: subsequent non-documentation drift must stop for another review. Full current C/C++ path set and ten unchanged gitlinks are pinned.

## Dependencies, licensing and packaging

- `.gitmodules` and all ten gitlinks unchanged. Recursive dependency checkout still requires its independent Windows gate.
- Four installers, `get_hybrid_assets.ps1`, original font and ImGui hash anchors unchanged. Installer byte/encoding/control-flow tests retained.
- `Licenses/MFGUnlock_LICENSE.txt` now describes moved provider recognition and retains MIT plus MinHook/HDE redistribution notices. RenoDX attribution adds SDR-to-HDR design credit. Both are shipped unmodified; no license-acceptance switch is introduced.
- `redist/streamline/manifest.json`: NVIDIA Streamline 2.14.1 -> 2.14.16, URL/versions/hashes updated by upstream; file allowlist and signer identities unchanged. Downloader-only package retains metadata, not proprietary binaries. No download/acceptance of this optional runtime was performed here.
- `package_release.ps1`: removes optional Ampere redistribution switch/copies, adds TROUBLESHOOTING.md, changes experimental toggle list. Existing forbidden-payload/downloader-only gates retained.
- `OptiScaler.vcxproj`: expanded upstream source set; prebuild events unchanged. Postbuild only moves the MFGUnlock license-copy line. Project/packager hashes updated after this diff review, hybrid hash unchanged.

## Coverage inspection outside pending count

New UI paths reviewed: profiles, multi-view screens, Superior Scaling, HDR output, Vulkan routing, dynamic XeFG, PluginsPage, FlowDiagnosticUi/FlowDebugViews, PluginsView and moved MFG status.

Fixed actual omissions: InputInt2 wrapper/scan; InputTextWithHint hint translation; FlowDebugViews arrays; plugin status/error producers and MFG status; raw profile/ASI names and paths. Added exact dynamic profile/plugin templates; unknown external diagnostics retain fallback. No bulk rewriting of configuration or path values.

New regression checks distinguish source arrays from internal static_assert text, verify hint/buffer/ID preservation, and protect raw names including names identical to translated UI words. Runtime template probes keep hostile-looking external strings as data, not format strings.

## Boundaries

Static candidates are not a proof of every runtime UI path or pixel layout. Windows MSVC Release, packaged output and GPU/game/Chinese layout require later independent gates. Loaded-profile supplementary LUT notes with arbitrary external data retain original text where safely splitting the user name is ambiguous.

## Independent review coverage additions

A second reviewer followed actual consumers instead of accepting zero pending entries. This found and fixed HDR output StatusLine/ReasonText; DebugPreviewDx11/Vk -> SharedFrame/SharedFrameVk error chains; Superior Pipeline.inl Say/GiveUp. Additional self-audit followed PluginRegistry wide states, loader switch-table help, ExposureAutoScan phase/status, and relocated MFG failure producers. Precise function/table/producer scope avoids treating general shader literals or diagnostic logs as translated UI. New full rendered templates cover HDR signal/active status, exposure waiting/found, debug shared-resource errors and MFG composed failure details. New C++ test cases exercise these chains.

The first v0.1.32-only representative fixture correctly failed on 14 deleted/rewritten upstream strings; these are archived verbatim under `audit/v0.1.32/retired-representatives.json`, not silently skipped based on catalog output. Current fixtures add explicit new plugin, profile, HDR, MFG, depth and optical-flow examples. A historical removed Ampere nested error now explicitly tests fallback rather than claiming its removed translation is active.

## Remote integration safety

Do not push this candidate directly to main. `upstream-sync.yml` can trigger on main changes to tests/contract and dispatch a publishing build. Use a separately authorized non-main branch + draft PR to run build.yml portable/Windows checks without publishing. No remote mutation, CI dispatch or Release was executed in this cloud preparation.

## Candidate verification snapshot

- Scan: 2696 active entries = 2495 changed display translations + 201 explained technical retentions; missing/stale 0. Net 430 additions and 119 obsolete entries versus the original CN catalog. 243 inherited reviewed states and 2453 machine-translated states; AI additions are not marked human-reviewed.
- Pristine exact source verification passed (1208 C/C++ paths, 10 unchanged gitlinks; nested submodule worktrees not yet initialized/compiled).
- Source injection: 1054 wrapped display calls across 13 files. Actual C++ wrapper syntax plus 173 boundary assertions passed.
- Independent representative catalog: 203 visible source probes plus 3 excluded persisted keys passed.
- Actual rendered-source fixtures: 58 cases passed under each of C++17 and C++20; source boundary integration checks passed.
- New dynamic tests cover 18 profile/plugin/HDR/exposure/shared-resource/MFG cases with actual RuntimeText compilation. Old-scanner red checks confirmed four newly covered producer families were previously absent.
- compileall, whitespace, reviewed-memory consistency and targeted secret-pattern inspection passed. Windows-specific checks remain unexecuted; final unittest post-commit status is reported separately in handoff.
