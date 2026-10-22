# 工作流与运维

```mermaid
flowchart LR
  G[绑定群 @ Bot / 已确认成员私聊] --> W[官方长连接 / 回调排重]
  W --> A[收到，处理中]
  W --> Q[持久化任务队列]
  Q --> R[进度与审核直接路由]
  Q --> C[Codex CLI 串行制作]
  C --> P[阶段说明 / 必要澄清]
  P --> G
  C --> S[文章 / 视频 / 来源 / 版本]
  S --> QA[构建与真实编码检查]
  QA --> D[公众号官方草稿 API]
  D --> O[官方预览链接 + MP4 / 来源会话出站队列]
  QA --> O
  O --> T[必要时生成较小完整审片副本]
  T --> G
```

## 代码位置

| 目录 | 内容 |
|---|---|
| `editorial/wecom-bot-local` | 官方 Bot、群绑定、任务队列、Codex app-server、即时控制、媒体压缩 |
| `editorial/wechat-content-studio` | 版本管理、Remotion/排版、草稿接口、审核、可选 TurboPush 本地库 |
| `wechat-editorial-workflow` | 全流程 Skill |
| `math-explainer-animation` | 数学 SVG 动画 Skill、模板和脚本 |
| `st-petersburg-math-documentary` | 人物纪录片 Skill、字幕及声音脚本 |
| `editorial/upstream/wechat-article-skills` | 固定版本的第三方排版与草稿构造辅助代码 |

视频先把 MP4 与实际标题、完整简介、目标账号发回来源会话，等用户看完确认后才上传视频号草稿箱；TurboPush 本地适配器只写内容库。[显式 MCP 连接](TURBOPUSH-MCP.md)配置后暴露 21 个工具，包含 `publish_video`；远端上传需核对版本、目标账号和真实记录，不能沿用登录状态或本地内容 ID 宣称成功。工具及站点策略仍适用，遇到拒绝时如实保留原始错误，不通过其他路径绕过。工具接入不等于当前环境已完成上传验收，Linux 上尚未实际验证。

## 运行状态

入站 `state/inbox/<msgid哈希>.json` 保存真实消息、发起人、排队和执行结果。任务按接收时间串行进入 Codex。会话 ID 保存在 `state/codex-thread.json`，后续任务续用；没有已有任务时不创建、发送稿件。重启遇到执行中的任务置 outcome_unknown，先核对本地 Codex 会话和实际产物，不自动重做。

单次制作任务最长 4 小时。可选 codex-weixin 适配器通过 `scripts/patch-codex-weixin-recovery.mjs` 安装相同的长任务时限；RPC 等待与整轮制作时限分开。任务异常保留 outcome_unknown，并向原会话回告停止原因，失败回告不自动重发。

桌面与机器人同时持有同一原生会话时可能返回 active writer。维护时先确认双方空闲，通过受本机令牌保护的 recover 入口从旧记录 fork，保留历史并切换机器人执行会话；不关闭桌面进程、删除锁或覆盖历史。该入口只 fork 历史，不自动运行内容任务。核对既有草稿、素材和发送回执后，可用 `scripts/recover-wecom-task.mjs --root <bot目录> --message <原msgid> --note-file <核对说明文件>` 恢复一条指定的 outcome_unknown 任务；原文、发起人、目的地和之前的错误均保留，不批量重放历史队列。官方草稿已存在时先查询，不重复创建。

绑定时记录发起者的私聊资格，绑定群中成功发过任务的成员也可私聊。消息记录 chattype 和真实 user_id，进度、控制回执、最终答复及附件都回原会话。私聊附件必须有匹配的真实入站凭据，不能把私聊内容发到默认群。不同来源会话的任务串行排队，彼此不自动 steer 或打断；同一来源会话继续支持即时补充和停止。

制作中逐段转发用户可见的 assistant commentary，不转发推理或工具日志。需要用户选择时先问并结束本轮等待下一条回复；不会把整个任务先做完才提问题。原生 app-server 只转发 commentary，最终答复在 turn/completed 后发送。

运行中的普通消息调用 turn/steer，不等整轮结束；显式“停止”调用 turn/interrupt，“打断：新要求”中断后优先续做。“新任务：……”才排队。进度查询直接读取状态。原始消息、即时控制消息和 native turnId 相互关联；旧控制到达时若目标已结束，不能作用于下一条任务。主动停止不启用 exec fallback，不把取消当失败重跑。

