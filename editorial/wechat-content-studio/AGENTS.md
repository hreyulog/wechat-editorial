# 内容制作工作室

## 2026-10-23 草稿身份与视频点播核验

同名草稿不能互换。保存过的视频卡片只属于其实际 media_id；原 ID 返回 40007 或不在列表时，记录原草稿不可读，不能据此认定已发表，也不能按同名、相同正文、最近更新时间自动选另一篇继续写。需用户明确指定新的草稿身份后再重新绑定、读回并送审；原稿、素材、历史记录不删除。

studio.py deliver/review 对含视频号文章会实时读取同一个 media_id，核对 receipt、official-preview、readback 哈希与 manifest；远端被用户修改则停止，不覆盖，先按版本采纳真实修改。API 卡片字段保留仅是数据检查，送审明确“手机显示与点播待确认”，不宣称后台可见或已发表页可播放。官方预览失效就暂停发送该预览及其二维码。

用户说“只发两句、不改文章、不搞别的”立即停止后续保存、上传或发表，将回复限制在用户新范围；正在执行的写入按实际回执核对，不擅自补做或回滚。

你在已获授权的公众号与视频内容工作区内。企业微信指定群的所有成员均可通过真正 @ 机器人发起制作、修改、进度查询与审核，已确认的群成员也可私聊机器人。消息凭据由机器人传入，保留真实发起人。只发送本工作室的内容。用户要求“谁发消息在哪回复”：进度、最终答复、文章链接、MP4 附件全部回到入站来源会话，私聊回本人，群消息回原群，不跨会话转发。

关键阶段的用户可见 commentary 会直接转到群里，不需要等全部完成。简短说明实际发现和下一步，不发内部推理或工具日志。需要用户选择音色、叙事方向或试听确认时，先提供真实小样/明确问题，在最终答复中说明等待选择并结束本轮，收到下一条消息后继续。不要边问边擅自全部做完。执行中的新群消息可由 turn/steer 即时补充；只按实际收到的消息调整，不虚称已读未知意见。停止调用原生 turn/interrupt，“打断：新要求”中断后按已有文件和最新要求续做；不要自动重做已完成的远端写入或推送过时稿件。

自然语言制作要求必须推进到实际文件。收到选题后先用 `python studio.py --help`；运行解释器使用 config.json 的 python（仓库 `.venv/bin/python`），不要替换成缺少依赖的系统 Python。用 `new --kind article|video|both --topic "题目"` 创建 C 编号。多任务同时存在时修改和审核必须带编号；主题不明且无法从已有任务确定时才澄清。

## 内容与 Skill

仓库根目录在本目录上两层。数学知识动画先读 `../../math-explainer-animation/SKILL.md`；人物纪录片读 `../../st-petersburg-math-documentary/SKILL.md`；端到端流程读 `../../wechat-editorial-workflow/SKILL.md`。按题目重新调研可靠来源和编写脚本，记录实际访问情况，不改旧案例标题冒充新作品。用户当次的时长、版式、声音要求优先。默认竖屏；知识动画无指定音乐可静音，人物片按其 Skill 处理配音和双语字幕。

已有数学人物系列中，“做马尔可夫的视频”“下一期做某位数学家”默认是人物纪录片；只有明确要求马尔可夫链、定理或算法原理才用知识动画。人物片先读仓库 Skill 的 references/petersburg-series.md，延续切比雪夫的“人物故事＋史料幻灯片＋克制配乐＋已选音色＋参考字幕”，在本期 brief 写 series_style 与参考版本。不得让静音/SVG/10–15秒知识试片的默认覆盖人物片，也不能把通用深色知识卡模板冒充同系列风格。

版本位于 `jobs/C编号/vN`。文章 `article.json` 含 title、subtitle、sections（heading、paragraphs）、sources（title、url）、fact_check（checked、notes）。历史、年代、数学条件及归属必须核对，推断与史实分开。视频源文件写 `src/index.tsx`，注册 Remotion composition `ReviewVideo`；逐帧驱动。需要导入独立视频时使用 `src/video-import.json`，源文件必须在本版本 src 内并记录 SHA256、帧数、宽高和 fps；不得引用其他项目的任意私人文件。

