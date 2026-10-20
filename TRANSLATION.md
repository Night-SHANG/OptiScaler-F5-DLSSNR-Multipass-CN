# 翻译与显示适配契约

适用基线：`v0.1.32` / `fadc3bf67f6c8548e94914baec3f2e551ba8d8a4`。本文说明已采用的实现规则与验收要求，不宣称所有游戏界面完成覆盖或人工验收。

## 词库与来源

- `Localization/master/` 是当前固定 F5 基线的活动目录。根目录兼容副本由扫描器同步；保留的 `stable/` 是工具格式兼容目录，不代表另一个已构建或发布的稳定版本。
- `Localization/zh-CN.json` 保存中文、源文哈希和状态。`machine_translated` 包括 AI 翻译及 AI 审校；只有真实人工确认才可标记 `reviewed`。复用项保留原始 `model`、来源说明和哈希。
- `translation-memory*.zh-CN.json` 以完整源文复用翻译；`glossary.json` 统一术语。不能根据相似词句直接继承上下文含义。
- `composed-templates.json` 显式登记已知的组合显示模板。源文有变化时需重新审查格式、数据字段和调用来源。

前期旧机器译文专项审校检查了 692 条精确源文复用项，提出 55 条普通修订、两条关联的复数拼接记录和一条上游默认值文案矛盾。它是 AI 语言/源码语义审校，不是人工或游戏画面验收。最终采用的改动应以词库记录及回归测试为准，不把独立审校建议自动算作已修复。

## 范围与明确保留的内容

扫描包括主菜单、合并后的 `DlssNr_Menu.cpp`、NativeDriver、深度查找器、通知、字体/布局相关显示调用，以及 `.h`/`.cpp`/`.inl` 中已识别的间接状态来源。扫描器登记的是候选与来源；最终显示能否译出还取决于边界和动态模板。

原样保留以下内容：

- INI 节、键、枚举值、菜单持久化 `name`、profile 键；包括 `Auto/Retarget/Ptx` 与 `FlipMetering` 状态值
- 业务比较和分支判断，如 `Restart required:` / `fallback` 与 DeferredSlider 原始标签比较
- API、GPU、模型、内核、导出函数、文件格式 token、资源名、路径、用户 LUT 文件名及错误码
- 许可证和版权文本、日志专用诊断、未用于用户 UI 的内部窗口名称、第三方演示/调试界面

安装脚本、上游 INI 注释和长篇技术文档保持原文；中文 README 提供使用入口。本仓库不把这些原文算成已经逐条汉化。

## 在显示边界翻译

`tools/scan_ui.py` / `ui_scan.py` / `f5_scan.py` 产生清单，`generate_cpp.py` 生成编译用数据，`localize_f5.py` 只把指定显示调用接入 `overlay/OptiScaler/localization/` 包装层。旧的 `localize_source.py` 不是当前 F5 构建入口。

保持生产者原始英文及配置语义，显示时生成中文副本；动态状态支持完整源文匹配和显式模板匹配。数值、路径和技术数据不得全局子串替换。未知来源、无有效译文或模板不匹配时保留原文，外部异常文本可能继续显示英文。

ImGui 控件 ID 必须与原上游完全一致。中文标签附带内部保留标记，窄范围 `ImHashStr` 适配在执行上游 CRC/`###` 语义前恢复完整原始字节与原作用域 seed；不能简单认定追加 `###原文` 就保持了旧哈希。普通标签、`##`、`###`、动态后缀、显式字符串长度以及父级 `PushID` 都需要测试。

字符串格式必须保留 printf 类型/顺序/精度、C++ 格式字段、换行与重要首尾空白。翻译后更长的字符串应在显示层使用稳定存储；避免让中文回流上游固定长度生产者缓冲区。中文复数不需要英文 `s`，只能处理已确认模板中的复数后缀，不能全局替换字母。

## 字体与语言回退

默认 `zh-CN`，可通过 DLL 目录的 `OptiScalerCN.ini` 改为 `en-US`，重启后生效。字体优先级为 `FontPath`、上游 `TTFFontPath`、已有 Windows CJK 字体；候选字体逐字验证当前译文字符覆盖。

F5 适配同时处理 Hack、Inter 和配置的 Classic 字体。失败时清除半完成的字库，切回原有英文分支。当前运行时保留内部警告状态，但没有把它接入可见提示或日志，不能依赖弹窗来判断回退。字库范围和字体数据的生命周期必须长于使用它们的绘制过程。当前按词库建立字形集，不保证任意用户输入的所有中文字符。

## 检查与仍需验收的部分

```sh
python -m compileall -q tools tests
python -m unittest discover -s tests -v
python tools/check_localization.py --strict --channel master
python tools/update_translation_memory.py --check
python tools/generate_cpp.py --channel master --out reports/Strings.F5.generated.h
```

在未适配的固定上游源码上重新扫描，使用 [CONTRIBUTING.md](CONTRIBUTING.md) 的命令；不要对已经替换了显示调用的树生成新源清单。

严格检查可证明当前活动条目的源文哈希、格式和译文状态满足工具约束。词库计数不能证明所有显示路径被扫描，测试名称也不等于真实全界面覆盖。审查必须同时跟踪来源 → 动态组合 → 显示边界，而非只检查单词已出现在 JSON 中。

仍需在 Windows 游戏内检查：全部 NR/F5 和主菜单页面、Classic/Modern、HQ/自定义字体、菜单/FPS/通知缩放、长提示、中文文件名、英文回退、保存/重载和语言切换后的状态；并比较相同配置下的 GPU 渲染行为。当前不宣称已完成这些 GPU/UI 验收。
