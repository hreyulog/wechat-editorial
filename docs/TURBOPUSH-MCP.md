# TurboPush MCP 接入

机器人执行器可以显式加载官方 TurboPush MCP stdio 服务。它与 `turbopush_local.py` 本地入库脚本独立，不依赖桌面 Codex 是否挂载了同名 MCP。

## 配置

在运行机器人这台机器安装并启动 TurboPush，登录目标账号，安装该平台的[官方 MCP 可执行文件](https://github.com/xueyc1f/turbopush-mcp/releases/tag/v1.1.3)。仓库和迁移包不携带该二进制、TurboPush 登录数据或密钥。凭证由官方 MCP 从本机 `~/.TurboPush/mcp.json` 读取，不写入仓库配置或命令参数。

```bash
.venv/bin/python scripts/configure-turbopush-mcp.py --binary /absolute/path/to/turbo-push-mcp
```

此命令只生成被忽略的 `editorial/wechat-content-studio/state/turbopush-mcp.json`，保存可执行路径、SHA256 和启用状态，不连接服务。也可用 `--studio` 指向独立工作室。更新 MCP 二进制后重新运行该配置命令，执行器会检查文件哈希。

等当前任务和上传结束后重启机器人。原生 `app-server-runner.mjs` 用显式 Codex 配置加载 `turbo_push`；无配置文件时维持原行为。目标 Linux 上的 TurboPush 可用性、MCP 运行和安装仍需部署者验收，本次没有执行 Linux 验证。

## 可用范围

当前配置与工作机保持一致，显式暴露 v1.1.3 的 21 个工具。实际白名单位于 `editorial/wecom-bot-local/turbopush-mcp.mjs` 的 `TURBOPUSH_TOOLS`，通过 `enabled_tools` 传给 Codex；配置 JSON 只保存启用状态、程序路径、哈希及范围说明。

- 查询：`list_platforms`、`list_accounts`、`list_logged_accounts`、`list_platform_settings`、`list_articles`、`get_article`、`list_records`、`get_record_info`、`get_platform_setting_schema`。
- 本地内容管理：`create_article`、`create_graph_text`、`create_video`、`update_article`。
- 发布及浏览器控制：`publish_video`、`publish_article`、`publish_graph_text`、`close_browser`。
- 平台设置与删除：`create_platform_setting`、`update_platform_setting`、`delete_platform_setting`、`delete_article`。

工具可见不代表每次调用都已获授权。删除内容或平台设置需要用户当次明确点名；审核通过只记录审核，公开发布需对应明确指令。实际执行仍遵守工具及站点策略，遇到拒绝时保留原始错误，不通过其他路径绕过。MCP 连接成功、本地内容保存、远端上传和公开发布分别记录，不能互相代替。

用户可以发“查询 TurboPush 已登录账号”或“查看 TurboPush 里 C编号-v版本 的本地内容”。已有版本的 `turbopush-local.json` 提供本地内容 ID，避免重复创建。

视频上传使用 MCP 的 `publish_video`，本地适配器 `turbopush_local.py` 仍只负责入库。调用应核对版本文件及目标账号，区分 `syncDraft:true` 保存草稿和 `syncDraft:false` 公开发布。执行后通过 `list_records` / `get_record_info` 核对对应账号、记录 ID 和实际状态；超时或结果不明不得自动重发。

## 原 Windows codex-weixin 实例

codex-weixin 0.3.14 默认隔离全局 MCP，单纯修改桌面 Codex 配置不会让机器人继承。可对该固定版本安装显式适配器：

```bash
node scripts/patch-codex-weixin-mcp.mjs /path/to/codex-weixin /path/to/editorial/wecom-bot-local/turbopush-mcp.mjs
```

启动 codex-weixin 的进程环境设置 `CODEX_EDITORIAL_MCP_CONFIG` 为工作室 `state/turbopush-mcp.json` 的绝对路径，然后在空闲时重启。此适配器保留其他全局集成的隔离，不复制认证 Token；原始文件保存 `.before-editorial-mcp` 本地备份。

适配器提供本地、同源且需请求 Token 的 `POST /api/editorial/mcp-status`，传当前会话的 accountId/sessionId。它从同一个执行器加载该会话、发现工具并调用只读 `list_logged_accounts`，只返回工具名和成功状态，不回传账号原始数据，不创建模型轮次或发送聊天消息。

诊断字段 `browser_publishing_enabled` 由实际发现的发布工具决定，仅表示工具是否可见，不代表已执行上传或发布。旧适配器的固定 `false` 会在重新应用补丁时更新。

工作机 Windows 已用官方 v1.1.3 完成上述发现和只读调用。Windows 官方资产 SHA256：`277d1926dcb581db4ce0b706e199d7d7fe29c0d5b41484dedd1d68fe4ef90cce`。这不代表 Linux 验收或视频号上传成功。
