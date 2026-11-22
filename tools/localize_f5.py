#!/usr/bin/env python3
"""Materialize display-boundary hooks without translating producer data."""
from pathlib import Path
import argparse,json,re,shutil,subprocess,sys
from loclib import ROOT, read_source_text,write_source_text,mask_cpp
from f5_font_patch import patch_font_and_init

INCLUDE='#include "localization/ImGuiLocalization.h"\n'
MARKER='// OPTISCALER_CN_SOURCE_ID_V1'
HASH_HOOK=r'''    // OPTISCALER_CN_SOURCE_ID_V1: only display wrappers emit this reserved marker.
    // Recover the exact original bytes before upstream CRC/### handling, including
    // its original scope seed. Ordinary upstream strings take the unchanged path.
    static const char cnMarker[] = "###\037CNID\037";
    const size_t cnLength = data_size ? data_size : strlen(data_p);
    const size_t cnMarkerLength = sizeof(cnMarker) - 1;
    for (size_t cnOffset = 0; cnOffset + cnMarkerLength <= cnLength; ++cnOffset)
    {
        if (memcmp(data_p + cnOffset, cnMarker, cnMarkerLength) == 0)
        {
            const size_t cnStart = cnOffset + cnMarkerLength;
            if (data_size && cnStart == data_size) return seed;
            data_p += cnStart;
            if (data_size) data_size -= cnStart;
            break;
        }
    }
'''

def patch_hash(path):
    text,encoding=read_source_text(path)
    if MARKER in text:return
    anchor='ImGuiID ImHashStr(const char* data_p, size_t data_size, ImGuiID seed)\n{\n'
    if text.count(anchor)!=1:raise RuntimeError('ImHashStr integration anchor changed')
    text=text.replace(anchor,anchor+HASH_HOOK,1)
    write_source_text(path,text,encoding)

# Profiles arrived after the original audited baseline. Names and executable
# filenames are user data, never dictionary keys (including names like Reset).
PROFILE_RAW_REPLACEMENTS = {
    'OptiScalerCN::UI::BeginCombo("Profile##nrprofile", pick ? pick->name.c_str() : "(none saved yet)")':
        'OptiScalerCN::UI::BeginComboRawPreview("Profile##nrprofile", pick ? pick->name.c_str() : OptiScalerCN::UI::TextValue("(none saved yet)").c_str())',
    'OptiScalerCN::UI::Selectable(profiles[i].name.c_str(), i == selected)':
        'OptiScalerCN::UI::SelectableRaw(profiles[i].name.c_str(), i == selected)',
    'OptiScalerCN::UI::SetTooltip("Saved in %s", profiles[i].file.savedFrom.c_str())':
        'OptiScalerCN::UI::SetTooltip("Saved in %s", OptiScalerCN::UI::Raw(profiles[i].file.savedFrom.c_str()))',
    'askName.c_str());': 'OptiScalerCN::UI::Raw(askName.c_str()));',
    'pick->name.c_str(), pick->file.savedFrom.c_str());':
        'OptiScalerCN::UI::Raw(pick->name.c_str()), OptiScalerCN::UI::Raw(pick->file.savedFrom.c_str()));',
}

def patch_profile_user_data(text):
    if '"Profile##nrprofile"' not in text:
        return text  # Historical baseline has no profile UI.
    for before, after in PROFILE_RAW_REPLACEMENTS.items():
        if text.count(before) != 1:
            raise RuntimeError('profile user-data display anchor changed: ' + before)
        text = text.replace(before, after, 1)
    return text

def exact_display_edits(text, replacements, scope):
    for before, after in replacements.items():
        if text.count(before) != 1:
            raise RuntimeError(f'{scope} display anchor changed: {before}')
        text = text.replace(before, after, 1)
    return text


def patch_model_weights(text):
    return exact_display_edits(text, {
        'std::string shown = stock;': 'std::string shown = OptiScalerCN::UI::TextValue(stock.c_str());',
        'current + " (no file for this model)"':
            'current + OptiScalerCN::UI::TextValue(" (no file for this model)")',
        'OptiScalerCN::UI::BeginCombo(label, shown.c_str())':
            'OptiScalerCN::UI::BeginComboRawPreview(label, shown.c_str())',
        'OptiScalerCN::UI::Selectable(name.c_str(), name == current)':
            'OptiScalerCN::UI::SelectableRaw(name.c_str(), name == current)',
    }, 'Weights folder')


