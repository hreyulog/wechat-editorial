# 公众号正文中的视频组件

视频号作品引用与上传公众号永久视频素材是两条不同的数据链。当前不把素材上传成功、API errcode:0、本地 iframe 或视频标题当作正文已有播放器的证据。

公众号草稿通过官方 api.weixin.qq.com 的 draft/add、draft/update 保存，随后必须 draft/get 读回。含视频文章只有读回的实际组件身份匹配后才能完整送审或记录审核。

- 公众号视频：检查 iframe/video/mpvideo 的实际视频标识属性，不能只在正文全文搜索到 vid 就判成功。
- 视频号卡片：检查 mp-common-videosnap 的 data-id，以及已绑定的 data-username。短分享链接、公众号 media_id、本地 TurboPush 内容 id 均不能替代这两个引用字段。
- 尚未保留所需组件：返回 video_embedding_incomplete / awaiting_video_embed，不把文章预览存在当作“含视频成稿”。
- phone_playback_tested 保持 false，直到有真实手机播放证据。

2026-10-23 Windows 单次诊断：在现有授权草稿中以真实发布记录的 export 引用字段尝试最小视频号组件，官方 draft/update 返回 errcode:0，draft/get 没有保留组件。本次没有调用 TurboPush 的上传/发布端点。该结果只证明这次组件未保留，不能据此认定所有原生卡片均不受官方 API 支持；还需编辑器生成的完整组件作对照。

同次诊断发现，将官方读回的含实体编码 HTML 原样重新提交可能清洗 CSS。已从原始排版产物恢复，读回正文与诊断前完全一致。后续更新必须从已核验的原始 HTML 生成最小修改，比较样式、正文及其他字段，不能仅凭返回成功报告完成。

编辑器真实卡片对照尚待取得，自动插入与手机播放未验收。运行凭证、目标作品标识、草稿内容和原始回执均只保存在本机忽略目录，不进入源码仓库。未在 Linux 实机运行验证。
