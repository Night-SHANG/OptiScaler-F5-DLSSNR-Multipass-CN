# 参与维护

欢迎报告翻译语义、漏译来源、显示边界、字体和构建集成问题。请先阅读 [UPSTREAM.md](UPSTREAM.md) 与 [TRANSLATION.md](TRANSLATION.md)。本仓库固定 F5 v0.1.32，不能直接套用 PreSR 分支或旧版 Release 的假设。

## 修改前

记录完整上游与中文仓库提交。新增源文必须能追溯到固定上游的实际显示路径；涉及动态状态时同时核对生产者和最终显示位置。不要只为使统计数字变好而加入无显示用途的词条。

保持格式占位符、隐藏 ID、配置键/值、判断字符串、品牌和技术标识不变。AI 翻译或审校保留 `machine_translated`，真实人工确认后才可用 `reviewed`。复用项保留已有来源，不把重新生成解释为重新审校。

## 检查步骤

Python 3.12 与 Git 可用于源码工具测试；完整 DLL 构建还需要工作流中的 Windows / MSVC 环境。先运行：

```sh
python -m compileall -q tools tests
python -m unittest discover -s tests -v
python tools/check_localization.py --strict --channel master
python tools/update_translation_memory.py --check
python tools/generate_cpp.py --channel master --out reports/Strings.F5.generated.h
```

源文/扫描规则有变化时，在干净副本运行：

```sh
python tools/prepare_tree.py
python tools/scan_ui.py --source _upstream --channel master --upstream-ref v0.1.32 --update --report reports/build-scan.md
python tools/check_localization.py --strict --channel master
python tools/prepare_tree.py --verify
```

检查并提交预期的词库差异，再重复扫描，确认 `git diff --exit-code -- Localization` 无漂移。扫描报告只反映该扫描器的候选范围。人工确认译文后，可运行 `python tools/update_translation_memory.py` 同步其允许记录的条目，再执行 `--check`。

已有 `_upstream` 时，准备工具会拒绝直接覆盖。`--clean` 只可重建该工具自己拥有的临时树，并会删除其中临时修改；个人工作必须另行保存。应用 `localize_f5.py` 之后的源码树不再是 pristine 树，不要用它反向生成源清单。

## 显示与构建适配

在 `localize_f5.py`、显示包装层或字体适配中保持最小确定性修改。锚点不匹配应失败并查明原因，不能放宽到全文件英文替换，也不能跳过失败检查。

增加相应回归样例：原始配置/判断保持、普通与动态 ImGuiID、格式和组合状态、字体失败回退。修改后运行全部测试，并在 [build.yml](.github/workflows/build.yml) 中核验该提交的可移植契约测试、真实 MSVC Release x64 构建及安装包检查。游戏内 GPU/排版测试另行记录，未执行的环节明确注明。

不要提交密钥、令牌、个人路径日志、`_upstream/`、编译输出或无再分发依据的第三方二进制。保留许可证与署名。当前流程仅上传 Actions artifacts 和诊断日志，不创建 GitHub Release；不要为方便发布而加入自动接受第三方许可的开关。