def patch_status_raw_values(text):
    substitutions = {f'Row("{key}", ': f'RowRaw("{key}", ' for key in ('GPU', 'Game', 'Quirks', 'ASI')}
    substitutions.update({
        'Pair("FG Nvngx", FgNvngxName((FgNvngx) state.activeFgNvngx, state.activeFgNvngxCustom),':
            'PairRaw("FG Nvngx", OptiScalerCN::UI::StatusReplacementValue(FgNvngxName((FgNvngx) state.activeFgNvngx, state.activeFgNvngxCustom), state.activeFgNvngx == FGNvngxReplacement::Custom && !state.activeFgNvngxCustom.empty()),',
        'Row("Vulkan route", summary.vulkanRoute);':
            'RowRaw("Vulkan route", OptiScalerCN::UI::VulkanStatusValue(summary.vulkanRoute));',
    })
    if 'NrModelText(config->DlssNrPreset' in text:
        substitutions.update({
            'Row("  Model",\n                    NrModelText(config->DlssNrPreset.value_or_default(), config->DlssNrWeightsSetA.value_or_default(),\n                                config->DlssNrWeightsSetB.value_or_default()));':
            'RowRaw("  Model",\n                    OptiScalerCN::UI::StatusWeightsValue(NrModelText(config->DlssNrPreset.value_or_default(), "", ""),\n                                config->DlssNrWeightsSetA.value_or_default(), config->DlssNrWeightsSetB.value_or_default()));',
            'barriers.push_back(name);':
            'barriers.push_back(OptiScalerCN::UI::TextValue(name));',
            'OptiScalerCN::UI::TextUnformatted(Join(barriers).c_str());':
            'ImGui::TextUnformatted(Join(barriers).c_str());',
        })
    return exact_display_edits(text, substitutions, 'Status runtime')



POST_LUT_REPORTERS = {
    'OptiScaler/dlssnr/DlssNrFeature_Vk.cpp': 'chain',
    'OptiScaler/shaders/dlssnr/DlssNr_Dx12.cpp': 'chain',
    'OptiScaler/shaders/f5lut/F5Lut_Common.h': '_chain',
}


def patch_post_lut_snapshot(root):
    entry=root/'OptiScaler/dlssnr/DlssNr_LutChain.h'
    text, enc=read_source_text(entry)
    if 'inline std::string DlssNr_DescribeChain(' not in text:
        return  # Historical pins do not have a post-LUT stack.
    trans=root/'OptiScaler/dlssnr/DlssNr_LutStatus.h'
    status, status_enc=read_source_text(trans)
    status=exact_display_edits(status, {
        '#include <string>': '#include <string>\n#include <memory>',
        'std::string chain;   // DlssNr_DescribeChain':
            'std::string chain;   // DlssNr_DescribeChain\n    std::shared_ptr<const std::string> cnChain;',
    }, 'Post LUT display snapshot')
    helper = '''

// Chinese display is computed once per bake, beside the English description.
// No translated string enters a cache key, path, setting or render decision.
inline std::string DlssNr_DescribeChainCn(const DlssNr_LutChainState& state,
                                         const std::vector<DlssNr::ChainEntry>& present)
{
    if (!state.Loaded()) return {};
    std::string out;
    int shown = 0;
    bool converted = false;
    for (size_t i = 0; i < present.size() && i < (size_t) DlssNr::kMaxLutChainLayers; ++i)
    {
        const auto& layer = state.layers[i];
        if (!layer.Loaded() || !(present[i].strength > 0.0f)) continue;
        const auto& in = state.inputs[i];
        if (!out.empty()) out += " -> ";
        out += OptiScalerCN::PostLut::Layer(layer.loadedPath, DlssNr::DescribeLutSize(layer.lut),
                                            in.converted ? DlssNr::LutSpaceName(in.space) : nullptr,
                                            in.converted && in.gamut != in.space ? DlssNr::LutGamutName(in.gamut) : nullptr);
        ++shown;
        converted = converted || in.converted;
    }
    return OptiScalerCN::PostLut::Finish(std::move(out), shown > 1 || converted ? state.baked.size : 0,
                                         converted ? DlssNr::FrameDecodeName(state.decode) : nullptr);
}
'''
    header=exact_display_edits(text,{
        '#include "DlssNr_LutSpaces.h"': '#include "DlssNr_LutSpaces.h"\n#include <localization/PostLutText.h>\n#include <memory>',
        '    bool wanted = false;\n    int failedLayer':
            '    std::shared_ptr<const std::string> cnDescription;\n    bool wanted = false;\n    int failedLayer',
        '// Parses the entries (a path already tried':
            'inline std::string DlssNr_DescribeChainCn(const DlssNr_LutChainState&, const std::vector<DlssNr::ChainEntry>&);\n\n// Parses the entries (a path already tried',
        '        state->description.clear();': '        state->description.clear();\n        state->cnDescription.reset();',
        '        state->description = DlssNr_DescribeChain(*state, baking);':
            '        state->description = DlssNr_DescribeChain(*state, baking);\n        state->cnDescription = std::make_shared<const std::string>(DlssNr_DescribeChainCn(*state, baking));',
    }, 'Post LUT chain snapshot') + helper
    # Old supported editions have only two reporters. Every existing reporter
    # is required to carry the same display snapshot when that route ships.
    edits=[]
    for rel, item in POST_LUT_REPORTERS.items():
        file=root/rel
        if not file.is_file():
            if rel.endswith('F5Lut_Common.h'): raise RuntimeError('Missing upscaler Post LUT reporter')
            continue
        body, encoding=read_source_text(file)
        anchor=f'status.chain = {item}.description;'
        if rel.endswith('DlssNrFeature_Vk.cpp') and anchor not in body:
            if (root/'OptiScaler/dlssnr/DlssNr_FinishedVk.cpp').is_file():
                raise RuntimeError('Missing Vulkan Post LUT reporter')
            continue  # Earlier pin did not report this route.
        indent=' '*(body.index(anchor)-body.rfind('\n',0,body.index(anchor))-1)
        body=exact_display_edits(body,{anchor:anchor+'\n'+indent+f'status.cnChain = {item}.cnDescription;'}, 'Post LUT report')
        edits.append((file,body,encoding))
    for file, body, encoding in [*edits, (entry,header,enc), (trans,status,status_enc)]:
        write_source_text(file,body,encoding)


