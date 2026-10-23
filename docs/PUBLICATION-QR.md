# TurboPush 发表与扫码确认

## 公众号文章预览码

用户提供的“使用微信扫码预览／扫码后可将预览消息转发给朋友”属于文章预览二维码，实际解码为 `mp.weixin.qq.com/mp/previewdraft`。它用于审稿，不能当作管理员发表授权。

`studio.py deliver` 现在还会调用 `article_preview_qr.py`，将当前版本已登记的真实公众号官方预览链接编码为 PNG，独立入队并通过 image 消息回到相同会话。它使用真实官方 URL，不生成新的微信授权令牌。发送器等待同一份文章链接的发送回执，再核对来源、版本、URL 和 PNG 哈希后发图。公众号预览刷新后旧 URL 对应的待发码会被拒绝；不重复发送已经完成的同一条二维码队列，也不重复发送视频。

预览码可以全自动生成。下述发表确认码必须由平台本次实际生成，两者用途分开记录。

文章准备及官方读回可用公众号 API。实际发表沿用 TurboPush MCP `publish_article`，不自动切换到没有账号权限的 freepublish API；视频审片确认依然只保存视频号草稿。全量 21 个 MCP 工具保持接入。

发表前核对用户真正批准的版本、对应 manifest 和完整 HTML。新版本不沿用旧版批准。保留视频号编辑器原始组件的全部原生字段，包括 nonce 和媒体地址；仅 ID 正确不足以说明组件完整。TurboPush 本地 HTML 相同也不证明平台实际保留了组件，必须读回平台草稿；手机/公开页实播另行记录。`publishType:publish` 与默认 `mass` 群发不同。不得通过关闭公众号风险保护来跳过管理员确认。

## 二维码送回来源会话

官方 Bot SDK 支持 image 上传和图片消息。`publication_qr.py` 只给当前真实任务创建出站记录，不启动发表，不生成或猜测二维码。既有唯一长连接发送器校验来源、版本哈希、捕获时间、图片哈希后，以 image 类型发送，私聊回本人、群消息回原群；不另开第二个 Bot 连接。二维码两分钟过期，发送前再次检查；已过期不发送，结果不明不自动重发。

先通过当前允许的工具取得 TurboPush 本次发表确认弹窗的真实 PNG，存为 `jobs/C编号/vN/publication/confirm.png`。不得拿主页宣传码或登录码冒充发表确认码，不从数据库 Cookie 或未经文档说明的浏览器控制端点提取二维码来绕过工具限制。

对应 capture.json 必须是本次实际观察的回执，包含：

```json
{
  "publisher":"turbo_push",
  "purpose":"publication_confirmation",
  "job_id":"C0001",
  "version":1,
  "source_message_id":"<当前真实入站 msgid，不加 wecom 前缀>",
  "publication_attempt_id":"<本次真实发表尝试的本地回执或平台记录标识>",
  "captured_at":"<实际捕获的 UTC ISO 时间>",
  "image_sha256":"<实际 PNG 的 SHA256>"
}
```

```bash
python publication_qr.py C0001 --version 1 \
  --image jobs/C0001/v1/publication/confirm.png \
  --evidence jobs/C0001/v1/publication/capture.json
```

此命令必须在原企微任务执行期间运行，使用其真实 active-wecom-task.json；不能为了发图伪造入站上下文。出站入队不代表已收到图片，更不代表扫码成功或文章已发表，最后查询 TurboPush 实际发布记录。

## 当前能力边界

v1.1.3 的 21 个 MCP 工具包含 publish_article / publish_video，但没有独立截图或二维码导出工具。图片回传通道可接收真实捕获结果；能否自动捕获取决于发布时实际可用的工具。未取得图片时应明确说“尚未生成/尚未取得二维码”，不得声称已经发出。
