# 视频手机预览后发布

流程是：制作视频 → 上传视频号草稿箱并读回真实草稿回执 → 取得该草稿的后台手机预览 → 发到任务来源会话 → 用户确认对应版本 → 交给发布执行器 → 查询真实结果。文章的公众号草稿预览和审核保留原流程。

## 当前接入范围

本次实现预览登记、版本绑定、二维码发送和真实确认消息的路由。未调用视频号上传或公开发布，也未验证 Linux 实机。手机预览的自动获取入口尚未接通：官方 [TurboPush MCP 发布实现](https://github.com/xueyc1f/turbopush-mcp/blob/main/tools_publish.go) 提供发布结果汇总，[记录查询实现](https://github.com/xueyc1f/turbopush-mcp/blob/main/tools_record.go) 提供记录数据，但当前工具清单没有独立获取手机预览的工具，不能假定每条记录必然带预览链接或二维码。

因此必须从合法、实际可用的来源取得后台真实预览及其对应草稿/预览标识后，才能登记并送审。缺少预览时 `deliver` 返回 `awaiting_video_phone_preview` 和 blocker，不把 MP4、本地网页或后台编辑地址当作手机预览，也不公开发布。工具和站点策略仍适用，不通过其他路径绕过拒绝。

## 登记真实预览

在对应 `jobs/C编号/vN` 内保存 `remote-phone-preview.json`，内容来自真实预览结果，不能填写猜测值。所需字段：

| 字段 | 内容 |
| --- | --- |
| `provenance` | 固定 `video_channel_phone_preview`，表示回执来自真实手机预览 |
| `account` | 实际目标账号名称或含账号 ID 的对象 |
| `remote_record_id` | 实际关联的远端草稿、预览或 TurboPush 记录标识 |
| `video_sha256` | 对应版本实际 MP4 的 SHA256，必须与 manifest 一致 |
| `draft_receipt` | 版本内实际草稿上传回执的相对路径，例如 `turbopush-remote.json`；本地入库回执不符合要求 |
| `url` | 实际官方 HTTPS 微信预览地址；只有二维码时可以省略 |
| `qr_image` | 版本内 `src/` 下实际二维码 PNG/JPEG 的相对路径；只有链接时可以省略 |
| `expires_at` | 若平台返回有效期，保留带时区的 ISO 时间；不能编造有效期 |

链接和二维码至少有一个。图片上限 2 MiB。

草稿回执必须包含实际 `job_id`、`version`、`video_sha256`、`account_id`、`account_name`、`record_id`，并满足 `syncDraft:true`、`public_publish_attempted:false`、`published:false`、`record_success:true`、`record_status:4`。`verified_via` 必须记录真实执行的 `turbo_push.get_record_info` 读回。不能凭发布参数或本地内容 ID 填成成功；应保留实际回执，不得编造上述字段。

登记命令：

```bash
python studio.py phone-preview C0001 --version 1 --receipt jobs/C0001/v1/remote-phone-preview.json
python studio.py deliver C0001 --version 1
```

登记生成 `phone-preview.json`，绑定 manifest、视频、草稿回执与二维码哈希。发送器把预览链接作为消息、二维码作为原生 image 发送，MP4 仍作为 file 附件。目的地沿用当前入站消息；私聊回本人、群消息回原群。`phone_preview_sent_at` 只在预览消息和二维码取得发送成功回执后记录，MP4 仍在传输时也可以确认已经收到的预览。

## 用户确认

建议回复 `确认发布 C0001-v1`。对于视频，`通过 C0001-v1` 和 `ok C0001-v1` 也表示确认发布；纯文章的“通过”仍只记审核。只有当前会话恰好一个未确认的当前版本时，才接受单独“ok / 可以发布 / 发布吧”。

路由核对真实企业微信入站记录、会话、确认时间、当前版本、已发送预览、有效期和哈希。未发送预览、跨会话、改稿、过期或多个候选均不会生成发布授权。确认生成 `video-publish-approval.json` 后，将带真实消息凭据的 `publish_request` 交给原 Codex 执行器；该文件本身不代表发布成功，也不绕过工具策略。

重复确认不会再次提交同一版本。修改用 `revise` 创建新版本，重新预览和确认。异常中断或结果不明时保留状态，先查询实际记录，不能自动重放发布。启动或部署本改动不重发历史稿件。

## 验证范围

Windows 离线测试使用虚构预览回执和模拟企业微信发送，覆盖无预览阻塞、原生二维码图片发送、版本和来源会话绑定、实际确认凭据、过期/修改拒绝及重复确认。测试没有取得真实后台手机预览，没有向用户发送测试消息，也没有发布视频。
