# wechat-editorial

在企业微信群 @ 机器人发任务，由 Codex 制作公众号文章和视频，把**公众号官方草稿预览链接和实际 MP4**送回同群审核。

指定群里的所有成员都可以 @ 使用。收到任务立即回复“收到，处理中”；制作结果排队发送，审核通过只做记录，不自动公开发布。

## Linux 部署

先读 [Linux 安装与迁移说明](docs/LINUX.md)。需要 Node.js 22+、Python 3.11+、FFmpeg、中文字体、Codex CLI 和自己的企业微信 Bot 凭证；公众号草稿还需开发接口权限与出口 IP 白名单。

```bash
git clone https://github.com/hreyulog/wechat-editorial.git
cd wechat-editorial
bash scripts/setup-linux.sh
# 编辑 .env；以同一 Linux 用户配置并登录 Codex CLI
# 停止旧机器上同一个 Bot 的实例后：
npm run bind
npm run bot
```

`bind` 会要求在目标群 @ Bot 发送随机口令，然后仅保存该群绑定。启动不发样例、不补发历史稿件。迁移包和仓库不含密钥、账号/登录状态、聊天或历史文章视频；目标机器单独配置。依赖需要联网安装。

**本次按用户要求未运行 Linux 安装、启动、功能测试或群收发验收。** Linux 版是可部署源码与安装入口，运行结果由目标环境确认；旧 Windows 流程的成功回执不能作为 Linux 验收结果。

## 包含的 Skill 与流程

| 入口 | 用途 |
|---|---|
| [wechat-editorial-workflow](wechat-editorial-workflow/SKILL.md) | 群任务、文章与视频、官方草稿、同群送审、修改与审核 |
| [math-explainer-animation](math-explainer-animation/SKILL.md) | 数学知识动画，Remotion / React / TypeScript / SVG |
| [st-petersburg-math-documentary](st-petersburg-math-documentary/SKILL.md) | 人物纪录片、中文配音、中英字幕与真实媒体核对 |
| [工作室说明](editorial/wechat-content-studio/AGENTS.md) | 实际文件格式、版本、构建、草稿及发送命令 |

文章排版与草稿构造复用固定版本上游代码，调用仅限官方草稿端点。较大的原生视频自动生成完整时长的小审片副本，保留原片及哈希。文本已发送而视频失败时不会重复文章；执行/发送结果不明时暂停该条，避免重复副作用。

Linux 企业微信路径直接调用本机 Codex CLI，不依赖桌面 WeChat 或 codex-weixin 网页服务。TurboPush 只保留可选的本地内容库适配器且默认关闭；本仓库不承诺视频号后台上传或发布。

## 文档与导出

- [Linux 部署、切换、常驻服务与验收入口](docs/LINUX.md)
- [架构、状态、故障与能力边界](docs/WORKFLOW.md)
- [原有视频 Skill 详细说明](docs/VIDEO-SKILLS.md)
- [第三方来源与许可](NOTICE.md)

从已提交的干净源码生成迁移包：

```bash
python3 scripts/export-migration.py --output ./dist
```

输出 tar.gz、ZIP、SHA256 和文件清单，绑定源码提交。只归档 Git 中的源文件，不遍历运行状态、私钥或本机依赖。不要把 `.env`、state、jobs、outbox、node_modules 或虚拟环境提交到 Git。
