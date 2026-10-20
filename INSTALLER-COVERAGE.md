# F5 安装与下载入口汉化覆盖

## 固定基线与接入

适配固定上游提交 `fadc3bf67f6c8548e94914baec3f2e551ba8d8a4`，对应本仓库的 F5 v0.1.32 基线。
本增量的接口为 `from f5_installer_patch import patch_installer_scripts; patch_installer_scripts(source)`。
`source` 是已检出的上游源码根目录。适配器只读写下表四个脚本；不执行脚本，不下载文件，不接受许可协议。
主 `localize_f5.py` 已接入适配器，CI 在构建前执行；打包器要求三个发行脚本与已汉化源码逐字节一致。本说明不代表已经验收完整 Windows 安装过程。

词库：`Localization/installers.zh-CN.json`。每项记录原始行号、完整源行、完整译文行、输入/输出指纹；保留项也逐行记录原文和理由。

## 覆盖分母

按**显示文本出现行**计数，重复出现的提示分别计数，安装脚本生成的卸载脚本提示也计入。
计数范围是脚本自行输出的 `echo`、`read -p`、`set /p`、`choice /m`、`Write-Host`、`Write-Error`、`throw` 文本；另列系统 `pause` 的中文替代提示。
空行、纯 ASCII 图案、命令本身、代码注释不计入文本分母。操作系统和第三方命令自身生成的诊断不计入脚本自有文案。

| 入口 | 原文本显示行 | 已译文案 | 原样保留项 | 已中文化 pause | 实际发行包 |
|---|---:|---:|---:|---:|---|
| `setup_windows.bat`，含生成的 Windows 卸载器 | 154 | 134 | 20 | 4 | 是 |
| `setup_linux.sh`，含生成的 Linux 卸载器 | 76 | 58 | 18 | 0 | 是 |
| `Streamlined_fetcher_windows.bat` | 26 | 24 | 2 | 3 | 否，仅源码树 |
| `get_streamline.ps1` | 12 | 12 | 0 | 0 | 是 |
| 合计 | 268 | 228 | 40 | 7 | |

- 可翻译文案覆盖：`(228 + 7) / (228 + 7) = 100%`，即 235 行提示均包含中文。
- 若把精确文件名、品牌、哈希等保留项也计入：275 行中 235 行包含中文，约 85.45%；另 40 行是经审查保留的技术标识，并非遗漏的英文句子。
- 实际发行包范围：246 行显示，其中 208 行中文提示、38 行技术保留项。源码中的旧 Streamline fetcher 不会因此被额外加入发行包。

覆盖已经包括选文件名、覆盖确认、GPU 选择、显卡身份伪装、OptiPatcher 下载询问、安装成功/失败、删除/卸载确认、DLSS-NR 运行库与签名警告、Linux 帮助和启动参数说明、Streamline 下载/校验/许可拒绝提示。

## 实际打包依据与下载入口

固定上游 `package_release.ps1` 的 `$sourceFiles` 清单包含 `setup_windows.bat`、`setup_linux.sh`、`get_streamline.ps1`；另单独复制 `redist/streamline/manifest.json`。
清单不包含 `Streamlined_fetcher_windows.bat`。本仓库 `tools/package.ps1` 使用上游打包器，并将上述三个脚本及 manifest 列为必需文件。

`redist/streamline/` 下只有 `manifest.json`，没有另一个可执行下载器。它由 `get_streamline.ps1` 读取：版本、下载地址、归档哈希、文件白名单、逐文件哈希及签名指纹均原样保留。
该 manifest 的固定 SHA-256 为 `62d13c33e335a42a50868b5b99803b121ea79229185c6f3f698aeb336024f691b`；以词库记录和测试核验值为准。

`get_streamline.ps1` 仍要求用户自行阅读许可并显式传入 `-AcceptNvidiaLicenses`；未传入时仍在创建目录或下载之前抛出错误。
没有新增默认同意、自动安装、忽略哈希、关闭签名验证或关闭安全防护的路径。`get_hybrid_assets.ps1`、`package_release.ps1` 和着色器构建脚本属于开发/打包工具，本增量不修改其开发日志。

## 明确保留的英文及原因

1. 40 行完整保留项分别是：Windows 安装器 20 行、Linux 安装器 18 行、旧 fetcher 2 行。词库中的 `preserved_entries` 逐行列明原因，测试要求覆盖集合与固定源文件一致。
2. DLL/脚本文件名、路径、命令行选项、INI 节名与键值、数字选项、`y/n` 和 `Y/N` 的大小写默认提示保持准确，以免改变安装行为或让用户无法照抄。
3. 品牌和技术标识，如 NVIDIA、AMD/Intel、OptiPatcher、DLSS、FSR、XeSS、SHA-256，以及实际哈希与变量输出，保持可检索和可核对。
4. Discord 的真实频道/帖子名、原菜单定位文字、URL、版本与驱动编号保留原值；其周围的说明已翻译。这里仅翻译固定上游提示，不独立更新其兼容性结论。
5. 许可证和第三方声明正文、英文 INI 注释、上游长篇文档、开发注释不纳入本次脚本显示文本分母。
6. `curl`、PowerShell、Windows `timeout`、文件系统等外部命令输出，以及 PowerShell 自动生成的参数绑定提示，随系统/工具语言显示；未改写第三方错误对象、退出码或日志。

