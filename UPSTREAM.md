# 上游、复用与许可证

## 初始审计基线

- 上游：[janblade/OptiScaler-F5-DLSSNR-Multipass](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass)
- 版本：`v0.1.32`
- 完整提交：[`fadc3bf67f6c8548e94914baec3f2e551ba8d8a4`](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/commit/fadc3bf67f6c8548e94914baec3f2e551ba8d8a4)
- 原分支：`main`，仅说明来源；实际构建以完整提交为准。
- 本仓库：[Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN](https://github.com/Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN)

`upstream-contract.json` 保存这个不可自动重写的审计基线；`upstream.json` 保存当前选定的完整构建 SHA。持续同步只能推进通过该契约的后续上游提交：完整源文件路径和语法结构、非显示字符串、脚本、项目、依赖 gitlink、许可证与资源指纹均受保护。仅少量明确审计过的显示字符串位置允许变化，且仍须完整扫描、零 missing/stale 与原有所有测试通过。具体见中文仓库 `CONTINUOUS-LOCALIZATION.md`。

完整构建的子模块使用固定提交记录的递归 gitlink，不执行 `submodule update --remote`。不兼容升级必须人工复审扫描范围、显示边界、字体锚点、构建和打包契约，不能自动重新生成契约让失败消失。

## 改动范围

这是薄层适配仓库：保留词库、工具、适配头文件、测试与文档。上游完整源码下载到忽略提交的 `_upstream/`。工作流仅在该临时副本中加入显示调用包装、精确原始 ImGui ID 恢复和字体初始化适配；源文生产者的配置值、算法和判断语义不应改写。

主菜单、NR/F5、通知和动态状态的文本到达显示边界后才翻译。原始 INI 节/键/值、持久化菜单页名、比较字符串、内核/API 标识与用户路径保留原义。动态字符串或外部错误未匹配时继续显示原文。具体约束和验证边界见中文仓库的 `TRANSLATION.md`。

## 中文基础复用

工具、词库结构及精确源文匹配的译文复用自 [Night-SHANG/OptiScaler-DLSSNR-PreSR-Multipass-CN](https://github.com/Night-SHANG/OptiScaler-DLSSNR-PreSR-Multipass-CN)，基线为 [`6de9e17a2c49996f2ea888d278c7f034780bd1a7`](https://github.com/Night-SHANG/OptiScaler-DLSSNR-PreSR-Multipass-CN/commit/6de9e17a2c49996f2ea888d278c7f034780bd1a7)。复用不代表 F5 调用路径、打包规则或文案语义与 PreSR 相同。

F5 新增了整树显示来源清点、`.inl` 与间接状态来源识别、显示边界包装、字体适配和固定版本构建契约。旧版专属的 v0.8.3、多变体 Release 与自动同步契约不适用于本仓库。翻译条目保留原始来源及审校状态；AI 审校不能升级为人工 `reviewed`。

## 主许可证与第三方署名

根目录 `LICENSE` 保留固定上游的 **GNU GPL version 3** 全文，不翻译或替换法律文本。本项目的中文适配沿用该许可；第三方代码、字体、模型与素材须分别遵守其原许可。提供构建文件不代表获得任意第三方运行库的再分发授权。

上游项目继承 OptiScaler、Dagherbou、wilsjo2 等项目，并采用 RenoDX 等组件。完整贡献与来源说明请查阅固定上游的 [CREDITS.md](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/blob/fadc3bf67f6c8548e94914baec3f2e551ba8d8a4/docs/CREDITS.md) 和 [Licenses 目录](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/tree/fadc3bf67f6c8548e94914baec3f2e551ba8d8a4/Licenses)。打包保留上游署名、许可证和依赖许可；中文说明不取代这些文件。

## Hybrid 资源与可选运行库

固定上游的 hybrid 取材流程使用 [wilsjo2 v0.7.5-nr-fixes ZIP](https://github.com/wilsjo2/OptiScaler-DLSSNR-PreSR-Multipass/releases/download/v0.7.5-nr-fixes/OptiScaler-DLSSNR-v0.7.5-nr-fixes.zip)，其 SHA-256 固定为：

`3e735f825b85872d20c35c0d75404c1a28b7b6e11ca28ef06243a18225191037`

打包校验整个来源 ZIP、15 个资源及其清单，并在 `Licenses/HybridSource/` 保留来源包中的许可与声明。资源路径和逐文件哈希记录在构建元数据中。

构建产物采用上游默认 downloader-only 契约，不自动启用接受 NVIDIA/Ampere 许可的选项。专有 `nvngx_dlssnr.dll`、可选 DLSS/Streamline 和外部 vendor-neutral port 不在本包交付范围；运行所需的独立下载与许可由使用者按固定上游说明处理。

## 验证声明

源码测试、静态扫描、主机 C++ 探针、Windows 编译、安装包完整性与实际游戏 GPU/UI 验收是不同环节。只报告实际完成的环节；构建元数据明确记录本流程不执行游戏运行验收。词库计数不能作为所有界面、所有语言排版或所有 GPU 已验证的证明。
