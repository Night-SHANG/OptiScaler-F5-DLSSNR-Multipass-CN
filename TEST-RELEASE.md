# 简体中文测试版发布门槛

本仓库只为一次明确授权的测试版开放窄范围发布入口：

- 目标仓库：`Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN`
- 唯一版本标签：`v0.1.32-cn-test.1`
- 固定上游：`fadc3bf67f6c8548e94914baec3f2e551ba8d8a4`（F5 v0.1.32）
- 唯一触发方式：推送到 `main`，该次推送的最后一个提交消息必须逐字等于 `release: publish v0.1.32-cn-test.1`

消息不能有额外正文、空格、换行或大小写变化。普通推送、PR、手动运行均只构建和检查。请先合入安装脚本、发布器及工作流，完成前置检查后，再单独创建触发提交。触发后不要继续推进 `main`，否则发布器会拒绝过期提交。

## 工作流集成

在 `.github/workflows/build.yml` 的 `jobs` 下增加以下任务，保持顶层 `permissions: contents: read`。`build` 和 `portable-contracts` 的任务 ID 与显示名均保持原样。下载步骤未指定其他运行 ID，因此只取**本次工作流**的指定 artifact。`actions: read` 用于独立核对同次运行的两个成功任务，只有此发布任务获得 `contents: write`。

```yaml
  publish-test-release:
    needs: [portable-contracts, build]
    if: >-
      ${{ github.repository == 'Night-SHANG/OptiScaler-F5-DLSSNR-Multipass-CN' &&
          github.event_name == 'push' && github.ref == 'refs/heads/main' &&
          github.event.head_commit.message == 'release: publish v0.1.32-cn-test.1' &&
          needs.portable-contracts.result == 'success' && needs.build.result == 'success' }}
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    permissions:
      contents: write
      actions: read
    concurrency:
      group: f5-cn-test-release-v0.1.32-cn-test.1
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.sha }}
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: actions/download-artifact@v4
        with:
          name: OptiScaler-F5-CN-v0.1.32-${{ github.sha }}
          path: release-artifact
      - name: Verify and publish the authorized test prerelease
        env:
          GH_TOKEN: ${{ github.token }}
          BUILD_RESULT: ${{ needs.build.result }}
          PORTABLE_RESULT: ${{ needs.portable-contracts.result }}
        run: python tools/publish_test_release.py --artifact-dir release-artifact
```

这里的令牌是 GitHub Actions 为当前任务提供的临时令牌；不需要个人令牌、已保存的凭据、额外授权或仓库密钥。发布器不读取令牌内容，不运行 `gh auth`，不创建持久访问凭据。若标准令牌或仓库规则不允许操作，流程停止，不自动扩大权限。

GitHub 当前文档指出：如果目标提交相对于仓库默认分支修改了工作流文件，创建 Release 可能要求工作流写权限，标准 `GITHUB_TOKEN` 不能获得此权限。将发布器先合入 `main`，使用另一个普通触发提交，并保持该提交为 `main` 当前头部；如果仍遭权限拒绝，应检查运行和仓库规则，不改用长期令牌绕过。

## 发布前逐项核对

`tools/publish_test_release.py` 再次检查事件仓库、分支、完整提交、精确提交消息，以及 GitHub API 返回的运行 ID、尝试编号、工作流路径和两个前置任务的成功结论。发布前再次要求远端 `main` 仍指向该提交。

本次 artifact 必须恰好包含三项：安装 ZIP、同名 `.sha256`、`build-metadata.json`。发布器验证：

