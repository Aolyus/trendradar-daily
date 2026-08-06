# TrendRadar Daily

每天生成两次 AI 资讯推送，并使用两个彼此独立的时钟降低 GitHub Actions 漏触发的概率。

## 当前推送时间

| 时段 | GitHub 主时钟 | Cloudflare 兜底时钟 | 内容 |
| --- | --- | --- | --- |
| 早报 | 北京时间 10:47 | 北京时间 11:17 | 当日全量资讯、AI 分析、视频选题 |
| 下午报 | 北京时间 15:47 | 北京时间 16:17 | 当日新增资讯补全 |

两个时钟会进入同一个 GitHub Actions 工作流。`state/delivery-log.json` 按“日期 + 时段”记录成功状态，所以主时钟已成功时，兜底时钟只检查并退出，不会重复推送。

Cloudflare 兜底时钟需要单独完成一次部署，详见 [双时钟部署说明](docs/DOUBLE_CLOCK_DEPLOY.md)。

## GitHub Secrets

现有资讯推送继续使用以下 Secrets：

- `FEISHU_WEBHOOK_URL`
- `AI_ANALYSIS_ENABLED`
- `AI_API_KEY`
- `AI_MODEL`
- `AI_API_BASE`

Cloudflare 的 `GITHUB_TOKEN` 只保存在 Cloudflare Worker Secret 中，不要加入代码文件。
