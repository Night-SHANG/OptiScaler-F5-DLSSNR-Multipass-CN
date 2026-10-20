#pragma once

// Community localization layer shared by OptiScaler Chinese derivative repositories.
// Generated translations are emitted as ASCII C++ source with UTF-8 byte escapes,
// so the result is independent from the compiler/source code page.

#include <Windows.h>
#include <imgui/imgui.h>
#include <ft2build.h>
#include FT_FREETYPE_H

#include <algorithm>
#include <array>
#include <cctype>
#include <filesystem>
#include <format>
#include <fstream>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

#include "generated/Strings.generated.h"

namespace OptiScalerCN::Loc
{
namespace detail
{
inline std::once_flag initFlag;
inline std::string requestedLanguage = "zh-CN";
inline std::string activeLanguage = "zh-CN";
inline std::filesystem::path explicitFontPath;
inline std::filesystem::path moduleDir;
inline std::string warning;
inline ImVector<ImWchar> glyphRanges;
inline int moduleAnchor = 0;

inline std::string Trim(std::string s)
{
    auto notSpace = [](unsigned char c) { return !std::isspace(c); };
    s.erase(s.begin(), std::find_if(s.begin(), s.end(), notSpace));
    s.erase(std::find_if(s.rbegin(), s.rend(), notSpace).base(), s.end());
    return s;
}

inline std::filesystem::path ModuleDirectory()
{
    HMODULE module = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            reinterpret_cast<LPCWSTR>(&moduleAnchor), &module))
        return std::filesystem::current_path();

    std::wstring buffer(32768, L'\0');
    const DWORD len = GetModuleFileNameW(module, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (len == 0 || len >= buffer.size())
        return std::filesystem::current_path();
    buffer.resize(len);
    return std::filesystem::path(buffer).parent_path();
}

inline std::filesystem::path AbsoluteFromModule(std::filesystem::path path)
{
    if (path.empty()) return {};
    if (path.is_relative()) path = moduleDir / path;
    std::error_code ec;
    auto normalized = std::filesystem::weakly_canonical(path, ec);
    return ec ? path : normalized;
}

inline std::filesystem::path Existing(std::filesystem::path p)
{
    p = AbsoluteFromModule(std::move(p));
    std::error_code ec;
    return !p.empty() && std::filesystem::is_regular_file(p, ec) ? p : std::filesystem::path{};
}

inline void ReadConfig()
{
    moduleDir = ModuleDirectory();
    const auto cfg = moduleDir / L"OptiScalerCN.ini";
    std::ifstream in(cfg, std::ios::binary);
    if (!in)
        return;

    std::string line;
    bool section = false;
    while (std::getline(in, line))
    {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        const auto stripped = Trim(line);
        if (stripped.empty() || stripped[0] == ';' || stripped[0] == '#') continue;
        if (stripped.front() == '[' && stripped.back() == ']')
        {
            section = stripped == "[Localization]";
            continue;
        }
        if (!section) continue;

        const auto pos = stripped.find('=');
        if (pos == std::string::npos) continue;
        const auto key = Trim(stripped.substr(0, pos));
        const auto value = Trim(stripped.substr(pos + 1));
        if (key == "Language" && (value == "zh-CN" || value == "en-US"))
            requestedLanguage = activeLanguage = value;
        else if (key == "FontPath" && !value.empty())
            explicitFontPath = std::filesystem::u8path(value);
    }
}

inline const Generated::TranslationEntry* ByKey(std::string_view key)
{
    for (const auto& e : Generated::kTranslations)
        if (key == e.key) return &e;
    return nullptr;
}

inline const Generated::TranslationEntry* BySource(std::string_view source)
{
    for (const auto& e : Generated::kTranslations)
        if (source == e.source) return &e;
    return nullptr;
}

inline bool HasChineseTranslation(const Generated::TranslationEntry& e)
{
    return activeLanguage == "zh-CN" && e.zh != nullptr && e.zh[0] != '\0';
}

inline bool NextUtf8Codepoint(std::string_view text, std::size_t& pos, unsigned long& cp)
{
    if (pos >= text.size()) return false;
    const auto* data = reinterpret_cast<const unsigned char*>(text.data());
    const unsigned char c0 = data[pos++];
    if (c0 < 0x80) { cp = c0; return true; }

    int extra = 0;
    unsigned long value = 0;
    if ((c0 & 0xE0) == 0xC0) { extra = 1; value = c0 & 0x1F; }
    else if ((c0 & 0xF0) == 0xE0) { extra = 2; value = c0 & 0x0F; }
    else if ((c0 & 0xF8) == 0xF0) { extra = 3; value = c0 & 0x07; }
    else return false;

    if (pos + static_cast<std::size_t>(extra) > text.size()) return false;
    for (int i = 0; i < extra; ++i)
    {
        const unsigned char cx = data[pos++];
        if ((cx & 0xC0) != 0x80) return false;
        value = (value << 6) | (cx & 0x3F);
    }
    cp = value;
    return true;
}

inline bool FontCoversCurrentChinese(const std::filesystem::path& path)
{
    // FreeType is already a dependency of the official OptiScaler project. Reading
    // the file ourselves keeps Unicode Windows paths working with FT_New_Memory_Face.
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) return false;
    const auto size = input.tellg();
    if (size <= 0) return false;
    std::vector<unsigned char> bytes(static_cast<std::size_t>(size));
    input.seekg(0, std::ios::beg);
    if (!input.read(reinterpret_cast<char*>(bytes.data()), size)) return false;

