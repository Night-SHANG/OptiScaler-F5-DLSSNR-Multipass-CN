#!/usr/bin/env python3
from __future__ import annotations
import argparse, re, shutil, subprocess, sys
from pathlib import Path
from loclib import *
from ui_scan import find_ui_candidates

INCLUDE_LINE = '#include "localization/Localization.h"\n'


def patch_precompiled_header(path: Path):
    text, source_encoding = read_source_text(path)
    if INCLUDE_LINE.strip() in text:
        return
    if '#pragma once' not in text:
        raise RuntimeError('integration conflict: OptiScaler/pch.h missing #pragma once')
    if not text.endswith('\n'):
        text += '\n'
    text += '\n' + INCLUDE_LINE
    write_source_text(path, text, source_encoding)


def patch_font_and_init(path: Path):
    text, source_encoding = read_source_text(path)
    if INCLUDE_LINE.strip() not in text:
        anchor='#include "menu_common.h"\n'
        if anchor not in text:
            raise RuntimeError('integration conflict: menu_common.h include anchor not found')
        text=text.replace(anchor, anchor+INCLUDE_LINE, 1)

    if 'OptiScalerCN::Loc::Initialize();' not in text:
        m=re.search(r'(void\s+MenuCommon::Init\s*\(HWND\s+InHwnd,\s*bool\s+isUWP\)\s*\{)', text)
        if not m:
            raise RuntimeError('integration conflict: MenuCommon::Init anchor not found')
        text=text[:m.end()]+'\n    OptiScalerCN::Loc::Initialize();'+text[m.end():]

    original_condition='if (io.Fonts->Fonts.empty() && Config::Instance()->UseHQFont.value_or_default())'
    localized_condition=('if (io.Fonts->Fonts.empty() && '
                         '(Config::Instance()->UseHQFont.value_or_default() || OptiScalerCN::Loc::IsChineseRequested()))')
    if original_condition in text:
        text=text.replace(original_condition, localized_condition, 1)
    elif localized_condition not in text:
        raise RuntimeError('integration conflict: overlay font gate changed; refusing unsafe release')

    if 'OptiScalerCN::Loc::ResolveChineseFont' not in text:
        # Semantic anchors make whitespace-only upstream formatting changes harmless.
        pat=re.compile(
            r'(?P<indent>^[ \t]*)if\s*\(Config::Instance\(\)->TTFFontPath\.has_value\(\)\)\s*\{'
            r'(?P<ifbody>.*?)'
            r'^\s*\}\s*else\s*\{'
            r'(?P<elsebody>.*?)'
            r'^\s*\}', re.M|re.S)
        match=None
        for m in pat.finditer(text):
            if ('AddFontFromFileTTF' in m.group('ifbody') and 'GetGlyphRangesDefault' in m.group('ifbody')
                    and 'AddFontFromMemoryCompressedBase85TTF' in m.group('elsebody')):
                match=m; break
        if not match:
            raise RuntimeError('integration conflict: upstream TTFFontPath/default font-loading block changed; refusing unsafe release')
        ind=match.group('indent')
        ifbody=match.group('ifbody')
        elsebody=match.group('elsebody')
        replacement=(
            f'{ind}if (OptiScalerCN::Loc::IsChineseRequested())\n'
            f'{ind}{{\n'
            f'{ind}    std::filesystem::path upstreamFont;\n'
            f'{ind}    if (Config::Instance()->TTFFontPath.has_value())\n'
            f'{ind}        upstreamFont = Config::Instance()->TTFFontPath.value();\n'
            f'{ind}    const auto cnFont = OptiScalerCN::Loc::ResolveChineseFont(upstreamFont);\n'
            f'{ind}    if (!cnFont.empty())\n'
            f'{ind}    {{\n'
            f'{ind}        const auto cnFontUtf8 = OptiScalerCN::Loc::PathUtf8(cnFont);\n'
            f'{ind}        io.FontDefault = atlas->AddFontFromFileTTF(cnFontUtf8.c_str(), fontSize, &fontConfig,\n'
            f'{ind}                                                   OptiScalerCN::Loc::BuildGlyphRanges(atlas));\n'
            f'{ind}    }}\n'
            f'{ind}    if (io.FontDefault == nullptr)\n'
            f'{ind}    {{\n'
            f'{ind}        OptiScalerCN::Loc::DisableChineseBecauseFontMissing();\n'
            f'{ind}        io.FontDefault = atlas->AddFontFromMemoryCompressedBase85TTF(hack_compressed_compressed_data_base85,\n'
            f'{ind}                                                                      fontSize, &fontConfig);\n'
            f'{ind}    }}\n'
            f'{ind}}}\n'
            f'{ind}else if (Config::Instance()->TTFFontPath.has_value())\n'
            f'{ind}{{{ifbody}{ind}}}\n'
            f'{ind}else\n'
            f'{ind}{{{elsebody}{ind}}}'
        )
        text=text[:match.start()]+replacement+text[match.end():]
    write_source_text(path, text, source_encoding)


