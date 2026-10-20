"""F5 font adapter contract and compiled control-flow regression tests.

The compiled harness substitutes only platform/ImGui/locale dependencies. It tests
our emitted C++ branches and lifetime contract; it is not a Windows rendering test.
"""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

# Recorded from Optical F5Low fadc3bf67f6c8548e94914baec3f2e551ba8d8a4.
FONT_BLOCK = '''    if (io.Fonts->Fonts.empty())
    {
        gHackFont = gInterFont = gClassicFont = nullptr;

        if (Config::Instance()->UseHQFont.value_or_default())
        {
            ImFontAtlas* atlas = io.Fonts;
            atlas->Clear();

            // This automatically becomes the next default font
            ImFontConfig fontConfig;

            if (Config::Instance()->FontSize.has_value())
                fontSize = Config::Instance()->FontSize.value();

            if (Config::Instance()->TTFFontPath.has_value())
            {
                gClassicFont =
                    atlas->AddFontFromFileTTF(wstring_to_string(Config::Instance()->TTFFontPath.value()).c_str(),
                                              fontSize, &fontConfig, io.Fonts->GetGlyphRangesDefault());
            }
            else
            {
                gHackFont = atlas->AddFontFromMemoryCompressedBase85TTF(hack_compressed_compressed_data_base85,
                                                                        fontSize, &fontConfig);
                gClassicFont = gHackFont;

                // Modern style text; Hack stays loaded for the live numbers.
                gInterFont = atlas->AddFontFromMemoryCompressedBase85TTF(inter_compressed_compressed_data_base85,
                                                                         fontSize, &fontConfig);
            }

            io.FontDefault = gClassicFont;
        }
    }'''

THEME = '''void MenuCommon::ApplyThemeFont()
{
    if (ImGui::GetCurrentContext() == nullptr || gClassicFont == nullptr)
        return;

    const bool useInter = Config::Instance()->ModernTheme.value_or_default() && gInterFont != nullptr;
    ImGui::GetIO().FontDefault = useInter ? gInterFont : gClassicFont;
}'''

MENU = '''#include "pch.h"
#include "menu_common.h"

static float fontSize = 14.0f;
static ImFont* gHackFont = nullptr;
static ImFont* gInterFont = nullptr;
static ImFont* gClassicFont = nullptr;
ImFont* MenuStyle::MonoFont() { return gHackFont; }
''' + THEME + '''
void MenuCommon::Init(HWND InHwnd, bool isUWP)
{
    ImGuiIO& io = ImGui::GetIO();
''' + FONT_BLOCK + '''
    ApplyThemeFont();
}
'''

