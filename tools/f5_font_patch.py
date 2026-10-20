#!/usr/bin/env python3
"""Fail-closed Chinese font adapter for Optical F5Low's three-font menu.

The checked font/theme contract is fadc3bf67f6c8548e94914baec3f2e551ba8d8a4.
Only localization initialization and font selection/loading are changed. The
English HQ block and ApplyThemeFont/MonoFont bodies remain byte-for-byte intact.
"""
from __future__ import annotations

import re
from pathlib import Path

from loclib import find_matching, read_source_text, write_source_text

INCLUDE_LINE = '#include "localization/Localization.h"\n'
INITIALIZE = '    OptiScalerCN::Loc::Initialize();\n'
BEGIN = '// BEGIN OPTISCALER_CN_F5_FONTS_V1'
END = '// END OPTISCALER_CN_F5_FONTS_V1'

# Check the entire small semantic region, rather than accepting any vaguely
# similar TTF call. Whitespace/comments may change; executable tokens may not.
_EXPECTED_FONT_BLOCK = r'''
if (io.Fonts->Fonts.empty())
{
    gHackFont = gInterFont = gClassicFont = nullptr;
    if (Config::Instance()->UseHQFont.value_or_default())
    {
        ImFontAtlas* atlas = io.Fonts;
        atlas->Clear();
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
            gInterFont = atlas->AddFontFromMemoryCompressedBase85TTF(inter_compressed_compressed_data_base85,
                                                                     fontSize, &fontConfig);
        }
        io.FontDefault = gClassicFont;
    }
}'''
_EXPECTED_THEME_BODY = r'''
{
    if (ImGui::GetCurrentContext() == nullptr || gClassicFont == nullptr)
        return;
    const bool useInter = Config::Instance()->ModernTheme.value_or_default() && gInterFont != nullptr;
    ImGui::GetIO().FontDefault = useInter ? gInterFont : gClassicFont;
}'''
_BRANCH = '''bool cnFontsReady = false;
        if (OptiScalerCN::Loc::IsChineseRequested())
            cnFontsReady = OptiScalerCnLoadF5Fonts(io);

        if (!cnFontsReady && Config::Instance()->UseHQFont.value_or_default())'''

