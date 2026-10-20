# F5 简体中文覆盖与验收清单

固定上游：`janblade/OptiScaler-F5-DLSSNR-Multipass@fadc3bf67f6c8548e94914baec3f2e551ba8d8a4`（v0.1.32）。本记录截至 2026-10-20 13:20（北京时间），属于源码与可移植测试证据；Windows 构建结果以对应 Actions run 为准。

## 扫描分母与来源

- 扫描规则遍历 **747** 个源码文件，覆盖 `.cpp/.h/.inl` 与通知渲染器的窄 `.hpp` 例外。
- **63** 个文件产生 **2888** 处来源，合并为 **2385** 条活动条目：**2191** 条变更译文、**194** 条原样技术项。缺失 0，过期 0。
- 原样项逐条理由见 [retained-English.json](Localization/retained-English.json)，全部文件列表与计数见 [coverage-inventory.json](reports/coverage-inventory.json)。候选中包含少量内部 ID/数值格式；这不是“2385 个独立控件”或“所有运行时文字 100% 覆盖”。
- 初始旧扫描器仅有 1399 条（旧源文精确复用 920，新条目 479）；后续全树追踪、异常路径和组合状态扩大了清单。初始数字不作为最终覆盖分母。
- 当前 244 条沿用旧库 `reviewed` 状态，2141 条保持 `machine_translated`。没有把本次 AI 生成或 AI 审校自动标为人工审核。
- 旧机器译文审校从初始 686 条扩大至 **692** 条，逐条核对含义、条件、风险和格式，合入 55 处语义修订。完整原状态/原译文/修订/证据见 [reused-2026-10-19.json](Localization/reviews/reused-2026-10-19.json)。

## 已扫描并接通的显示面

| 区域 | 覆盖内容与边界 |
|---|---|
| 主菜单、Classic/Modern、导航、浮层 | 所有常规标签、按钮、选项、帮助、快捷键状态、FPS/延迟数据、保存/重载提示、绘制与测宽。导航 label 翻译，持久化 name 原样 |
| 合并后的 NR 菜单 | 输入/模型/输出、曝光与白点、多轮处理、调试、预设、帧间复用、边缘压缩、LUT、F5 开关及发现提示 |
| F5 原生路径 | DX11/DX12/Vulkan 状态、光流/信任/场景切换错误、虚拟超分与呈现桥拒绝原因、低延迟与帧率状态 |
| 深度查找器 | DX11/DX12/Vulkan 标签、选中尺寸、反向 Z、不可读原因、重启后状态 |
| 间接状态 | `.inl` 的完成图像/Deferred SR 状态、颜色编码、曝光校准测量与比较、ViT/细节/编辑缓存、Hybrid 初始化/异常/计数 |
| 帧生成与旧路径 | MFG temporal/flip metering、Ampere loader、桥接设置、低延迟选择、旧下采样 tooltip 的附加禁用段落 |
| 通知 | hook/FeatureProvider/XeSS/forwarder 等产生的标题、正文、按钮、默认 Success/Warning/Error/Info；不改生产者缓冲与逻辑 |
| 动态组合 | 49 个显式组合模板；数字格式、嵌套状态、LUT 解析错误、Hybrid 计数、Streamline DLL 列表。CompareWords 按其明确语法在显示边界处理 |

当前物化适配了 **962** 个显示调用，分布在 **11** 个上游文件；此外仅对字体初始化和 ImGui 原始 ID 恢复做窄适配。配置键、接口、枚举、源码生产者字符串和模型/GPU 算法不汉化。

## 英文保留与数据保护

品牌、API、模型/内核名、GPU 枚举、文件格式 token、数值单位、路径、用户 LUT 文件名及许可证保持原样。未知外部 DLL/驱动/操作系统异常保留原诊断；本仓生成并进入 UI 的异常已纳入清单。

用户 LUT 文件名在独立显示边界转为 UTF-8，并绕过词库，即使名字是 `Off` 或 `Auto (On)` 也不翻译。存储路径和配置解析保持上游行为。LUT 错误中的用户行内容、路径和 shader/export 标识使用 raw 字段，不能把 `%n`、花括号或 `##` 重新当格式串执行。

