# Smart Nudge PoC architecture

更新日期：2026-09-14（Asia/Shanghai）。

## Runtime flow

```text
JSON Rule Pack
    ↓ render two bounded queries
Foundry Responses web_search + existing Bing Custom Search configuration
    ↓ native in-scope URL citation check and URL deduplication
Grounded source notes
    ↓ one no-tool Foundry summarization and attention assessment request
Top-5 English executive brief with compact attention labels
    ↓
Markdown + JSON
```

默认流程保持不变。`--search-approach foundry-agent` 可将搜索阶段替换为同一项目中固定名称和版本的 Prompt Agent；后续规范化、去重、摘要和输出完全共用。

香港、澳门和中国大陆各有独立 Rule Pack，一次运行只选择一个地区和一个 Custom Bing configuration。每个 Rule Pack 定义两个语言查询，每个搜索请求最多返回 5 个候选，摘要阶段最多输出 5 条。默认 Custom Bing 路径最多产生 2 次搜索和 1 次摘要；Agent 路径按每两个允许域名拆分每个语言查询，香港最多产生 6 次搜索和 1 次摘要，澳门或中国大陆最多产生 4 次搜索和 1 次摘要。所有请求均无自动重试。

## Rule Pack

`config/rules/` 下的地区 Rule Pack 是业务规则入口，每份都包含 `bing`、`search` 与 `summarization`。Rule Pack 通过 JSON Schema 和附加模板校验后加载，并在产物中记录 ID、版本及 SHA-256。香港是默认规则；澳门和中国大陆通过 CLI 的 `--rule` 显式选择。

查询模板只允许 `{topic}`、`{date_from}`、`{date_to}` 三个变量。CLI 的 `--topic` 限制为 1–300 个无控制字符文本，`--days` 限制为 1–90。新规则必须放在 `config/rules/` 下。

## Search stage

每次查询通过 Responses API 的 `web_search` 工具强制使用 `.env` 指定的 Bing Custom Search project connection 和所选 Rule Pack 指定的 configuration/instance。地区切换不需要改写 `.env`。选择该 API surface 是因为当前 GPT-5-mini 支持 `web_search`，但不支持旧的 `bing_custom_search_preview` 工具类型。检索内容被明确视为不可信数据，不能覆盖本地指令。

Rule Pack 仍定义双语查询、市场、语言和每次最多展示的候选数；`web_search` 不接收旧 Bing 工具的 `count`、`market`、`set_lang` 字段，因此语言和范围约束由预渲染查询、提示、Custom Search instance 与本地过滤共同执行。发给 Structured Outputs 的 schema 会删除 Azure 不支持的约束，并把 `const` 转换为等价的单值 `enum`。

搜索请求固定加入 `include: ["web_search_call.action.sources"]`。模型以严格结构返回标题、发布者、可选日期、grounded note 和 citation URLs；本地转换只保留 citation URL 能规范化匹配 `web_search_call.action.sources` 原生 URL、且 host 在 Rule Pack 允许列表中的条目。`message.content[].annotations` 中的 `url_citation` 只补充标题和 citation offset；annotation 缺失不会使已经通过 action source 匹配的 URL 失效。Bing attribution link 不作为来源，跨语言结果按规范 URL 去重。

可选 Agent 路径调用 `{project_endpoint}/agents/{name}/endpoint/protocols/openai/responses?api-version=v1`，不向共享 Responses endpoint 发送 `agent_reference`。Portal 中该 endpoint 的 Active version 必须与本地记录版本一致。为了避免单个普通 Web Search 查询同时覆盖过多网站，每个语言查询按 Rule Pack 顺序以两个允许域名为一组拆分为独立请求；每个请求使用 `tool_choice=required` 与 `max_tool_calls=1`，本地还会拒绝包含多个 Web Search call 的响应。Prompt Agent 不接受请求级 `text.format`，因此该路径把搜索 JSON Schema 放入运行时提示，要求只返回一个 JSON 对象，再用同一套严格本地 JSON、schema 和引用校验拒绝不合格输出；这不等同于服务端 Structured Outputs 保证。每个拆分请求只组合当前组的 `site:host` 条件，并在提示中重复该组 allowlist；本地引用过滤也限制为当前组。由于普通 Web Search 不提供 Custom Bing 等价的检索端域名保证，站外或跨组结果只产生 warning，不进入摘要。

该检查只保证来源链接来自预期 Grounding 响应，不判断 grounded note 中每个事实是否被原文逐句支持。

## Summarization stage

摘要请求不携带搜索工具，只接收规范化后的 source notes，且只能通过 `source_item_id` 引用已有输入。模型不生成 URL；最终链接由本地代码重新附加。

输出是面向 AIA Group CEO 的英文 Top-5 简报，包含 headline、summary、why it matters、发布日期、发布者、来源链接，以及 `High`／`Medium`／`Low` 管理层关注等级、监管信号类型和一句评级理由。关注等级按监管强度、AIA 相关性与紧迫性三项轻量规则生成；不展示虚假精确的数字分数，也不等同于企业风险评级。

`High` 只允许用于模型判定为 `final_rule` 或 `enforcement` 的直接相关事项；本地转换会把其他信号类型的 High 保守降为 Medium 并记录 warning。法律状态、紧迫性或 AIA 适用性不清楚时不得使用 High。评级仍只依据 Bing-grounded source notes，并未独立读取原文。

## Failure behavior

- 一个语言搜索失败：继续另一个查询，结果为 `partial`。
- 单条内容无引用、越界或结构无效：只丢弃该条并记录 warning。
- 有成功搜索但没有合格条目：输出 `empty` 简报，不声称“没有事件发生”，且不调用摘要模型。
- 摘要失败或返回未知 source ID：用 grounded notes 生成确定性 fallback，结果为 `partial`；fallback 项标为 `MEDIUM | UNCLASSIFIED`，明确要求人工复核。
- 所有计划内搜索均失败：不生成 brief，CLI 返回非零状态。

原始 Foundry、Bing 工具输出和访问令牌不会写入产物。`--execute-live` 是唯一联网开关；不带该参数时只离线展示查询计划。产物记录所选 search approach；Agent 路径只记录非敏感名称和固定版本，不记录连接凭据。

## Out of scope

本 PoC 不包含独立网页下载、Verify Agent、claim/evidence 图、多轮补搜、数据库、跨运行去重、调度、前端或实际推送渠道。输出是可供推送的内容，不是已获生产审批或独立事实核验的报告。
