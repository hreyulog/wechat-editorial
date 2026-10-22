# math-documentary-skill

从一个题目开始制作可播放数学视频的 Codex Skills，分别用于知识点动画与数学人物纪录片。

| 要做的内容 | 使用的Skill | 默认首轮 |
| --- | --- | --- |
| 用图形变化讲清一个数学问题 | [math-explainer-animation](../math-explainer-animation/SKILL.md) | 9:16、30fps、中文字幕、无旁白；10—15秒知识演示 |
| 数学家的生平与贡献 | [st-petersburg-math-documentary](../st-petersburg-math-documentary/SKILL.md) | 9:16、24fps、中文男声、中英字幕；约90秒人物试作 |

当次用户要求优先。数学动画使用Remotion、React、TypeScript与SVG，让对象变化承担解释；人物版结合史料、照片、视频与图解。

机器人延续切比雪夫系列时，“做一个马尔可夫的视频”等裸人物选题默认走人物纪录片，使用[人物系列风格](../st-petersburg-math-documentary/references/petersburg-series.md)：人物故事、史料幻灯片、克制音乐、已选声音和参考字幕。下方“马尔可夫链”示例仅适用于用户明确要求知识点讲解的情况。音色转换样本、音乐素材与完整成片不进入源码包，新机器须提供相应授权本地资源。

数学动画当前默认采用严肃、克制的教学风格，以稳定构图、自然缓动和理解停顿组织画面。已接入[上游方法与版本记录](../math-explainer-animation/references/upstream-methods.md)：Remotion官方技术指引、animation-basics动作原理、中文过程动画参考。它们按需读取，调研与数学核对仍由本Skill承担；外部技能源文件不在本仓库重新分发。

## 给一个题目，开始制作数学动画

```text
$math-explainer-animation
题目：马尔可夫链究竟要记住多少过去？
面向有高中数学基础的人，做中文竖屏数学动画。
先调查资料，找一个有趣的具体例子，设计前五秒。
写全片脚本与分镜，先交付15秒可播放样片，确认后继续。
```

流程：调查可靠资料→明确核心问题、定义和条件→选择直观例子与开头→统一数学计算→脚本分镜→SVG动画→指定音乐分析与少量音效→渲染→最终MP4验收→逐段接续。没有指定音乐时先做静音试片；已确认片段保留版本，每轮检查与前段连接。全片确认后再制作封面、发布文案和公众号提纲。

新增Skill包含可运行Remotion起步工程、模板、音频分析、实际成片检查与手机视口浏览器检查。示例是自设明牌抽取，换题后须重新调查和设计，不把旧例子改标题当新片。详见 [数学动画安装与命令](../math-explainer-animation/README.md)。把整个`math-explainer-animation`目录复制到个人Codex skills目录，安装后新开会话，或让助手直接读取其SKILL.md。

自动解码、关键帧查看、短时浏览器播放、实际听审、实体手机和平台上传分别记录，不自动互相代替。公开仓库不含用户附件、私聊、第三方音视频或完整成片。

以下为保留的人物纪录片Skill安装与说明。

## 安装

先克隆仓库：

```sh
git clone https://github.com/hreyulog/wechat-editorial.git
cd wechat-editorial
```

将整个 `st-petersburg-math-documentary` 文件夹复制到个人 Codex skills 目录。Windows PowerShell：

```powershell
New-Item -ItemType Directory -Path "$env:USERPROFILE/.codex/skills" -Force | Out-Null
Copy-Item -LiteralPath ./st-petersburg-math-documentary -Destination "$env:USERPROFILE/.codex/skills/" -Recurse
```

macOS / Linux：

```sh
mkdir -p ~/.codex/skills
cp -R st-petersburg-math-documentary ~/.codex/skills/
```

若已有同名 skill，请先比较版本和自己的修改。安装后新开一个会话；也可以让助手直接读取该目录的 `SKILL.md`。

## 调用示例

```text
$st-petersburg-math-documentary
制作一条介绍马尔可夫生平和贡献的90秒中文竖屏纪录片。
采用中文男声，上中文下英文字幕，结合历史照片与可使用的视频片段。
交付可播放MP4、高清版、字幕、素材来源、封面及核对报告。
```

用户要求全套时，制作约90秒主推版和5–6分钟完整版。人物、时长、声音与素材以用户本次要求为准。

## 制作流程

1. 核实人物事实及数学贡献，完成中文旁白与逐句英文。
2. 登记素材作者、来源页、许可和年代，区分历史资料、当代画面和情景再现。
3. 生成旁白与实际时间轴，再制作镜头、双语字幕及连续音频混合。
4. 输出9:16、H.264/AAC、恒定帧率MP4，并生成小于15,000,000字节的播放副本。
5. 核对最终文件的完整解码、音轨、真实编码帧，以及史实、英译和素材来源。
6. 补齐封面、旁白稿、来源页、播放入口和最终文件清单。

本地技术脚本负责音视频及技术验证；封面、网页和史实、英译、许可复核由执行 skill 的助手完成。自动报告不会把这些复核自动标记为通过。详见 [使用说明](../st-petersburg-math-documentary/README.md) 与 [核对流程](../st-petersburg-math-documentary/references/verification.md)。

## 本地脚本

依赖 Python、Pillow、edge-tts 和 FFmpeg。语音合成需要网络，已有旁白 WAV 和准确字幕时可采用离线路径。可指定现有 FFmpeg 或使用 imageio-ffmpeg。

```sh
cd st-petersburg-math-documentary
python -m pip install -r requirements.txt
python scripts/video_runtime.py doctor
python scripts/video_runtime.py build --project /absolute/path/project.json
```

从 [配置示例](../st-petersburg-math-documentary/examples/project.example.json) 创建独立项目，填入核实过的内容和素材路径。相对路径以项目配置所在目录解析。可用 `--ffmpeg`、`--vendor` 等参数指定现有工具；准确字段和分步命令以 `--help` 为准。

## 已验证范围

这套流程已用于切比雪夫制作，并完成马尔可夫90秒独立试作：中文男声、中英双语字幕，1080p竖屏成片及720p播放副本。两份最终MP4均通过完整解码与24fps恒定帧率检查，36个音频窗口通过比对，45张实际编码抽帧完成手机尺寸视觉复核。

这些结果属于已制作的案例。新人物必须重新核实事实、来源、字幕和最终文件；不能沿用旧片通过记录。未声称已在抖音或真实手机上完成播放测试，也不保证传播效果。

## 仓库内容

- `st-petersburg-math-documentary/SKILL.md`：触发范围与执行流程。
- `scripts/`：制作、配音、运行环境与冒烟验证脚本。
- `examples/`：通用项目配置示例。
- `references/`：叙事、手机排版、音频、验收和历史案例说明。
- `agents/openai.yaml`：显示名称与默认调用提示。
- `skill-package-manifest.json`：发布文件包的大小与SHA256清单。

后五项均位于 skill 目录内。本仓库不包含私人对话、账号信息、第三方视频、完整成片、依赖二进制或缓存。每次制作的素材权限和署名需要单独核查。
