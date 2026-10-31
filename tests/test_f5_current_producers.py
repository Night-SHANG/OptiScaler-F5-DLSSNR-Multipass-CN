"""New 0.1.35 UI producers remain catalogued without changing their storage."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from f5_scan import find_f5_candidates

class CurrentProducerTests(unittest.TestCase):
    def test_flow_debug_view_arrays(self):
        text = 'inline const char* kNames[] = {"Motion arrows"};'
        found = find_f5_candidates(text, 'OptiScaler/native/FlowDebugViews.h', {})
        self.assertIn('Motion arrows', [x.source for x in found])

    def test_plugin_status_and_error_functions_only(self):
        text = 'inline auto ErrorText(int n) { return "access denied"; }\ninline auto AsiRow() { return "loaded late"; }\nconst char* unrelated = "internal token";'
        found = find_f5_candidates(text, 'OptiScaler/plugins/PluginsView.h', {})
        self.assertEqual({'access denied', 'loaded late'}, {x.source for x in found})

    def test_plugin_wide_states_reach_display_catalog(self):
        text = 'inline const wchar_t* StateText(int n) { return L"blocked"; }'
        found = find_f5_candidates(text, 'OptiScaler/plugins/PluginRegistry.h', {})
        self.assertEqual({'blocked'}, {x.source for x in found})

    def test_plugin_loader_table_tooltips(self):
        text = 'const Switch switches[] = {{Plugins::kLoaderSpecialK, &option, "Loads SpecialK64.dll"}};'
        found = find_f5_candidates(text, 'OptiScaler/menu/PluginsPage.cpp', {})
        self.assertEqual({'Loads SpecialK64.dll'}, {x.source for x in found})

    def test_moved_mfg_failure_assignments(self):
        text = 'report.failure = "no kernel containers"; LOG_INFO("diagnostic log");'
        found = find_f5_candidates(text, 'OptiScaler/framegen/mfgunlock/MfgUnlock.cpp', {})
        self.assertEqual({'no kernel containers'}, {x.source for x in found})

    def test_exposure_auto_phase_and_status_producers(self):
        text = 'const char* PhaseName(int p) { return "watching"; } std::string AutoStatus() { return "searching"; }'
        found = find_f5_candidates(text, 'OptiScaler/dlssnr/DlssNr_ExposureAutoScan.cpp', {})
        self.assertEqual({'watching', 'searching'}, {x.source for x in found})

    def test_hdr_status_reason_functions(self):
        for file, function in [('SdrToHdr_Status.h', 'StatusLine'), ('SdrToHdr_Common.h', 'ReasonText')]:
            text = 'inline auto ' + function + '() { return "HDR output: active"; }'
            found = find_f5_candidates(text, 'OptiScaler/output/' + file, {})
            self.assertEqual({'HDR output: active'}, {x.source for x in found})

    def test_shared_preview_error_chain(self):
        for file in ('DebugPreviewDx11.h', 'DebugPreviewVk.h', 'SharedFrame.cpp', 'SharedFrameVk.cpp'):
            found = find_f5_candidates('_error = "copy failed";', 'OptiScaler/native/' + file, {})
            self.assertEqual({'copy failed'}, {x.source for x in found})

    def test_superior_giveup_and_status(self):
        text = 'GiveUp("private DLSS unavailable"); Say("waiting for submission");'
        found = find_f5_candidates(text, 'OptiScaler/shaders/dlssnr/superior/Pipeline.inl', {})
        self.assertEqual({'private DLSS unavailable', 'waiting for submission'}, {x.source for x in found})

    def test_vkinterop_error_out_parameter(self):
        text = 'error = "Vulkan extension missing";'
        found = find_f5_candidates(text, 'OptiScaler/native/SharedFrameVk.cpp', {})
        self.assertEqual({'Vulkan extension missing'}, {x.source for x in found})
        self.assertFalse(find_f5_candidates(text, 'OptiScaler/native/SharedFrame.cpp', {}))

    def test_mfg_status_not_log(self):
        text = 'inline auto FormatStatus() { return "waiting for a provider"; }\ninline auto LogStatus() { return "internal log"; }'
        found = find_f5_candidates(text, 'OptiScaler/framegen/mfgunlock/Status.h', {})
        self.assertEqual({'waiting for a provider'}, {x.source for x in found})

if __name__ == '__main__': unittest.main()

class CurrentContractTests(unittest.TestCase):
    def test_new_contract_is_exact_and_preserves_historical_evidence(self):
        import json
        from f5_upstream_contract import load_contract
        root = Path(__file__).resolve().parents[1]
        new = load_contract(root / 'upstream-contract.json')
        old = load_contract(root / 'audit/v0.1.32/upstream-contract.json')
        self.assertEqual(new['baseline_commit'], '4d72d53e521b34a5cda9dd4f63ee7f4cd0438035')
        self.assertEqual(old['baseline_commit'], 'fadc3bf67f6c8548e94914baec3f2e551ba8d8a4')
        self.assertEqual(new['gitlinks'], old['gitlinks'])
        self.assertTrue(all(not r['mutable_literal_ordinals'] for r in new['audited_sources'].values()))
        self.assertEqual(new['protected_files']['package_release.ps1']['sha256'], 'cc274ff0d11ace00172b49a5330d2aa648dd5952c25ba877e2c71c9acf369bcc')
        self.assertEqual(new['protected_files']['OptiScaler/OptiScaler.vcxproj']['sha256'], 'c8040f6dd9340d9a7e5cd5ced7f0d922e25e31b78b3a2ab50ee7fdc8cb8d9744')