工作室 `jobs/C编号/vN` 保存 brief、源文件、输出、manifest、QA、真实审核与 official API 回执。每个版本不可原地覆盖已送审文件，修改创建下一版本。`outbox/*.json` 保存目的地、文件 SHA256、发送步骤和回执，必须由发送器独占写入。

| 状态 | 含义与处理 |
|---|---|
| queued | 等待处理，不能当作已发出 |
| sending | 正在生成传输副本、上传或发送；不能在此时重启 |
| sent | 所有业务发送得到官方成功回执；仍需用户确认实际收到 |
| upload_failed | 准备或上传失败，尚未调用视频发送；可依据明确错误处理后由操作员重新入队，保留 text ACK |
| delivery_unknown | 发送结果不明；先查实际群消息，禁止自动重复发送 |
| outcome_unknown | Codex 执行或回复结果不明；先核对会话与任务再决定后续 |
| steered | 原生接口已接受当前任务的追加消息；结果跟随原任务返回 |
| interrupted | 当前原生 turn 已确认中断；保留已生成文件 |
| control_unknown | 即时控制结果不明，不自动重放控制或复制执行任务 |

上传初始化与上传分片不等于群内已发送。MP4 默认以 file 类型上传并发送为文件附件，保留 C编号-v版本.mp4 文件名。大于 9.5MiB 的视频仍生成单独传输副本，原始版本和清单不变；副本绑定原片 SHA256、完整解码，并抽帧到 delivery 子目录。业务发送成功后每一步立即落盘，文本成功而附件失败不重复文本。出站签名及文件去重包含媒体类型，旧视频消息回执不会冒充文件附件回执；修改默认格式不会自动补发历史任务。

出站内容关联 source_message_id。收到停止后，该任务尚未发送的关联内容取消；上传已经开始时可以完成临时素材上传，但在实际发视频前再核对取消状态，不把过时成品继续推送。已成功发出的消息和已完成的远端写入不会因停止而回滚。

## 公众号接口

只允许 token、draft/count/get/add/update、封面永久素材和正文图片等明确端点。SSL 校验开启，不跟随第三方跳转，不调用 freepublish/submit。草稿创建前记录 creating；网络断开保留 outcome_unknown，防止重复草稿。真正的 draft/get URL 才能作为官方预览；media_id、后台编辑地址或本地网页都不能替代。含视频文章还要通过[实际组件读回检查](ARTICLE-VIDEO.md)，组件被过滤时保留未完成状态。

未设置或错误凭证只影响需要该接口的任务，不在终端、群或 Git 中输出密钥。文章审核只改变 review 状态，不公开发布。视频按 [视频审核后上传草稿](VIDEO-REVIEW.md) 先发 MP4 和实际文案，真实消息确认绑定版本后再交给执行器以 syncDraft:true 上传草稿；返回视频名、完整简介、目标账号、版本、文件名、草稿上传实际状态和记录号。OK 不授权公开发布，不再要求手机预览。

## Windows 实测与 Linux 移植

旧 Windows 实例曾完成公众号草稿、企业微信群文本及视频收发。约 19.4MB 的原生视频请求被拒，改为约 8.8MB、完整约178秒副本后上传和发送成功。这是设计传输副本与错误记录的来源，**不是本仓库 Linux 移植运行结果**。

按用户要求，本次未执行 Linux 安装、依赖运行、Codex 续会话、Remotion 渲染或真实群收发验证。源码测试入口及安装脚本仅随包提供，目标机器验收结果由用户完成。

## 第三方与发布

排版与草稿构造借助 Apache-2.0 上游子集，来源、固定提交和 LICENSE 随包提供。调用入口限制在工作室官方草稿封装，不直接调用上游公开发布命令。Remotion、React、SDK、Playwright、Sharp 等由依赖锁安装，其各自许可保持有效；部署使用者按各项目条款使用。

本包不含历史稿件、用户附件、账号凭证、Cookies、聊天、登录缓存、依赖二进制。发布或迁移现有任务是另一个操作，不能直接把当前工作机 state 整目录提交到仓库。
