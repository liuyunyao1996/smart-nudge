# Smart Nudge PoC architecture

## Optional Asia executive-news branch

The `asia_executive_news` Rule Pack workflow extends only the Custom Bing branch. A query references one of three versioned configuration records, and the runtime binds that query to the matching Bing instance and host allowlist. Foundry Agent search is rejected before any request for this workflow.

```text
3 Custom Bing configurations x 2 languages
    -> up to 60 normalized, natively cited candidates
    -> URL deduplication and local freshness classification
    -> all-news.json (in-window + out-of-window + unknown date)
    -> in-window candidates only
    -> one no-tool English Top-10 curation request
    -> brief.json + brief.md
```

The source catalogue records `source_tier` (`primary` or `authoritative_media`), `source_type`, and source market for every host. The search model supplies candidate market, entities, topic and signal type; local code attaches the configured source metadata and rejects URLs outside the active configuration. The final schema requires attention level/reason and three structured AIA impact dimensions, each with `direct`, `potential`, `not_established`, or `not_applicable` status.

Freshness is intentionally asymmetric: all normalized candidates remain visible in `all-news.json`, while a missing or out-of-window publication date makes a candidate ineligible for summarization. URL quality is intentionally non-destructive: URL shape classifies citations as `specific_article`, `listing_page`, `homepage`, or `unknown`; specific articles receive ranking preference, and listing/homepage-only evidence cannot retain High attention, but candidates remain auditable. These are local eligibility and ranking rules, not independent verification of the model-returned date or page content. The workflow remains subject to the existing native URL citation boundary and does not fetch original pages.

更新日期：2026-09-16（Asia/Shanghai）。

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

默认云端调用机制保持不变；用户已要求回退新增的严格日期和具体来源准入。`--search-approach foundry-agent` 可将搜索阶段替换为同一项目中固定名称和版本的 Prompt Agent；后续规范化、去重、摘要和输出完全共用。

香港、澳门和中国大陆各有独立 Rule Pack，一次运行只选择一个地区和一个 Custom Bing configuration。每个 Rule Pack 定义两个基础语言查询，每个搜索请求最多返回 5 个候选，摘要阶段最多输出 5 条。默认 Custom Bing 路径最多产生 2 次搜索和 1 次摘要。Agent 路径每个网站独立请求一次，英中搜索共享每站最多 3 次 Web Search 工具调用：香港 5 站（含 SFC 同站子域名）最多 5 次 Agent 请求、配置工具预算共 15 次；澳门 2 站最多 2 次 Agent 请求、配置工具预算共 6 次；大陆 4 站最多 4 次 Agent 请求、配置工具预算共 12 次。另有最多 1 次摘要。HTTP 请求均无自动重试。

## Rule Pack

`config/rules/` 下的地区 Rule Pack 是业务规则入口，每份都包含 `bing`、`search` 与 `summarization`。Rule Pack 通过 JSON Schema 和附加模板校验后加载，并在产物中记录 ID、版本及 SHA-256。香港是默认规则；澳门和中国大陆通过 CLI 的 `--rule` 显式选择。

查询模板只允许 `{topic}`、`{date_from}`、`{date_to}` 三个变量。CLI 的 `--topic` 限制为 1–300 个无控制字符文本，`--days` 限制为 1–90。新规则必须放在 `config/rules/` 下。

v1.2.0 Rule Pack 在 `search.agent` 中定义 `sites` 和 `max_tool_calls_per_site`（1–3）。每站有唯一 `site_id` 和 `hosts`，首个 host 用于生成候选查询，同站别名或子域名可用于剩余预算内的改写和本地引用匹配。校验要求网站划分恰好覆盖全部允许域名一次，不能遗漏、重叠或加入未知域名。未配置该可选扩展的旧 Rule Pack 默认将每个 host 视为独立网站，每站预算 3 次。默认 Custom Bing 查询模板与 configuration 未变。

Agent 响应在正式解析前生成 `citation_diagnostics` 并写入每站搜索审计记录，JSON、schema 或调用上限校验失败时仍保留。诊断记录 output/action/source/annotation 类型和固定字段数量、提取到的原生范围内 URL 数、来源与候选脱敏 URL 及哈希。逐 URL 区分 exact match、没有提取到原生范围内 URL、完整 URL 不同、同 host/path 下 query 或 port 不同、站外及无效/非 HTTPS 链接。诊断不会更改引用集合或接受规则；`url_match_status` 仅表示链接比较，最终接受/失败以 `local_validation` 为准。每组最多保留 100 个引用、100 个候选及每候选 100 个 URL，并标记截断。只显示当前网站的 scheme/host/path（path 最多 2048 字符），隐藏 query 值和 fragment，拒绝含凭据 URL 的显示；站外链接只保留哈希。原始 URL/规范化 URL 哈希用于在不保存查询值的情况下比较链接。回答正文、标题及任意未知类型名不进入诊断。

Agent 请求必须显式带 `include=["web_search_call.action.sources"]`，本地 adapter 仅允许这一 include 值；其他额外 include、缺省 include、请求级 `text.format` 仍被拒绝。诊断额外记录 `requested_include` 和 `envelope_checks`（必需字段是否存在、版本/coverage 是否合法、额外字段数量），不记录不受信的 envelope 值。香港 v1.2.0 真实运行已验证四个成功站点返回来源，其他站点不作保证，失败不自动 fallback。运行时提示要求原样复制工具来源 URL，不重建路径、不删除 query、不以索引页替代原文，并提供合法空 envelope 模板；这些只是提示约束，不替代原生证据校验。

