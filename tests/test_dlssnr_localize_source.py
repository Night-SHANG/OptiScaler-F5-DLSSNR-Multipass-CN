import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import localize_source

RULES = json.loads((ROOT / "Localization" / "scanner-rules.json").read_text(encoding="utf-8"))


class DlssNrLocalizeSourceTests(unittest.TestCase):
    def test_deferred_slider_call_and_logic_comparison_use_same_translation(self):
        source = '''
        static bool DeferredSlider(const char* label) {
            if (std::strcmp(label, "Intensity") == 0) return true;
            return false;
        }
        void Render() {
            DeferredSlider("Intensity", &config->DlssNrIntensity, 0.0f, 2.0f, 1.0f);
        }
        '''
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DlssNr_MenuModel.cpp"
            path.write_text(source, encoding="utf-8")
            count = localize_source.instrument_file(
                path,
                "OptiScaler/dlssnr/DlssNr_MenuModel.cpp",
                RULES,
                {"Intensity": "ui.test.intensity"},
            )
            patched = path.read_text(encoding="utf-8")
        translated = 'OptiScalerCN::Loc::T("ui.test.intensity", "Intensity")'
        self.assertEqual(count, 2)
        self.assertIn(f'DeferredSlider({translated},', patched)
        self.assertIn(f'std::strcmp(label, {translated})', patched)

    def test_pipeline_dynamic_fragments_and_return_labels_are_instrumented(self):
        source = '''
        inline const char* SectionName(Section section) {
            if (section == Section::Input) return "Input";
            return "Model passes";
        }
        void Draw() {
            add(0, 0, "Prepare NR input", "HDR / exposure / " + std::to_string(scalePercent) + "%");
            add(0, 1, "NR model", std::to_string(passes) + (passes == 1 ? " pass" : " passes"));
        }
        '''
        mapping = {
            "Input": "ui.test.input",
            "Model passes": "ui.test.model_passes",
            "Prepare NR input": "ui.test.prepare",
            "HDR / exposure / ": "ui.test.hdr",
            "NR model": "ui.test.model",
            " pass": "ui.test.pass_one",
            " passes": "ui.test.pass_many",
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DlssNr_PipelineUi.h"
            path.write_text(source, encoding="utf-8")
            count = localize_source.instrument_file(
                path,
                "OptiScaler/dlssnr/DlssNr_PipelineUi.h",
                RULES,
                mapping,
            )
            patched = path.read_text(encoding="utf-8")
        self.assertEqual(count, len(mapping))
        for english, key in mapping.items():
            self.assertIn(f'OptiScalerCN::Loc::T("{key}", "{english}")', patched)


if __name__ == "__main__":
    unittest.main()