## 编码与 Windows 代码页恢复

- BAT 输出为 UTF-8 无 BOM、CRLF；第一条中文出现之前，ASCII 前导块通过 `chcp` 保存原代码页，再切换到 `65001`。变量局部化，不写系统或用户永久设置。
- `setup_windows.bat` 的唯一正常 `exit /b 0`，以及旧 fetcher 的三个正常退出点（含 `exit /b 1` 错误退出）均在退出前恢复原代码页。原有跳转和退出码保持不变。
- 生成的 `Remove_OptiScaler.bat` 有独立的代码页保存/切换逻辑；恢复指令位于暂停之后、原有最后自删除块之前。不能依赖脚本删除自身之后再读取恢复代码。
- `echo` 生成卸载器时，百分号和括号沿用双层转义：`%%%%C`、`^(` / `^)`、`%%_F5_CN_OLD_CP%%`、`^>nul`。新增转义有静态断言及 Windows 专用无害夹具测试。
- 原 `pause` 替换为中文 `echo` 加 `pause >nul`，保持等待按键的操作。PowerShell 使用带 BOM 的 UTF-8，以兼容 Windows PowerShell 5.1；Bash 使用无 BOM 的 UTF-8 和 LF。
- 恢复保证覆盖脚本的**正常完成、正常取消与原有错误退出路径**。强制关闭进程、关闭控制台或在 Ctrl+C 提示中终止批处理会跳过余下命令，无法保证收尾恢复；这种情况下可新开终端。没有为此改变原版 Ctrl+C/控制流语义。

## 严格适配与验证边界

1. 对全部四个文件先进行 UTF-8 解码与整文件指纹预检，仅容忍 Git 的 LF/CRLF 转换；任一源文件缺失、变化或出现不完整汉化，均在写入其他文件之前拒绝。
2. 每条译文使用固定行号与完整源行锚点，限制在显式显示位置内；检查变量占位符、外围命令和必要转义，拒绝额外换行、NUL、命令连接符或参数扩展。
3. 对完整输出也固定指纹。重复应用完全相同的产物幂等；手改输出不会被静默覆盖。所有文件预检在写入前完成，但不声称跨文件写入具有文件系统事务保证。
4. 测试移除经过审查的编码/暂停支持代码，并将译文反向还原，要求整个脚本与固定上游完全一致。这包括所有下载 URL、删除/重命名命令、选择值、配置修改命令和生成卸载器的控制骨架。
5. 在云端 Linux 实际运行了 `bash -n`，以及安装脚本和从 heredoc 提取的卸载脚本的 `--help` 安全路径。未运行安装、卸载、删除、网络下载或接受许可证的操作路径。
6. Windows 专用测试只运行人工构造的 `echo/chcp/exit` 夹具以及生成这些夹具的转义块，检查 437、936、65001 的代码页恢复和退出码；不执行原安装器或卸载器。PowerShell 专用测试只解析脚本并走未同意许可的早期拒绝路径。

Windows CI 运行 `39373596303` 已实际通过全部 125 项测试，包含 `cmd.exe` 代码页/退出码夹具、PowerShell 解析/未接受许可的拒绝路径，以及 Git for Windows Bash 的语法和帮助路径。云端 Linux 已使用微软官方 PowerShell 7.6.7 复测，125 项中 124 项通过，仅 `cmd.exe` 平台测试跳过。

早期 Windows Bash 夹具误选 PATH 的 WSL stub，现已从 `git.exe` 安装目录识别 Git for Windows 的 `bin/bash.exe` 或 `usr/bin/bash.exe`，不回退到 WSL stub。语法检查和帮助调用使用临时目录作为 `cwd`、只传脚本 basename，并明确按 UTF-8 解码。Linux 仍使用 PATH 上的原生 Bash。选择器回归覆盖 Git 的 `cmd/`、`bin/`、`mingw64/bin/` 布局；修复后的 Windows 实测已通过。

尚未完成 Windows 实机终端观感、完整安装/卸载或游戏运行验证；不能将无害夹具、静态解析或帮助测试称为完整 Windows 安装验收。

## 运行测试

```sh
python -m unittest discover -s tests -p test_f5_installer_patch.py -v
python -m unittest discover -s tests -v
python -m py_compile tools/f5_installer_patch.py tests/test_f5_installer_patch.py
```

测试需要已经物化的固定上游 Git 检出，以便从固定提交读取原始脚本；不会把已汉化工作树当作原始夹具。

首次云端验证记录（2026-10-20）：专用套件共 13 项，11 项通过、2 项按上述平台条件跳过；全仓套件共 93 项，88 项通过、5 项因缺少 Windows/PowerShell 跳过，无失败。另 3 项跳过属于既有打包器 PowerShell 测试。两个 Python 文件的 `py_compile` 通过。

Bash 选择器修复后的云端 Linux 回归（同日）：专用套件共 16 项，14 项通过、2 项平台跳过；全仓套件共 119 项，114 项通过、5 项平台跳过，无失败；测试文件 `py_compile` 通过。此记录不替代修复后的 Windows CI 或完整安装实机验收。
