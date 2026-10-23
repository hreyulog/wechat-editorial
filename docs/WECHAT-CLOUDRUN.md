# 微信云托管部署评估

目标是尽量整套在云端运行，使用微信云托管的容器、对象存储与数据库，不把另外购买 Linux 云服务器作为前置条件。当前仍为部署前改造阶段，尚未上传镜像、创建新服务或迁移正在运行的 Bot。

## 已完成的真实检查

- 在 Windows 安装并执行官方 `@wxcloud/cli@2.3.3`，未改动全局 npm 或升级现有工具。
- 使用用户单独提供的 CLI AppID 与密钥，通过官方 CLI 相同的授权传输，读取环境、服务、版本、对象存储和数据库信息。
- 目标环境存在正常运行的服务，同时返回对象存储桶与 MySQL 集群信息。没有输出密钥、数据库密码、临时令牌或原始环境变量。
- 服务创建、镜像构建、云端启动、容器恢复、TurboPush Linux 上传和企业微信云端收发均未验证；现有生产实例未停止或切换。

## 纯容器方案

| 组件 | 部署职责 | 数据去向 |
|---|---|---|
| 工作台 Web/API 容器 | 登录、选题排期、进度和审核界面 | MySQL 保存计划与内容索引 |
| 单实例执行容器 | 企业微信长连接、Codex 原生会话、排版与渲染、TurboPush MCP | MySQL 保存入站、出站和步骤状态；对象存储保存实际文件 |
| 对象存储 | 图片、视频、稿件、源文件、检查回执与恢复快照 | 私有桶，按内容编号、版本与哈希隔离 |
| MySQL | 内容索引、审核授权、消息排重、任务队列、执行租约与发送状态 | 独立表或数据库，保留事务与版本约束 |

Web 与执行容器可以作为同一环境中的两个服务，也可以先用一个固定实例验证流程；实际拆分需结合资源和运行检查。对象存储保存文件，不执行 Python/Node 程序，也不能直接替代 SQLite 或具有本地文件锁语义的目录。

## 现有代码需要的改造

1. **公网入口**：现有工作台是仅本机使用的服务，会给本机访问者自动签发会话。上云前必须加入真实管理员认证、HTTPS 入口及严格的来源检查，不能只改监听地址就公开。
2. **状态与队列**：当前 jobs、inbox、outbox 与审核状态是本机 JSON。上云需要外置存储，真实消息只有可靠落库后才确认；保留 outcome_unknown / delivery_unknown，不因重启重复上传或发消息。
3. **素材与版本**：本机文件变为容器内临时工作副本。源文件、MP4、封面和 manifest 上传对象存储，并核对哈希后登记版本。返回受认证的访问入口或短效地址，不将桶设为公开读。
4. **长任务与唯一执行器**：执行服务保持常驻、单一 Bot 连接，避免缩容到零或滚动更新时出现两个执行者。最大实例数为 1 也不能单独保证更新期间不重叠，需要租约和发布前排空当前任务。
5. **Codex 会话**：索引数据库、会话记录、配置与身份认证分别处理；不能把 SQLite 文件直接放在对象存储挂载上。需验证会话恢复和长任务中断后的核对流程，云端身份认证由部署操作员完成，不把桌面登录缓存打包进镜像。
6. **TurboPush**：官方发布 Linux 版本；MCP 本身仍代理同一运行环境中的 TurboPush 本地服务。需在云端验证其图形依赖、浏览器、登录及 publish_video 实际结果。安装 MCP 二进制不代表这些已验证。
7. **切换**：先验证云端配置、素材和恢复流程，再等待工作机空闲，执行同一 Bot 的单实例切换。此阶段不自动重放 Windows 历史队列，也不公开发表内容。

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