    FT_Library library = nullptr;
    if (FT_Init_FreeType(&library) != 0) return false;
    FT_Face face = nullptr;
    const auto faceResult = FT_New_Memory_Face(library, bytes.data(), static_cast<FT_Long>(bytes.size()), 0, &face);
    if (faceResult != 0 || face == nullptr)
    {
        FT_Done_FreeType(library);
        return false;
    }

    bool ok = true;
    for (const auto& entry : Generated::kTranslations)
    {
        if (entry.zh == nullptr || entry.zh[0] == '\0') continue;
        std::string_view text(entry.zh);
        std::size_t pos = 0;
        while (pos < text.size())
        {
            unsigned long cp = 0;
            if (!NextUtf8Codepoint(text, pos, cp)) { ok = false; break; }
            if (cp >= 0x80 && FT_Get_Char_Index(face, static_cast<FT_ULong>(cp)) == 0)
            {
                ok = false;
                break;
            }
        }
        if (!ok) break;
    }

    FT_Done_Face(face);
    FT_Done_FreeType(library);
    return ok;
}

inline std::filesystem::path ValidFont(const std::filesystem::path& candidate)
{
    if (auto p = Existing(candidate); !p.empty() && FontCoversCurrentChinese(p)) return p;
    return {};
}

inline std::filesystem::path FindWindowsCjkFont()
{
    wchar_t windowsDir[MAX_PATH]{};
    if (!GetWindowsDirectoryW(windowsDir, MAX_PATH)) return {};
    const auto fonts = std::filesystem::path(windowsDir) / L"Fonts";

    // Prefer Simplified Chinese fonts. The final choices are broader CJK fallbacks,
    // but every candidate is validated against every codepoint actually used by the
    // current zh-CN catalog before it can be selected.
    static constexpr std::array<const wchar_t*, 12> names = {
        L"msyh.ttc", L"msyhbd.ttc", L"simhei.ttf", L"simsun.ttc", L"simsunb.ttf",
        L"Deng.ttf", L"Dengb.ttf", L"NotoSansCJK-Regular.ttc", L"SourceHanSansCN-Regular.otf",
        L"YuGothM.ttc", L"meiryo.ttc", L"msgothic.ttc"
    };
    for (const auto* name : names)
        if (auto p = ValidFont(fonts / name); !p.empty()) return p;
    return {};
}
} // namespace detail

inline void Initialize()
{
    std::call_once(detail::initFlag, [] { detail::ReadConfig(); });
}

inline bool IsChineseRequested()
{
    Initialize();
    return detail::requestedLanguage == "zh-CN";
}

inline bool IsChineseActive()
{
    Initialize();
    return detail::activeLanguage == "zh-CN";
}

inline const char* T(std::string_view key, const char* englishFallback)
{
    Initialize();
    if (detail::activeLanguage != "zh-CN") return englishFallback;
    if (const auto* e = detail::ByKey(key); e && detail::HasChineseTranslation(*e)) return e->zh;
    return englishFallback;
}

inline std::string TL(std::string_view english)
{
    Initialize();
    if (detail::activeLanguage == "zh-CN")
        if (const auto* e = detail::BySource(english); e && detail::HasChineseTranslation(*e)) return e->zh;
    return std::string(english);
}

template <typename... Args>
inline std::string F(std::string_view key, const char* englishFallback, Args&&... args)
{
    // std::format requires a compile-time format string on current MSVC.
    // Localization is runtime data, so translated format strings use vformat.
    return std::vformat(T(key, englishFallback), std::make_format_args(args...));
}

inline const ImWchar* BuildGlyphRanges(ImFontAtlas* atlas)
{
    Initialize();
    detail::glyphRanges.clear();
    ImFontGlyphRangesBuilder builder;
    builder.AddRanges(atlas->GetGlyphRangesDefault());
    if (detail::activeLanguage == "zh-CN")
        for (const auto& e : Generated::kTranslations)
            if (detail::HasChineseTranslation(e)) builder.AddText(e.zh);
    builder.BuildRanges(&detail::glyphRanges);
    return detail::glyphRanges.Data;
}

inline std::filesystem::path ResolveChineseFont(const std::filesystem::path& upstreamConfiguredFont = {})
{
    Initialize();
    if (auto p = detail::ValidFont(detail::explicitFontPath); !p.empty()) return p;
    if (auto p = detail::ValidFont(upstreamConfiguredFont); !p.empty()) return p;
    return detail::FindWindowsCjkFont();
}

inline std::string PathUtf8(const std::filesystem::path& path)
{
    const auto& w = path.wstring();
    if (w.empty()) return {};
    const int needed = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), static_cast<int>(w.size()), nullptr, 0, nullptr, nullptr);
    if (needed <= 0) return {};
    std::string result(static_cast<std::size_t>(needed), '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), static_cast<int>(w.size()), result.data(), needed, nullptr, nullptr);
    return result;
}

inline void DisableChineseBecauseFontMissing()
{
    Initialize();
    detail::activeLanguage = "en-US";
    detail::warning = "zh-CN requested but no font covering the current Chinese catalog was found; English fallback is active.";
}

inline std::string_view Warning()
{
    Initialize();
    return detail::warning;
}

} // namespace OptiScalerCN::Loc
