# 微信云托管部署

使用微信云托管容器、私有对象存储与 MySQL，不要求另外购买 Linux 服务器。新 Bot 创建独立服务，namespace 由它的 ID 哈希隔离；原 Windows Bot、任务和已有云服务保持独立。

## 已实现

- `Dockerfile` 安装 Node / Python / Chromium / FFmpeg / Codex，`cloud/runtime.py` 启动公网入口、持久化服务和单一 Bot。原本机模式仅在明确设置 `EDITORIAL_CLOUD` 时启用云端行为。
- Nginx 与工作台均验证管理员登录；同源 POST、HttpOnly / Secure 会话及私有媒体访问。外部只开放 8080；MySQL、Bot 长连接、VNC 与持久化端点不直接公开。
- `cloud/store.py` 将 JSON 迁移状态先写 MySQL 再确认消息；发送前上传版本文件到私有 COS，恢复时核对 SHA256。启动从 SQL/COS 恢复工作副本，不把容器磁盘视为唯一副本。
- MySQL 连接级 advisory lock 独占本 Bot 的执行器；租约检查禁止自动重连，滚动更新等待旧连接释放。对外消息发送前再次检查所有权；未知发送或执行结果保留 unknown，不自动重放。
- 云端独立 Codex 设备授权或显式提供 API Key；云端生成的 auth.json 使用环境中的加密密钥加密后存 MySQL，不打包工作机登录缓存。会话 JSONL 和任务素材可检查点到私有对象存储；SQLite 不挂在 COS 上。
- 官方 Linux TurboPush 与 MCP 二进制按 SHA256 校验安装，图形界面经同一个 HTTPS 管理员入口的 `/desktop/vnc.html?autoconnect=1&resize=scale&path=websockify` 使用。目标账号需要用户在云端重新登录。原生数据库通过 SQLite backup 后加密保存；不得据此声称每种平台浏览器状态已恢复验证。
- `scripts/deploy-wxcloud.py` 只改动该 Bot 对应的 `editorial-*` 独立服务，读取指定旧服务的五项数据库/COS 连接配置，不覆盖旧服务。源码 ZIP 不含状态、凭证和登录缓存；中文文件名使用 ASCII 资源包在镜像内恢复。

## 部署与检查

```bash
python scripts/deploy-wxcloud.py \
  --appid-file /private/cloud-appid.txt --key-file /private/cloud-cli-key.txt \
  --credentials /private/new-bot-credentials --private-output /private/cloud-deployment \
  --env-id YOUR_ENV --settings-source YOUR_EXISTING_SERVICE

python scripts/cloud-status.py \
  --appid-file /private/cloud-appid.txt --key-file /private/cloud-cli-key.txt \
  --private-file /private/cloud-deployment/deployment-private.json
```

凭证目录包含 appid.txt / appsecret.txt / botid.txt / qiyesecret.txt。私有部署回执含管理员密码和服务环境，不能提交、截图或回传原文。`--base-version editorial-...-NNN` 可复用同服务已构建的运行镜像，避免重建大依赖。构建完成不等于容器就绪，云 API finished 也不等于 Bot / Codex 已授权；检查 `/api/cloud/status` 的真实组件状态。

进入工作台“账号与连接”，按当前随机口令在目标企微群真正 @ 新 Bot 绑定，完成云端 Codex 授权并打开 TurboPush 登录目标账号。公众号 API 的新出口 IP 可能需要用户加入白名单。用新的真实企微消息验证制作、原会话送审、二维码图片、审批及平台草稿；不补发历史队列。

下面保留最初的资源检查与验收清单。最终云端收发、视频制作/上传和重启恢复必须分别提供真实回执；源码适配或 Windows 成功不代替云端端到端验收。

## 已完成的真实检查

- 在 Windows 安装并执行官方 `@wxcloud/cli@2.3.3`，未改动全局 npm 或升级现有工具。
- 使用用户单独提供的 CLI AppID 与密钥，通过官方 CLI 相同的授权传输，读取环境、服务、版本、对象存储和数据库信息。
- 目标环境存在正常运行的服务，同时返回对象存储桶与 MySQL 集群信息。没有输出密钥、数据库密码、临时令牌或原始环境变量。
- 已真实创建独立新服务并在云端构建、推送、部署镜像；MySQL 连接与私有 COS 上传/下载检查通过，启动能恢复已存储的探针文件。工作机 Bot 与已有云服务未切换。
- 完整任务恢复、云端 Codex 执行、TurboPush Linux 登录/上传及新 Bot 收发需要各自验收，不能由上述基础检查推断成功。

