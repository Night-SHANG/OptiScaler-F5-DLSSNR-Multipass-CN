# Windows-only, fail-closed wrapper for the audited F5 downloader-only packager.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$OutputDir
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$hybridArchiveHash = '3e735f825b85872d20c35c0d75404c1a28b7b6e11ca28ef06243a18225191037'
$hybridArchiveUrl = 'https://github.com/wilsjo2/OptiScaler-DLSSNR-PreSR-Multipass/releases/download/v0.7.5-nr-fixes/OptiScaler-DLSSNR-v0.7.5-nr-fixes.zip'
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Assert-UpstreamConfig($Config) {
    # Check native values before string coercion; this must remain safe even when
    # invoked independently by AST-based Windows regression tests.
    if ($Config.repository -isnot [string] -or
        $Config.repository -cne 'https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass.git' -or
        $Config.branch -isnot [string] -or $Config.branch -cne 'main' -or $Config.commit -isnot [string] -or
        $Config.commit -cnotmatch '\A[0-9a-f]{40}\z' -or
        $Config.upstream_version -isnot [string] -or $Config.upstream_version.Length -gt 96 -or
        $Config.package_prefix -isnot [string] -or
        $Config.package_prefix -cne 'OptiScaler-F5-DLSSNR-Multipass-CN') {
        throw 'Invalid exact F5 upstream identity'
    }
    $safeVersion = '\Av(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?\z'
    if ($Config.upstream_version -cnotmatch $safeVersion -and
        $Config.upstream_version -cne ('main-' + $Config.commit.Substring(0, 12))) {
        throw 'Unsafe upstream version'
    }
}

