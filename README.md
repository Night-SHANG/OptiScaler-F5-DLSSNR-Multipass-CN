# OptiScaler F5 DLSSNR Multipass CN

[janblade/OptiScaler-F5-DLSSNR-Multipass](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass) 的社区简体中文适配层。初始审计基线为 **v0.1.32**，提交 **`fadc3bf67f6c8548e94914baec3f2e551ba8d8a4`**。本项目不是上游官方中文版。

本仓库维护词库、显示边界适配、中文字体处理和可复现的构建流程；构建时取得固定上游源码及其递归子模块，不复制整份上游到本仓库，每次构建仍固定到完整 SHA。每日检查上游 `main`，仅在兼容性、译文和全套测试门槛通过后推进当前 `upstream.json`。

- [中文安装、依赖与构建说明](README.zh-CN.md)
- [来源、固定版本与许可](UPSTREAM.md)
- [翻译范围、实现与验收边界](TRANSLATION.md)
- [覆盖清单与未验证范围](COVERAGE.md)
- [贡献与检查步骤](CONTRIBUTING.md)
- [构建工作流](.github/workflows/build.yml)

## 当前交付边界

首个测试版 [v0.1.32-cn-test.1](https://github.com/Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN/releases/tag/v0.1.32-cn-test.1) 已发布。该版本扫描器候选 2385 项：2191 项显示译文 + 194 项有保留理由的技术项，缺失 0、过期 0；其中 reviewed 244、machine_translated 2141，AI 审校不等于人工确认。此统计不代表所有运行时 UI 100% 覆盖。

持续同步每天 03:17 UTC 检查上游，也支持手动运行。新词先复用精确源文词库；**未配置新的翻译服务**，无法复用的条目会阻止提交和发布。结构、依赖、许可证、构建或安装脚本变化超出审计契约时同样停止。只有同次 Linux 可移植检查、Windows MSVC Release x64 编译和完整产物校验通过，才创建独立测试 Pre-release；不覆盖既有标签/资产，不设为 Latest。

详见 [持续同步与失败处理](CONTINUOUS-LOCALIZATION.md) 和 [测试发布门槛](TEST-RELEASE.md)。每个包的实际上游、中文提交、覆盖统计和验证范围以其 Release 及构建元数据为准。

中文适配面向主菜单、NR/F5 页面、提示、通知及已识别的动态状态显示路径。原始配置值、比较逻辑、着色器标识和用户文件名不作为中文替换目标。扫描条目全部有译文，也不能证明所有运行时界面都已覆盖。

**Windows 游戏内 GPU 渲染、中文排版、全部主题/缩放和真实硬件兼容性尚未验收。** 这仍是实验性模组；勿用于带反作弊保护的多人游戏。

## 许可与致谢

保留上游 [GPL-3.0 许可证原文](LICENSE)；依赖、字体与素材遵循各自许可。感谢 OptiScaler、Dagherbou、wilsjo2、janblade、RenoDX 及其他上游贡献者。中文基础工具与精确源文译文复用自 Night-SHANG 的 PreSR-CN 项目，具体来源见 [UPSTREAM.md](UPSTREAM.md)。
