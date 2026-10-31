"""Regressions for v0.1.35 profile input and user-owned display data."""
import json
from pathlib import Path
import sys
import unittest
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import localize_f5
from ui_scan import find_ui_candidates

class NewBoundaries(unittest.TestCase):
    def test_new_input_calls_are_scanned_and_hooked(self):
        rules=json.loads((ROOT/'Localization/scanner-rules.json').read_text())
        text='ImGui::InputInt2("Depth size (0 = automatic)##depthsize", size, 0); ImGui::InputTextWithHint("##nrprofilename", "new profile name", typedName, sizeof(typedName));'
        sources={v.source for v in find_ui_candidates(text,'OptiScaler/native/NativeDriver.cpp',rules)}
        self.assertIn('Depth size (0 = automatic)##depthsize',sources)
        self.assertIn('new profile name',sources)
        self.assertIn('InputInt2',json.loads((ROOT/'tools/f5_boundaries.json').read_text())['imgui_calls'])
    def test_profile_boundary_preserves_user_data(self):
        source = 'OptiScalerCN::UI::BeginCombo("Profile##nrprofile", pick ? pick->name.c_str() : "(none saved yet)")\nOptiScalerCN::UI::Selectable(profiles[i].name.c_str(), i == selected)\nOptiScalerCN::UI::SetTooltip("Saved in %s", profiles[i].file.savedFrom.c_str())\naskName.c_str());\npick->name.c_str(), pick->file.savedFrom.c_str());'
        self.assertEqual(len(localize_f5.PROFILE_RAW_REPLACEMENTS), 5)
        changed=localize_f5.patch_profile_user_data(source)
        for before,after in localize_f5.PROFILE_RAW_REPLACEMENTS.items():
            self.assertIn(after,changed)
        self.assertIn('BeginComboRawPreview',changed)
        self.assertIn('SelectableRaw',changed)
    def test_profile_partial_upgrade_fails_closed(self):
        source='OptiScalerCN::UI::BeginCombo("Profile##nrprofile", pick ? pick->name.c_str() : "(none saved yet)")'
        with self.assertRaisesRegex(RuntimeError,'profile user-data'):
            localize_f5.patch_profile_user_data(source)
    def test_plugin_filename_and_folder_are_not_dictionary_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'OptiScaler/menu/PluginsPage.cpp'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'#include "pch.h"\nvoid f() { ImGui::TextUnformatted(row.label.c_str()); ImGui::TextDisabled("Folder: %s%s", folder.empty() ? "(not read yet)" : folder.c_str(), ""); }')
            self.assertNotIn(b'\r', path.read_bytes())  # Match audited upstream LF bytes on Windows too.
            names=json.loads((ROOT/'tools/f5_boundaries.json').read_text())['imgui_calls']
            localize_f5.patch_file(path,root,names)
            patched=path.read_text()
            self.assertIn('ImGui::TextUnformatted(row.label.c_str());',patched)
            self.assertNotIn('OptiScalerCN::UI::TextUnformatted(row.label.c_str());',patched)
            self.assertIn('OptiScalerCN::UI::Raw(folder.empty()',patched)
            self.assertIn('OptiScalerCN::UI::TextValue("(not read yet)")',patched)
    def test_old_baseline_without_profiles_unchanged(self):
        source='ImGui::Text("hello");'
        self.assertEqual(localize_f5.patch_profile_user_data(source),source)
if __name__=='__main__': unittest.main()
