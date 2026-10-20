# OptiScaler F5 中文版使用说明

本项目为 **OptiScaler F5 DLSSNR Multipass v0.1.32** 提供简体中文显示适配，固定上游提交为 `fadc3bf67f6c8548e94914baec3f2e551ba8d8a4`。它是社区派生项目，不是上游官方发布。

源代码与维护说明：[中文仓库](https://github.com/Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN) · [固定上游](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/tree/fadc3bf67f6c8548e94914baec3f2e551ba8d8a4) · [上游安装指南](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/blob/fadc3bf67f6c8548e94914baec3f2e551ba8d8a4/INSTALL-DLSSNR.md)

## 下载内容与验证边界

提供 GitHub Actions 构建流程；授权测试入口仅能发布固定标签 `v0.1.32-cn-test.1` 的 Pre-release，须先通过同次 Windows 编译、可移植测试及产物校验，详情见 [测试发布门槛](https://github.com/Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN/blob/main/TEST-RELEASE.md)。可从仓库 Releases 查找实际已发布的测试版，不能仅凭此说明认定发布已完成。从一次成功的 `Build pinned F5 Chinese artifact` 运行中取得 `OptiScaler-F5-CN-v0.1.32-<CN提交>` artifact；其中包含安装 ZIP、同名 `.sha256` 和 `build-metadata.json`。Actions 下载的外层 ZIP 需先解开，再解开里面的安装 ZIP。

安装 ZIP 中保留上游英文说明，并增加 `README.CN.zh-CN.md`、`UPSTREAM.CN.md`、`OptiScalerCN.ini`、`BUILD-INFO.CN.json` 和重新生成的 `SHA256SUMS.txt`。构建记录列出中文仓库提交、固定上游、子模块、工具链及文件哈希。

**[Windows 构建基线已通过](https://github.com/Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN/actions/runs/39373596303)：MSVC v143 Release x64、125 项测试、完整包校验。Windows 游戏内 GPU 渲染、中文排版及真实硬件兼容性尚未验收。** 请以对应提交的 Actions 日志和产物为准，保留原安装备份。

## 依赖与安装包差异

这里采用固定上游的 **downloader-only** 打包方式，不能假定与任意上游 Release ZIP 的内容相同。

- 包含本次源码编译的 `OptiScaler.dll` 和 `nvngx.dll_dlssnr.dll`，以及上游构建阶段要求的后端依赖和许可证。
- 包含固定来源、校验哈希的 15 个 hybrid 资源及其许可。资源存在不代表已在相应 GPU 上验证。
- **不包含 `nvngx_dlssnr.dll`**。这是另行取得的 NVIDIA Neural Rendering 运行库，与开源转发器 `nvngx.dll_dlssnr.dll` 是两个不同文件。
- 不预打包可选的 NVIDIA DLSS/Streamline 帧生成 DLL、Ampere MFG DLL 或外部 vendor-neutral port。保留上游 `get_streamline.ps1` 和清单；是否取得可选依赖、接受其许可由使用者决定。
- 不附带 Windows 中文字体，也不修改系统字体。优先使用使用者指定的字体或已有 Windows CJK 字体。

固定上游安装指南要求受支持的 64 位游戏、NVIDIA 驱动 616.56 或更新版本，以及适合 GPU 的 310.8 NR 运行库。RTX 50 与 RTX 20/30/40 所用文件不同；获取来源及 SHA-256 请查阅上面链接的固定版本安装指南。不要根据文件名猜测兼容性，也不要为了安装关闭安全保护。

本仓库所构建的转发器走 NVIDIA NGX 路径。不能把上游文档中可选的 vendor-neutral port 说明理解为本包已支持或验证 AMD/Intel GPU。

## Windows 安装

1. 关闭游戏和启动器，备份现有代理 DLL、`OptiScaler.ini` 和整个旧安装。
2. 检查安装 ZIP 的 SHA-256 与同次构建的 `.sha256` 一致。将安装 ZIP 的**全部文件**解压至实际游戏 EXE 所在目录，不要只复制 DLL。
3. 按固定上游指南另行取得并校验适合 GPU 的 `nvngx_dlssnr.dll`，放在同一目录。
4. 运行上游保留的 `setup_windows.bat`，按游戏情况选择代理名称和 NVIDIA 路径。已有其他注入器时先查上游指南，不要随意覆盖其 DLL。
5. 启动游戏，按 `Insert` 打开菜单。先用单 Pass 测试神经渲染，再调整模型分辨率等参数；额外 Pass 会增加性能开销。

`setup_windows.bat`、`setup_linux.sh`、生成卸载器和 `get_streamline.ps1` 的自有交互提示已汉化；文件名、命令和选择键保持原样。上游 INI 注释和长篇技术文档保留原文。带反作弊保护的多人游戏不要使用注入模组。卸载使用安装脚本产生的卸载方式，并按备份恢复原有文件。

## 语言与字体

DLL 所在目录的 `OptiScalerCN.ini`：

```ini
[Localization]
Language=zh-CN
FontPath=
```

- 改为 `Language=en-US` 可使用英文；修改后重启游戏。
- `FontPath` 可指定可读取的中文字体路径；相对路径以 DLL 目录为基准。留空时先检查上游 `[Menu] TTFFontPath`，再尝试已有 Windows CJK 字体。
- 字体必须覆盖当前有效中文词库使用的字符。适配将中文字形合并到 Hack、Inter，以及配置的 Classic 字体，兼顾菜单和等宽状态显示。
- 字体不可用、缺字或注册失败时，整套本地化退回英文，避免半中文界面。若始终显示英文，请检查字体路径与字符覆盖。未识别或不可用的译文也保留英文。
- 当前字形集合按词库建立；任意中文 LUT 文件名等用户输入的全部字符不在保证范围内。主题切换、缩放、通知、长提示和极端分辨率仍需游戏内截图验收。

## 构建与核验

推荐使用仓库 [build.yml 工作流](https://github.com/Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN/blob/main/.github/workflows/build.yml)：手动触发、`main` 推送和 PR 均可运行；两个构建任务只读仓库，不定时跟随上游。另有严格门控的测试发布任务，只有它具有 `contents: write` 与核对同次任务所需的 `actions: read`；不会自动发布普通提交或 PR。

- `portable-contracts`：Ubuntu 24.04 上检查固定源码、词库、Python 测试，并用 g++ 运行显示层/真实 ImGui 契约探针；不下载完整递归构建依赖。
- `build`：Windows 2022、Python 3.12、Visual Studio 2022 / MSVC v143 与上游要求的 Windows SDK。先验证固定源码和递归子模块，再做扫描/严格检查和测试，应用显示适配，编译转发器与 `OptiScaler.sln` 的 Release x64。保留原有 PostBuildEvent，不用占位 DLL 或跳过编译伪造成功。

在干净的仓库副本中可复现源码检查：

```sh
python tools/prepare_tree.py
python tools/scan_ui.py --source _upstream --channel master --upstream-ref v0.1.32 --update --report reports/build-scan.md
git diff --exit-code -- Localization
python tools/check_localization.py --strict --channel master
python -m unittest discover -s tests -v
python tools/prepare_tree.py --verify
python tools/localize_f5.py --source _upstream --channel master
```

`prepare_tree.py --verify` 仅用于应用中文适配之前的原始源码树。已有 `_upstream` 时脚本不会覆盖它；`--clean` 只允许重建该工具自己标记的临时树，会删除其中的临时修改，不能用于保存个人工作。

完整 MSBuild 命令、日志和 `reports/build-evidence.json` 的产生步骤见工作流。完成同一提交的真实构建与全部前置报告后，在 PowerShell 中运行：

```powershell
./tools/package.ps1 -SourceRoot ./_upstream -OutputDir ./dist
```

`dist` 必须是尚不存在的新目录；打包器拒绝缺失或过期的构建证据。成功时上传安装 artifact；两个任务无论成功失败，均尝试上传各自的 `build-diagnostics-<运行编号>-<尝试次数>` 或 `portable-contracts-<运行编号>-<尝试次数>` 报告，保留 14 天。ZIP/二进制校验通过仍不等于游戏运行验证。

## 报告问题

请提供中文仓库提交或 artifact 名、上游版本、游戏、GPU、驱动、渲染 API、语言/字体/主题/缩放设置，以及具体页面截图和可复现步骤。日志中可能含有个人路径，分享前请检查。

翻译问题和中文适配回归提交到本中文仓库。上游也会出现的问题，请附英文模式复现与固定上游版本。来源、署名及各组件许可见仓库 `UPSTREAM.md`，安装包内见 `UPSTREAM.CN.md`；主许可证原文保持不变。