def patch_file(path,root,names):
    rel=path.relative_to(root).as_posix()
    text,encoding=read_source_text(path);masked=mask_cpp(text);changes=[]
    if rel == 'OptiScaler/plugins/PluginApi.cpp':
        # The SDK receives third-party labels, format strings and IDs. Only the
        # application-owned crash notice is a Chinese display surface.
        a = list(re.finditer(r'\bImGui::TextColored(?=\s*\()', masked))
        if len(a) != 1: raise RuntimeError('Plugin crash notice display anchor changed')
        changes.append((a[0].start(),a[0].end(),'OptiScalerCN::UI::TextColored'))
    elif rel=='OptiScaler/include/imgui/ImGuiNotify.hpp':
        start=masked.find('inline void RenderNotifications(')
        if start<0:raise RuntimeError('toast renderer anchor changed')
        # Only the rendering body is hooked; constructors retain original buffers.
        pattern=re.compile(r'(?<![\w:])(?:'+ '|'.join(map(re.escape,names))+r')(?=\s*\()')
        for m in pattern.finditer(masked,start):changes.append((m.start(),m.end(),'OptiScalerCN::UI::'+m.group()))
    else:
        pattern=re.compile(r'\bImGui::('+'|'.join(map(re.escape,names))+r')(?=\s*\()')
        for m in pattern.finditer(masked):changes.append((m.start(),m.end(),'OptiScalerCN::UI::'+m.group(1)))
        for m in re.finditer(r'\b([A-Za-z_]\w*)->(AddText|CalcTextSizeA)\s*\(',masked):
            changes.append((m.start(),m.end(),'OptiScalerCN::UI::'+m.group(2)+'('+m.group(1)+', '))
    if not changes:return 0
    for a,b,replacement in sorted(changes,reverse=True):text=text[:a]+replacement+text[b:]
    if rel == 'OptiScaler/dlssnr/DlssNr_Menu.cpp':
        # Explicit source-boundary exceptions: labels/format stay localized while
        # file names remain user data, even when named "Reset" or "Auto (On)".
        modern_lut = 'static void RenderPostLutSection' in text
        replacements = {
            'current.empty() ? "(none)" : std::filesystem::path(current).filename().string()':
                'current.empty() ? "(none)" : OptiScalerCN::UI::PathUtf8(std::filesystem::path(current).filename())',
            'cal.compareWords.c_str()':
                'OptiScalerCN::UI::Raw(OptiScalerCN::UI::ComparisonValue(cal.compareWords).c_str())',
            'OptiScalerCN::UI::BeginCombo("LUT", preview.c_str())':
                'OptiScalerCN::UI::BeginComboRawPreview("LUT", current.empty() ? OptiScalerCN::UI::TextValue("(none)").c_str() : preview.c_str())',
            'OptiScalerCN::UI::Selectable(path.filename().string().c_str(), selected)':
                'OptiScalerCN::UI::SelectableRaw(OptiScalerCN::UI::PathUtf8(path.filename()).c_str(), selected)',
            'std::filesystem::path(lutStatus.loadedPath).filename().string().c_str(), lutStatus.size)':
                'OptiScalerCN::UI::Raw(OptiScalerCN::UI::PathUtf8(std::filesystem::path(lutStatus.loadedPath).filename()).c_str()), lutStatus.size)',
            'std::filesystem::path(lutStatus.attemptedPath).filename().string().c_str(),':
                'OptiScalerCN::UI::Raw(OptiScalerCN::UI::PathUtf8(std::filesystem::path(lutStatus.attemptedPath).filename()).c_str()),',
        }
        if modern_lut:
            old = 'OptiScalerCN::UI::BeginCombo("LUT", preview.c_str())'
            replacements.pop(old)
            replacements['OptiScalerCN::UI::BeginCombo("Input LUT", preview.c_str())'] = (
                'OptiScalerCN::UI::BeginComboRawPreview("Input LUT", current.empty() ? OptiScalerCN::UI::TextValue("(none)").c_str() : preview.c_str())')
            replacements['OptiScalerCN::UI::BeginCombo(label.c_str(), preview.c_str())'] = (
                'OptiScalerCN::UI::BeginComboRawPreview(label.c_str(), current.empty() ? OptiScalerCN::UI::TextValue("(none)").c_str() : preview.c_str())')
            replacements['OptiScalerCN::UI::Selectable(path.filename().string().c_str(), pathStr == current)'] = (
                'OptiScalerCN::UI::SelectableRaw(OptiScalerCN::UI::PathUtf8(path.filename()).c_str(), pathStr == current)')
            replacements['std::filesystem::path(status.failedPath).filename().string().c_str(),'] = (
                'OptiScalerCN::UI::Raw(OptiScalerCN::UI::PathUtf8(std::filesystem::path(status.failedPath).filename()).c_str()),')
            # The precomposed chain contains arbitrary user filenames: never feed
            # it into recursive generic translation or comma-splitting heuristics.
            replacements['"Loaded: %s", status.chain.c_str()'] = (
                '"Loaded: %s", OptiScalerCN::UI::Raw((OptiScalerCN::Loc::IsChineseActive() && status.cnChain ? *status.cnChain : status.chain).c_str())')
        for before, after in replacements.items():
            expected = 2 if modern_lut and before.startswith('current.empty()') else 1
            if text.count(before) != expected:
                raise RuntimeError('LUT user-data display anchor changed: ' + before)
            text = text.replace(before, after, expected)
    if rel == 'OptiScaler/dlssnr/DlssNr_Menu.cpp':
        text = patch_profile_user_data(text)
        if 'static void ModelWeightsCombo(' in text:
            text = patch_model_weights(text)
    if rel == 'OptiScaler/menu/StatusPage.cpp':
        text = patch_status_raw_values(text)
        # Display-only values bypass generic formatting's recursive dictionary;
        # don't duplicate labels, table identifiers or upstream state decisions.
        before = 'void SetupPairs()'
        after = """void RowRaw(const char* label, const std::string& value)
{
    ImGui::TableNextColumn();
    OptiScalerCN::UI::TextDisabled("%s", label);
    ImGui::TableNextColumn();
    OptiScalerCN::UI::TextWrapped("%s", OptiScalerCN::UI::Raw(value.c_str()));
}

void PairRaw(const char* label, const std::string& value, bool dim)
{
    ImGui::TableNextColumn();
    OptiScalerCN::UI::TextDisabled("%s", label);
    ImGui::TableNextColumn();
    if (dim)
        OptiScalerCN::UI::TextDisabled("%s", OptiScalerCN::UI::Raw(value.c_str()));
    else
        OptiScalerCN::UI::TextWrapped("%s", OptiScalerCN::UI::Raw(value.c_str()));
}

void SetupPairs()"""
        text = exact_display_edits(text, {before: after}, 'Status raw renderer')
    if rel == 'OptiScaler/menu/menu_common.cpp' and '##custom%d' in text:
        # Only the provider technology annotation is translated; both folder
        # name and original ImGui ID are kept byte-for-byte.
        before = 'if (OptiScalerCN::UI::Selectable(label.c_str(), isSelected))\n                    pick(upscaler, name);'
        after = ('auto cnLabel = StrFmt("%s (%s)##custom%d", name.c_str(), '
                 'OptiScalerCN::UI::TextValue(tag).c_str(), (int) upscaler);\n'
                 '                if (ImGui::Selectable(OptiScalerCN::Runtime::Label(label, cnLabel).c_str(), isSelected))\n'
                 '                    pick(upscaler, name);')
        text = exact_display_edits(text, {
            before: after,
            'OptiScalerCN::UI::BeginCombo("##UpscalerCombo", selectedName.c_str())':
                'OptiScalerCN::UI::BeginComboRawPreview("##UpscalerCombo", targetCustom.empty() ? OptiScalerCN::UI::TextValue(selectedName.c_str()).c_str() : selectedName.c_str())',
        }, 'Custom upscaler name')
        if '##rr%s' in text:
            text = exact_display_edits(text, {
                'OptiScalerCN::UI::BeginCombo(label, preview.c_str(), ImGuiComboFlags_HeightLargest)':
                    'OptiScalerCN::UI::BeginComboRawPreview(label, runsDlssd && !current.empty() ? preview.c_str() : OptiScalerCN::UI::TextValue(preview.c_str()).c_str(), ImGuiComboFlags_HeightLargest)',
                'auto label = StrFmt("%s##rr%s", entryName(entry).c_str(), entry.c_str());\n\n        if (OptiScalerCN::UI::Selectable(label.c_str(), selected) && !selected)':
                    'auto label = StrFmt("%s##rr%s", entryName(entry).c_str(), entry.c_str());\n\n        if ((entry.empty() ? OptiScalerCN::UI::Selectable(label.c_str(), selected) : OptiScalerCN::UI::SelectableRaw(label.c_str(), selected)) && !selected)',
            }, 'Custom Ray Reconstruction provider name')
    if rel == 'OptiScaler/menu/PluginsPage.cpp':
        # ASI row labels are user filenames, unlike localized built-in/loader labels.
        before = 'OptiScalerCN::UI::TextUnformatted(row.label.c_str());'
        if text.count(before) != 1:
            raise RuntimeError('plugin filename display anchor changed')
        text = text.replace(before, 'ImGui::TextUnformatted(row.label.c_str());', 1)
        before = 'folder.empty() ? "(not read yet)" : folder.c_str(),'
        if text.count(before) != 1:
            raise RuntimeError('plugin folder display anchor changed')
        text = text.replace(before,
            'OptiScalerCN::UI::Raw(folder.empty() ? OptiScalerCN::UI::TextValue("(not read yet)").c_str() : folder.c_str()),', 1)
    if INCLUDE not in text:
        pch='#include "pch.h"\n'
        if pch in text:text=text.replace(pch,pch+INCLUDE,1)
        elif '#pragma once' in text:text=text.replace('#pragma once','#pragma once\n\n'+INCLUDE,1)
        else:raise RuntimeError('cannot safely add localization include to '+rel)
    write_source_text(path,text,encoding)
    return len(changes)