function Assert-Leaf([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Required file missing: $Path" }
    if ((Get-Item -LiteralPath $Path).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Linked inputs are forbidden: $Path"
    }
}
function Get-Sha([string]$Path) {
    Assert-Leaf $Path
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Assert-Hash([string]$Path, [string]$Expected) {
    if ((Get-Sha $Path) -ne $Expected) { throw "SHA256 mismatch: $Path" }
}
function Invoke-Git([string]$Root, [string[]]$Arguments) {
    $result = & git -C $Root @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Git verification failed: $($Arguments -join ' ')" }
    return ($result -join "`n").Trim()
}
function Invoke-PinnedPowerShellScript([string]$Script, [string[]]$ScriptArguments) {
    # The audited upstream scripts do not opt into StrictMode. Isolate their
    # original execution semantics, while keeping this verifier strict. A child
    # process also makes an upstream `exit` observable rather than ending us.
    $hostPath = (Get-Process -Id $PID).Path
    & $hostPath -NoProfile -NonInteractive -File $Script @ScriptArguments
    if ($LASTEXITCODE -ne 0) { throw "Pinned PowerShell script failed ($LASTEXITCODE): $Script" }
}
function Assert-Pe64([string]$Path) {
    Assert-Leaf $Path
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 256 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { throw "Not a PE DLL: $Path" }
    $offset = [BitConverter]::ToUInt32($bytes, 0x3c)
    if ($offset -gt $bytes.Length - 96 -or [BitConverter]::ToUInt32($bytes, $offset) -ne 0x4550 -or
        [BitConverter]::ToUInt16($bytes, $offset + 4) -ne 0x8664 -or
        [BitConverter]::ToUInt16($bytes, $offset + 24) -ne 0x20b -or
        ([BitConverter]::ToUInt16($bytes, $offset + 22) -band 0x2000) -eq 0) {
        throw "Expected an x64 PE32+ DLL: $Path"
    }
}
function Assert-SafeArchive([string]$Path) {
    # Validate the complete archive before any extraction, including license entries.
    $archive = [IO.Compression.ZipFile]::OpenRead($Path)
    try {
        if ($archive.Entries.Count -eq 0 -or $archive.Entries.Count -gt 10000) { throw 'Invalid ZIP entry count' }
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        [long]$expanded = 0
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName
            if ($name -match '(^[/\\]|[\\:\x00-\x1f])' -or $name -match '(^|/)\.{1,2}(/|$)') {
                throw "Unsafe ZIP path: $name"
            }
            foreach ($part in $name.TrimEnd('/').Split('/')) {
                if (-not $part -or $part -match '[. ]$|[<>"|?*]' -or
                    $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { throw "Unsafe ZIP component: $name" }
            }
            if (-not $seen.Add($name.TrimEnd('/'))) { throw "Duplicate ZIP entry: $name" }
            if ((($entry.ExternalAttributes -shr 16) -band 0xf000) -eq 0xa000) { throw "ZIP symlink: $name" }
            $expanded += $entry.Length
            if ($entry.Length -gt 1GB -or $expanded -gt 2GB) { throw 'ZIP expands beyond the audited size budget' }
        }
    } finally { $archive.Dispose() }
}
function Assert-NoForbiddenPayload([string]$Stage, [switch]$AllowForwarderBuildImports) {
    $items = @(Get-ChildItem -LiteralPath $Stage -Recurse -Force)
    if ($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Linked package payload' }
    $bad = @($items | Where-Object { -not $_.PSIsContainer -and (
        $_.Name -ieq 'nvngx_dlssnr.dll' -or $_.Name -match '^(nvngx_dlss.*|sl\..*)\.dll$' -or
        $_.Name -match '\.(pdb|exp|lib|ilk|asi)$|latewarp|nrtrace' -or $_.Name -ieq 'dlssg_sm86.dll'
    ) })
    # MSVC writes these two import/link products next to the built forwarder.
    # The upstream explicit packaging allowlist does not copy them. Never allow
    # this exception for the final stage, nested files, or other build artifacts.
    if ($AllowForwarderBuildImports) {
        $root = [IO.Path]::GetFullPath($Stage)
        $allowed = @((Join-Path $root 'nvngx.dll_dlssnr.lib'), (Join-Path $root 'nvngx.dll_dlssnr.exp'))
        $bad = @($bad | Where-Object { $allowed -inotcontains $_.FullName })
    }
    if ($bad.Count) { throw "Forbidden public payload: $($bad.Name -join ', ')" }
}
function Assert-StagedDependencies([string]$Stage) {
    # Check every dependency copied by the unchanged Release PostBuildEvent, byte for byte.
    $pairs = @(
        @('external/xess/LICENSE.txt', 'Licenses/XeSS_LICENSE.txt'),
        @('external/FidelityFX-SDK/docs/license.md', 'OptiScaler/Licenses/FidelityFX_v1_LICENSE.md'),
        @('external/FidelityFX-SDK/PrebuiltSignedDLL/amd_fidelityfx_vk.dll', 'OptiScaler/amd_fidelityfx_vk.dll'),
        @('external/FidelityFX-SDK-v2/docs/license.md', 'Licenses/FidelityFX_v2_LICENSE.md'),
        @('external/directx_agility_sdk/LICENSE.txt', 'Licenses/DirectX_LICENSE.txt')
    )
    foreach ($name in @('amd_fidelityfx_loader_dx12.dll', 'amd_fidelityfx_upscaler_dx12.dll', 'amd_fidelityfx_framegeneration_dx12.dll')) {
        $pairs += ,@("external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/$name", "OptiScaler/$name")
    }
    foreach ($mapping in @(@('external/xess/bin', '*.dll', 'OptiScaler'),
                           @('external/directx_agility_sdk/lib', '*.dll', 'OptiScaler/D3D12_OptiScaler'),
                           @('Licenses', '*', 'Licenses'), @('LUTs', '*', 'OptiScaler/LUTs'))) {
        $source = Join-Path $SourceRoot $mapping[0]
        $files = @(Get-ChildItem -LiteralPath $source -Filter $mapping[1] -File)
        if (-not $files.Count) { throw "Required dependency source set is empty: $source" }
        foreach ($file in $files) { $pairs += ,@("$($mapping[0])/$($file.Name)", "$($mapping[2])/$($file.Name)") }
    }
    foreach ($pair in $pairs) { Assert-Hash (Join-Path $Stage $pair[1]) (Get-Sha (Join-Path $SourceRoot $pair[0])) }
}
function Write-Checksums([string]$Stage) {
    $lines = @(Get-ChildItem -LiteralPath $Stage -Recurse -File | Where-Object { $_.Name -ne 'SHA256SUMS.txt' } |
        Sort-Object FullName | ForEach-Object {
            $relative = [IO.Path]::GetRelativePath($Stage, $_.FullName).Replace('\', '/')
            '{0} *{1}' -f (Get-Sha $_.FullName), $relative
        })
    [IO.File]::WriteAllLines((Join-Path $Stage 'SHA256SUMS.txt'), $lines, [Text.UTF8Encoding]::new($false))
}

$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if ($SourceRoot -ne (Join-Path $repo '_upstream') -or $OutputDir -ne (Join-Path $repo 'dist')) {
    throw 'Only repository-local _upstream and new dist directories are allowed'
}
if ((Get-Item -LiteralPath $SourceRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked source tree' }
if (Test-Path -LiteralPath $OutputDir) { throw 'dist already exists; outputs are never overwritten or deleted' }
$cfg = Get-Content -LiteralPath (Join-Path $repo 'upstream.json') -Raw | ConvertFrom-Json
Assert-UpstreamConfig $cfg
# Share the Python contract validator rather than relying only on duplicated
# PowerShell syntax checks. The source has already been intentionally localized.
& python -c "import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from f5_upstream_contract import load_contract,validate_config; validate_config(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')),load_contract(sys.argv[3]))" `
    $PSScriptRoot (Join-Path $repo 'upstream.json') (Join-Path $repo 'upstream-contract.json')
if ($LASTEXITCODE -ne 0) { throw 'Upstream compatibility configuration rejected' }
$pin = [string]$cfg.commit
$version = [string]$cfg.upstream_version
if ((Invoke-Git $SourceRoot @('rev-parse', 'HEAD')) -ne $pin) { throw 'Upstream commit mismatch' }
$cnCommit = Invoke-Git $repo @('rev-parse', 'HEAD')
if ($cnCommit -notmatch '^[0-9a-f]{40}$') { throw 'Missing full CN commit' }
$submodules = & git -C $SourceRoot submodule status --recursive
if ($LASTEXITCODE -ne 0 -or -not $submodules -or @($submodules | Where-Object { $_ -notmatch '^ [0-9a-f]{40} ' }).Count) {
    throw 'Recursive submodule gitlinks are uninitialized or changed'
}
# The localized checkout may differ only where localization was intentionally applied.
# Packaging and project staging logic are immutable audited inputs.
$upstreamPackager = Join-Path $SourceRoot 'package_release.ps1'
$hybridFetcher = Join-Path $SourceRoot 'get_hybrid_assets.ps1'
Assert-Hash $upstreamPackager 'ceb7cf129a654591e70f897c0ba410039a94eb626c507fd252584969ff4a5a1c'
Assert-Hash $hybridFetcher '5fcd0c8018c1030e63e664d5df56e9a757bdafda77df688354cd4527e90172b1'
Assert-Hash (Join-Path $SourceRoot 'OptiScaler/OptiScaler.vcxproj') '516fb296ea12deab12a2d35a1a96ea1a87955a3bfeb3e2bb1a033b0519c7d774'
$buildEvidencePath = Join-Path $repo 'reports/build-evidence.json'
Assert-Leaf $buildEvidencePath
$buildEvidence = Get-Content -LiteralPath $buildEvidencePath -Raw | ConvertFrom-Json
if ($buildEvidence.cn_commit -ne $cnCommit -or $buildEvidence.upstream_commit -ne $pin -or
    $buildEvidence.configuration -ne 'Release' -or $buildEvidence.platform -ne 'x64' -or $buildEvidence.toolset -ne 'v143') {
    throw 'Successful MSVC Release x64 build evidence is missing or stale'
}
$builtStage = Join-Path $SourceRoot 'x64/Release/a'
foreach ($dll in @('OptiScaler.dll', 'nvngx.dll_dlssnr.dll')) {
    $proof = @($buildEvidence.binaries | Where-Object { $_.name -eq $dll })
    if ($proof.Count -ne 1) { throw "Build evidence does not name exactly one $dll" }
    Assert-Pe64 (Join-Path $builtStage $dll)
    Assert-Hash (Join-Path $builtStage $dll) $proof[0].sha256
}
Assert-StagedDependencies $builtStage
Assert-NoForbiddenPayload $builtStage -AllowForwarderBuildImports
foreach ($required in @('README.zh-CN.md', 'UPSTREAM.md', 'Localization/OptiScalerCN.ini',
                       'reports/upstream-materialization.json', 'reports/build-scan.md',
                       'reports/display-boundaries.json', 'reports/strict-localization.log',
                       'reports/tests.log', 'reports/forwarder-build.log', 'reports/solution-build.log')) {
    Assert-Leaf (Join-Path $repo $required)
}

New-Item -ItemType Directory -Path $OutputDir | Out-Null
$work = Join-Path $OutputDir '_package-work'
New-Item -ItemType Directory -Path $work | Out-Null
$archivePath = Join-Path $work 'hybrid-source.zip'
Invoke-WebRequest -Uri $hybridArchiveUrl -OutFile $archivePath
Assert-Hash $archivePath $hybridArchiveHash
Assert-SafeArchive $archivePath
$hybridScratch = Join-Path $work 'hybrid-assets' # Must not exist when the upstream helper starts.
Invoke-PinnedPowerShellScript $hybridFetcher @('-Destination', $hybridScratch, '-Archive', $archivePath)
$hybridManifestPath = Join-Path $hybridScratch 'asset-manifest.json'
$hybridManifest = Get-Content -LiteralPath $hybridManifestPath -Raw | ConvertFrom-Json
if (@($hybridManifest.files).Count -ne 15) { throw 'Expected exactly 15 verified hybrid assets' }
$packageVersion = "$version-cn-$($cnCommit.Substring(0, 12))"
$packageArguments = @('-Version', $packageVersion, '-SkipBuild', '-HybridAssetsDirectory', $hybridScratch)
# No proprietary or optional runtime switches are forwarded. The pinned defaults apply.
Invoke-PinnedPowerShellScript $upstreamPackager $packageArguments
$sourceZip = Join-Path $SourceRoot "release/OptiScaler-DLSSNR-F5-$packageVersion.zip"
Assert-Leaf $sourceZip
Assert-SafeArchive $sourceZip
$stage = Join-Path $work 'cn-stage'
Expand-Archive -LiteralPath $sourceZip -DestinationPath $stage

# Preserve the source archive's license and notices as well as the upstream runtime licenses.
$archive = [IO.Compression.ZipFile]::OpenRead($archivePath)
try {
    $license = @($archive.Entries | Where-Object { $_.FullName -eq 'LICENSE' -and $_.Name })
    if ($license.Count -ne 1) { throw 'Pinned hybrid source archive is missing its LICENSE' }
    $notices = @($archive.Entries | Where-Object { $_.Name -and ($_.FullName -eq 'LICENSE' -or $_.FullName.StartsWith('Licenses/')) })
    foreach ($entry in $notices) {
        $destination = Join-Path $stage ('Licenses/HybridSource/' + $entry.FullName)
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $false)
    }
} finally { $archive.Dispose() }
Copy-Item -LiteralPath (Join-Path $repo 'Localization/OptiScalerCN.ini') -Destination (Join-Path $stage 'OptiScalerCN.ini')
Copy-Item -LiteralPath (Join-Path $repo 'README.zh-CN.md') -Destination (Join-Path $stage 'README.CN.zh-CN.md')
Copy-Item -LiteralPath (Join-Path $repo 'UPSTREAM.md') -Destination (Join-Path $stage 'UPSTREAM.CN.md')
$metadata = [ordered]@{
    schema = 1; upstream_repository = $cfg.repository; upstream_commit = $pin; upstream_version = $version;
    cn_commit = $cnCommit; package_version = $packageVersion; variant = 'downloader-only';
    configuration = 'Release'; platform = 'x64'; toolset = 'v143'; msbuild_version = $buildEvidence.msbuild_version;
    hybrid_archive_url = $hybridArchiveUrl; hybrid_archive_sha256 = $hybridArchiveHash;
    hybrid_assets = @($hybridManifest.files); recursive_submodules = @($submodules);
    binaries = @($buildEvidence.binaries); built_at_utc = $buildEvidence.built_at_utc;
    packaged_at_utc = [DateTime]::UtcNow.ToString('o'); game_runtime_validation = 'not performed by this workflow'
}
$metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stage 'BUILD-INFO.CN.json') -Encoding utf8
Assert-StagedDependencies $stage
Assert-NoForbiddenPayload $stage
foreach ($dll in @('OptiScaler.dll', 'nvngx.dll_dlssnr.dll')) {
    Assert-Pe64 (Join-Path $stage $dll)
    Assert-Hash (Join-Path $stage $dll) (Get-Sha (Join-Path $builtStage $dll))
}
foreach ($entry in $hybridManifest.files) {
    Assert-Hash (Join-Path $stage ('OptiScaler/nvfp4/hybrid/' + $entry.path)) $entry.sha256
}
foreach ($required in @('LICENSE', 'README.md', 'INSTALL-DLSSNR.md', 'OptiScaler.ini', 'setup_windows.bat',
                       'setup_linux.sh', 'get_streamline.ps1', 'redist/streamline/manifest.json',
                       '!! EXTRACT ALL FILES TO GAME FOLDER !!', 'Licenses/HybridSource/LICENSE')) {
    Assert-Leaf (Join-Path $stage $required)
}
# User-facing scripts must be the exact localized outputs, not stale staged originals.
foreach ($script in @('setup_windows.bat', 'setup_linux.sh', 'get_streamline.ps1', 'redist/streamline/manifest.json')) {
    Assert-Hash (Join-Path $stage $script) (Get-Sha (Join-Path $SourceRoot $script))
}
Write-Checksums $stage
$zipName = "$($cfg.package_prefix)-$packageVersion-$($pin.Substring(0, 12)).zip"
if ($zipName -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]+\.zip$') { throw 'Unsafe package filename' }
$zipPath = Join-Path $OutputDir $zipName
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipPath -CompressionLevel Optimal
Assert-SafeArchive $zipPath
# Read every final archive entry and compare hashes with the verified stage, without trusting ZIP creation alone.
$finalZip = [IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $entries = @($finalZip.Entries | Where-Object { $_.Name })
    if ($entries.Count -ne @(Get-ChildItem -LiteralPath $stage -Recurse -File).Count) { throw 'Final ZIP file count mismatch' }
    foreach ($entry in $entries) {
        $stream = $entry.Open()
        $hash = [Security.Cryptography.SHA256]::Create()
        try { $actual = ([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
        finally { $hash.Dispose(); $stream.Dispose() }
        if ($actual -ne (Get-Sha (Join-Path $stage $entry.FullName))) { throw "Final ZIP content mismatch: $($entry.FullName)" }
    }
} finally { $finalZip.Dispose() }
$zipHash = Get-Sha $zipPath
$metadata['package'] = $zipName
$metadata['sha256'] = $zipHash
$metadata['verified_archive_files'] = $entries.Count
$metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDir 'build-metadata.json') -Encoding utf8
[IO.File]::WriteAllText(($zipPath + '.sha256'), "$zipHash *$zipName`n", [Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath $hybridManifestPath -Destination (Join-Path $repo 'reports/hybrid-asset-manifest.json')
Write-Host "PACKAGE=$zipName"
Write-Host "SHA256=$zipHash"
