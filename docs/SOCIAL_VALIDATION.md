# 选题平台验证

这个模块只验证已经生成的视频选题，不参与新闻抓取，也不会重新生成选题。

## 工作规则

- 早报只验证推荐靠前的 2 个选题。
- 下午报只验证第 1 个新增强选题。
- 查询小红书、B站、YouTube、Reddit 和 X 的公开搜索索引。
- 同一查询缓存 4 小时，避免重复调用搜索服务。
- 少于 2 条相关证据或少于 3 个成功平台查询时，不在飞书显示验证模块。
- 搜索失败或未配置密钥时，原有资讯与选题仍会正常发送。
- 数量表示本次公开索引能够验证到的结果，不代表平台内容总量。

## 配置 Brave Search

1. 打开 [Brave Search API](https://api-dashboard.search.brave.com/) 并注册。
2. 创建 Search API Key。
3. 打开仓库的 [Actions Secrets](https://github.com/Aolyus/trendradar-daily/settings/secrets/actions)。
4. 点击 `New repository secret`。
5. `Name` 填写 `BRAVE_SEARCH_API_KEY`。
6. `Secret` 填写刚创建的 API Key，然后保存。

不要把 API Key 写进代码、配置文件、README 或聊天截图。

## 飞书显示

只有证据达到最低门槛时，选题消息末尾才会出现：

```text
平台验证｜公开索引
01｜升温｜抢跑 8/10
公开命中：小红书 1｜B站 2｜海外 6
判断：海外已有讨论，中文公开内容仍少，存在抢跑窗口。
证据（公开索引）：YouTube｜代表视频标题｜URL
```

原始搜索结果保存在 `state/social-validation-cache.json`，飞书最多展示每个选题的一条代表证据。
