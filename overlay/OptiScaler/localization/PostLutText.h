#pragma once
#include <filesystem>
#include <string>
#include "RuntimeText.h"

namespace OptiScalerCN::PostLut
{
inline std::string Filename(const std::string& path)
{
    // This path originates in the game's local LUT configuration, not the
    // dictionary. Use the same native narrow path decoding as the upstream loader.
    const auto bytes = std::filesystem::path(path).filename().u8string();
    return std::string(reinterpret_cast<const char*>(bytes.data()), bytes.size());
}

inline std::string Layer(const std::string& path, const std::string& size,
                         const char* space, const char* gamut)
{
    auto text = Filename(path) + " (" + size;
    if (space)
    {
        text += Runtime::Exact(", as ") + Runtime::Exact(space);
        if (gamut) text += Runtime::Exact(" in ") + Runtime::Exact(gamut);
    }
    return text + ")";
}

inline std::string Finish(std::string text, int size, const char* decode)
{
    if (size > 0) text += Runtime::Exact(", baked at ") + std::to_string(size) + "^3";
    if (decode) text += " (" + Runtime::Exact(decode) + ")";
    return text;
}
}
