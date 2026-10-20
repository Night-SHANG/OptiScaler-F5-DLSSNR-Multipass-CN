#pragma once
#include "Localization.h"
#include "RuntimeText.h"
#include <imgui/imgui_internal.h>
#include <tuple>
#include <type_traits>
#include <utility>
#include <cstring>
#include <filesystem>

// This namespace only adapts display calls. Configuration, source literals,
// branches, arrays, numeric values and callback indices stay upstream-owned.
namespace OptiScalerCN::UI
{
inline std::string TextValue(const char* source)
{
    if (!source) return {};
    return Loc::IsChineseActive() ? Runtime::Translate(source) : std::string(source);
}
inline std::string LabelValue(const char* source)
{
    if (!source) return {};
    if (!Loc::IsChineseActive()) return source;
    const std::string_view original(source);
    std::string translated = TextValue(source);
    const auto suffix = original.find("##");
    if (translated == original && suffix != std::string_view::npos && suffix > 0)
    {
        const auto visible = original.substr(0, suffix);
        auto candidate = TextValue(std::string(visible).c_str());
        if (candidate != visible) translated = std::move(candidate);
        else
        {
            const auto fragment = original.substr(0, suffix + 2);
            candidate = TextValue(std::string(fragment).c_str());
            if (candidate != fragment) translated = std::move(candidate);
        }
    }
    return Runtime::Label(source, translated);
}
// Raw data (filenames, paths, user-provided LUT lines) is never a translation key.
inline std::string PathUtf8(const std::filesystem::path& path)
{
    const auto bytes = path.u8string();
    return std::string(reinterpret_cast<const char*>(bytes.data()), bytes.size());
}
struct RawText { const char* value; };
inline RawText Raw(const char* value) { return { value }; }
// CompareWords joins complete clauses using top-level commas. Its clauses may
// themselves contain a comma inside parentheses; generic format matching cannot
// safely infer that grammar. Only this producer's display call uses this adapter.
inline std::string ComparisonValue(std::string_view source)
{
    if (!Loc::IsChineseActive()) return std::string(source);
    std::string result;
    size_t start = 0;
    unsigned nesting = 0;
    for (size_t pos = 0; pos < source.size(); ++pos)
    {
        if (source[pos] == '(') ++nesting;
        else if (source[pos] == ')' && nesting) --nesting;
        else if (!nesting && source[pos] == ',' && pos + 1 < source.size() && source[pos + 1] == ' ')
        {
            if (!result.empty()) result += "\357\274\233";
            result += Runtime::Translate(source.substr(start, pos - start));
            start = pos + 2;
            ++pos;
        }
    }
    if (!result.empty()) result += "\357\274\233";
    result += Runtime::Translate(source.substr(start));
    return result;
}
struct StringArgument { std::string value; bool isNull; };
inline StringArgument Wrap(RawText value) { return { value.value ? value.value : "", value.value == nullptr }; }
inline StringArgument Wrap(const char* value) { return { TextValue(value), value == nullptr }; }
inline StringArgument Wrap(char* value) { return Wrap(static_cast<const char*>(value)); }
template<class T> inline T Wrap(T value) { return value; }
inline const char* Pass(const StringArgument& value) { return value.isNull ? nullptr : value.value.c_str(); }
template<class T> inline T Pass(const T& value) { return value; }
inline void SuppressPointPlural(StringArgument& value) { if (value.value == "s") value.value.clear(); }
template<class T> inline void SuppressPointPlural(T&) {}
// Keep concrete pointer parameters: upstream uses Windows NULL (integer 0),
// whose null-pointer conversion would be lost through a forwarding reference.
inline bool Begin(const char* label, bool* open = nullptr, ImGuiWindowFlags flags = 0)
{ return ImGui::Begin(LabelValue(label).c_str(), open, flags); }
template<class... Args> inline auto Button(const char* label, Args&&... args)
{ return ImGui::Button(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto SmallButton(const char* label, Args&&... args)
{ return ImGui::SmallButton(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto Checkbox(const char* label, Args&&... args)
{ return ImGui::Checkbox(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto CheckboxFlags(const char* label, Args&&... args)
{ return ImGui::CheckboxFlags(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto RadioButton(const char* label, Args&&... args)
{ return ImGui::RadioButton(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto Selectable(const char* label, Args&&... args)
{ return ImGui::Selectable(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto TreeNode(const char* label, Args&&... args)
{ return ImGui::TreeNode(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto TreeNodeEx(const char* label, Args&&... args)
{ return ImGui::TreeNodeEx(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto CollapsingHeader(const char* label, Args&&... args)
{ return ImGui::CollapsingHeader(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto BeginListBox(const char* label, Args&&... args)
{ return ImGui::BeginListBox(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto BeginTabItem(const char* label, Args&&... args)
{ return ImGui::BeginTabItem(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto BeginMenu(const char* label, Args&&... args)
{ return ImGui::BeginMenu(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto MenuItem(const char* label, Args&&... args)
{ return ImGui::MenuItem(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto SliderFloat(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderFloat(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto SliderFloat2(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderFloat2(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto SliderFloat3(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderFloat3(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto SliderFloat4(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderFloat4(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto SliderInt(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderInt(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto SliderInt2(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderInt2(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto SliderInt3(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderInt3(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto SliderInt4(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderInt4(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto SliderScalar(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderScalar(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto SliderScalarN(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderScalarN(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto SliderAngle(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::SliderAngle(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto DragFloat(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::DragFloat(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto DragFloat2(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::DragFloat2(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto DragFloat3(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::DragFloat3(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto DragFloat4(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::DragFloat4(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto DragInt(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::DragInt(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto DragInt2(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::DragInt2(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto DragInt3(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::DragInt3(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto DragInt4(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::DragInt4(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto DragScalar(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::DragScalar(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto InputFloat(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::InputFloat(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto InputFloat2(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::InputFloat2(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto InputFloat3(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::InputFloat3(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto InputFloat4(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::InputFloat4(LabelValue(label).c_str(), Pass(value)...); }, values); }
template<class... Args> inline auto InputInt(const char* label, Args&&... args)
{ const auto values = std::make_tuple(Wrap(args)...); return std::apply([&](const auto&... value) { return ImGui::InputInt(LabelValue(label).c_str(), Pass(value)...); }, values); }
inline bool InputScalar(const char* label, ImGuiDataType type, void* data,
                        const void* step = nullptr, const void* fastStep = nullptr,
                        const char* format = nullptr, ImGuiInputTextFlags flags = 0)
{ const auto translated = Wrap(format);
  return ImGui::InputScalar(LabelValue(label).c_str(), type, data, step, fastStep, Pass(translated), flags); }
template<class... Args> inline auto InputText(const char* label, Args&&... args)
{ return ImGui::InputText(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto InputTextMultiline(const char* label, Args&&... args)
{ return ImGui::InputTextMultiline(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto InputTextWithHint(const char* label, Args&&... args)
{ return ImGui::InputTextWithHint(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto ColorEdit3(const char* label, Args&&... args)
{ return ImGui::ColorEdit3(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto ColorEdit4(const char* label, Args&&... args)
{ return ImGui::ColorEdit4(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto TableSetupColumn(const char* label, Args&&... args)
{ return ImGui::TableSetupColumn(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto TextLink(const char* label, Args&&... args)
{ return ImGui::TextLink(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto TextLinkOpenURL(const char* label, Args&&... args)
{ return ImGui::TextLinkOpenURL(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto BeginPopupModal(const char* label, Args&&... args)
{ return ImGui::BeginPopupModal(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline auto PlotHistogram(const char* label, Args&&... args)
{ return ImGui::PlotHistogram(LabelValue(label).c_str(), std::forward<Args>(args)...); }
template<class... Args> inline void Text(const char* format, Args... args)
{
    auto values = std::make_tuple(Wrap(args)...);
    if (Loc::IsChineseActive() && std::string_view(format).find("point%s)") != std::string_view::npos)
        std::apply([](auto&... value) { (SuppressPointPlural(value), ...); }, values);
    const auto translated = TextValue(format);
    std::apply([&](const auto&... value) { ImGui::Text(translated.c_str(), Pass(value)...); }, values);
}
template<class... Args> inline void TextDisabled(const char* format, Args... args)
{
    auto values = std::make_tuple(Wrap(args)...);
    if (Loc::IsChineseActive() && std::string_view(format).find("point%s)") != std::string_view::npos)
        std::apply([](auto&... value) { (SuppressPointPlural(value), ...); }, values);
    const auto translated = TextValue(format);
    std::apply([&](const auto&... value) { ImGui::TextDisabled(translated.c_str(), Pass(value)...); }, values);
}
template<class... Args> inline void TextWrapped(const char* format, Args... args)
{
    auto values = std::make_tuple(Wrap(args)...);
    if (Loc::IsChineseActive() && std::string_view(format).find("point%s)") != std::string_view::npos)
        std::apply([](auto&... value) { (SuppressPointPlural(value), ...); }, values);
    const auto translated = TextValue(format);
    std::apply([&](const auto&... value) { ImGui::TextWrapped(translated.c_str(), Pass(value)...); }, values);
}
template<class... Args> inline void BulletText(const char* format, Args... args)
{
    auto values = std::make_tuple(Wrap(args)...);
    if (Loc::IsChineseActive() && std::string_view(format).find("point%s)") != std::string_view::npos)
        std::apply([](auto&... value) { (SuppressPointPlural(value), ...); }, values);
    const auto translated = TextValue(format);
    std::apply([&](const auto&... value) { ImGui::BulletText(translated.c_str(), Pass(value)...); }, values);
}
template<class... Args> inline void SetTooltip(const char* format, Args... args)
{
    auto values = std::make_tuple(Wrap(args)...);
    if (Loc::IsChineseActive() && std::string_view(format).find("point%s)") != std::string_view::npos)
        std::apply([](auto&... value) { (SuppressPointPlural(value), ...); }, values);
    const auto translated = TextValue(format);
    std::apply([&](const auto&... value) { ImGui::SetTooltip(translated.c_str(), Pass(value)...); }, values);
}
template<class... Args> inline void SetItemTooltip(const char* format, Args... args)
{
    auto values = std::make_tuple(Wrap(args)...);
    if (Loc::IsChineseActive() && std::string_view(format).find("point%s)") != std::string_view::npos)
        std::apply([](auto&... value) { (SuppressPointPlural(value), ...); }, values);
    const auto translated = TextValue(format);
    std::apply([&](const auto&... value) { ImGui::SetItemTooltip(translated.c_str(), Pass(value)...); }, values);
}
template<class... Args> inline void TextColored(const ImVec4& color, const char* format, Args... args)
{
    auto values = std::make_tuple(Wrap(args)...);
    if (Loc::IsChineseActive() && std::string_view(format).find("point%s)") != std::string_view::npos)
        std::apply([](auto&... value) { (SuppressPointPlural(value), ...); }, values);
    const auto translated = TextValue(format);
    std::apply([&](const auto&... value) { ImGui::TextColored(color, translated.c_str(), Pass(value)...); }, values);
}
template<class... Args> inline void LabelText(const char* label, const char* format, Args... args)
{
    auto values = std::make_tuple(Wrap(args)...);
    if (Loc::IsChineseActive() && std::string_view(format).find("point%s)") != std::string_view::npos)
        std::apply([](auto&... value) { (SuppressPointPlural(value), ...); }, values);
    const auto translated = TextValue(format);
    std::apply([&](const auto&... value) { ImGui::LabelText(LabelValue(label).c_str(), translated.c_str(), Pass(value)...); }, values);
}
inline std::string Slice(const char* begin, const char* end)
{
    if (!begin) return {};
    const std::string source = end ? std::string(begin, end) : std::string(begin);
    return TextValue(source.c_str());
}
inline void TextUnformatted(const char* text, const char* end = nullptr)
{ const auto value = Slice(text, end); ImGui::TextUnformatted(value.c_str()); }
inline void SeparatorText(const char* text) { ImGui::SeparatorText(TextValue(text).c_str()); }
inline void SeparatorTextEx(ImGuiID id, const char* begin, const char* end, float extraWidth)
{ const auto value = Slice(begin, end); ImGui::SeparatorTextEx(id, value.data(), value.data() + value.size(), extraWidth); }
inline bool BeginComboRawPreview(const char* label, const char* preview, ImGuiComboFlags flags = 0)
{ return ImGui::BeginCombo(LabelValue(label).c_str(), preview, flags); }
inline bool SelectableRaw(const char* label, bool selected = false, ImGuiSelectableFlags flags = 0, const ImVec2& size = ImVec2(0, 0))
{ return ImGui::Selectable(label, selected, flags, size); }
inline bool BeginCombo(const char* label, const char* preview, ImGuiComboFlags flags = 0)
{ return ImGui::BeginCombo(LabelValue(label).c_str(), preview ? TextValue(preview).c_str() : nullptr, flags); }
inline bool Combo(const char* label, int* current, const char* const items[], int count, int height = -1)
{
    std::vector<std::string> translated; translated.reserve(count);
    std::vector<const char*> pointers; pointers.reserve(count);
    for (int i = 0; i < count; ++i) translated.push_back(LabelValue(items[i]));
    for (const auto& item : translated) pointers.push_back(item.c_str());
    return ImGui::Combo(LabelValue(label).c_str(), current, pointers.data(), count, height);
}
inline bool Combo(const char* label, int* current, const char* items, int height = -1)
{
    std::string translated;
    for (const char* p = items; p && *p; p += std::strlen(p) + 1) { translated += LabelValue(p); translated += '\0'; }
    translated += '\0';
    return ImGui::Combo(LabelValue(label).c_str(), current, translated.c_str(), height);
}
inline void ProgressBar(float fraction, const ImVec2& size = ImVec2(-FLT_MIN, 0), const char* overlay = nullptr)
{ ImGui::ProgressBar(fraction, size, overlay ? TextValue(overlay).c_str() : nullptr); }
inline ImVec2 CalcTextSize(const char* text, const char* end = nullptr, bool hideId = false, float wrapWidth = -1.0f)
{
    const std::string source = !text ? std::string() : end ? std::string(text, end) : std::string(text);
    const auto value = hideId ? LabelValue(source.c_str()) : TextValue(source.c_str());
    return ImGui::CalcTextSize(value.c_str(), nullptr, hideId, wrapWidth);
}
inline void PlotLines(const char* label, const float* values, int count, int offset = 0,
                      const char* overlay = nullptr, float low = FLT_MAX, float high = FLT_MAX,
                      ImVec2 size = ImVec2(0, 0), int stride = sizeof(float))
{ ImGui::PlotLines(LabelValue(label).c_str(), values, count, offset,
                   overlay ? TextValue(overlay).c_str() : nullptr, low, high, size, stride); }
inline void PlotLines(const char* label, float (*getter)(void*, int), void* data, int count,
                      int offset = 0, const char* overlay = nullptr, float low = FLT_MAX,
                      float high = FLT_MAX, ImVec2 size = ImVec2(0, 0))
{ ImGui::PlotLines(LabelValue(label).c_str(), getter, data, count, offset,
                   overlay ? TextValue(overlay).c_str() : nullptr, low, high, size); }
inline void AddText(ImDrawList* draw, const ImVec2& position, ImU32 color, const char* text, const char* end = nullptr)
{ const auto value = Slice(text, end); draw->AddText(position, color, value.c_str()); }
inline void AddText(ImDrawList* draw, ImFont* font, float size, const ImVec2& position, ImU32 color,
                    const char* text, const char* end = nullptr, float wrapWidth = 0.0f,
                    const ImVec4* clip = nullptr)
{ const auto value = Slice(text, end); draw->AddText(font, size, position, color, value.c_str(), nullptr, wrapWidth, clip); }
inline ImVec2 CalcTextSizeA(ImFont* font, float size, float maxWidth, float wrapWidth,
                          const char* text, const char* end = nullptr, const char** remaining = nullptr)
{
    // No translated pointer may escape. Upstream calls do not request remaining.
    if (remaining) return font->CalcTextSizeA(size, maxWidth, wrapWidth, text, end, remaining);
    const auto value = Slice(text, end);
    return font->CalcTextSizeA(size, maxWidth, wrapWidth, value.c_str());
}
} // namespace OptiScalerCN::UI