# This is deliberately kept local to menu_common.cpp: no new project item,
# translation surface, global rendering behavior, or upstream header is needed.
_HELPERS = r'''// BEGIN OPTISCALER_CN_F5_FONTS_V1
#include <exception>
#include <filesystem>
#include <fstream>
#include <limits>
#include <vector>

static std::vector<unsigned char> OptiScalerCnReadF5Font(const std::filesystem::path& path)
{
    // The filesystem overload uses a wide Windows path; no ANSI conversion.
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input)
        return {};
    const auto size = input.tellg();
    // Match ImGui's integer length and its minimum-length sanity check.
    if (size <= 100 || size > (std::numeric_limits<int>::max)())
        return {};
    std::vector<unsigned char> bytes(static_cast<std::size_t>(size));
    input.seekg(0, std::ios::beg);
    if (!input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size)))
        return {};
    return bytes;
}

static bool OptiScalerCnLoadF5Fonts(ImGuiIO& io)
{
    ImFontAtlas* atlas = io.Fonts;
    bool ready = false;
    try
    {
        // ResolveChineseFont validates every translated codepoint through FreeType.
        std::filesystem::path configuredFont;
        if (Config::Instance()->TTFFontPath.has_value())
            configuredFont = Config::Instance()->TTFFontPath.value();
        const auto cnFont = OptiScalerCN::Loc::ResolveChineseFont(configuredFont);
        auto cnBytes = cnFont.empty() ? std::vector<unsigned char>{} : OptiScalerCnReadF5Font(cnFont);
        if (!cnBytes.empty())
        {
            if (Config::Instance()->FontSize.has_value())
                fontSize = Config::Instance()->FontSize.value();

            // The shared API has a disable operation but no re-enable operation.
            // Retry the requested language after a prior failed context; rollback
            // below disables the entire translation layer if any registration fails.
            OptiScalerCN::Loc::detail::activeLanguage = "zh-CN";
            const ImWchar* ranges = OptiScalerCN::Loc::BuildGlyphRanges(atlas);
            ImFontConfig fontConfig;
            ImFontConfig mergeConfig;
            mergeConfig.MergeMode = true;
            // This vendored ImGui copies unowned input into atlas-owned storage.
            // Local vectors may therefore die, and re-init cannot invalidate data.
            mergeConfig.FontDataOwnedByAtlas = false;
            const auto mergeChinese = [&]()
            {
                return atlas->AddFontFromMemoryTTF(cnBytes.data(), static_cast<int>(cnBytes.size()),
                                                    fontSize, &mergeConfig, ranges) != nullptr;
            };
            const auto registerFonts = [&]()
            {
                // Merge immediately after each base: MergeMode targets Fonts.back().
                gHackFont = atlas->AddFontFromMemoryCompressedBase85TTF(hack_compressed_compressed_data_base85,
                                                                        fontSize, &fontConfig);
                if (gHackFont == nullptr || !mergeChinese())
                    return false;
                gClassicFont = gHackFont;
                gInterFont = atlas->AddFontFromMemoryCompressedBase85TTF(inter_compressed_compressed_data_base85,
                                                                         fontSize, &fontConfig);
                if (gInterFont == nullptr || !mergeChinese())
                    return false;
                if (!configuredFont.empty())
                {
                    auto classicBytes = OptiScalerCnReadF5Font(configuredFont);
                    if (classicBytes.empty())
                        return false;
                    ImFontConfig classicConfig;
                    classicConfig.FontDataOwnedByAtlas = false;
                    gClassicFont = atlas->AddFontFromMemoryTTF(classicBytes.data(),
                                                              static_cast<int>(classicBytes.size()), fontSize,
                                                              &classicConfig, atlas->GetGlyphRangesDefault());
                    if (gClassicFont == nullptr || !mergeChinese())
                        return false;
                }
                return true;
            };
            ready = registerFonts();
        }
    }
    catch (const std::exception&)
    {
        // A path/read failure must not leave the menu half-Chinese or stale fonts.
        ready = false;
    }
    if (ready)
    {
        io.FontDefault = gClassicFont;
        OptiScalerCN::Loc::detail::warning.clear();
        return true;
    }

    // Discard all partial merges before the original English branch runs.
    atlas->Clear();
    gHackFont = gInterFont = gClassicFont = nullptr;
    io.FontDefault = nullptr;
    OptiScalerCN::Loc::DisableChineseBecauseFontMissing();
    return false;
}
// END OPTISCALER_CN_F5_FONTS_V1

'''

_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
                    r'[A-Za-z_]\w*|\d+(?:\.\d*)?[A-Za-z]*|::|->|&&|\|\||==|!=|[^\s]', re.S)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(m.group() for m in _TOKEN.finditer(text) if not m.group().startswith(('//', '/*')))


def _pattern(text: str) -> str:
    return r'\s*'.join(re.escape(token) for token in _tokens(text))


def _one(pattern: str, text: str, label: str, flags: int = 0) -> re.Match:
    matches = list(re.finditer(pattern, text, flags))
    if len(matches) != 1:
        raise RuntimeError(f'integration conflict: F5 {label} must occur exactly once')
    return matches[0]


def _body(text: str, anchor: re.Match, label: str) -> tuple[int, int]:
    start = text.find('{', anchor.start(), anchor.end())
    if start < 0:
        after = re.match(r'\s*\{', text[anchor.end():])
        if not after:
            raise RuntimeError(f'integration conflict: F5 {label} body missing')
        start = anchor.end() + after.end() - 1
    end = find_matching(text, start, '{', '}')
    if end < 0:
        raise RuntimeError(f'integration conflict: F5 {label} body unbalanced')
    return start, end + 1


