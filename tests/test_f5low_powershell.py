"""Execute the package-stage exceptions on CI Windows, without loading DLLs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class F5LowPowerShellTests(unittest.TestCase):
    def setUp(self):
        self.pwsh = shutil.which('pwsh')
        if not self.pwsh:
            self.skipTest('PowerShell unavailable; actual Windows package checks remain required')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    @staticmethod
    def quote(path):
        return "'" + str(path).replace("'", "''") + "'"

    def invoke(self, body):
        script = (
            "$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest; "
            "$tokens=$null; $errors=$null; "
            f"$ast=[Management.Automation.Language.Parser]::ParseFile({self.quote(ROOT / 'tools/package.ps1')},[ref]$tokens,[ref]$errors); "
            "if ($errors.Count) { throw ($errors | Out-String) }; "
            "foreach ($function in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]}, $true)) { Invoke-Expression $function.Extent.Text }; "
            + body)
        result = subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-Command', script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def rejected(self, command):
        return (f"$rejected=$false; try {{ {command} }} catch {{ $rejected=$true }}; "
                "if (-not $rejected) { throw 'Unpinned payload was accepted' }; ")

    def test_package_exception_never_allows_wrong_bytes_wrong_path_or_nvidia(self):
        stage = self.root / 'stage'
        stage.mkdir()
        for relative in ('OptiScaler/plugins/f5low.dll', 'f5low.dll', 'wrong/f5low.dll',
                         'OptiScaler/plugins/nvngx_dlssnr.dll', 'OptiScaler/sl.common.dll',
                         'OptiScaler/nvngx_dlssg.dll', 'nvngx.dll_dlssnr.lib'):
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'inert forbidden fixture')
            for flags in ('', '-AllowPinnedF5Low', '-AllowForwarderBuildImports -AllowPinnedF5Low'):
                self.invoke(self.rejected(f'Assert-NoForbiddenPayload {self.quote(stage)} {flags}'))
            path.unlink()

    def make_dependencies(self):
        source = self.root / 'source'
        stage = self.root / 'stage'
        pairs = [
            ('external/xess/LICENSE.txt', 'Licenses/XeSS_LICENSE.txt'),
            ('external/FidelityFX-SDK/docs/license.md', 'OptiScaler/Licenses/FidelityFX_v1_LICENSE.md'),
            ('external/FidelityFX-SDK/PrebuiltSignedDLL/amd_fidelityfx_vk.dll', 'OptiScaler/amd_fidelityfx_vk.dll'),
            ('external/FidelityFX-SDK-v2/docs/license.md', 'Licenses/FidelityFX_v2_LICENSE.md'),
            ('external/directx_agility_sdk/LICENSE.txt', 'Licenses/DirectX_LICENSE.txt'),
            ('external/xess/bin/libxess_fg.dll', 'OptiScaler/libxess_fg.dll'),
            ('external/xess/bin/libxess.dll', 'OptiScaler/libxess.dll'),
            ('external/directx_agility_sdk/lib/D3D12Core.dll', 'OptiScaler/D3D12_OptiScaler/D3D12Core.dll'),
            ('Licenses/other.txt', 'Licenses/other.txt'), ('LUTs/fixture.bin', 'OptiScaler/LUTs/fixture.bin'),
        ]
        for name in ('amd_fidelityfx_loader_dx12.dll', 'amd_fidelityfx_upscaler_dx12.dll', 'amd_fidelityfx_framegeneration_dx12.dll'):
            pairs.append((f'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/{name}', f'OptiScaler/{name}'))
        for original, target in pairs:
            data = ('inert unchanged dependency ' + original).encode()
            for path in (source / original, stage / target):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        return source, stage

    def test_build_dependency_bytes_stay_exact_but_cannot_stand_in_for_new_package_intel(self):
        source, stage = self.make_dependencies()
        prefix = f'$SourceRoot={self.quote(source)}; '
        self.invoke(prefix + f'Assert-StagedDependencies {self.quote(stage)}; ' +
                    self.rejected(f'Assert-StagedDependencies {self.quote(stage)} -PackageStage'))
        (stage / 'OptiScaler/libxess.dll').write_bytes(b'wrong dependency')
        self.invoke(prefix + self.rejected(f'Assert-StagedDependencies {self.quote(stage)}'))

    def test_official_new_intel_is_package_only_and_signature_version_remain_required(self):
        archive = os.environ.get('F5LOW_KIT_ZIP')
        if not archive or os.name != 'nt':
            self.skipTest('Official kit and Windows Authenticode are required')
        source, stage = self.make_dependencies()
        intel = stage / 'OptiScaler/libxess_fg.dll'
        with zipfile.ZipFile(archive) as kit:
            intel.write_bytes(kit.read('libxess_fg.dll'))
            (stage / 'Licenses/XeSS_LICENSE.txt').write_bytes(kit.read('XeSS_LICENSE.txt'))
        prefix = f'$SourceRoot={self.quote(source)}; '
        self.invoke(prefix + f'Assert-StagedDependencies {self.quote(stage)} -PackageStage; ' +
                    self.rejected(f'Assert-StagedDependencies {self.quote(stage)}'))
        for signature in ("[pscustomobject]@{Status='NotSigned'; SignerCertificate=$null}",
                          "[pscustomobject]@{Status='Valid'; SignerCertificate=[pscustomobject]@{Subject='O=Other Corporation'}}"):
            self.invoke('function Get-AuthenticodeSignature { ' + signature + ' }; ' +
                        self.rejected(f'Assert-F5LowIntel {self.quote(intel)}'))
        self.invoke("function Get-Item { [pscustomobject]@{Attributes=0; VersionInfo=[pscustomobject]@{FileVersion='1.3.1.78'}} }; " +
                    self.rejected(f'Assert-F5LowIntel {self.quote(intel)}'))
        (stage / 'OptiScaler/libxess.dll').write_bytes(b'other dependency cannot change')
        self.invoke(prefix + self.rejected(f'Assert-StagedDependencies {self.quote(stage)} -PackageStage'))

    def test_exact_official_plugin_is_allowed_only_at_package_path_not_in_build(self):
        archive = os.environ.get('F5LOW_KIT_ZIP')
        if not archive:
            self.skipTest('Optional official-kit integration fixture not supplied')
        stage = self.root / 'stage'
        plugin = stage / 'OptiScaler/plugins/f5low.dll'
        plugin.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive) as source:
            plugin.write_bytes(source.read('f5low.dll'))
        self.invoke(f'Assert-NoForbiddenPayload {self.quote(stage)} -AllowPinnedF5Low; ' +
                    self.rejected(f'Assert-NoForbiddenPayload {self.quote(stage)}') +
                    self.rejected(f'Assert-NoForbiddenPayload {self.quote(stage)} -AllowForwarderBuildImports'))
        for relative in ('nvngx_dlssnr.dll', 'OptiScaler/sl.common.dll', 'OptiScaler/nvngx_dlssg.dll',
                         'OptiScaler/plugins/dlssg_sm86.dll', 'nvngx.dll_dlssnr.lib'):
            forbidden = stage / relative
            forbidden.parent.mkdir(parents=True, exist_ok=True)
            forbidden.write_bytes(b'inert forbidden fixture beside a valid F5Low DLL')
            self.invoke(self.rejected(f'Assert-NoForbiddenPayload {self.quote(stage)} -AllowPinnedF5Low'))
            forbidden.unlink()
        wrong = stage / 'f5low.dll'
        plugin.rename(wrong)
        self.invoke(self.rejected(f'Assert-NoForbiddenPayload {self.quote(stage)} -AllowPinnedF5Low'))


if __name__ == '__main__':
    unittest.main()
