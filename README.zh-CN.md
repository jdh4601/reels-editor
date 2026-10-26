<div align="center">
<img src="docs/images/icon.png" alt="Reels Editor" width="112">

# Reels Editor

**在自己的电脑上，将 YouTube 长视频制作成竖屏短视频。**

[한국어](README.ko.md) · [English](README.md) · **简体中文**
</div>

粘贴一个带字幕的 YouTube 视频链接，查看 10 个有原文依据的片段建议，再生成选中的片段。Reels Editor 使用原始视频制作 1080×1920 竖屏视频，添加标题和翻译字幕，根据实际语音对齐字幕，并在导出前检查最终 MP4。

这是一个专注于短视频生成的本地工具，无需私人工作空间、公司专属素材或 Google Drive 账号。

## 0.2 版本更新

- 独立应用接入了最新的语音对齐、独立审核和自动修复流程。
- 开场引用必须与连续的原始字幕一致。剪辑保留原话、数字、否定关系、因果关系和上下文。
- 开场放大效果和内置风声以实际测得的重点词为时间依据，并检查最终视频中的应用结果。
- 支持 **한국어 / English / 简体中文** 输出语言，应用于标题、字幕和配文。语言按任务保存，重试时保留，分析缓存也区分语言。中文标题无需添加不自然的空格。
- 修改标题或字幕叠加层后必须重新审核。导出时再次检查获批 MP4 的哈希，包括复制后的文件。
- 视频和封面不显示底部标志或集数。
- 使用中性的默认样式和开放授权的 CJK 字体，所需提示词、字体和音效随包提供，无需私人素材。
- 未配置云盘时可以导出到本地。封面失败不会丢弃已通过审核的 MP4。

## 运行要求

完整生成流程目前面向 **Apple silicon macOS**。本地词级时间测量使用 MLX Whisper，原生窗口和人脸检测也使用 macOS API。Python 测试与 UI 构建可在 Linux 上运行，但这不代表完整应用支持 Linux 或 Windows。

| 要求 | 用途 |
| --- | --- |
| Python 3.11 及以上 | 后端与视频处理 |
| Node.js 22.13 及以上、npm | 构建 React 界面 |
| FFmpeg、FFprobe | 媒体处理和检查 |
| 已登录的 Codex CLI | 字幕对齐与有限次数修复 |
| 可使用 Opus 的 Claude Code CLI | 独立最终审核 |
| 网络连接 | YouTube、模型请求、首次下载 ASR 模型 |

生成阶段可选择 Codex、Claude、Gemini、OpenAI 或 Kimi。**无论选择哪种生成服务，验证层仍然需要 Codex 和 Claude/Opus。** 请使用自己的账号登录；可用额度和费用取决于账号条件。审核失败时不会静默切换模型或跳过检查。

## 安装与启动

```bash
brew install ffmpeg

git clone https://github.com/jdh4601/reels-editor.git
cd reels-editor
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

npm ci --prefix desktop/ui
npm run build --prefix desktop/ui
```

如果尚未安装验证所需的 CLI，请安装并登录：

```bash
npm install -g @openai/codex @anthropic-ai/claude-code
codex login
claude
```

完成 Claude 的交互式登录后启动应用：

```bash
.venv/bin/reels-editor-desktop
```

应用使用由随机会话令牌保护的本地回环服务器，无需公开服务器或其他工作空间。软件包包含 Noto Sans CJK 字体和程序生成的风声音效。ASR 模型首次使用时下载，随后使用本地缓存。

## 制作短视频

1. 粘贴一个可读取字幕的 YouTube 单视频链接。
2. 在 **Output language** 中选择 한국어、English 或 简体中文。
3. 分析 10 个候选片段，选择要生成的内容。每个建议包含原文片段 ID 和开场引用。
4. 生成选中的片段。脚本确定后只下载需要的原视频区间。片段以讲清一个主题为目标，不会为满足固定时长而强行添加或裁掉发言。
5. 检查竖屏预览、标题、字幕和封面。修改标题或人物信息后，重新渲染叠加层并进行独立审核。
6. 选择已完成的视频并导出。未配置 Drive 时，保存到 `~/Movies/Reels Editor Exports/` 下的本地文件夹；也可以使用已配置的本地 Google Drive 文件夹。

语言选项改变生成的文字，**不会为原始语音配音或替换原声**。界面、菜单、通知和错误提示使用英语。新任务默认输出英语，也可以选择韩语或简体中文。直接引用保留原文语言。人物可见的视频更适合竖屏构图；身份、语音或时间依据不足时，流程可能无法通过审核，而不是编造信息。