安装 `.bat/.sh` 与 Streamline PowerShell 入口已接入中文适配：4 个入口共 235 行中文提示（含生成卸载器与暂停提示），40 行精确技术标识保留原文；详见 [安装交互覆盖清单](INSTALLER-COVERAGE.md)。它们单独计数，不混入 2385 项 UI 词库。INI 注释及上游长篇文档保持英文；[中文安装说明](README.zh-CN.md) 提供中文入口。

## 已完成的检查

- 严格词库检查：所有活动条目源文哈希、printf/C++ 格式字段、顺序和隐藏后缀一致；0 缺失/0 过期。
- 当前 125 项单元测试：[Windows CI 39373596303](https://github.com/Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN/actions/runs/39373596303) 全部 125 项通过，零跳过；云端 Linux 加官方 PowerShell 7.6.7 后 124 项通过，仅 cmd.exe 专用夹具跳过。测试通过不代表 Windows GPU 游戏验证。
- 独立可移植显示契约：168 项断言，使用当前上游真实 `ImHashStr` 与非零作用域 seed；包装器主要重载按真实 ImGui 头文件编译。验证 plain/`##`/`###`/动态标签/显式切片、语言回退、输入缓冲和选中索引、原数组、格式与 raw 数据。
- MSVC 首次完整编译发现的 Begin/InputScalar `NULL` 转换和 PlotLines 回调重载缺口已补齐；新增 24 项实际调用行为回归，旧头负对照会明确失败。上述 Windows CI 已完成真实 MSVC v143 Release x64 编译确认。
- 58 条固定预期的真实运行时样本在 C++17/C++20 各通过 58/58，包含旧多行 tooltip、嵌套异常、路径、状态和组合语序。
- 204 条独立可见源文代表探针全部命中，3 个持久化键正确排除。它们证明代表性条目的纳入，不证明穷举覆盖。
- 字体适配的编译 stub 检查涵盖 HQ 开/关、三字体、配置字体、初始化回退与上下文重建；额外云端真实 ImGui/STB smoke 检查过 CJK 字形与 Hack 等宽数字、主题切换。它们不是 Windows FreeType/GPU 截图。
- 所有中文仍在动态显示副本中，未写回上游 48/96/192 字节固定缓冲；静态译文最长 571 UTF-8 字节。当前词库共有 948 个非 ASCII 码点，字体选择逐字验证当前集。

## 已验证的 Windows 构建与安装包

[基线提交 6f6195c54565](https://github.com/Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN/actions/runs/39373596303) 已完成两项 CI、真实 MSVC 编译、完整打包和上传。下载真实 Actions artifact 后，在另一云端进程用发布器离线重验 **106** 个包内文件、内部校验清单、两枚 DLL、15 项 Hybrid 资源与三个中文安装入口，全部通过。回执与关键文件 SHA-256 见 [Windows 构建回执](reports/windows-build-validation-2026-10-20.json)。

测试 Release 会从精确发布提交重新运行同样检查，最终发布包以该次 CI 与包内 `BUILD-INFO.CN.json` 为准；上述基线包哈希不能代替最终发布包哈希。

## 尚未验证的运行时范围

- Windows 游戏中的全部菜单、tooltip、通知与浮层的实际视觉效果、裁切和不同缩放。测宽适配已接通，但不能据此宣称不存在截断。
- DX11/DX12/Vulkan、各 GPU/模型/帧生成路线的真实游戏渲染及性能回归。
- 任意用户输入的所有中文字符、外部诊断编码和上游持久化路径的所有代码页组合。当前字库按词库建立，不承诺任意 Unicode 完整覆盖。
- 缺少中文字体时恢复英文；内部警告目前没有单独显示或写日志，应依据 README 配置字体检查。

构建通过、词库零缺失和代表样本通过均不能替代以上实际验收。发现遗漏时需记录“来源 → 组合 → 显示边界”，并新增精确回归，而非仅把英文片段放进词库。
