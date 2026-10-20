#!/usr/bin/env python3
"""Golden real-source rendering regressions, independently reviewed 2026-10-19.

58 representative real display cases cover nested/composed output, not an exhaustive
coverage percentage. Expected text is fixed here; this test never derives expected
translations from the catalog under test. Run after materialization:
  python test_real_display_samples.py --repo target
It compiles and runs the actual runtime/UI headers under C++17 and C++20, with only
Windows locale initialization and the final ImGui drawing function stubbed.
"""
from pathlib import Path
import argparse, json, shutil, subprocess, sys, tempfile
CASES = [
    ('Original FP8 fallback: M=1024 dims=32x32 no supplied contraction template', '回退至原始 FP8：M=1024，尺寸=32x32；未提供收缩运算模板'),
    ('Original FP8 fallback: M=1024 dims=32x32 initialization: Missing asset C:\\OptiScaler\\nvfp4\\hybrid\\Off.bin | rewritten original launches: 5 | candidate split contractions: 7', '回退至原始 FP8：M=1024，尺寸=32x32；初始化：缺少资源 C:\\OptiScaler\\nvfp4\\hybrid\\Off.bin | 已重写的原始启动次数：5 | 候选拆分收缩次数：7'),
    ('model DLL or capability parameters unavailable', '模型 DLL 或能力参数不可用'),
    ('model initialization failed', '模型初始化失败'),
    ('model feature creation failed', '创建模型功能实例失败'),
    ('model evaluation failed', '模型执行失败'),
    ('invalid model feature or capability parameters', '模型功能实例或能力参数无效'),
    ('Missing fused helper/driver export cuCtxPushCurrent_v2', '缺少融合助手/驱动导出 cuCtxPushCurrent_v2'),
    ('Fused D3D-address encoding failed status 7 pop 2', '融合 D3D 地址编码失败，状态码 7，弹出上下文状态 2'),
    ('D3D12 status 2147500037', 'D3D12 状态码 2147500037'),
    ('NVAPI status -1', 'NVAPI 状态码 -1'),
    ('could not open C:\\aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.cube', '无法打开 C:\\aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.cube'),
    ('Designed primarily for downscaling.\nRetains good contrast with minimal artefacts, but softer than Lanczos.\n\nOnly FSR1 and Bicubic are supported when Ratio is below 1.0.', '主要为降采样设计。\n能很好保留对比度且伪影较少，但比 Lanczos 更柔和。\n\n当比例低于 1.0 时仅支持 FSR1 和 Bicubic。'),
    ('Similar to Lanczos3.\nFar less prone to artefacting than Lanczos3, but much heavier on the GPU.\nConsidered the best along with Lanczos3.\n\nOnly FSR1 and Bicubic are supported when Ratio is below 1.0.', '与 Lanczos3 类似。\n伪影明显少于 Lanczos3，但 GPU 开销大得多。\n通常与 Lanczos3 并列为最佳方案。\n\n当比例低于 1.0 时仅支持 FSR1 和 Bicubic。'),
    ("Colour: saturation as the game's, warmer", '色彩：饱和度与游戏相同，更暖'),
    ("Colour: 20% more saturated than the game's, slightly cooler", '色彩：相对游戏画面，饱和度变化 20%（增加），略冷'),
    ('Shadows (30% of the picture): 10% darker, nothing crushed', '阴影（占画面 30%）：变暗 10%，没有暗部压黑'),
    ("Shadows (30% of the picture): kept as the game's, 2.5% of the picture crushed toward black", '阴影（占画面 30%）：保持游戏原样，画面的 2.5% 被压向黑色'),
    ('more detail (+20%), more flicker (+10%, worse), less saturated (-5 points)', '细节增加（+20%）；闪烁增加（+10%，更差）；饱和度减少（-5 个百分点）'),
    ('flicker was none, now 0.05000 (worse)', '闪烁：之前为零，当前为 0.05000（变差）'),
    ('Auto (Game exposure)', '自动（游戏曝光）'),
    ("Auto (Game's setting)", '自动（游戏设置）'),
    ('Auto (Native look)', '自动（原生外观）'),
    ('Light (85 / 95)', '轻度 (85 / 95)'),
    ('Balanced (80 / 90)', '均衡 (80 / 90)'),
    ('Strong (70 / 80)', '强力 (70 / 80)'),
    ('Compress screen edges: Off', '压缩画面边缘：关闭'),
    ('Bottleneck reuse: computed 20, reused 10 (3 from a copy)', '瓶颈复用：已计算 20，已复用 10（其中 3 来自副本）'),
    ('off for this session (unexpected NR launch order)', '本次会话已关闭（NR 启动顺序不符合预期）'),
    ('Paper white (editing point 3)', '纸白亮度（正在编辑点 3）'),
    ('> scan 0.1234  ->  white 80.00   [editing]', '> 扫描 0.1234  ->  白点 80.00   [编辑中]'),
    ('could not open C:\\LUTs\\Off.cube', '无法打开 C:\\LUTs\\Off.cube'),
    ('LUT_3D_SIZE is missing its number (line 18)', 'LUT_3D_SIZE 缺少数值（第 18 行）'),
    ('LUT_3D_SIZE 99 is out of range (2..65)', 'LUT_3D_SIZE 99 超出范围（2..65）'),
    ('DOMAIN_MIN needs three numbers (line 2)', 'DOMAIN_MIN 需要三个数值（第 2 行）'),
    ('could not parse line 7: Off %n {0}##id', '无法解析第 7 行：Off %n {0}##id'),
    ('data row on line 12 needs three numbers', '第 12 行的数据需要三个数值'),
    ('a data row appeared before LUT_3D_SIZE (line 3)', '在 LUT_3D_SIZE 之前出现了数据行（第 3 行）'),
    ('more data rows than LUT_3D_SIZE 17 calls for', '数据行数超过 LUT_3D_SIZE 17 所需数量'),
    ('expected 4913 data rows for LUT_3D_SIZE 17, found 4900', '预期 4913 行数据（LUT_3D_SIZE 17），实际为 4900 行'),
    ('waiting for GPU completion slots; clean SR frame retained (NR frames 12, skipped 9)', '正在等待 GPU 完成槽位；保留未叠加 NR 的超分帧（NR 帧数 12，跳过 9）'),
    ('FP8 selected | rewritten original launches: 5 | candidate split contractions: 7', '已选择 FP8 | 已重写的原始启动次数：5 | 候选拆分收缩次数：7'),
    ('Fused hybrid M=1024 dims=32x32 expansion block 3', '融合混合模式 M=1024，尺寸=32x32，扩展块 3'),
    ('Candidate hybrid M=1024 dims=32x32 FFN pairs recorded 8/8 (16/16 original launches); other operators FP8', '候选混合模式 M=1024，尺寸=32x32，已记录 FFN 对 8/8（原始启动次数 16/16）；其他算子使用 FP8'),
    ('Original FP8 fallback: M=1024 dims=32x32 unsupported original module hash', '回退至原始 FP8：M=1024，尺寸=32x32；原始模块哈希不受支持'),
    ('Original FP8 fallback: hybrid init failed: External API error 0x0001', '回退至原始 FP8：混合模式初始化失败：External API error 0x0001'),
    ('Could not start: no bytecode for OpticalFlow Luma', '无法启动：缺少 OpticalFlow Luma 的字节码'),
    ('Could not start: no bytecode for TrustMask Classify', '无法启动：缺少 TrustMask Classify 的字节码'),
    ('Could not start: no bytecode for SceneCut Reduce', '无法启动：缺少 SceneCut Reduce 的字节码'),
    ('Could not start: creating the pipeline Classify', '无法启动：正在创建管线 Classify'),
    ('Error writing dlssg_sm86.ini: Could not finish writing dlssg_sm86.ini', '写入 dlssg_sm86.ini 时出错：无法完成 dlssg_sm86.ini 的写入'),
    ('Failed to load dlssg_sm86.dll (error code 126).', '加载 dlssg_sm86.dll 失败（错误码 126）。'),
    ('buffer, 512 bytes', '缓冲区，512 字节'),
    ('You are missing the following dlls from the streamline folder:\n- sl.common.dll\n- sl.dlss_g.dll\n', 'streamline 文件夹中缺少以下 DLL：\n- sl.common.dll\n- sl.dlss_g.dll\n'),
    ('TYPED DEPTH', '深度：已选中 1920x1080，反向 Z （下次启动时关闭查找器）'),
    ('TYPED PLURAL', '扫描 0.12345  →  白点 80.00（3 个点）'),
    ('TYPED RAW LOADED', '已加载：Auto (Off).cube（17^3）'),
    ('TYPED RAW LUT ERROR', 'Off.cube：无法解析第 7 行：Off %n {0}##id'),
]

