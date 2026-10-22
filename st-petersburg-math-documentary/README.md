# 圣彼得堡数学人物纪录片 skill

用于制作以人物生平与贡献为主线的中文竖屏纪录片，默认中文男声、上中文下英文字幕。它包含制作说明、通用本地脚本、项目配置示例及验证流程。

延续切比雪夫、马尔可夫等人物系列时，先读[系列风格](references/petersburg-series.md)：人物叙事、史料幻灯片、克制配乐、已选声音与参考片字幕。裸人物选题默认进入人物片，不因“马尔可夫”与数学概念同名而转成知识动画。系列已选的声音、帧率和视觉优先于通用默认；私人参考声音和媒体不随仓库分发。

## 安装和使用

将整个 `st-petersburg-math-documentary` 文件夹放入个人 Codex skills 目录，例如 `~/.codex/skills/`。随后在任务里调用 `$st-petersburg-math-documentary`，描述人物、时长和已有素材。当前会话若尚未更新技能列表，可以直接让助手读取该目录的 `SKILL.md`。

开始项目时复制 `examples/project.example.json`，填入核实过的人物内容、中文句子、英文翻译与可用素材路径。所有相对路径以配置文件所在目录解析。

## 运行环境

使用已有 Python 运行环境，依赖 Pillow、edge-tts；FFmpeg可由命令行参数指定，也可使用imageio-ffmpeg提供的二进制。语音合成需要网络；已有WAV/准确字幕可走离线制作。不要把环境、vendor和媒体缓存在skill目录中。

```text
python scripts/video_runtime.py doctor
python scripts/video_runtime.py build --project /absolute/path/project.json --ffmpeg /absolute/path/ffmpeg
```

已有依赖放在其他目录时可使用 `--vendor /absolute/path/dependency-directory`；需要指定Python时使用 `--python /absolute/path/python`。脚本不会复制这些依赖进skill。安装新的独立环境时，使用根目录 `requirements.txt`。

以脚本 `--help` 和配置示例作为字段与分步命令的准确信息。输出在项目配置的 `output_dir` 下分为 `build`、`delivery`。`build` 命令负责旁白、时间轴、镜头、双语字幕、两份MP4和技术验证；随后由执行skill的助手补齐封面、旁白稿、来源网页、播放入口及最终清单，并完成史实、英译、权限和真实编码帧的人工复核。技术报告会保留这些人工项目为待核，不将自动检查等同于完整交付。

发布用1080p成片，应用预览用小体积播放副本。

## 文件范围

- `SKILL.md`：触发范围、执行流程及分享边界。
- `scripts/`：通用制作与验证程序。
- `examples/`：不含个人内容的项目配置。
- `references/`：叙事、手机排版、音频、核对与案例教训。
- `agents/openai.yaml`：显示名称与默认用法。

包内不保留私人对话、旧项目绝对路径、账号、个人附件、第三方视频、语音缓存或依赖。影片素材在每个独立项目登记来源和许可。

## 版本证据

原始切比雪夫案例已核对最终交付元数据，示例数字见 `references/chebyshev-case.md`。新人物需重新验证。本版会通过一次独立人物试作验证通用脚本的可运行性；其结果单独存档，不将旧片通过报告充作新片证据。

## GitHub

当前交付为本地skill文件包。用户明确给出上传指令和目标仓库后，再进行上传、提交或推送。
