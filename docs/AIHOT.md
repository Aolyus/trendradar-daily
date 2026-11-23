# AIHOT 信源与 AI 分析状态

`config/config.yaml` 仅保留 AIHOT 精选摘要 RSS，已移除旧 RSS 并清空热榜平台列表，飞书不再展示旧热榜。沿用现有两天新鲜度过滤、关键词筛选、早晚推送和去重流程，不回补几个月的历史消息。AIHOT 摘要由信源提供，不消耗本项目的翻译模型额度；本项目独立分析和视频选题仍需 AI_API_KEY 对应账户的可用余额。

原始 RSS：https://aihot.news/feed.xml

## 余额不足

飞书出现 `Insufficient Balance` 表示模型服务余额不足。DeepSeek 官方说明：https://api-docs.deepseek.com/quick_start/error_codes/

在 https://platform.deepseek.com/ 登录与当前 AI_API_KEY 对应的账户，查看 API 余额并自行充值。无需因充值更换密钥，充值后下一次定时运行自动尝试分析。

余额不足时仍发送资讯，并用一句中文提示说明分析不可用。`output/ai-status.json` 仅在当前工作流共享状态，视频选题跳过已确认会失败的余额/认证请求。每次运行清空该状态，不会在充值后永久禁用分析。临时网络或服务错误不阻止独立选题尝试。

## 验证

运行 `python -m unittest discover -s tests -v`。真实 RSS 应返回 RSS 2.0，包含中文标题、摘要和阅读链接。工作流的 Collect only 模式可验证抓取，但不会调用 AI 或发送消息；真实模型恢复需充值后以一次正常工作流验证。

成功推送记录表示资讯已送达；若 AI 分析失败，Actions 会另有 AI analysis 警告，不应把推送成功理解成分析也成功。