`build C编号` 实际生成排版、封面、MP4、完整解码、编码关键帧及 manifest。必须实际查看最终图片/编码帧，修复后重建，再写 visual-review.json（checked:true、notes）。未实际查看、未听审的项目如实标未执行，不能自动勾选。已入队或审核的版本不能原地覆盖；修改用 `revise C编号 --note "意见"` 生成下一版本。

## 公众号草稿

只允许官方 `https://api.weixin.qq.com` 草稿接口。凭证在仓库根 `.env`，不要打印密钥或 token。`official_api.py check` 只核查凭证及草稿读取权限；新的 Linux 出口 IP 需要加入公众号白名单。

文章 build 后运行 `official C编号 --step prepare`；用 config.json 的 node 运行 `preview-html.mjs jobs/C编号/vN/official/wechat.html`，实际查看生成的 wechat.png 和封面。将结果写 official/visual-review.json，含 checked:true、notes 和 binding.json 对应的 html_sha256。然后运行 `official C编号 --step submit`：上传封面、创建一次草稿、按 media_id 读回真实官方预览 URL。outcome_unknown 不得自动重建草稿。已有 media_id 时 submit 只读回刷新预览。

只接受官方真实返回或用户直接提供的 HTTPS mp.weixin.qq.com/s 预览地址；编辑器后台地址、localhost、伪造 URL 不能作为审核链接。不得绕过浏览器站点限制访问后台。公众号草稿不是公开发布；纯文章的“通过 C编号-vN”只记录审核，不执行发布。

含视频文章还必须核对 draft/get 正文中的实际组件及身份；素材上传、errcode:0 和标题保留均不代表播放器保留。video_embedding_incomplete / awaiting_video_embed 时不能当作含视频成稿送审或审核。视频号原生卡片已用真实编辑器样本验证可经官方 add/update 保存。使用 article.channel_video 的 source（src 内描述文件）和 after_paragraph，由 channel_video.py 自动插入；描述文件必须含真实 export_id 和该账号 username，不从短链接或标题猜测作品身份。旧 video_embed 与 channel_video 二选一。新作品不得沿用旧作品 ID；上传视频号草稿也不代表已经存在公开引用 ID。可用 capture 从指定官方草稿提取卡片；用户手动保存的当前版本可显式 adopt 后 submit 刷新读回，adopt 不改远端或已送审源文件。修改已有草稿时只用授权的 draft/update，保留原始 HTML 和前后读回，不直接往返提交含实体编码的回读 HTML 造成样式丢失。详见 ../../docs/ARTICLE-VIDEO.md。

## 企业微信群送审

公众号文章送审自动附真实官方预览链接和该链接的预览二维码 PNG，以 image 消息回原会话；`studio.py deliver` 自动入队，`article_preview_qr.py` 可以为已发送的同版本审稿回执补一张预览码。预览码不是管理员发表确认码，不代表公开发表。不得伪造入站、擅自改目的地或重复发送视频。

`deliver C编号` 将真实官方预览链接和 MP4 文件附件入队。当前入站上下文 state/active-wecom-task.json 的 reply_to 决定目的地；不要覆盖上下文或手改 outbox。私聊来源只回该私聊，群来源回原群。机器人常驻服务通过单一官方长连接发送，上传和发送均使用 file 类型，保留 C编号-v版本.mp4 文件名。不要仅给视频路径或下载链接。默认自动回复严格为“收到，处理中”。所有群成员可 @；不要限制到最初绑定者。禁止补发历史队列或跨发其他会话。

旧 video 类型实测会拒绝约 19.4MB 的视频；不要把 SDK 通用 50MiB 分片上限当成各媒体类型限额。当前改发 file 类型，仍保留超过 9.5MiB 时生成完整时长 720p 审片副本的策略，保留原片和 manifest，记录来源哈希与解码结果。文本成功而附件失败时，只续传附件，不重复文章。sent 仅代表服务器成功回执；未确认实际收到时不冒称用户已收到。

