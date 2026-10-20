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

def patch_file(path,root,names):
    rel=path.relative_to(root).as_posix()
    text,encoding=read_source_text(path);masked=mask_cpp(text);changes=[]
    if rel=='OptiScaler/include/imgui/ImGuiNotify.hpp':
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
        for before, after in replacements.items():
            if text.count(before) != 1:
                raise RuntimeError('LUT user-data display anchor changed: ' + before)
            text = text.replace(before, after, 1)
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
    patch_font_and_init(args.source/'OptiScaler/menu/menu_common.cpp')
    patch_hash(args.source/'OptiScaler/include/imgui/imgui.cpp')
    reports=ROOT/'reports';reports.mkdir(exist_ok=True)
    write_boundary_report(reports/'display-boundaries.json', files)
    print(f'Adapted {count} display boundaries in {len(files)} files; upstream strings retained')
if __name__=='__main__':main()
