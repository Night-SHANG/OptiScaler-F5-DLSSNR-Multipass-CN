"""November display producer and filename-boundary regressions."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from f5_scan import find_f5_candidates
import localize_f5

class NovemberDisplay(unittest.TestCase):
    def setUp(self):
        self.rules = json.loads((ROOT / 'Localization/scanner-rules.json').read_text())

    def test_new_status_producers_and_config_separation(self):
        source = '''const char* GeneratorText() { return "xefg_tensor"; }
        const char* RunStateLabel() { return "own frame generator running"; }
        const char* DlssgFilesMissing() { return "DLSS-G needs Streamline"; }
        const char* GeneratorLabel() { return "XeFG (Intel library)"; }'''
        values = {c.source for c in find_f5_candidates(source, 'OptiScaler/framegen/f5low/F5LowRules.h', self.rules)}
        self.assertEqual(values, {'own frame generator running', 'DLSS-G needs Streamline', 'XeFG (Intel library)'})

    def test_post_lut_errors_not_logs(self):
        source = '''void Run() { LOG_ERROR("internal GPU log");
        Report(false, "could not upload the LUT to the GPU");
        failure = "could not make the pass's views"; }'''
        values = {c.source for c in find_f5_candidates(source, 'OptiScaler/shaders/f5lut/F5Lut_Dx11.cpp', self.rules)}
        self.assertEqual(values, {'could not upload the LUT to the GPU', "could not make the pass's views"})

    def test_notifications_and_fg_rule_are_scanned(self):
        for rel, source, expected in [
            ('OptiScaler/menu/NotificationsPage.cpp', 'const char* LabelOf(int n) { return "Note"; }', 'Note'),
            ('OptiScaler/menu/FgStatusRule.h', 'Status Describe() { return { Tone::Neutral, "Frame generation off" }; }', 'Frame generation off')]:
            self.assertIn(expected, {c.source for c in find_f5_candidates(source, rel, self.rules)})

    def test_composition_templates_have_provenance_and_raw_module_fields(self):
        entries = {e['source']: e for e in json.loads((ROOT / 'Localization/composed-templates.json').read_text())}
        for label in ('Post LUT {}', 'Look input {}', 'LUT strength {}', 'Auto: {}', '{}: off, {}', 'starting: {}'):
            self.assertIn(label, entries)
            self.assertTrue(entries[label]['file'].startswith('OptiScaler/'))
        self.assertEqual(entries['{}: {} {} from {}, {}']['raw_fields'], [0, 1])

    @unittest.skipUnless(shutil.which('g++'), 'requires C++ compiler')
    def test_rendered_statuses_and_dynamic_ids(self):
        import generate_cpp
        templates = json.loads((ROOT / 'Localization/composed-templates.json').read_text())
        templates += [{'source': 'no version', 'text': '无版本信息'}, {'source': 'signed', 'text': '已签名'}, {'source': 'the plugins folder', 'text': '插件文件夹'}]
        catalog = {'entries': {str(i): {'source': e['source'], 'source_hash': str(i)} for i, e in enumerate(templates)}}
        zh = {'entries': {str(i): {'text': e['text'], 'source_hash': str(i), 'state': 'machine_translated'} for i, e in enumerate(templates)}}
        cases = [
            ("F5Low: waiting for the game's swap chain", 'F5Low：正在等待游戏交换链'),
            ('F5Low: paused', 'F5Low：已暂停'),
            ('Auto: ARRI LogC4 AWG4 (header)', '自动：ARRI LogC4 AWG4（文件头）'),
            ('Post LUT 3', '后置 LUT 3'),
            ('Look input 2', '调色输入空间 2'),
            ('LUT strength 4', 'LUT 强度 4'),
            ('XeFG: libxess_fg.dll no version from the plugins folder, signed', 'XeFG：libxess_fg.dll 无版本信息，来自 插件文件夹，已签名'),
            ("XeFG: libxess_fg.dll no version from the plugins folder, signed; the game's own no version is loaded too", 'XeFG：libxess_fg.dll 无版本信息，来自 插件文件夹，已签名；游戏自带的 无版本信息 也已加载'),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp); (out / 'generated').mkdir()
            (out / 'generated/Strings.generated.h').write_text(generate_cpp.render_header(catalog, zh))
            shutil.copyfile(ROOT / 'overlay/OptiScaler/localization/RuntimeText.h', out / 'RuntimeText.h')
            code = '#include "RuntimeText.h"\n#include <cassert>\nint main(){\n'
            for original, translated in cases:
                code += 'assert(OptiScalerCN::Runtime::Translate(' + json.dumps(original) + ') == ' + json.dumps(translated) + ');\n'
            code += '}\n'
            (out / 'test.cpp').write_text(code)
            for standard in ('c++17', 'c++20'):
                subprocess.run(['g++', '-std=' + standard, str(out / 'test.cpp'), '-o', str(out / 'test')], check=True, capture_output=True)
                subprocess.run([str(out / 'test')], check=True, capture_output=True)

    @unittest.skipUnless((ROOT / '_upstream/OptiScaler/dlssnr/DlssNr_Menu.cpp').exists(), 'requires pristine pinned source')
    def test_real_lut_stack_filename_boundaries(self):
        source = ROOT / '_upstream/OptiScaler/dlssnr/DlssNr_Menu.cpp'
        if 'static void RenderPostLutSection' not in source.read_text(encoding='utf-8-sig'):
            self.skipTest('historical baseline')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / 'OptiScaler/dlssnr/DlssNr_Menu.cpp'
            target.parent.mkdir(parents=True); shutil.copyfile(source, target)
            names = json.loads((ROOT / 'tools/f5_boundaries.json').read_text())['imgui_calls']
            localize_f5.patch_file(target, root, names)
            text = target.read_text(encoding='utf-8-sig')
            self.assertEqual(text.count('OptiScalerCN::UI::PathUtf8('), 7)
            self.assertIn('BeginComboRawPreview("Input LUT"', text)
            self.assertIn('BeginComboRawPreview(label.c_str()', text)
            self.assertIn('"Loaded: %s", OptiScalerCN::UI::Raw(status.chain.c_str())', text)
            self.assertIn('const std::string pathStr = path.string();', text)
            self.assertIn(' + "###postlut" + id;', text)
            self.assertIn('OptiScalerCN::UI::SetTooltip(enabled ?', text)

if __name__ == '__main__': unittest.main()
