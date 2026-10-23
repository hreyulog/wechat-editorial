# 公众号正文中的视频组件

视频号作品引用与上传公众号永久视频素材是两条不同的数据链。当前不把素材上传成功、API errcode:0、本地 iframe 或视频标题当作正文已有播放器的证据。

公众号草稿通过官方 api.weixin.qq.com 的 draft/add、draft/update 保存，随后必须 draft/get 读回。含视频文章只有读回的实际组件身份匹配后才能完整送审或记录审核。

- 公众号视频：检查 iframe/video/mpvideo 的实际视频标识属性，不能只在正文全文搜索到 vid 就判成功。
- 视频号卡片：检查 mp-common-videosnap 的 data-id，以及已绑定的 data-username。短分享链接、公众号 media_id、本地 TurboPush 内容 id 均不能替代这两个引用字段。
- 尚未保留所需组件：返回 video_embedding_incomplete / awaiting_video_embed，不把文章预览存在当作“含视频成稿”。
- phone_playback_tested 保持 false，直到有真实手机播放证据。

2026-10-23 Windows 对照：用户在公众号编辑器手动插入并保存后，draft/get 读到了真实 mp-common-videosnap。其作品 ID 与先前发布记录中的未验证候选不同，且带有真实 data-username。使用完整组件创建独立测试草稿成功；在同一测试草稿中用仅含真实作品 ID、账号、基本描述和尺寸的组件 draft/update，再 draft/get 仍保留组件。先前失败不能归结为所有官方草稿接口都过滤视频号组件；错误候选 ID 和缺少账号的构造未成功，具体是哪一个条件导致失败未单独判定。

同次诊断发现，将官方读回的含实体编码 HTML 原样重新提交可能清洗 CSS。已从原始排版产物恢复，读回正文与诊断前完全一致。后续更新必须从已核验的原始 HTML 生成最小修改，比较样式、正文及其他字段，不能仅凭返回成功报告完成。

## 自动插入入口

工作室新增 `channel_video.py`，render 和 official prepare 自动调用插入函数。文章配置示意：

```json
{"channel_video":{"source":"src/channel-video.json","after_paragraph":"先看短片，再往下读。"}}
```

`src/channel-video.json` 记录真实 `export_id`（export/ 开头）、`username`（v2_…@finder）、`nickname`、`description`，可选 `width`、`height`。不得从短分享链接、内容标题、本地内容 ID 猜测作品标识；也不能把另一期作品的 ID 沿用到新视频。视频号草稿上传成功不等于已取得可被文章引用的公开作品身份。

从用户手动保存的某篇草稿提取指定作品（只调用 draft/get，不写远端）：

```powershell
python channel_video.py capture --media-id "实际草稿ID" --export-id "实际export作品ID" --output jobs/C编号/vN/src/channel-video.json
```

也可使用已核实的发布记录作品 ID，配合该账号从官方卡片取得的真实 username 生成描述文件。只有候选 ID、没有可确认身份时保持待补充状态，不伪造成功。当前账号已取得一次真实样本，工作机缓存位于忽略的 state/channel-components，迁移包不带该缓存。

流程：设置 channel_video → build（原始排版 HTML 后的唯一段落位置插卡）→ official prepare → 查看本地排版并绑定哈希 → official submit → 官方读回核对 ID 与账号 → deliver。插入保留原始 HTML，不解码整个正文；已经存在的同一张卡片不重复插入，不静默覆盖其他作品。不能同时配置旧的 video_embed iframe。卡片被清洗时继续返回 video_embedding_incomplete。

用户已经手动替换了既有版本的视频时，可以显式采纳这份远端卡片：

```powershell
python channel_video.py adopt C编号 --version N --export-id "实际export作品ID"
python official_drafts.py submit C编号 --version N
```

adopt 只读取当前草稿并记录 official/channel-binding.json，不改远端、不改已送审源文件。绑定包含原草稿 ID 与 manifest 哈希；跨版本或跨草稿失效。后续仍必须读回匹配的卡片才允许送审。

工作机实际通过“新插入函数生成组件 → 独立测试草稿 update → get 校验”验证；用户原稿正文和其他稳定字段未改变，未公开发表、未自动发消息。手机播放尚未验证。保留了一篇标题为《接口验证｜视频号卡片》的测试草稿。运行凭证、目标作品标识、草稿内容和原始回执均只保存在本机忽略目录，不进入源码仓库。未在 Linux 实机运行验证。
