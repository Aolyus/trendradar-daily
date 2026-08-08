# TrendRadar Daily

每天生成两次 AI 资讯推送，并使用两个彼此独立的时钟降低 GitHub Actions 漏触发的概率。

## 当前推送时间

| 时段 | GitHub 主时钟 | Cloudflare 兜底时钟 | 内容 |
| --- | --- | --- | --- |
| 早报 | 北京时间 10:47 | 北京时间 11:17 | 当日全量资讯、AI 分析、视频选题 |
| 下午报 | 北京时间 15:47 | 北京时间 16:17 | 当日新增资讯补全、强增量视频选题 |

两个时钟会进入同一个 GitHub Actions 工作流。`state/delivery-log.json` 按“日期 + 时段”记录成功状态，所以主时钟已成功时，兜底时钟只检查并退出，不会重复推送。

Cloudflare 兜底时钟需要单独完成一次部署，详见 [双时钟部署说明](docs/DOUBLE_CLOCK_DEPLOY.md)。

## GitHub Secrets

现有资讯推送继续使用以下 Secrets：

- `FEISHU_WEBHOOK_URL`
- `AI_ANALYSIS_ENABLED`
- `AI_API_KEY`
- `AI_MODEL`
- `AI_API_BASE`

选题平台验证可选使用：

- `BRAVE_SEARCH_API_KEY`：验证小红书、B站、YouTube、Reddit 和 X 的公开索引。未配置或搜索失败时会自动跳过，不影响原有推送。

配置方法和消息规则见 [选题平台验证说明](docs/SOCIAL_VALIDATION.md)。

Cloudflare 的 `GITHUB_TOKEN` 只保存在 Cloudflare Worker Secret 中，不要加入代码文件。