def write_boundary_report(path, files):
    # Filesystem traversal order differs between clones and operating systems.
    # Keep the report byte-stable without masking changed paths or call counts.
    ordered = sorted(files, key=lambda record: record['file'])
    report = {'calls': sum(record['display_calls'] for record in ordered), 'files': ordered}
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',required=True,type=Path);ap.add_argument('--channel',default='master');args=ap.parse_args()
    from f5_installer_patch import patch_installer_scripts
    patch_installer_scripts(args.source)
    dst=args.source/'OptiScaler/localization';shutil.copytree(ROOT/'overlay/OptiScaler/localization',dst,dirs_exist_ok=True)
    subprocess.run([sys.executable,str(ROOT/'tools/generate_cpp.py'),'--channel',args.channel,'--out',str(dst/'generated/Strings.generated.h')],check=True)
    names=json.loads((ROOT/'tools/f5_boundaries.json').read_text())['imgui_calls']
    count=0;files=[]
    for path in sorted((args.source/'OptiScaler').rglob('*')):
        if path.suffix not in ('.h','.cpp','.inl','.hpp'):continue
        rel=path.relative_to(args.source).as_posix()
        if '/localization/' in rel:continue
        if '/include/' in rel and rel!='OptiScaler/include/imgui/ImGuiNotify.hpp':continue
        n=patch_file(path,args.source,names)
        if n:files.append({'file':rel,'display_calls':n});count+=n
    patch_post_lut_snapshot(args.source)
    patch_font_and_init(args.source/'OptiScaler/menu/menu_common.cpp')
    patch_hash(args.source/'OptiScaler/include/imgui/imgui.cpp')
    reports=ROOT/'reports';reports.mkdir(exist_ok=True)
    write_boundary_report(reports/'display-boundaries.json', files)
    print(f'Adapted {count} display boundaries in {len(files)} files; upstream strings retained')
if __name__=='__main__':main()
