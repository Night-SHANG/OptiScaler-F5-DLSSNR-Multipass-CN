#pragma once
// Portable display-only translator. Never mutates upstream data or keys.
#include <string>
#include <string_view>
#include <vector>
#include <cctype>
#include <unordered_map>
#include "generated/Strings.generated.h"

namespace OptiScalerCN::Runtime
{
inline std::string Exact(std::string_view source)
{
    static const auto index = [] {
        std::unordered_map<std::uint64_t, const char*> result;
        for (const auto& entry : Generated::kTranslations)
            if (entry.zh && entry.zh[0]) result.emplace(entry.source.value, entry.zh);
        return result;
    }();
    auto found = index.find(Generated::HashSource(source));
    return found == index.end() ? std::string(source) : std::string(found->second);
}
inline std::vector<std::string_view> Parts(std::string_view packed)
{
    std::vector<std::string_view> result;
    size_t start = 0;
    for (size_t i = 0; i < packed.size(); ++i)
        if (packed[i] == '\x1f') { result.push_back(packed.substr(start, i - start)); start = i + 1; }
    result.push_back(packed.substr(start));
    return result;
}
inline bool Numeric(std::string_view value, char kind)
{
    if (kind == 's' || kind == 'p' || kind == 'r') return true;
    if (value.empty()) return false;
    bool digit = false;
    for (unsigned char c : value)
    {
        if (std::isdigit(c)) { digit = true; continue; }
        if (std::string_view(" +-.,xXaAbBcCdDeEfFpPinINfF").find(c) == std::string_view::npos) return false;
    }
    return digit || value == "nan" || value == "inf" || value == "-inf";
}
inline bool MatchFields(std::string_view source, const std::vector<std::string_view>& parts,
                        std::string_view kinds, size_t field, size_t pos,
                        std::vector<std::string_view>& values, unsigned& budget)
{
    if (budget == 0) return false;
    --budget;
    if (field == kinds.size()) return pos == source.size();
    const auto delimiter = parts[field + 1];
    if (field + 1 == kinds.size() && delimiter.empty())
    {
        const auto value = source.substr(pos);
        if (!Numeric(value, kinds[field])) return false;
        values.push_back(value);
        return true;
    }
    size_t end = delimiter.empty() ? pos : source.find(delimiter, pos);
    while (end != std::string_view::npos && end <= source.size())
    {
        const auto value = source.substr(pos, end - pos);
        if (Numeric(value, kinds[field]))
        {
            values.push_back(value);
            if (MatchFields(source, parts, kinds, field + 1, end + delimiter.size(), values, budget)) return true;
            values.pop_back();
        }
        if (!budget || end == source.size()) break;
        end = delimiter.empty() ? end + 1 : source.find(delimiter, end + 1);
    }
    return false;
}
inline std::string TranslateImpl(std::string_view source, unsigned depth = 0)
{
    std::string exact = Exact(source);
    if (exact != source || source.empty() || source.size() > 16384 || depth > 5) return exact;
    struct Pattern { std::vector<std::string_view> source; std::vector<std::string_view> target; std::string_view kinds; };
    static const auto patterns = [] {
        std::vector<Pattern> result;
        for (const auto& entry : Generated::kRenderedFormats)
            result.push_back({ Parts(entry.sourceParts), Parts(entry.targetParts), entry.kinds });
        return result;
    }();
    for (const auto& entry : patterns)
    {
        const auto& src = entry.source;
        const auto& dst = entry.target;
        const auto kinds = entry.kinds;
        if (kinds.empty() || src.size() != kinds.size() + 1 || dst.size() != src.size()) continue;
        if (source.substr(0, src[0].size()) != src[0]) continue;
        std::vector<std::string_view> values;
        unsigned budget = 512;
        if (!MatchFields(source, src, kinds, 0, src[0].size(), values, budget)) continue;
        std::string output(dst[0]);
        for (size_t i = 0; i < values.size(); ++i)
        {
            output += kinds[i] == 'p' && values[i] == "s" ? std::string() :
                      (kinds[i] == 's' || kinds[i] == 'p') ? TranslateImpl(values[i], depth + 1) : std::string(values[i]);
            output += dst[i + 1];
        }
        return output;
    }
    // MenuOption tooltips append a separate disabled-reason paragraph. Keep the
    // original multiline tooltip intact so its exact catalog key wins before
    // comma suffix heuristics can split natural-language prose.
    const auto paragraph = source.find("\n\n");
    if (paragraph != std::string_view::npos)
    {
        const auto left = TranslateImpl(source.substr(0, paragraph), depth + 1);
        const auto right = TranslateImpl(source.substr(paragraph + 2), depth + 1);
        if (left != source.substr(0, paragraph) || right != source.substr(paragraph + 2))
            return left + "\n\n" + right;
    }
    // Preserve a producer's comma-prefixed suffix as a unit (", warmer", etc.)
    // before considering a bare separator. Only finite source catalog entries
    // can change this suffix; it is not a global substring replacement.
    const auto comma = source.rfind(", ");
    if (comma != std::string_view::npos)
    {
        const auto suffix = TranslateImpl(source.substr(comma), depth + 1);
        if (suffix != source.substr(comma))
            return TranslateImpl(source.substr(0, comma), depth + 1) + suffix;
    }
    // Explicitly registered composition delimiters only. Each side must make a
    // real translation, and the original data remains untouched. User filename
    // displays opt out at their source boundary.
    for (const auto delimiter : { std::string_view("\n\n"), std::string_view("\n"), std::string_view(" | "), std::string_view(", "), std::string_view(" or ") })
    {
        const size_t split = source.find(delimiter);
        if (split == std::string_view::npos) continue;
        auto left = TranslateImpl(source.substr(0, split), depth + 1);
        auto right = TranslateImpl(source.substr(split + delimiter.size()), depth + 1);
        if (left != source.substr(0, split) || right != source.substr(split + delimiter.size()))
            return left + (delimiter == " or " ? Exact(" or ") : std::string(delimiter)) + right;
    }
    return exact;
}
inline std::string Translate(std::string_view source)
{
    // Bound memory and avoid repeating format parsing for steady labels/statuses.
    static thread_local std::unordered_map<std::string, std::string> cache;
    const std::string key(source);
    const auto found = cache.find(key);
    if (found != cache.end()) return found->second;
    auto result = TranslateImpl(source);
    if (source.size() <= 4096)
    {
        if (cache.size() >= 1024) cache.clear();
        cache.emplace(key, result);
    }
    return result;
}
inline std::string Label(std::string_view original, std::string_view translated)
{
    if (original == translated || original.substr(0, 2) == "##") return std::string(original);
    // The narrow ImHashStr marker hook recovers the entire original byte string
    // before hashing. A normal ### suffix alone would NOT preserve plain IDs.
    return std::string(translated.substr(0, translated.find("##"))) + "###\037CNID\037" + std::string(original);
}
} // namespace OptiScalerCN::Runtime