FAKE_DEPENDENCIES = r'''
#pragma once
#include <cassert>
#include <filesystem>
#include <fstream>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>
using HWND = void*;
using ImWchar = unsigned short;
struct ImFont { int base; bool chinese = false; };
struct ImFontConfig { bool FontDataOwnedByAtlas = true; bool MergeMode = false; };
static const char* hack_compressed_compressed_data_base85 = "hack";
static const char* inter_compressed_compressed_data_base85 = "inter";
static int failAt = -1;
static int loadCalls = 0;
struct ImFontAtlas {
    std::vector<ImFont*> Fonts;
    std::vector<std::vector<unsigned char>> retained;
    ~ImFontAtlas() { Clear(); }
    void Clear() { for (auto* f : Fonts) delete f; Fonts.clear(); retained.clear(); }
    const ImWchar* GetGlyphRangesDefault() { static ImWchar r[] = {32, 127, 0}; return r; }
    ImFont* AddFontFromMemoryCompressedBase85TTF(const char* name, float, const ImFontConfig*) {
        if (++loadCalls == failAt) return nullptr;
        auto* f = new ImFont{std::string(name) == "hack" ? 1 : 2};
        Fonts.push_back(f); return f;
    }
    ImFont* AddFontFromFileTTF(const char*, float, const ImFontConfig*, const ImWchar*) {
        if (++loadCalls == failAt) return nullptr;
        auto* f = new ImFont{3}; Fonts.push_back(f); return f;
    }
    ImFont* AddFontFromMemoryTTF(void* data, int size, float, const ImFontConfig* cfg, const ImWchar* ranges) {
        assert(size > 100);
        assert(!cfg->FontDataOwnedByAtlas); // this ImGui revision copies unowned input
        if (++loadCalls == failAt) return nullptr;
        auto* b = static_cast<unsigned char*>(data);
        if (b[0] != 66) return nullptr;
        retained.emplace_back(b, b + size);
        ImFont* f;
        if (cfg->MergeMode) { assert(!Fonts.empty()); f = Fonts.back(); }
        else { f = new ImFont{3}; Fonts.push_back(f); }
        if (ranges && ranges[2] == 0x4e2d) f->chinese = true;
        return f;
    }
};
struct ImGuiIO { ImFontAtlas* Fonts; ImFont* FontDefault = nullptr; };
namespace ImGui {
inline ImGuiIO* io = nullptr;
inline ImGuiIO& GetIO() { return *io; }
inline void* GetCurrentContext() { return io; }
}
struct BoolSetting { bool value = false; bool value_or_default() const { return value; } };
struct Config {
    BoolSetting UseHQFont, ModernTheme;
    std::optional<float> FontSize;
    std::optional<std::filesystem::path> TTFFontPath;
    static Config* Instance() { static Config c; return &c; }
};
inline std::string wstring_to_string(const std::filesystem::path& p) { return p.string(); }
struct MenuStyle { static ImFont* MonoFont(); };
struct MenuCommon { static void Init(HWND, bool); static void ApplyThemeFont(); };
namespace OptiScalerCN::Loc {
namespace detail { inline std::string activeLanguage = "zh-CN"; inline std::string warning; }
inline bool requested = true;
inline std::filesystem::path candidate;
inline bool throwResolve = false;
inline int initializeCalls = 0;
inline void Initialize() { ++initializeCalls; }
inline bool IsChineseRequested() { return requested; }
inline bool IsChineseActive() { return detail::activeLanguage == "zh-CN"; }
inline std::filesystem::path ResolveChineseFont(const std::filesystem::path&) {
    if (throwResolve) throw std::runtime_error("simulated filesystem failure");
    return candidate;
}
inline const ImWchar* BuildGlyphRanges(ImFontAtlas* atlas) {
    static ImWchar cn[] = {32, 127, 0x4e2d, 0x4e2d, 0};
    return IsChineseActive() ? cn : atlas->GetGlyphRangesDefault();
}
inline void DisableChineseBecauseFontMissing() { detail::activeLanguage = "en-US"; detail::warning = "missing"; }
inline const char* T(const char*, const char* en) { return IsChineseActive() ? "Chinese" : en; }
}
'''

