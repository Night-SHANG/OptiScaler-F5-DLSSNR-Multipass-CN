# OptiScaler F5 DLSSNR Multipass CN

[janblade/OptiScaler-F5-DLSSNR-Multipass](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass) 的社区简体中文适配层。固定上游为 **v0.1.32**，提交 **`fadc3bf67f6c8548e94914baec3f2e551ba8d8a4`**。本项目不是上游官方中文版。

本仓库维护词库、显示边界适配、中文字体处理和可复现的构建流程；构建时取得固定上游源码及其递归子模块，不复制整份上游到本仓库，也不追踪浮动 `main` 自动升级。

- [中文安装、依赖与构建说明](README.zh-CN.md)
- [来源、固定版本与许可](UPSTREAM.md)
- [翻译范围、实现与验收边界](TRANSLATION.md)
- [贡献与检查步骤](CONTRIBUTING.md)
- [构建工作流](.github/workflows/build.yml)

## 当前交付边界

工作流包含 Linux 可移植契约测试及 Windows 2022 / MSVC v143 Release x64 构建，上传 Actions artifact 与诊断日志；**不创建 GitHub Release**。只有具体运行成功后才有可下载的构建产物，仓库中的工作流和测试不等同于已完成编译。

中文适配面向主菜单、NR/F5 页面、提示、通知及已识别的动态状态显示路径。原始配置值、比较逻辑、着色器标识和用户文件名不作为中文替换目标。扫描条目全部有译文，也不能证明所有运行时界面都已覆盖。

**Windows 游戏内 GPU 渲染、中文排版、全部主题/缩放和真实硬件兼容性尚未验收。** 这仍是实验性模组；勿用于带反作弊保护的多人游戏。

## 许可与致谢

保留上游 [GPL-3.0 许可证原文](LICENSE)；依赖、字体与素材遵循各自许可。感谢 OptiScaler、Dagherbou、wilsjo2、janblade、RenoDX 及其他上游贡献者。中文基础工具与精确源文译文复用自 Night-SHANG 的 PreSR-CN 项目，具体来源见 [UPSTREAM.md](UPSTREAM.md)。
