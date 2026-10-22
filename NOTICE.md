# 来源与授权说明

本仓库原有两个视频 Skill 保留其文件与方法来源。新增的 editorial 目录整理了本机内容制作和企业微信审核工作流，并为 Linux 去除固定机器路径。

`editorial/upstream/wechat-article-skills` 是 [aiworkskills/wechat-article-skills](https://github.com/aiworkskills/wechat-article-skills) 的排版与草稿构造辅助代码子集，固定于 `ca036f75f4bac4fcefe6eaedd8d22d97bf8c92ca`，未修改。上游 [Apache-2.0 LICENSE](editorial/upstream/wechat-article-skills/LICENSE) 与来源记录随包保留。完整套件的其他 Skill 不在该子集中，部分上游参考链接指向原仓库的其他目录。

企业微信连接使用 [WecomTeam/aibot-node-sdk](https://github.com/WecomTeam/aibot-node-sdk)，依赖版本 1.0.7。运行依赖由 npm / pip 安装，不把它们的二进制或 node_modules 重新打进迁移包。Remotion 等依赖的使用应遵守各自项目许可。

未将私人对话、微信/公众号凭证、原始附件、第三方音视频、已有完整成片、缓存或登录状态分发到本仓库。
