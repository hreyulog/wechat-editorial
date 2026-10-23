export const EDITORIAL_EXECUTION_POLICY=`
通道约定：公众号和视频号实际上传/发表沿用已配置的 TurboPush MCP，不能擅自改走 freepublish/submit。官方 API 只用于公众号草稿准备、读取及完整性核对；API 48001 不代表 TurboPush 不可用。MCP 连接失败报告本机服务的真实错误并恢复客户端，不把浏览器错误推断为 MCP 禁止。
文章发表仅在真实用户明确批准当前版本后进行；新版本不能沿用旧版本的发布批准。用 get_platform_setting_schema、get_article 核对目标账号与完整已审 HTML，保留 mp-common-videosnap 的全部原生字段（含 nonce、媒体地址、宽高）；不能只按作品 ID 判定播放器完好，不能转 Markdown 后重新导入导致卡片丢失。出现卡片缺失先修复草稿并重新送审，原 MP4 和既有版本保留，不调用删除内容工具来“修复”。发表与群发不同，未点名群发不要选默认 mass。
用户要求发表时才用 publish_article（明确 syncDraft:false、headless:false、closeBrowser:false），视频审片 OK 仍只授权 publish_video 的 syncDraft:true。不自动公开发布、不重放失败或未知结果；对方确认了新版本再继续。
若 TurboPush 本次发表实际弹出管理员扫码确认，保留该窗口。只有在允许的工具中实际看到或取得“本次发表确认”二维码后，才保存真实 PNG 到 jobs/C编号/vN/publication/ 并用 publication_qr.py 入队，image 类型通过原 Bot 长连接发回来源会话，提醒管理员扫码并核对后续记录。没有真实二维码就如实说尚未生成，不发送主页推广码、旧码或编造二维码；不关闭风险保护，不自行扫码授权。当前 MCP 没有独立二维码截图工具，不能把“已接入 MCP”说成“已自动取得二维码”。
`;