RUNTIME = r'''
static void run(bool requested, bool hq, bool modern, bool configured, const std::filesystem::path& font,
                int fail, bool expectChinese) {
    using namespace OptiScalerCN::Loc;
    ImFontAtlas atlas;
    ImGuiIO io{&atlas}; ImGui::io = &io;
    auto* config = Config::Instance();
    config->UseHQFont.value = hq;
    config->ModernTheme.value = modern;
    config->TTFFontPath = configured ? std::optional<std::filesystem::path>(font) : std::nullopt;
    config->FontSize = 17.f;
    OptiScalerCN::Loc::requested = requested;
    candidate = font;
    failAt = fail; loadCalls = 0;
    if (!requested) detail::activeLanguage = "en-US";
    MenuCommon::Init(nullptr, false);
    assert(IsChineseActive() == expectChinese);
    if (expectChinese) {
        assert(gHackFont && gInterFont && gClassicFont);
        assert(gHackFont->chinese && gInterFont->chinese && gClassicFont->chinese);
        assert(gHackFont->base == 1 && gInterFont->base == 2);
        assert(gClassicFont->base == (configured ? 3 : 1));
        assert(MenuStyle::MonoFont() == gHackFont);
        assert(io.FontDefault == (modern ? gInterFont : gClassicFont));
        config->ModernTheme.value = !modern; MenuCommon::ApplyThemeFont();
        assert(io.FontDefault == (modern ? gClassicFont : gInterFont));
        assert(detail::warning.empty());
        assert(atlas.Fonts.size() == (configured ? 3u : 2u));
        // Initializing the same atlas again must not replace/re-add fonts.
        auto* before = gHackFont;
        auto count = atlas.Fonts.size();
        MenuCommon::Init(nullptr, false);
        assert(gHackFont == before && count == atlas.Fonts.size());
        // The local file buffers are gone, but atlas-owned copies remain valid.
        for (const auto& bytes : atlas.retained) assert(bytes.size() == 128 && bytes[0] == 66);
    } else {
        assert(std::string(T("any", "English")) == "English");
        if (requested) assert(!detail::warning.empty());
        if (!hq) {
            assert(atlas.Fonts.empty());
            assert(!gHackFont && !gInterFont && !gClassicFont && !io.FontDefault);
        } else if (configured) {
            assert(!gHackFont && !gInterFont && gClassicFont && io.FontDefault == gClassicFont);
        } else {
            assert(gHackFont && gClassicFont == gHackFont && gInterFont);
            assert(!gHackFont->chinese && !gInterFont->chinese);
            assert(io.FontDefault == (modern ? gInterFont : gClassicFont));
            assert(atlas.Fonts.size() == 2);
        }
    }
    ImGui::io = nullptr;
}
int main(int argc, char** argv) {
    assert(argc == 3);
    std::filesystem::path valid = std::filesystem::u8path(argv[1]);
    std::filesystem::path invalid = std::filesystem::u8path(argv[2]);
    for (bool hq : {false, true}) for (bool modern : {false, true}) {
        run(true, hq, modern, false, valid, -1, true);
        run(true, hq, modern, true, valid, -1, true);
        run(false, hq, modern, false, valid, -1, false);
        run(false, hq, modern, true, valid, -1, false);
        run(true, hq, modern, false, {}, -1, false);
        run(true, hq, modern, false, invalid, -1, false);
        OptiScalerCN::Loc::throwResolve = true;
        run(true, hq, modern, false, valid, -1, false);
        OptiScalerCN::Loc::throwResolve = false;
        // Every partially registered font stage must roll back before fallback.
        for (int fail = 1; fail <= 4; ++fail) run(true, hq, modern, false, valid, fail, false);
        for (int fail = 1; fail <= 6; ++fail) run(true, hq, modern, true, valid, fail, false);
        // A previous fallback must not leave Chinese disabled after re-init.
        run(true, hq, modern, false, valid, -1, true);
    }
}
'''