两条路径都在收到响应后生成 `citation_diagnostics`；Agent 额外接受原生 `url_citation` annotation 作为引用证据。v1.2.0 香港真实复测已在四个成功 Agent 响应中收到 action sources，IA 请求超时；这不代表所有站点均已验证；后续 v1.3.0 真实测试为空，该严格准入现已回退。

## Search stage

每次查询通过 Responses API 的 `web_search` 工具强制使用 `.env` 指定的 Bing Custom Search project connection 和所选 Rule Pack 指定的 configuration/instance。地区切换不需要改写 `.env`。选择该 API surface 是因为当前 GPT-5-mini 支持 `web_search`，但不支持旧的 `bing_custom_search_preview` 工具类型。检索内容被明确视为不可信数据，不能覆盖本地指令。

Rule Pack 仍定义双语查询、市场、语言和每次最多展示的候选数；`web_search` 不接收旧 Bing 工具的 `count`、`market`、`set_lang` 字段，因此语言和范围约束由预渲染查询、提示、Custom Search instance 与本地过滤共同执行。发给 Structured Outputs 的 schema 会删除 Azure 不支持的约束，并把 `const` 转换为等价的单值 `enum`。

搜索请求固定加入 `include: ["web_search_call.action.sources"]`。模型以严格结构返回标题、发布者、可选日期、grounded note 和 citation URLs；本地转换只保留 citation URL 能规范化匹配 `web_search_call.action.sources` 原生 URL、且 host 在 Rule Pack 允许列表中的条目。`message.content[].annotations` 中的 `url_citation` 只补充标题和 citation offset；annotation 缺失不会使已经通过 action source 匹配的 URL 失效。Bing attribution link 不作为来源，跨语言结果按规范 URL 去重。

可选 Agent 路径调用 `{project_endpoint}/agents/{name}/endpoint/protocols/openai/responses?api-version=v1`，不向共享 Responses endpoint 发送 `agent_reference`。Portal 中该 endpoint 的 Active version 必须与本地记录版本一致。每站分别提交一次请求，包含两个独立的英中 site-scoped 候选查询，不将它们拼成大型 Boolean 查询；结果不足时可在剩余预算内改写一个同站查询，必须保持日期、主题和网站边界。每请求使用 `tool_choice=required` 与 Rule Pack 配置的 `max_tool_calls`（最多 3 次），提示要求结果足够时停止，且不按语言翻倍预算。本地拒绝超出配置预算的响应，但这不能撤销已发生工具调用；真实服务曾返回超限调用，因此配置预算不是硬性计费保证。Prompt Agent 不接受请求级 `text.format`，因此该路径把搜索 JSON Schema 放入运行时提示，要求只返回一个 JSON 对象，再用同一套严格本地 JSON、schema 和引用校验拒绝不合格输出；这不等同于服务端 Structured Outputs 保证。本地引用过滤只接受当前网站的配置 hosts。由于普通 Web Search 不提供 Custom Bing 等价的检索端域名保证，跨网站结果只产生 warning，不进入摘要。

该检查只保证来源链接来自预期 Grounding 响应，不判断 grounded note 中每个事实是否被原文逐句支持。

发布日期可为空，无效格式标准化为 null 并记录 warning。本地不对日期窗口或索引/具体发布来源进行严格准入；索引页只要通过原生引用匹配便可能进入摘要。日期窗口仍保留在查询和业务提示中，但不构成结果端硬性保证。

## Summarization stage

摘要请求不携带搜索工具，只接收规范化后的 source notes，且只能通过 `source_item_id` 引用已有输入。模型不生成 URL；最终链接由本地代码重新附加。

输出是面向 AIA Group CEO 的英文 Top-5 简报，包含 headline、summary、why it matters、发布日期、发布者、来源链接，以及 `High`／`Medium`／`Low` 管理层关注等级、监管信号类型和一句评级理由。关注等级按监管强度、AIA 相关性与紧迫性三项轻量规则生成；不展示虚假精确的数字分数，也不等同于企业风险评级。

`High` 只允许用于模型判定为 `final_rule` 或 `enforcement` 的直接相关事项；本地转换会把其他信号类型的 High 保守降为 Medium 并记录 warning。法律状态、紧迫性或 AIA 适用性不清楚时不得使用 High。评级仍只依据 Bing-grounded source notes，并未独立读取原文。

## Failure behavior

- 一个搜索请求失败：继续其他计划内请求，不自动重试，结果为 `partial`。
- 单条内容无引用、越界或结构无效：只丢弃该条并记录 warning。
- 有成功搜索但没有合格条目：输出 `empty` 简报，不声称“没有事件发生”，且不调用摘要模型。
- 摘要失败或返回未知 source ID：用 grounded notes 生成确定性 fallback，结果为 `partial`；fallback 项标为 `MEDIUM | UNCLASSIFIED`，明确要求人工复核。
- 所有计划内搜索均失败：不生成 brief，CLI 返回非零状态。

原始 Foundry、Bing 工具输出和访问令牌不会写入产物。`--execute-live` 是唯一联网开关；不带该参数时只离线展示查询计划。产物记录所选 search approach；Agent 路径记录非敏感名称、记录版本、site ID、基础查询 IDs、目标 hosts、配置预算及实际返回 Web Search 调用数。收到响应后的本地契约失败也保留脱敏 request/response ID 与 usage，不记录连接凭据或回答正文。

## Out of scope

本 PoC 不包含独立网页下载、Verify Agent、claim/evidence 图、多轮补搜、数据库、跨运行去重、调度、前端或实际推送渠道。输出是可供推送的内容，不是已获生产审批或独立事实核验的报告。
