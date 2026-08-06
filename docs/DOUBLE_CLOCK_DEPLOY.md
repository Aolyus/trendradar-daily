# 双时钟部署说明

## 工作方式

系统每天有两个推送时段，每个时段由两个独立时钟检查：

| 时段 | GitHub Actions 主时钟 | Cloudflare Worker 兜底时钟 |
| --- | --- | --- |
| 早报 | 北京时间 10:47 | 北京时间 11:17 |
| 下午报 | 北京时间 15:47 | 北京时间 16:17 |

GitHub 主时钟正常运行后会把成功记录写入 `state/delivery-log.json`。Cloudflare 到点后仍会触发同一个工作流，但工作流读取到成功记录就会安全退出。只有主时钟漏跑或执行失败时，Cloudflare 才会补发。

> GitHub Actions 的 `schedule` 可能延迟，甚至在高负载时被丢弃。Cloudflare Cron 也使用 UTC，配置发布后最长可能需要约 15 分钟传播。

## 第一步：创建 GitHub 令牌

1. 打开 [GitHub Fine-grained tokens](https://github.com/settings/personal-access-tokens/new)。
2. `Token name` 填写 `TrendRadar Cloudflare Watchdog`。
3. `Expiration` 建议选择 1 年，并在到期前更换。
4. `Repository access` 选择 `Only select repositories`。
5. 只选择 `Aolyus/trendradar-daily`。
6. 在 `Repository permissions` 中找到 `Actions`，设为 `Read and write`。
7. `Metadata` 保持自动出现的 `Read-only`。
8. 创建令牌，并临时保存。令牌只显示一次，不要发到聊天或写入仓库文件。

## 第二步：部署 Cloudflare 兜底时钟

在 PowerShell 中逐条运行：

```powershell
cd F:\每日AI讯息采集\trendradar-daily-audit\watchdog
npm.cmd install
npx.cmd wrangler login
npx.cmd wrangler secret put GITHUB_TOKEN
npm.cmd test
npx.cmd wrangler deploy
```

执行 `wrangler secret put GITHUB_TOKEN` 后，把第一步创建的令牌粘贴进去并回车。令牌会加密保存在 Cloudflare，不会出现在 GitHub 仓库中。

部署成功后，Cloudflare 会显示 Worker 地址。浏览器打开该地址，应看到：

```json
{"service":"trendradar-watchdog","status":"ok"}
```

## 第三步：确认 GitHub 设置

1. 打开 [Actions 工作流](https://github.com/Aolyus/trendradar-daily/actions/workflows/crawler.yml)。
2. 确认左侧工作流名为 `Get Hot News`。
3. 打开 [Actions 权限设置](https://github.com/Aolyus/trendradar-daily/settings/actions)。
4. 在 `Workflow permissions` 中选择 `Read and write permissions`，保存。

## 手动测试

1. 打开 [Get Hot News](https://github.com/Aolyus/trendradar-daily/actions/workflows/crawler.yml)。
2. 点击 `Run workflow`。
3. 第一次先选 `slot: morning`、`source: manual`、`dry_run: true`，确认抓取可运行但不推送。
4. 再运行一次，选 `slot: morning`、`source: manual`、`force: true`、`dry_run: false`，验证真实推送。
5. 成功后打开 [成功账本](https://github.com/Aolyus/trendradar-daily/blob/main/state/delivery-log.json)，应看到当天 `morning` 的 `success` 记录。
6. 再次用 `force: false` 运行同一时段，日志应显示 `already-delivered`，飞书不会收到重复消息。

## 日常排查

- 完全没有 GitHub Run：GitHub 主时钟漏触发；等待 Cloudflare 兜底时钟。
- Run 显示 `already-delivered`：当天该时段已经成功，不是故障。
- Run 在 `Run TrendRadar with strict Feishu status` 失败：抓取、AI 或飞书发送失败，不会写入成功账本，兜底时钟仍可补发。
- Run 在 `Record successful delivery` 失败：消息可能已发出，但账本保存失败。不要立刻强制重跑，先检查飞书和 Actions 日志。
- Cloudflare 没有触发：检查 Worker 是否部署、Cron Trigger 是否存在，以及令牌是否过期。

官方文档：[Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)、[GitHub Workflow Dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)。