TYPED = {
'TYPED DEPTH': 'OptiScalerCN::UI::Text("Depth: picked %ux%u%s%s",1920u,1080u,", reversed-Z"," (finder off at next start)");',
'TYPED PLURAL': 'OptiScalerCN::UI::Text("Scan %.5f  ->  white point %.2f   (%u point%s)",0.12345,80.0,3u,"s");',
'TYPED RAW LOADED': 'OptiScalerCN::UI::Text("Loaded: %s (%d^3)",OptiScalerCN::UI::Raw("Auto (Off).cube"),17);',
'TYPED RAW LUT ERROR': 'OptiScalerCN::UI::Text("%s: %s",OptiScalerCN::UI::Raw("Off.cube"),"could not parse line 7: Off %n {0}##id");',
}

def run(repo,source):
    compiler=shutil.which('g++')
    if not compiler: raise RuntimeError('g++ unavailable; real rendering assertions have not run')
    overlay=repo/'overlay/OptiScaler/localization'
    materialized=source/'OptiScaler/localization'
    for name in ('RuntimeText.h','ImGuiLocalization.h'):
        assert (materialized/name).read_bytes()==(overlay/name).read_bytes(), 'Materialized header is stale: '+name
    menu=(source/'OptiScaler/dlssnr/DlssNr_Menu.cpp').read_text(encoding='utf-8-sig')
    assert menu.count('OptiScalerCN::UI::Raw(OptiScalerCN::UI::ComparisonValue(cal.compareWords).c_str())')==1, 'Comparison producer bypasses its required grammar-aware display adapter'
    assert menu.count('OptiScalerCN::UI::PathUtf8(')==4, 'Not all four LUT filename display paths convert to UTF-8'
    assert 'std::string pathStr = path.string();' in menu, 'LUT stored path semantics were unexpectedly changed'
    common=(source/'OptiScaler/menu/menu_common.cpp').read_text(encoding='utf-8-sig')
    assert 'OptiScalerCN::UI::SeparatorTextEx(0, label, ImGui::FindRenderedTextEnd(label)' in common, 'help-separator labels are not localized'
    sys.path.insert(0,str(repo/'tools'));import generate_cpp
    catalog=json.loads((repo/'Localization/master/catalog.json').read_text())
    zh=json.loads((repo/'Localization/zh-CN.json').read_text())
    with tempfile.TemporaryDirectory(prefix='f5-real-display-') as directory:
        out=Path(directory);(out/'generated').mkdir()
        expected_header=generate_cpp.render_header(catalog,zh)
        actual_header=materialized/'generated/Strings.generated.h'
        assert actual_header.read_text()==expected_header, 'Materialized dictionary is stale'
        shutil.copy2(actual_header,out/'generated/Strings.generated.h')
        shutil.copy2(materialized/'RuntimeText.h',out/'RuntimeText.h')
        wrapper=(materialized/'ImGuiLocalization.h').read_text().replace('#include "Localization.h"','#include "imgui.h"\n#include <filesystem>\nnamespace OptiScalerCN::Loc { inline bool IsChineseActive(){return true;} }')
        (out/'ImGuiLocalization.h').write_text(wrapper)
        cpp=r"""#include <iostream>
#include <cstdarg>
#include <cstdio>
#include "ImGuiLocalization.h"
static std::string captured;
namespace ImGui { void Text(const char* fmt, ...){ char b[8192];va_list a;va_start(a,fmt);std::vsnprintf(b,sizeof b,fmt,a);va_end(a);captured=b; } }
int main(){ unsigned checks=0,failed=0;auto check=[&](const std::string& got,const std::string& expected){ if(got!=expected){++failed;std::cout<<"FAIL case "<<checks<<"\nactual="<<got<<"\nexpected="<<expected<<"\n";}++checks; };
"""
        for text,expected in CASES:
            if text in TYPED:
                cpp+=TYPED[text]+'\n'; expression='captured'
            else:
                function='OptiScalerCN::UI::ComparisonValue' if text.startswith('more detail (+20%)') else 'OptiScalerCN::Runtime::Translate'
                expression=function+'('+json.dumps(text,ensure_ascii=False)+')'
            cpp+='check('+expression+','+json.dumps(expected,ensure_ascii=False)+');\n'
        cpp+='std::cout<<"real rendered cases="<<checks<<" failures="<<failed<<"\\n";return failed?1:0;}\n'
        # Normalize the Python assembly's explicit separators, not data literals.
        cpp=cpp.replace(';\\ncheck(', ';\ncheck(')
        # All added line breaks after calls are actual C++ newlines.
        cpp=cpp.replace(');\\n', ');\n').replace(';}\\n', ';}\n')
        (out/'real.cpp').write_text(cpp)
        for standard in ('c++17','c++20'):
            executable=out/standard
            built=subprocess.run([compiler,'-std='+standard,'-O2','-I',str(out),'-I',str(source/'OptiScaler/include/imgui'),'-I',str(source/'OptiScaler/include'),str(out/'real.cpp'),'-o',str(executable)],capture_output=True,text=True)
            if built.returncode: print(built.stderr);return built.returncode
            result=subprocess.run([str(executable)],text=True,capture_output=True)
            print(standard+': '+result.stdout,end='')
            if result.returncode:return result.returncode
    print('source boundary integration checks passed')
    return 0

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--source',type=Path)
    args=parser.parse_args();repo=args.repo.resolve()
    raise SystemExit(run(repo,(args.source or repo/'_upstream').resolve()))
