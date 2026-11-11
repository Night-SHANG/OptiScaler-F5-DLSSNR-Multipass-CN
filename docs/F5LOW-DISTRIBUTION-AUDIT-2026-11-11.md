# F5Low release-content correction, 2026-11-11

## Scope and correction

The first 0.1.37.2 CN candidate deliberately passed `-NoF5Low` to preserve the previous package boundary. That omitted a component shipped by the new upstream main ZIP and was not a requirement of upstream's source layout or of a blanket redistribution prohibition. This revision restores the upstream main package's F5Low kit and two player defaults. It does not claim GPU gameplay validation.

`downloader-only` in the existing metadata continues to describe the NVIDIA runtime distribution policy. It no longer means F5Low is excluded. NVIDIA DLSS/Streamline binaries remain separately obtained using the retained upstream downloader; the F5Low DLSS-G generator needs those files. The F5Low / XeFG Tensor component files are bundled. The separate vendor-neutral NR forwarder is not bundled, and the NR model DLL remains separately supplied as in upstream.

## Published assets inspected

Public assets were read as ZIP/data without executing their binaries. All archive SHA-256 values below matched GitHub's reported asset digests.

| Source | Actual result | Archive SHA-256 |
| --- | --- | --- |
| [Upstream 0.1.37.2 main ZIP](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/releases/download/v0.1.37.2/v0.1.37.2-Optiscaler-F5.zip) | 121 entries; F5Low 1.1.0.140, Intel 1.3.4.95 and notices present; `FGOutput=f5low`, `FrameGenerator=xefg_tensor` | `ca7cd4f4d0765bd72885c9f8f21ab4f2bed332c8f9aa158233bba8824f0b8980` |
| [Optional F5Low 1.1.0.184 update](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/releases/download/v0.1.37.2/Optional-F5Low-Update-1.1.0.184.zip) | F5Low DLL, license and update README; not a full Intel kit | `674453cb6af3f0d1db1ad8499ed23a4f577cea4cb2f64ae966550c9284871a7f` |
| [Optional vendor-neutral forwarder](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/releases/download/v0.1.37.2/Optional-Vendor-Neutral-DLSS5-Forwarder.zip) | Four files, no F5Low; independent NR forwarder option | `8a41f620e0c3f56fb6b617bb824b2099c5f04608f801ba1b4a7ca5c1f2674e96` |
| [Troubleshooting document](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/releases/download/v0.1.37.2/OptiScaler-DLSSNR-Troubleshooting.md) | Explicitly documents bundled F5Low/Intel and missing-DLL failure | `422e90bf78ad1eef0e8a435f868311be59182e2851cf49cd9c3adbe7e7a3511c` |
| [Upstream 0.1.35.1 main ZIP](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/releases/download/v0.1.35.1/OptiScaler-DLSSNR-F5-v0.1.35.1-with-dlss-fg.zip) | 116 entries; no F5Low file; Intel 1.3.1.78 | `29532c7dff93a7171e5825238fc0bdd0cfb9828cde7d4fcef5608537d589dc23` |
| [Previous CN 0.1.35.1 ZIP](https://github.com/Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN/releases/download/cn-candidate-20261031-8a18828f/OptiScaler-F5-DLSSNR-Multipass-CN-v0.1.35.1-zh20261101.zip) | 133 entries; no F5Low file; same old Intel bytes; `FGOutput=auto` | `12545ad9eacfc892d9a36060d048b0c5e751bc015bebe65e776cf3af29b86955` |

The old built-in **Optical F5Low** motion-estimation mode is different from the newer independent **FG Output F5Low** plugin. The old source pin has no F5Low FGOutput enum or kit packager. Missing `f5low.dll` does not trigger a first-run download: the runtime checks local paths and reports unavailable. Background initialization builds working data in memory from the local Intel DLL; it is not network installation.

## Official kit and immutable inputs

Use [f5low-fg v1.1.0.140](https://github.com/janblade/f5low-fg/releases/tag/v1.1.0.140), matching the main 0.1.37.2 player ZIP. Do not silently upgrade to the separately offered 1.1.0.184 update.

- Kit: `f5low-kit-1.1.0.140+1f17d38.zip`, 14,161,135 bytes, SHA-256 `97fa6fb53a2278dfc651e4de2b2201f399f40ce49474b5f8199a2e5794d87f56`.
- Source commit: [`1f17d38621270dd1fc0f835ea79f1b90bf1d6c7a`](https://github.com/janblade/f5low-fg/tree/1f17d38621270dd1fc0f835ea79f1b90bf1d6c7a).
- `f5low.dll`: 6,350,848 bytes; PE file version 1.1.0.140; SHA-256 `0993352a97a05537a88bd1d0266cb62ae581f219b75fc588fbc15eeeacb48fa4`.
- `libxess_fg.dll`: 22,866,056 bytes; PE file version 1.3.4.95; SHA-256 `752b1491350a29fb2850fa4d0d14f62d79980e0b3cd067d147bb2469c1ec3182`.
- Both DLL hashes exactly match the upstream main ZIP. Both official kit140 and kit184 contain the same Intel DLL. The old CN and upstream 0.1.35.1 Intel DLL has SHA-256 `ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27` and version 1.3.1.78.
- The seven kit files are the two DLLs, `LICENSE`, `XeSS_LICENSE.txt`, `zstd_LICENSE.txt`, `README-KIT.txt`, and `kit_hashes.txt`. The build verifies the archive and each file independently of the archive's self-reported manifest.

## Notices and limitations

The kit's complete `LICENSE` embeds GPLv3 and the project's section 7 linking/distribution exception. [make_kit.ps1](https://github.com/janblade/f5low-fg/blob/1f17d38621270dd1fc0f835ea79f1b90bf1d6c7a/tools/make_kit.ps1#L49-L79) appends that exception, so preserving the full kit LICENSE preserves it. The package retains it as `Licenses/f5low_LICENSE.txt`, retains Intel's `Licenses/XeSS_LICENSE.txt`, `Licenses/f5low_zstd_LICENSE.txt`, and `Licenses/f5low_README-KIT.txt` with the exact source repository and commit. Existing `Licenses/MFGUnlock_LICENSE.txt` notices remain unchanged.

The [F5Low exception](https://github.com/janblade/f5low-fg/blob/1f17d38621270dd1fc0f835ea79f1b90bf1d6c7a/LICENSE-EXCEPTION.md) permits specified combinations and joint distribution but does not grant rights to Intel/NVIDIA/AMD libraries. Those retain their own terms. Intel's text permits unmodified binary redistribution with notices and also restricts reverse engineering and runtime modification. Shipping the original Intel bytes and notices is not a legal guarantee about every runtime use or implementation. No DLL was executed during this asset-content audit.

The upstream [packaging workflow](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/blob/f10dedf93a2d5412c753c751c120d52b223800f6/.github/workflows/package_release.yml#L59-L113) requires a kit unless omission is explicitly selected. The CN correction keeps its existing build workflow and immutable source packager; it does not copy upstream's draft-asset `--clobber` publication step. Builds, final archive validation and actual game/GPU validation remain separate evidence.