1. 安装 ZIP 文件名、实际 SHA-256、外部校验文件与元数据一致；中文仓库提交必须等于当前运行提交。
2. 固定上游、Release x64、v143、downloader-only、递归子模块记录及构建时间等证据完整。
3. ZIP 路径安全，无重复或大小写碰撞、目录/文件碰撞、符号链接、特殊文件、加密条目或超预算解压量。
4. `BUILD-INFO.CN.json` 与外层构建元数据一致；`SHA256SUMS.txt` 覆盖全部其他文件，逐项核对实际字节。
5. `OptiScaler.dll` 与 `nvngx.dll_dlssnr.dll` 的编译记录哈希与包内实际哈希一致，且具有 x64 PE32+ DLL 标头。
6. 15 项 hybrid 资源的路径和哈希、必要文件与许可均在包内；禁止误打包专有 NR DLL、可选 NVIDIA/Streamline/Ampere 组件和调试输出。
7. 三个实际打包的安装入口 `setup_windows.bat`、`setup_linux.sh`、`get_streamline.ps1` 的归一化中文输出指纹与已提交词库一致；另一个 Windows 下载器只在源码适配，不是上游默认安装包成员。原始 vendor 清单哈希保持不变。
8. 中文安装说明与默认 `Language=zh-CN` 配置存在。

这些校验建立同一次受信任工作流内的内容一致性，不是独立代码签名，也不能抵御拥有仓库写权限者修改发布器本身。不要把哈希一致或 DLL 文件格式正确解释为 GPU 功能已经验收。

## 发布、重试与冲突

发布器先创建带固定完整目标提交的**草稿**，显式指定 `prerelease: true` 和 `make_latest: "false"`。随后仅添加缺失资产，下载远端资产逐字节计算 SHA-256，并核对 GitHub 提供的摘要（如有）。三项都通过后才发布；发布后再核对标签最终指向、Pre-release 状态及资产。

- 不删除或替换 Release、标签或资产，不更新标签，不强推，不使用 `--clobber`。
- 已发布版本只有在完整提交、标签、发布器标记和全部资产完全一致时才视为“已发布”，此时不会再写入。
- 只有本发布器为同一提交、同一资产清单创建的草稿可继续。已存在且逐字节验证通过的资产会跳过，缺失的才上传。
- 其他版本类型、不同提交或资产、额外资产、未验证的草稿、孤立标签、失败或不完整上传均停止；不会清理或覆盖冲突。
- 创建、上传或发布响应不确定时，先读取远端状态并验证。若无法确认成功，保留草稿和现有内容，报错退出；不会盲目重复写入。重新运行前应先查看失败原因，通常应重新运行整个工作流，以获得同一尝试的完整成功证据。
- 同一标签的发布任务使用串行并发组。外部人员同时修改 Release 仍可能触发冲突；校验失败应人工检查，不能自动修复公开版本。

重跑完整构建会重新生成时间戳，ZIP 或元数据哈希也可能变化。已经存在的草稿/Release 与新产物不完全相同时，流程会拒绝继续。不要以删除旧资产或改标签的方式强行重跑；应保留原始同次运行产物并审查恢复方案，或为后续版本另行授权和审查新门槛。

## 测试范围声明

这是测试版，不是稳定版。发布说明由脚本生成中文内容，包含提交、上游、同次工作流链接和 ZIP 哈希，并明确说明：

- 未执行实际 GPU/游戏验收。Windows 编译成功不能代替游戏运行、画面正确性、中文排版、主题或缩放测试。
- downloader-only 包不含专有 NR 模型/运行库 `nvngx_dlssnr.dll`，也不预装可选 NVIDIA DLSS/Streamline、Ampere MFG 或外部 vendor-neutral 组件。独立下载、校验和相关许可仍由使用者确认。
- 中文菜单依赖已经安装或自行提供的兼容中文字体，不附带 Windows 中文字体；字体不可用时回退英文。
- 保留旧安装备份，完整解压，并避免带反作弊的多人游戏。

## 离线回归测试

```sh
python -m unittest discover -s tests -p test_test_release_gate.py -v
python -m unittest discover -s tests -v
```

测试使用合成 ZIP、PE 标头和内存 GitHub 状态机；拦截全部外部子进程，不访问网络、不读取凭据、不发布任何内容。它们不替代真正的 Windows 构建或 GitHub 工作流运行。

## GitHub 官方参考

- [创建和更新 Release 的字段与权限](https://docs.github.com/en/rest/releases/releases#create-a-release)
- [Release 资产与下载校验](https://docs.github.com/en/rest/releases/assets#get-a-release-asset)
- [GitHub CLI 上传资产；默认不覆盖现有资产](https://cli.github.com/manual/gh_release_upload)
- [GitHub Actions 自动令牌](https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication)