不要编辑 outbox/*.json 或机器人的 state；发送器独占这些状态。执行或发送结果不明时保留 outcome_unknown/delivery_unknown，不能盲目重试。上传明确失败可由操作员依据真实错误解除后重新入队。查询用 `status C编号` / `status`；群里 `进度 C编号` / `任务列表` 直接由路由处理。

审核命令：纯文章的 `通过 C编号-vN` 记录审核；视频的确认规则见下节，始终保持 published:false。`修改 C编号 …` 新建版本，保留旧版。`草稿链接 C编号-vN https://...` 仅登记该入站用户直接给出的官方预览。不要自行生成或代替用户执行“通过”。

## 视频文件审核后上传草稿

公众号明确发表任务沿用 TurboPush MCP `publish_article`，不要擅自改走 `freepublish/submit`，也不要在官方发布 API 返回 48001 后就结束任务。真正批准当前版本后，先查询 schema/账号、核对完整已审 HTML，再显式区分发表与群发。新版本必须重新确认，不沿用旧版本批准。真实 QR 出现时，按 [扫码确认图片](../../docs/PUBLICATION-QR.md) 用 image 类型送回原会话；二维码尚未生成就如实报告。保留原始 MP4 和所有已审版本；修复卡片不删除素材或重建视频。

含视频文章从编辑器 capture 的 `native_html` 原样插入，按 SHA256 绑定；官方读回要核对全部原生 data 属性，不能再只保留 ID、账号、标题。历史的仅 ID 描述不足以证明可播放，发表前需换成完整真实组件。草稿字段齐全仍不等于手机或已发表页面已实播验证。

用户最新要求：视频做好后，先把实际 MP4 文件以及视频名、完整简介、目标视频号和版本发回来源会话；用户看完回复 OK 后才上传视频号草稿箱。不再要求后台手机预览二维码。本流程仅授权保存草稿，不能把 OK 当作公开发布授权。

每个视频版本必须有 video-metadata.json，含 title、description 和 account；account 优先用 MCP 返回的目标账号 id/name。标题和简介写准备实际上传的完整内容，不能只写选题占位。build 将文案加入 manifest，deliver 在文本中列出视频名、完整简介、目标账号、C编号-vN.mp4，并以 file 附件发送 MP4。送审后修改文案或视频都要 revise，新版本重新送审。

用户回复 `OK C编号-vN` 或 `确认上传 C编号-vN` 后，路由验证真实入站、来源会话、已发送的文件成功回执和当前版本哈希，生成 video-draft-approval.json 与 draft_request。只有当前会话恰好一个未确认当前视频时接受单独 OK。视频的“通过 C编号-vN”同样只授权草稿上传；纯文章仍只记录审核。重复确认不重复提交。

执行器核对审核回执、manifest、video-metadata.json，使用已审核的同一视频、标题、简介和目标账号，通过 TurboPush MCP publish_video 明确设置 syncDraft:true。已有本地内容时先查 id 与实际文案；本地入库不等于视频号草稿成功。结果不明先查 list_records/get_record_info，不盲目重试，不处理历史稿件。

最终答复必须列出：视频名、完整视频简介、目标视频号、任务版本、文件名、实际草稿上传状态和记录号。失败或结果不明如实说明；只有真实记录成功才能说已上传草稿箱。已由队列发送的文件不重复发。公众号继续发送真实官方草稿预览链接，不能由视频确认顺带公开发布文章。

可选 TurboPush MCP 配置在 state/turbopush-mcp.json，由执行器显式加载为 turbo_push，方法见 ../../docs/TURBOPUSH-MCP.md。启用后暴露与工作机一致的 21 个工具，包括 publish_video。查询优先用 MCP，已有 turbopush-local.json 时用其 id 避免重复创建。删除内容或平台设置必须由用户当次明确点名。

执行仍遵守实际工具和站点策略，遇到拒绝保留对应工具的实际错误，不通过其他路径绕过。区分浏览器、MCP、本地入库、远端草稿和公开发布的实际结果，不把未调用工具的推断当作原始报错。Linux 版未实机运行验收，不能沿用 Windows 历史成功结论。详细格式见 ../../docs/VIDEO-REVIEW.md。
