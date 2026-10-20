import json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from loclib import extract_string_expression, find_candidates, format_tokens, printf_tokens, key_for_source

RULES = json.loads((ROOT / 'Localization' / 'scanner-rules.json').read_text(encoding='utf-8'))

class LoclibTests(unittest.TestCase):
    def test_concatenated_cpp_string_and_escapes(self):
        self.assertEqual(extract_string_expression('"Hello "  u8"world\\n"'), 'Hello world\n')

    def test_direct_imgui_call_is_found(self):
        text = 'if (ImGui::Button("Apply##main")) {}\n'
        got = find_candidates(text, 'OptiScaler/menu/sample.cpp', RULES)
        self.assertEqual([(x.source, x.callee, x.rewrite) for x in got], [('Apply##main', 'ImGui::Button', True)])

    def test_comments_do_not_create_candidates(self):
        text = '// ImGui::Button("Not UI")\n/* ImGui::Text("No") */\n'
        self.assertEqual(find_candidates(text, 'OptiScaler/menu/sample.cpp', RULES), [])


    def test_visible_on_off_statuses_are_localizable(self):
        text = 'ImGui::Text("ON"); ImGui::Text("OFF");\n'
        got = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        self.assertEqual([x.source for x in got], ['ON','OFF'])

    def test_all_caps_visible_ui_is_not_dropped(self):
        text = 'ImGui::Text("DEFAULT");\n'
        got = find_candidates(text, 'OptiScaler/menu/sample.cpp', RULES)
        self.assertEqual([x.source for x in got], ['DEFAULT'])

    def test_scoped_strfmt_is_catalogued_only_in_menu(self):
        text = 'auto label = StrFmt("Disable##%d", id);\n'
        menu = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        core = find_candidates(text, 'OptiScaler/core/something.cpp', RULES)
        self.assertEqual([x.source for x in menu], ['Disable##%d'])
        self.assertEqual(core, [])


    def test_ui_printf_vararg_string_literals_are_catalogued(self):
        text = 'ImGui::Text("%08x, %s", id, enabled ? "Active" : "Passive");\n'
        got = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        sources = [x.source for x in got]
        self.assertIn('Active', sources)
        self.assertIn('Passive', sources)

    def test_menu_option_set_disabled_reason_is_catalogued(self):
        text = 'options[i].set_disabled(true, "Unsupported API");\n'
        got = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        self.assertEqual([x.source for x in got], ['Unsupported API'])

    def test_flag_definition_container_is_catalogued(self):
        text = 'static std::vector<FlagDefinition> flags = { { "FLAG", 1, "Enable anti-ghosting correction" } };\n'
        got = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        self.assertIn('Enable anti-ghosting correction', [x.source for x in got])

    def test_menu_option_label_assignment_is_catalogued(self):
        text = 'options[index].label = "FSR3-MFG via DLSS Enabler";\n'
        got = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        self.assertEqual([x.source for x in got], ['FSR3-MFG via DLSS Enabler'])


    def test_menu_c_string_array_entries_are_catalogued_and_rewritable(self):
        text = 'static const char* colorSpaces[] = { "Linear", "Non-Linear" };\n'
        got = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        self.assertEqual([x.source for x in got], ['Linear', 'Non-Linear'])
        self.assertTrue(all(x.rewrite for x in got))

    def test_api_enum_style_array_items_are_not_localized(self):
        text = 'const char* states[] = { "RENDER_TARGET", "UNORDERED_ACCESS" };\n'
        got = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        self.assertEqual(got, [])

    def test_imgui_combo_label_is_catalogued(self):
        text = 'ImGui::Combo("Input Color Space", &current, colorSpaces, 2);\n'
        got = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        self.assertEqual([x.source for x in got], ['Input Color Space'])

    def test_conditional_ui_argument_literals_are_catalogued(self):
        text = 'ScopedCollapsingHeader(useDlssd ? "Advanced DLSSD Settings" : "Advanced DLSS Settings");\n'
        got = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        self.assertEqual([x.source for x in got], ['Advanced DLSSD Settings', 'Advanced DLSS Settings'])
        self.assertTrue(all(x.rewrite for x in got))

    def test_nested_std_format_in_ui_text_argument_is_catalogued(self):
        text = 'ImGui::TextColored(color, std::format("ON {}x", count + 1).c_str());\n'
        got = find_candidates(text, 'OptiScaler/menu/menu_common.cpp', RULES)
        self.assertIn('ON {}x', [x.source for x in got])

    def test_plain_percentage_prose_is_not_printf_token(self):
        self.assertEqual(printf_tokens("~2-4% additional GPU latency reduction"), [])

    def test_printf_and_std_format_tokens(self):
        self.assertEqual(printf_tokens('FPS %6.2f / %s / %%'), ['%6.2f', '%s', '%%'])
        self.assertEqual(format_tokens('Value {} / {:.2f} / {name} / {0:04X}'), ['{}', '{:.2f}', '{name}', '{0:04X}'])

    def test_std_format_percent_prose_is_not_printf(self):
        for source in ["Detail: {:.0f}% less than the game's", "{:.0f}% lifted", "Shadows ({:.0f}% of the picture): ", "{:.0f}% darker"]:
            self.assertEqual(printf_tokens(source), [], source)
        self.assertEqual(printf_tokens('integer: % d'), ['% d'])

    def test_key_is_stable(self):
        self.assertEqual(key_for_source('Quality'), key_for_source('Quality'))
        self.assertNotEqual(key_for_source('Quality'), key_for_source('Balanced'))

if __name__ == '__main__':
    unittest.main()