## 验证层

```text
原始字幕 → 有依据的候选片段 → 选定脚本
  → 原文与上下文检查 → 本地词级时间测量 → 字幕语义对齐
  → 基于测量的开场放大与音效 → 最终 MP4
  → 最终音轨再分析 + 程序检查 + 独立 Opus 审核
       ├─ 通过：将批准绑定到确切的 MP4 哈希 → 导出
       └─ 失败或不确定：修复 → 重新对齐 → 重新渲染 → 再审核（最多修复 2 次）
```

审核覆盖主题、翻译、字幕时间、开场音频、开场字幕、可读性、人物裁切、放大效果和开场音效。缺失检查项、依据不足、不确定结论、程序检测到的问题或视频哈希不一致，都会阻止批准。

审核模型收到最终 MP4 的实际帧，以及从音轨提取的词级时间和信号数据。它不会直接聆听音频，ASR 时间戳也仍然是估计值。

每次尝试的依据、模型原始响应、修复和审核报告保存在 `jobs/<任务>/sN/quality/`。失败片段可以重试，其他已完成片段会保留。旧任务如果缺少完整且与当前 MP4 匹配的批准，必须重新生成后才能导出。

代码路径、约束和回归检查见[验证说明](docs/verification.md)。

## 本地处理与外部请求

FFmpeg 渲染、媒体存储、人脸检测和 ASR 在本机运行。原文片段、选定脚本和时间依据会发送到生成或对齐模型；最终视频帧和音频分析依据会发送到 Claude/Opus。人物验证或可选封面搜索可能查询公开来源。它不是完全离线的 AI 流程，也不包含自动发布步骤。

| 数据 | 默认位置 |
| --- | --- |
| 任务、原文字幕、下载区间和审核依据 | `~/Library/Application Support/reels-editor/jobs/` |
| 原视频与分析共享缓存 | `jobs/.source-cache/` |
| 用户设置 | `~/.config/reels-editor/config.yaml` |
| 已完成视频归档 | `~/Movies/Reels Editor/` |
| 已选视频本地导出 | `~/Movies/Reels Editor Exports/` |

已完成的视频可在归档中重新打开 7 天。不要将私人媒体、凭据、任务数据或审核依据提交到源码仓库。

配置示例：

```yaml
provider: codex-cli
model: ""
output_language: zh  # ko | en | zh
style:
  speed: 1.2
```

新任务以界面选择的语言为准。已有任务保留保存的语言；没有语言字段的旧任务默认使用韩语。新工作区会记住最后选择的语言。

## 重新渲染与开发验证

```bash
.venv/bin/reels-editor render path/to/workdir --title 1
```

工作目录需要包含 `edl.json`、`segments.json` 和可访问的原始媒体。命令使用与桌面应用相同的验证流程和模型认证，在 `.verified-jobs/` 保存审核记录。最终审核不能批准时，命令返回失败。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
npm run typecheck --prefix desktop/ui
npm run build --prefix desktop/ui
npm run test:dashboard --prefix desktop/ui
```

单元和集成测试使用隔离的模型替身。界面测试检查三种窗口尺寸、语言选择与持久化、视频切换和实际创建请求。通过自动测试不代表每个原视频都能通过在线模型审核。

构建 macOS 应用：

```bash
.venv/bin/pyinstaller desktop/pyinstaller/reels_editor_desktop.spec --noconfirm
open "dist/Reels Editor.app"
```

自行构建的应用没有签名。另见[贡献指南](CONTRIBUTING.md)和[更新记录](CHANGELOG.md)。

## 常见问题

- **没有原始字幕：** 请使用带字幕的视频。ASR 用于验证选定音频，不会静默替代缺失的 YouTube 字幕。
- **CLI 缺失或未登录：** 检查 `codex --version`、`claude --version` 和两个账号的登录状态。仅配置生成服务不足以运行验证层。
- **审核失败：** 查看片段错误和保存的依据后重试。不完整或不确定的审核不会标为成功。
- **封面失败：** 已通过审核的 MP4 仍可预览和导出；可以换用其他画面或图片重做封面。
- **YouTube 提取失败：** 更新环境中的 `yt-dlp` 后重试。不保证能够访问私人或受限视频。

## 许可证

[MIT](LICENSE) © DongHyun Jung。Noto Sans CJK 使用 [SIL OFL 1.1](reels_editor/resources/styles/assets/fonts/OFL.txt)；详见[素材来源](reels_editor/resources/styles/assets/README.md)。仅处理和发布你有权使用的媒体。