## 纯容器方案

| 组件 | 部署职责 | 数据去向 |
|---|---|---|
| 工作台 Web/API 容器 | 登录、选题排期、进度和审核界面 | MySQL 保存计划与内容索引 |
| 单实例执行容器 | 企业微信长连接、Codex 原生会话、排版与渲染、TurboPush MCP | MySQL 保存入站、出站和步骤状态；对象存储保存实际文件 |
| 对象存储 | 图片、视频、稿件、源文件、检查回执与恢复快照 | 私有桶，按内容编号、版本与哈希隔离 |
| MySQL | 内容索引、审核授权、消息排重、任务队列、执行租约与发送状态 | 独立表或数据库，保留事务与版本约束 |

Web 与执行容器可以作为同一环境中的两个服务，也可以先用一个固定实例验证流程；实际拆分需结合资源和运行检查。对象存储保存文件，不执行 Python/Node 程序，也不能直接替代 SQLite 或具有本地文件锁语义的目录。

## 运行验收清单

1. **公网入口**：未登录不能访问任务、媒体或远程桌面；跨源请求拒绝。管理员密码验证通过才签发会话。
2. **消息与恢复**：新真实回调先落 MySQL，再答“收到，处理中”；重启中的 running/replying/sending 保持未知，不重放。
3. **文件与版本**：真实 MP4/图片/Codex 会话检查点进入私有 COS；重启恢复后 SHA256 相同；版本和已审文案不能偷偷改变。
4. **长任务与租约**：固定最小/最大实例为 1，MySQL advisory lock 防止滚动版本重复接单；长任务独立于 HTTP 请求时限，最长 4 小时。
5. **Codex 授权**：用户在云端独立授权或显式提供 API Key 后，用真实企微消息完成一次执行并验证检查点恢复；不复制桌面缓存。
6. **TurboPush**：在云端图形界面重新登录，MCP 查询实际目标账号；确认审片版本后调用 publish_video 的 syncDraft:true 并查询真实草稿记录。安装二进制、MCP 配置和旧 Windows 成功都不代替该测试。
7. **隔离**：本次为不同 Bot，保留工作机实例；新群通过真实消息绑定，不迁移旧群绑定、历史发送队列和审核批准，不自动公开发表。

CFS 是可选的持久文件系统方案，不是纯云部署的必要条件。CloudBase 文档存在 CFS 方案，但这不等于目标微信云托管环境已经开通同一能力；本次跨服务 CFS 只读查询返回 -9991，没有用它推断云托管容器不可部署。

## 只读检查工具

```bash
python scripts/inspect-wxcloud.py \
  --appid-file /private/wxcloud-appid.txt \
  --key-file /private/wxcloud-cli-private-key.txt \
  --output editorial/workbench/state/wxcloud-inventory.json
```

脚本依据发布的 `@wxcloud/cli@2.3.3` 中 `lib/api/base.js` 与 `cloudapiDirect.js` 实现，限定只读云 API。凭证从本机文件读取，不以命令行参数值传入，不写入 Git。输出仅包含环境、服务及域名清单；不能用它创建、更新或删除云资源。

## 官方参考

- [微信云托管 Python 容器模板](https://github.com/WeixinCloud/wxcloudrun-flask)
- [微信云托管 CLI](https://www.npmjs.com/package/@wxcloud/cli)
- [云托管对象存储挂载说明](https://docs.cloudbase.net/run/deploy/configuring/storage/cos)
- [云托管计费说明中的两种环境区别](https://docs.cloudbase.net/run/faq/fee)
- [TurboPush Linux 与桌面运行环境说明](https://github.com/xueyc1f/turbopush-website)
- [TurboPush MCP 本地服务调用实现](https://github.com/xueyc1f/turbopush-mcp/blob/main/client.go)