def patch_font_and_init(path: Path) -> None:
    """Patch one known F5 menu atomically in memory, or refuse without writing."""
    text, encoding = read_source_text(path)
    include = _one(r'^\s*#include\s+"menu_common\.h"[^\S\n]*\n', text, 'menu_common.h include', re.M)
    init = _one(_pattern('void MenuCommon::Init(HWND InHwnd, bool isUWP)') + r'\s*\{', text, 'Init')
    init_start, init_end = _body(text, init, 'Init')
    font = _one(_pattern('if (io.Fonts->Fonts.empty())'), text, 'empty font atlas gate')
    font_start, font_end = _body(text, font, 'font-loading')
    if not (init_start < font.start() < font_end <= init_end):
        raise RuntimeError('integration conflict: F5 font-loading block moved outside Init')

    for name in ('gHackFont', 'gInterFont', 'gClassicFont'):
        _one(_pattern(f'static ImFont* {name} = nullptr;'), text, name)
    theme = _one(_pattern('void MenuCommon::ApplyThemeFont()') + r'\s*\{', text, 'ApplyThemeFont')
    theme_start, theme_end = _body(text, theme, 'ApplyThemeFont')
    if _tokens(text[theme_start:theme_end]) != _tokens(_EXPECTED_THEME_BODY):
        raise RuntimeError('integration conflict: F5 theme font selection changed')
    mono = _one(_pattern('ImFont* MenuStyle::MonoFont()') + r'\s*\{', text, 'MonoFont')
    mono_start, mono_end = _body(text, mono, 'MonoFont')
    if _tokens(text[mono_start:mono_end]) != _tokens('{ return gHackFont; }'):
        raise RuntimeError('integration conflict: F5 monospaced font selection changed')
    _one(_pattern('ApplyThemeFont();'), text[init_start:init_end], 'Init ApplyThemeFont call')

    patched = BEGIN in text or END in text
    expected = _EXPECTED_FONT_BLOCK
    if patched:
        if text.count(BEGIN) != 1 or text.count(END) != 1 or text.count(_HELPERS) != 1:
            raise RuntimeError('integration conflict: F5 font helper is partial or modified')
        expected = expected.replace('if (Config::Instance()->UseHQFont.value_or_default())', _BRANCH)
    elif 'OptiScalerCnLoadF5Fonts' in text or 'cnFontsReady' in text:
        raise RuntimeError('integration conflict: F5 font helper name collision or partial patch')
    actual_block = text[font.start():font_end]
    if _tokens(actual_block) != _tokens(expected):
        raise RuntimeError('integration conflict: F5 font-loading block changed; refusing unsafe release')

    include_count = text.count(INCLUDE_LINE.strip())
    initialize_count = text.count('OptiScalerCN::Loc::Initialize();')
    if include_count > 1 or initialize_count > 1:
        raise RuntimeError('integration conflict: F5 localization initialization is ambiguous')
    if initialize_count and 'OptiScalerCN::Loc::Initialize();' not in text[init_start:font.start()]:
        raise RuntimeError('integration conflict: F5 localization initialization moved')
    if patched:
        if include_count != 1 or initialize_count != 1:
            raise RuntimeError('integration conflict: F5 localization patch is incomplete')
        return

    gate = _one(_pattern('if (Config::Instance()->UseHQFont.value_or_default())'), actual_block, 'HQ font gate')
    replacement = actual_block[:gate.start()] + _BRANCH + actual_block[gate.end():]
    changes = [(font.start(), font_end, replacement), (init.start(), init.start(), _HELPERS)]
    if not initialize_count:
        changes.append((init_start + 1, init_start + 1, '\n' + INITIALIZE.rstrip('\n')))
    if not include_count:
        changes.append((include.end(), include.end(), INCLUDE_LINE))
    for start, end, replacement in sorted(changes, reverse=True):
        text = text[:start] + replacement + text[end:]
    write_source_text(path, text, encoding)
