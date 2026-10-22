# Linux 部署与迁移

本包是从 Windows 已跑通流程整理的 Linux 移植版。按用户要求，本次**没有运行 Linux 安装、启动、Codex 任务或群收发验收**。下面命令供目标机器实际部署；依赖需联网安装，迁移包不是离线依赖镜像。

## 1. 系统依赖

建议 Ubuntu 24.04 / Debian 12 或更新的 x86_64 Linux，Node.js 22+、npm、Python 3.11+、FFmpeg 和中文字体。Node.js 可使用你已有安装；安装后确认 PATH 包含 node/npm。

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv ffmpeg fonts-noto-cjk \
  ca-certificates libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
  libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
  libxrandr2 libgbm1 libasound2t64
```

Debian 12 的音频库包名使用 `libasound2`；若系统自带 Chromium，可在 `.env` 设置 CHROME_BINARY。无桌面的服务器也使用 headless 浏览器渲染本地产物，不需要登录公众号网页。

```bash
git clone https://github.com/hreyulog/wechat-editorial.git
cd wechat-editorial
# 若用迁移包：tar -xzf wechat-editorial-linux-*.tar.gz 后进入该目录
bash scripts/setup-linux.sh
```

脚本创建 `.venv`、按 package-lock 安装 Node 依赖、生成本机路径配置、安装 Remotion/Playwright 所需浏览器。脚本不连接企业微信或公众号，不生成/发送稿件。字体、浏览器系统库缺失要在目标机补齐。

若浏览器仍报告缺少动态库，可在安装完 Node 依赖后按当前发行版运行 `npx playwright install-deps chromium`。这一步需要系统安装权限，由目标环境操作员执行。

## 2. Codex 与凭证

安装你可用版本的官方 Codex CLI（`npm install -g @openai/codex`），用运行机器人同一个 Linux 用户完成 `codex login`，或按自己的 Codex API/provider 配置认证。本仓库不会复制 Windows Codex 登录缓存。CLI 需支持 `codex app-server --stdio` 以及 thread/start/resume、turn/start/steer/interrupt 和 agentMessage 事件；兼容性留给目标环境验收。现在使用原生会话服务，已替换只能读取最终结果的 exec 调用方式。

编辑仓库根 `.env`（setup 只在不存在时从模板生成）：

```dotenv
WECOM_BOT_ID=填同一机器人的BotID
WECOM_BOT_SECRET=填同一机器人的长连接Secret
WECHAT_APPID=填公众号AppID
WECHAT_APPSECRET=填公众号AppSecret
CODEX_BIN=codex
CODEX_MODEL=
```

密钥只在目标机填写，不发到群或 Git。`.env` 权限建议 600。仅做视频可暂不填公众号凭证；文章要求真实官方草稿时必须填并具有相关接口权限。新 Linux 公网出口 IP 需要加入公众号开发接口白名单。

配置路径在 `editorial/wechat-content-studio/config.json`，由 `scripts/configure.py` 按安装目录产生，不随包迁移。换目录后重新运行 `.venv/bin/python scripts/configure.py`。本次包里不带已制作文章、MP4、聊天或群身份。

## 3. 切换机器人与绑定群

**同一个 Bot 只启动一个长连接实例。** Linux 启动/绑定前先停止旧 Windows 企业微信 Bot，避免互相挤掉连接。Windows 可在旧机器用：

```powershell
New-Item -ItemType File -Path '<Windows安装目录>\wecom-bot-local\state\stop' -Force
```

应先等旧机器当前制作/上传完成，再停止；不要在传视频途中切换。回退时停止 Linux 服务，再启动旧 Windows 的 start.ps1。本次整理没有主动停止旧实例。

在 Linux 执行：

```bash
npm run bind
```

终端会给出一次性 `绑定审核群 随机口令`。在目标企业微信群**真正 @ 机器人**并发这句话；本地保存该群绑定后命令退出，不发示例或历史稿件。然后：

```bash
npm run bot
```

该群所有成员 @ 机器人均可发任务，例如：

```text
@机器人 做一篇介绍切比雪夫概率界的公众号文章，并做15秒竖屏动画给我审核。
@机器人 任务列表
@机器人 进度 C0001
@机器人 修改 C0001：把开头改得直观一点。
@机器人 通过 C0001-v2
```

立即确认回复是“收到，处理中”。制作中的阶段说明会发回群里；需要选择音色、方向或试听确认时，先问并暂停这一轮，等下一条回复。成品由出站队列发回同群，包含真实公众号草稿预览及带文件名的 MP4 文件附件。“通过”只记审核，不发布。

即时控制示例（都需真正 @ 机器人）：

```text
补充：旁白不要加背景音乐。  # 普通执行中消息直接 steer 当前任务
停止                     # 中断当前一轮，保留已有文件
打断：先做女声10秒试听。  # 中断后按新要求续做
新任务：另写一篇马尔可夫文章。 # 明确另起选题才排队
```

进度/任务列表可直接查询。控制绑定当前来源消息与 turnId；若原任务刚结束，不能误打断下一条。控制回执不明保留 control_unknown，不自动重放。停止不撤销已经发出的消息或已完成的远端写入；只取消本条任务尚未发送的关联出站内容。

## 4. 可选常驻服务

先前台确认配置可用，再把 `deploy/wechat-editorial.service.example` 复制成你用户的 systemd unit，替换工作目录与 node 绝对路径。使用用户服务可复用该 Linux 用户的 Codex 登录状态。

```bash
mkdir -p ~/.config/systemd/user
cp deploy/wechat-editorial.service.example ~/.config/systemd/user/wechat-editorial.service
# 编辑 unit 中的路径以及必要的 PATH
systemctl --user daemon-reload
systemctl --user enable --now wechat-editorial
journalctl --user -u wechat-editorial -f
```

退出登录后需要继续运行，可按你的服务器管理方式为该用户启用 linger。不要同时启动前台 npm run bot 和服务；本地 lock 会拒绝同安装目录重复启动。

## 5. 你在目标机验收

下面步骤只提供入口，**本次未执行**：

1. `.venv/bin/python editorial/wechat-content-studio/official_api.py check`：检查公众号凭证、白名单与草稿读取权限。
2. `npm run test:bridge`；在 studio 目录用 `.venv` 的 Python 执行 `-m unittest test_studio test_official_drafts`：可选本地测试，不发群消息。
3. 群内 @ 发小任务，检查收到确认、实际生成、真实官方预览、视频发送和修改新版本。
4. 检查大视频 transport 副本、原片哈希、完整时长；实际点开视频/预览，再确认收到和播放。

与这些入口有关的结果请在目标机保存，不复用旧 Windows QA。仓库 `docs/WORKFLOW.md` 列出状态和故障处理。

## 能力边界

Linux 路径只覆盖官方企业微信 Bot、Codex CLI、文章/视频制作、公众号官方草稿和同群送审。它不操作桌面 WeChat，不接管视频号后台。TurboPush 是可选本地内容库适配器，默认关闭；视频号实际上传或发布仍需另行集成，不会凭本地内容库 ID 宣称视频号草稿已建。