def patch_dynamic_helpers(path: Path):
    text, source_encoding = read_source_text(path)
    # Central translation for labels/tooltips stored in MenuOption vectors and
    # for the rotating splash string container. These are not direct literal
    # arguments, so the literal scanner cannot rewrite their call sites itself.
    replacements={
        'preview = opt.label;':'preview = OptiScalerCN::Loc::TL(opt.label);',
        'ImGui::Selectable(opt.label.c_str(), isSelected)':'ImGui::Selectable(OptiScalerCN::Loc::TL(opt.label).c_str(), isSelected)',
        'ImGui::SetTooltip("%s", opt.tooltip.c_str())':'ImGui::SetTooltip("%s", OptiScalerCN::Loc::TL(opt.tooltip).c_str())',
        'return it->label;':'return OptiScalerCN::Loc::TL(it->label);',
        'splashMessage.c_str());':'OptiScalerCN::Loc::TL(splashMessage).c_str());',
        'ImGui::Selectable(q[n], (_mipmapUpscalerQuality == n))':'ImGui::Selectable(OptiScalerCN::Loc::TL(q[n]).c_str(), (_mipmapUpscalerQuality == n))',
        'ImGui::CheckboxFlags(flag.name.c_str(), &temp_flags, flag.mask)':'ImGui::CheckboxFlags(OptiScalerCN::Loc::TL(flag.name).c_str(), &temp_flags, flag.mask)',
        'ImGui::SetTooltip("%s", flag.description.c_str())':'ImGui::SetTooltip("%s", OptiScalerCN::Loc::TL(flag.description).c_str())',
    }
    for a,b in replacements.items():
        if a in text and b not in text:
            text=text.replace(a,b)

    # The Mipmap Bias utility keeps quality names in a local C string array.
    # Translate both the preview and the Selectable rows without changing the
    # upstream data model.
    if 'const char* selectedQ = q[configQ];' in text:
        text=text.replace('const char* selectedQ = q[configQ];',
                          'const std::string selectedQ = OptiScalerCN::Loc::TL(q[configQ]);',1)
        text=text.replace('ImGui::BeginCombo("Upscaler Quality", selectedQ)',
                          'ImGui::BeginCombo("Upscaler Quality", selectedQ.c_str())',1)
        # If the first argument was already instrumented, patch the second argument instead.
        text=re.sub(r'(ImGui::BeginCombo\(OptiScalerCN::Loc::T\([^\n]+?\),\s*)selectedQ(\))',r'\1selectedQ.c_str()\2',text,count=1)
    write_source_text(path, text, source_encoding)

def instrument_file(path: Path, rel: str, rules: dict, source_to_key: dict):
    text, source_encoding = read_source_text(path)
    candidates=find_ui_candidates(text,rel,rules)
    changes=[]
    for c in candidates:
        if not c.rewrite: continue
        key=source_to_key.get(c.source)
        if not key: continue
        if 'OptiScalerCN::Loc::T(' in c.original_expr or 'OptiScalerCN::Loc::F(' in c.original_expr: continue
        if c.callee == 'nested:std::format':
            expr=c.original_expr
            p=expr.find('(')
            q=find_matching(expr,p) if p >= 0 else -1
            if p < 0 or q < 0:
                raise RuntimeError(f'integration conflict: cannot parse nested std::format at {rel}:{c.line}')
            args=split_args(expr,p+1,q)
            if not args:
                raise RuntimeError(f'integration conflict: std::format without format argument at {rel}:{c.line}')
            a0,b0=args[0]
            fallback=expr[a0:b0].strip()
            tail=expr[b0:q]
            repl=f'OptiScalerCN::Loc::F("{key}", {fallback}{tail})'
        else:
            repl=f'OptiScalerCN::Loc::T("{key}", {c.original_expr})'
        changes.append((c.start,c.end,repl))
    if not changes: return 0
    for a,b,repl in reversed(changes): text=text[:a]+repl+text[b:]
    if INCLUDE_LINE.strip() not in text:
        pch='#include "pch.h"\n'
        if pch in text: text=text.replace(pch,pch+INCLUDE_LINE,1)
        else: text=INCLUDE_LINE+text
    write_source_text(path, text, source_encoding)
    return len(changes)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--source',required=True,type=Path); ap.add_argument('--channel',choices=CHANNELS,default='master'); args=ap.parse_args()
    paths=localization_channel_paths(args.channel)
    cat=load_json(paths['catalog'],{}); rules=load_json(LOC/'scanner-rules.json',{})
    active={k:v for k,v in cat.get('entries',{}).items() if not v.get('obsolete')}
    source_to_key={v['source']:k for k,v in active.items()}
    generated=args.source/'OptiScaler'/'localization'/'generated'/'Strings.generated.h'
    dst=args.source/'OptiScaler'/'localization'; dst.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'overlay'/'OptiScaler'/'localization'/'Localization.h',dst/'Localization.h')
    subprocess.run([sys.executable,str(ROOT/'tools'/'generate_cpp.py'),'--channel',args.channel,'--out',str(generated)],check=True)

    pch=args.source/'OptiScaler'/'pch.h'
    if not pch.exists(): raise RuntimeError('integration conflict: OptiScaler/pch.h missing')
    patch_precompiled_header(pch)

    total=0
    for p in iter_source_files(args.source,rules):
        rel=p.relative_to(args.source).as_posix()
        total += instrument_file(p,rel,rules,source_to_key)

    menu=args.source/'OptiScaler'/'menu'/'menu_common.cpp'
    if not menu.exists(): raise RuntimeError('integration conflict: OptiScaler/menu/menu_common.cpp missing')
    patch_font_and_init(menu)
    patch_dynamic_helpers(menu)
    print(f'instrumented {total} literal UI arguments')

if __name__=='__main__':
    try: main()
    except Exception as e:
        print(f'ERROR: {e}',file=sys.stderr); raise
