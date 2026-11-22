"""Compile the real rendered-format engine against audited dynamic examples."""
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import generate_cpp

class DynamicStatus(unittest.TestCase):
    def test_profile_names_and_plugin_errors_are_not_translated_as_keys(self):
        tm=json.loads((ROOT/'Localization/translation-memory.f5-20261031-dynamic.zh-CN.json').read_text()) if (ROOT/'Localization/translation-memory.f5-20261031-dynamic.zh-CN.json').exists() else {}
        self.assertIn('Saved {}.',tm)
        tm = {**json.loads((ROOT/'Localization/translation-memory.f5-20261031.zh-CN.json').read_text()), **tm}
        catalog={'entries':{}};zh={'entries':{}}
        for i,(src,tr) in enumerate({**tm,'Reset':'重置','Off':'关闭','module not found':'找不到模块'}.items()):
            key=str(i);catalog['entries'][key]={'source':src,'source_hash':key};zh['entries'][key]={'text':tr,'source_hash':key,'state':'machine_translated'}
        cases=[('Could not save Reset: Could not write the file.','无法保存 Reset：无法写入文件。'),('Loaded Reset. LUT Off is not in OptiScaler\\LUTs: LUT off.','已加载 Reset. LUT Off is not in OptiScaler\\LUTs: LUT off。'),('Saved Reset.','已保存 Reset。'),('Loaded Off.','已加载 Off。'),('Deleted Reset.','已删除 Reset。'),('Could not save Reset: external error %n','无法保存 Reset：external error %n'),('Could not delete Off.','无法删除 Off。'),('waiting, loads after 15 s','等待中，将在 15 秒后加载'),('active: 2 of 4 patches','已启用：2 / 4 项补丁'),('failed to load (0x7E, module not found)','加载失败（0x7E，找不到模块）')]
        cases += [
            ('HDR output: active, HDR10, game white 203 nits, peak 1000 nits (display)', 'HDR 输出：已启用，HDR10，游戏白色 203 尼特，峰值 1000 尼特（显示器）'),
            ('The signal changes to scRGB at the next resolution / window change', '信号将在下次分辨率或窗口变化时变为 scRGB'),
            ('searching (3 more waiting their turn)', '搜索中（另有 3 个仍在排队）'),
            ("found the game's exposure (divisor)", '已找到游戏曝光（divisor）'),
            ('stood aside: no kernel containers', '已让路：没有内核容器'),
            ('container@12 cannot be rewritten for sm_75: null image', '容器@12 无法为 sm_75 重写：空映像'),
            ("Could not make the debug view's shared picture: CreateFence (shared) failed: 0x80070005", '无法创建调试视图的共享画面：CreateFence（共享）失败：0x80070005'),
            ('Private DLSS evaluation failed; keeping the game frame.', '专用 DLSS 求值失败；保留游戏画面。'),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'generated').mkdir();(path/'generated/Strings.generated.h').write_text(generate_cpp.render_header(catalog,zh));shutil.copy2(ROOT/'overlay/OptiScaler/localization/RuntimeText.h',path/'RuntimeText.h')
            code='#include "RuntimeText.h"\n#include <iostream>\nint main(){int bad=0;\n'
            for src,tr in cases:
                code+='if(OptiScalerCN::Runtime::Translate('+json.dumps(src)+') != '+json.dumps(tr,ensure_ascii=False)+'){std::cerr << '+json.dumps(src)+' << "\\n";++bad;}\n'
            code+='return bad;}';(path/'probe.cpp').write_text(code)
            subprocess.run(['g++','-std=c++17','-I',str(path),str(path/'probe.cpp'),'-o',str(path/'probe')],check=True,capture_output=True)
            subprocess.run([str(path/'probe')],check=True,capture_output=True)
if __name__=='__main__':unittest.main()
