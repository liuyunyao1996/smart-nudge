# Smart Nudge PoC architecture

更新日期：2026-09-13（Asia/Shanghai）。

## Runtime flow

```text
JSON Rule Pack
    ↓ render two bounded queries
Foundry + Grounding with Custom Bing Search
    ↓ native in-scope URL citation check and URL deduplication
Grounded source notes
    ↓ one no-tool Foundry summarization request
Top-5 English executive brief
    ↓
Markdown + JSON
```

默认 Rule Pack 运行英文和繁体中文两个香港查询。每个查询最多请求 5 个结果；摘要阶段最多输出 5 条。因此一次完整运行最多产生 3 个 Foundry Responses 请求，且没有自动重试。

## Rule Pack

`config/rules/hk-regulatory-pulse.json` 是唯一业务规则入口，包含 `search` 与 `summarization` 两部分。Rule Pack 通过 JSON Schema 和附加模板校验后加载，并在产物中记录 ID、版本及 SHA-256。

查询模板只允许 `{topic}`、`{date_from}`、`{date_to}` 三个变量。CLI 的 `--topic` 限制为 1–300 个无控制字符文本，`--days` 限制为 1–90。新规则必须放在 `config/rules/` 下。

## Search stage

每次查询强制使用 `.env` 指定的 Bing Custom Search project connection 和 Rule Pack 指定的 instance。检索内容被明确视为不可信数据，不能覆盖本地指令。

模型以严格结构返回标题、发布者、可选日期、grounded note 和 citation URLs。本地转换只保留至少有一个 Bing 原生 `https` citation、且 host 在 Rule Pack 允许列表中的条目。citation offset 不可用只形成 warning，不过滤合法 URL；Bing attribution link 不作为来源。跨语言结果按规范 URL 去重。

该检查只保证来源链接来自预期 Grounding 响应，不判断 grounded note 中每个事实是否被原文逐句支持。

## Summarization stage

摘要请求不携带搜索工具，只接收规范化后的 source notes，且只能通过 `source_item_id` 引用已有输入。模型不生成 URL；最终链接由本地代码重新附加。

输出是面向 AIA Group CEO 的英文 Top-5 简报，包含 headline、summary、why it matters、发布日期、发布者和来源链接。对 AIA 的影响必须使用条件式表达，不能从公开内容虚构实体适用性或量化影响。

## Failure behavior

- 一个语言搜索失败：继续另一个查询，结果为 `partial`。
- 单条内容无引用、越界或结构无效：只丢弃该条并记录 warning。
- 有成功搜索但没有合格条目：输出 `empty` 简报，不声称“没有事件发生”，且不调用摘要模型。
- 摘要失败或返回未知 source ID：用 grounded notes 生成确定性 fallback，结果为 `partial`。
- 两次搜索均失败：不生成 brief，CLI 返回非零状态。

原始 Foundry、Bing 工具输出和访问令牌不会写入产物。`--execute-live` 是唯一联网开关；不带该参数时只离线展示查询计划。

## Out of scope

本 PoC 不包含独立网页下载、Verify Agent、claim/evidence 图、多轮补搜、数据库、跨运行去重、调度、前端或实际推送渠道。输出是可供推送的内容，不是已获生产审批或独立事实核验的报告。
