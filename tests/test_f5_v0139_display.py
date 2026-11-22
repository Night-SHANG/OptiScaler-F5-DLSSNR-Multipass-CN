import shutil
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from f5_scan import find_f5_candidates
from localize_f5 import POST_LUT_REPORTERS, patch_model_weights, patch_post_lut_snapshot, patch_status_raw_values


class V0139Boundaries(unittest.TestCase):
    def test_status_helpers_and_vulkan_producers_scanned_not_table_ids(self):
        source = '''
        void draw() {
            if (MenuCard card("System status", scale); card.IsOpen()) {}
            if (BeginRows("statusSystem")) {}
            Row("Swap chain", raw_name);
            Pair("Output format", value);
            Flag("ASI plugins", installed);
        }'''
        found = {v.source for v in find_f5_candidates(source, 'OptiScaler/menu/StatusPage.cpp', {})}
        self.assertTrue({'System status', 'Swap chain', 'Output format', 'ASI plugins'} <= found)
        self.assertNotIn('statusSystem', found)
        source = 'inline std::string RunsOnText(Mode m) { return "Vulkan (native swapchain)"; }'
        self.assertIn('Vulkan (native swapchain)', {v.source for v in find_f5_candidates(source, 'OptiScaler/dlssnr/DlssNr_VulkanRoute.h', {})})

    def test_weight_folder_identity_and_suffix(self):
        src = '''std::string shown = stock;
            shown = ok ? current : current + " (no file for this model)";
            if (OptiScalerCN::UI::BeginCombo(label, shown.c_str())) {}
            if (OptiScalerCN::UI::Selectable(name.c_str(), name == current)) {}
        '''
        patched = patch_model_weights(src)
        self.assertIn('SelectableRaw(name.c_str(), name == current)', patched)
        self.assertIn('BeginComboRawPreview(label, shown.c_str())', patched)
        self.assertIn('current + OptiScalerCN::UI::TextValue(', patched)
        self.assertNotIn('TextValue(current', patched)

    def test_status_raw_boundary_stays_narrow(self):
        source = '''
          Row("GPU", gpu.name);
          Row("Game", state.gameExe + (state.gameName.empty() ? "" : " (" + state.gameName + ")"));
          Row("Quirks", Join(state.detectedQuirks));
          Row("ASI", asi);
          Pair("FG Nvngx", FgNvngxName((FgNvngx) state.activeFgNvngx, state.activeFgNvngxCustom),
                 state.activeFgNvngx == FGNvngxReplacement::None);
          Row("Vulkan route", summary.vulkanRoute);
        '''
        changed = patch_status_raw_values(source)
        for value in ('GPU', 'Game', 'Quirks', 'ASI'):
            self.assertIn(f'RowRaw("{value}", ', changed)
        self.assertIn('PairRaw("FG Nvngx"', changed)
        self.assertIn('VulkanStatusValue(summary.vulkanRoute)', changed)


    @unittest.skipUnless(shutil.which('g++') and (ROOT / '_upstream/OptiScaler/dlssnr/DlssNr_FinishedVk.cpp').is_file(),
                         'requires g++ and pinned v0.1.39 source')
    def test_actual_lut_snapshot_localizes_connectors_not_names_in_both_standards(self):
        original = ROOT / '_upstream'
        with tempfile.TemporaryDirectory() as name:
            case = Path(name)
            for rel in (*POST_LUT_REPORTERS, 'OptiScaler/dlssnr/DlssNr_Lut.h',
                        'OptiScaler/dlssnr/DlssNr_LutChain.h', 'OptiScaler/dlssnr/DlssNr_LutStatus.h',
                        'OptiScaler/dlssnr/DlssNr_LutSpaces.h', 'OptiScaler/dlssnr/DlssNr_LutFile.h'):
                dst = case / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original / rel, dst)
            overlay = case / 'OptiScaler/localization'
            shutil.copytree(ROOT / 'overlay/OptiScaler/localization', overlay)
            subprocess.run([sys.executable, str(ROOT / 'tools/generate_cpp.py'), '--channel', 'master',
                            '--out', str(overlay / 'generated/Strings.generated.h')], check=True, capture_output=True)
            patch_post_lut_snapshot(case)
            for rel in POST_LUT_REPORTERS:
                self.assertIn('status.cnChain', (case / rel).read_text(encoding='utf-8-sig'))
            cpp = case / 'fixture.cpp'
            cpp.write_text(r'''
#include <dlssnr/DlssNr_LutChain.h>
#include <dlssnr/DlssNr_LutStatus.h>
#include <cassert>
using namespace DlssNr;
int main()
{
    DlssNr_LutChainState state;
    state.baked.size = 17;
    const std::string sentinel = "Off, as Reset %n {0} ##suffix.cube";
    std::vector<ChainEntry> present(2);
    present[0].strength = present[1].strength = 1.f;
    state.layers[0].loadedPath = sentinel;
    state.layers[1].loadedPath = "Reset.cube";
    state.layers[0].lut.size = 33;
    state.layers[1].lut.size = 65;
    state.inputs[1].converted = true;
    const auto en = DlssNr_DescribeChain(state, present);
    const auto zh = DlssNr_DescribeChainCn(state, present);
    assert(en.find(sentinel) == 0 && zh.find(sentinel) == 0);
    assert(zh.find("Reset.cube") != std::string::npos);
    assert(en.find(", baked at 17^3") != std::string::npos);
    assert(zh.find(", baked at 17^3") == std::string::npos);
    assert(zh.find("17^3") != std::string::npos);
    assert(zh != en);
}
''', encoding='utf-8')
            for std in ('c++17', 'c++20'):
                exe = case / ('probe-' + std)
                result = subprocess.run(['g++', '-std=' + std, '-I', str(case / 'OptiScaler'),
                                         str(cpp), '-o', str(exe)], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run([str(exe)], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))


if __name__ == '__main__':
    unittest.main()
