# 内容制作工作室

你在已获授权的公众号与视频内容工作区内。企业微信指定群的所有成员均可通过真正 @ 机器人发起制作、修改、进度查询与审核。消息凭据由机器人传入，保留真实发起人。只发送本工作室的内容，所有成品回到绑定群。

自然语言制作要求必须推进到实际文件。收到选题后先用 `python studio.py --help`；运行解释器使用 config.json 的 python（仓库 `.venv/bin/python`），不要替换成缺少依赖的系统 Python。用 `new --kind article|video|both --topic "题目"` 创建 C 编号。多任务同时存在时修改和审核必须带编号；主题不明且无法从已有任务确定时才澄清。

## 内容与 Skill

仓库根目录在本目录上两层。数学知识动画先读 `../../math-explainer-animation/SKILL.md`；人物纪录片读 `../../st-petersburg-math-documentary/SKILL.md`；端到端流程读 `../../wechat-editorial-workflow/SKILL.md`。按题目重新调研可靠来源和编写脚本，记录实际访问情况，不改旧案例标题冒充新作品。用户当次的时长、版式、声音要求优先。默认竖屏；知识动画无指定音乐可静音，人物片按其 Skill 处理配音和双语字幕。

版本位于 `jobs/C编号/vN`。文章 `article.json` 含 title、subtitle、sections（heading、paragraphs）、sources（title、url）、fact_check（checked、notes）。历史、年代、数学条件及归属必须核对，推断与史实分开。视频源文件写 `src/index.tsx`，注册 Remotion composition `ReviewVideo`；逐帧驱动。需要导入独立视频时使用 `src/video-import.json`，源文件必须在本版本 src 内并记录 SHA256、帧数、宽高和 fps；不得引用其他项目的任意私人文件。

`build C编号` 实际生成排版、封面、MP4、完整解码、编码关键帧及 manifest。必须实际查看最终图片/编码帧，修复后重建，再写 visual-review.json（checked:true、notes）。未实际查看、未听审的项目如实标未执行，不能自动勾选。已入队或审核的版本不能原地覆盖；修改用 `revise C编号 --note "意见"` 生成下一版本。

## 公众号草稿

只允许官方 `https://api.weixin.qq.com` 草稿接口。凭证在仓库根 `.env`，不要打印密钥或 token。`official_api.py check` 只核查凭证及草稿读取权限；新的 Linux 出口 IP 需要加入公众号白名单。

文章 build 后运行 `official C编号 --step prepare`；用 config.json 的 node 运行 `preview-html.mjs jobs/C编号/vN/official/wechat.html`，实际查看生成的 wechat.png 和封面。将结果写 official/visual-review.json，含 checked:true、notes 和 binding.json 对应的 html_sha256。然后运行 `official C编号 --step submit`：上传封面、创建一次草稿、按 media_id 读回真实官方预览 URL。outcome_unknown 不得自动重建草稿。已有 media_id 时 submit 只读回刷新预览。

只接受官方真实返回或用户直接提供的 HTTPS mp.weixin.qq.com/s 预览地址；编辑器后台地址、localhost、伪造 URL 不能作为审核链接。不得绕过浏览器站点限制访问后台。草稿不是公开发布；“通过 C编号-vN”只记录审核，不执行发布。

## 企业微信群送审

`deliver C编号` 将真实官方预览链接和 MP4 入队。机器人常驻服务通过单一官方长连接发送，不依赖桌面微信。默认自动回复严格为“收到，处理中”。所有群成员可 @；不要限制到最初绑定者。禁止补发历史队列或跨发其他群。

原生视频实测会拒绝约 19.4MB 的视频；不要把 SDK 通用 50MiB 分片上限当成视频类型限额。发送器对超过 9.5MiB 的视频生成完整时长的 720p 审片副本，保留原片和 manifest，记录来源哈希与解码结果。文本成功而视频失败时，只续传视频，不重复文章。sent 仅代表服务器成功回执；未确认实际收到时不冒称用户已收到。

不要编辑 outbox/*.json 或机器人的 state；发送器独占这些状态。执行或发送结果不明时保留 outcome_unknown/delivery_unknown，不能盲目重试。上传明确失败可由操作员依据真实错误解除后重新入队。查询用 `status C编号` / `status`；群里 `进度 C编号` / `任务列表` 直接由路由处理。

审核命令：`通过 C编号-vN` 记录真实用户消息凭据，保持 published:false。`修改 C编号 …` 新建版本，保留旧版。`草稿链接 C编号-vN https://...` 仅登记该入站用户直接给出的官方预览。不要自行生成或代替用户执行“通过”。

最终答复简短列任务编号、产物和真实发送状态。已由队列发送的文件不要用其他渠道再发。Linux 版尚未实际部署验收；遇到运行问题保存证据并如实报告，不沿用 Windows 历史成功结论。

TurboPush 仅是可选本地内容库适配器，默认关闭；不代表视频号后台已上传。Linux 包不承诺桌面 TurboPush 可用，不调用其浏览器发布接口，也不自动公开发布。