class F5FontPatchTests(unittest.TestCase):
    def adapter(self):
        spec = importlib.util.find_spec('f5_font_patch')
        self.assertIsNotNone(spec, 'the independent F5 adapter must exist')
        import f5_font_patch
        return f5_font_patch

    def patch(self, text=MENU, encoding='utf-8'):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / 'menu_common.cpp'
        path.write_bytes(text.encode(encoding))
        self.adapter().patch_font_and_init(path)
        return path

    def test_f5_font_path_is_inserted_before_hq_gate(self):
        out = self.patch().read_text()
        self.assertIn('OptiScalerCN::Loc::Initialize();', out)
        init = out[out.index('void MenuCommon::Init'):]
        self.assertLess(init.index('IsChineseRequested()'), init.index('UseHQFont.value_or_default()'))
        self.assertIn('FontDataOwnedByAtlas = false', out)
        self.assertIn('MergeMode = true', out)
        self.assertIn('std::ifstream', out)
        self.assertIn('BuildGlyphRanges(atlas)', out)
        self.assertIn('DisableChineseBecauseFontMissing()', out)

    def test_english_font_loading_and_theme_function_are_preserved(self):
        out = self.patch().read_text()
        original_hq_body = FONT_BLOCK[FONT_BLOCK.index('        {', FONT_BLOCK.index('UseHQFont')):FONT_BLOCK.rfind('\n    }')]
        self.assertIn(original_hq_body, out)
        self.assertIn(THEME, out)
        self.assertIn('ImFont* MenuStyle::MonoFont() { return gHackFont; }', out)

    def test_patch_is_idempotent_and_preserves_utf8_bom(self):
        path = self.patch(encoding='utf-8-sig')
        once = path.read_bytes()
        self.assertTrue(once.startswith(b'\xef\xbb\xbf'))
        self.adapter().patch_font_and_init(path)
        self.assertEqual(path.read_bytes(), once)
        self.assertEqual(once.count(b'OptiScalerCN::Loc::Initialize();'), 1)

    def test_whitespace_only_upstream_formatting_is_accepted(self):
        source = MENU.replace('if (io.Fonts->Fonts.empty())', 'if ( io.Fonts -> Fonts.empty ( ) )')
        path = self.patch(source)
        self.adapter().patch_font_and_init(path)
        self.assertIn('IsChineseRequested', path.read_text())

    def test_legacy_source_encoding_is_preserved(self):
        path = self.patch(MENU + '// Legacy dash: \u2014\n', 'cp1252')
        self.assertTrue(path.read_bytes().endswith(b'// Legacy dash: \x97\n'))

    def test_semantic_anchor_drift_fails_without_writing(self):
        changes = [
            ('#include "menu_common.h"', '#include "other.h"'),
            ('void MenuCommon::Init(HWND InHwnd, bool isUWP)', 'void MenuCommon::Init(void* other)'),
            ('if (io.Fonts->Fonts.empty())', 'if (io.Fonts->Fonts.Size == 0)'),
            ('UseHQFont.value_or_default()', 'SomeNewFontFlag.value_or_default()'),
            ('gClassicFont = gHackFont;', 'gClassicFont = nullptr;'),
            ('static ImFont* gInterFont = nullptr;', 'static ImFont* gModernFont = nullptr;'),
            ('useInter ? gInterFont : gClassicFont', 'gClassicFont'),
            ('MonoFont() { return gHackFont;', 'MonoFont() { return gClassicFont;'),
            ('atlas->Clear();', 'atlas->Clear();\n            newFontBehavior();'),
            ('AddFontFromFileTTF', 'NewFontLoader'),
        ]
        for old, new in changes:
            with self.subTest(anchor=old), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'menu_common.cpp'
                raw = MENU.replace(old, new).encode()
                path.write_bytes(raw)
                with self.assertRaisesRegex(RuntimeError, 'integration conflict'):
                    self.adapter().patch_font_and_init(path)
                self.assertEqual(path.read_bytes(), raw)

    def test_ambiguous_and_partial_patches_fail_closed(self):
        for source in [MENU + FONT_BLOCK, MENU.replace(THEME, THEME + '\n' + THEME)]:
            with self.subTest(kind=source[-60:]), tempfile.TemporaryDirectory() as td:
                path = Path(td) / 'menu.cpp'; path.write_text(source)
                with self.assertRaisesRegex(RuntimeError, 'integration conflict'):
                    self.adapter().patch_font_and_init(path)
        path = self.patch()
        raw = path.read_text().replace('MergeMode = true', 'MergeMode = false')
        path.write_text(raw)
        with self.assertRaisesRegex(RuntimeError, 'integration conflict'):
            self.adapter().patch_font_and_init(path)
        self.assertEqual(path.read_text(), raw)

    @unittest.skipUnless(shutil.which('g++'), 'g++ is required for the compiled adapter harness')
    def test_generated_cpp_font_matrix_and_reinitialization(self):
        path = self.patch()
        td = path.parent
        (td / 'pch.h').write_text(FAKE_DEPENDENCIES)
        (td / 'menu_common.h').write_text('#pragma once\n')
        (td / 'localization').mkdir()
        (td / 'localization' / 'Localization.h').write_text('#pragma once\n')
        (td / 'runner.cpp').write_text('#include "menu_common.cpp"\n' + RUNTIME)
        font = td / '\u5b57\u4f53 \u6d4b\u8bd5.ttf'
        font.write_bytes(b'B' * 128)
        invalid = td / 'invalid.ttf'; invalid.write_bytes(b'bad')
        compile_result = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                                         '-I', str(td), str(td / 'runner.cpp'), '-o', str(td / 'runner')],
                                        capture_output=True, text=True)
        self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
        result = subprocess.run([str(td / 'runner'), str(font), str(invalid)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
