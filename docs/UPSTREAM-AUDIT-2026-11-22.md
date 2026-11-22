# F5 v0.1.39 中文维护核验

上游固定为 [v0.1.39](https://github.com/janblade/OptiScaler-F5-DLSSNR-Multipass/releases/tag/v0.1.39) / `956bb7198e819da857710f7f9ace223790a7ba55`。上游发布正文把本版称为预发行；CN 不按正式最新版发布。更新基线是已发行的 `v0.1.37.2-cn.1`。保留历史契约于 `audit/2026-11-11/`，不调整或放宽验证实现。

## 上游源与发行物

- 369 个变更路径，包括 Vulkan 原生 F5Low/最终画面、NR 权重与内存生命周期、DLSS-G 新预设、状态页、插件提供者和新版 FFX。验收来源是固定提交，不等于对 GPU 行为做验证。
- 新契约覆盖 1,376 个 C/C++ 路径、1,774 个字节锁定项与 17 个继承的、字节相同的结构项。没有新增可自动变更的字符串槽。10 个 gitlink 中只有 FidelityFX-SDK-v2 改到 `7539ae8b6568ad29ed78a753404351daf3b5cca7`；原
  AMD FFX v1 通用 Vulkan DLL 从上游构建复制列表移除，CN 改为逐项验证 FFX v2 当前 DX12/Vulkan 的 loader、超分和帧生成共六个 DLL。安装脚本及下载器/Streamline 清单、源打包脚本均保持原哈希。
- 上游主 ZIP `532ada6b80d1caaae222734e053f6fc992ead5bbcd01ecaac851f26e6fd66ecf`。原 DLL 和新版 `nvngx.dll_dlssnr.dll` 资源版本均为 0.1.39.1，本包以同一源码重编而不是复用原 DLL。独立的 vendor-neutral forwarder 不在主包改动范围，更不是本包的内置模型。
- [F5Low 1.1.0.208](https://github.com/janblade/f5low-fg/releases/tag/v1.1.0.208) 固定源 `46af9a0b5167d6a2ad56f350750e84ed34c8070f`，kit SHA-256 `1463f5d5851f3f82b1b79f6c113a2d9db195cec5b1aa547c85a9f924102839be`。官方 kit 全七文件（含完整 GPL 链接例外、未改 Intel XeSS-FG 1.3.4.95 和 zstd 许可、来源及哈希）均核验；F5Low、Intel 两个 DLL 与上游主 ZIP 无字节差异。保留 `FGOutput=f5low`、`FrameGenerator=xefg_tensor` 两个新安装默认，不修改用户已有配置。
- CN 延用 downloader-only NVIDIA 策略：不分发上游本地使用包里的 6 个 NVIDIA Streamline/DLSS-G DLL，不代接受许可；保留官方下载入口和清单。DLSS-NR 模型依旧需另自行提供。将自行构建的 CN 主 DLL 与 NR 转发器视为预期差异，不要求二进制与英文包相同。

## 汉化与边界

- 保留旧中文条目及来源状态，新增状态页、NR 共享权重、Vulkan 原生/桥接、F5Low/最终画面诊断、DLSS-G C 预设、超分与光线重建相关可见文字。静态审计数见 `reports/maintenance-summary.json`，不等于所有运行时 UI。
- 权重/自定义提供者/已加载 LUT 的用户文件名用原字节，不送入递归翻译。动态 LUT 已加载描述由已有结构化数据生成另一路中文显示快照，不重解析输出、不读取另一个时刻的配置，也不改变原 LUT 算法或设置。
- 继续保留第三方 DLL、驱动/系统诊断中的外部内容。不宣称实测实际游戏/显卡、所有主题缩放或排版。由当前提交的 CI 覆盖 Windows 编译、签名与最终包检查。
