# P4-B Foundry/Bing 模拟适配器

更新日期：2026-09-04（Asia/Shanghai）。本阶段实现初扫、事件级补搜、获准精确 URL 原文读取和 locator-bound 核验的 mocked transport 闭环；不读取 `.env`、不获取真实 Azure 凭据、不发起网络请求，也不创建或修改云资源。

## 已实现

`smart_nudge.foundry_research.FoundryResearchRequestBuilder` 接收已经通过 P4-A 契约验证的研究请求、当前 `ResearchContext`、coverage plan、固定版本的 Skill bundle，以及显式传入的 Foundry/Bing 配置对象。它为每个覆盖任务中的本地 Skill 查询模板生成一个 Foundry Responses 请求候选。`MockedFoundryResearchRole` 只能通过 `httpx.MockTransport` 执行这些请求；没有 mock transport 时在认证前拒绝。

请求具有以下边界：

- 直接指定模型部署和 `bing_custom_search_preview`，不使用 `agent_reference` 或托管 Agent 会话。
- `store=false`，且审计记录不包含 prompt、查询文本、响应正文或未来证据内容。
- 每个请求消耗一个本地查询预算单位；请求批次数不超过 `remaining_queries`。
- Bing `count` 的批次合计不超过 `remaining_evidence_records`，单请求最多 7 条候选结果。
- 查询模板必须来自该市场固定的 Skill bundle；被篡改或重复的模板拒绝执行。
- P2 trusted/primary 来源必须与任务一致，而且每个来源至少有一个 host 位于显式 Bing Custom Search scope 中。
- 香港英文和繁体中文任务分别携带对应的 Bing market/language 参数；接口同时为已规划的中国内地和马来西亚语言组合保留明确映射。
- 监管查询使用官方发布机构、领域术语、市场和时间窗口，不强制加入 AIA 或其他公司名。
- 控制器只从已形成的未决事件生成补搜简报：稳定事件身份、首次发现语言、原生发现 URL，以及根据结构化缺口推导出的固定证据问题代码；不会把模型自由文本中的 unknowns 直接复制进查询。
- 每个未决事件每轮最多一个窄查询，锁定该事件的发布机构与已登记来源。第一轮沿用发现语言，后续轮次在该市场已规划语言间轮换；不使用市场级初扫模板，也不设置会排除窗口前 prior baseline 的 `after:` 条件。
- 补搜响应最多包含一个信号，issuer、document title 与 jurisdiction 必须与目标事件一致；已知 instrument ID 不得改变，原先为空时可以补全。转换器把结果固定归并到原 `event_id`，不能借补搜引入另一事件。
- ResearchRole 显式报告实际尝试的事件 ID；控制器只对这些事件累计补搜轮次，并把事件补搜与覆盖复查分开计账。
- 输出使用 `text.format` 下的严格 JSON Schema。发送给 Azure 的副本移除官方文档列明的不支持关键词，本地转换器仍使用完整 Schema 校验长度、格式、数量和唯一性。
- 转换器要求一个已完成的可识别 Bing 调用、唯一的结构化文本输出和范围内的原生 URL citation；模型正文中的 URL 不能自行成为证据。
- citation 只转换为 `bing_grounding`、`approved_metadata_only`、`discovery_signal` evidence；excerpt 固定为 `null`，claim 固定为 `not_checked/unverified`。
- `MockedVerifiedResearchRole` 只接收 `MockedFoundryResearchRole`、使用 `httpx.MockTransport` 的 P2 客户端和核验适配器；三条外部通道任一不是 mock 都会在执行前拒绝。
- 每个 Bing 原生 citation 的精确 URL 先通过 P2 allowlist、DNS／SSRF 和逐跳同来源重定向检查。manual-only、未授权来源、401/403/429、空正文和解析失败均保守降级，不尝试绕过或把响应正文写入错误。
- 提取文本仅在内存中进入无工具、`store=false` 的 bounded verification 请求；响应必须覆盖目标 claim 集合且每个支持／反驳决定只能引用请求中真实存在的 locator。模型新增 citation、重复 claim 或伪造 locator 都会被拒绝。
- 只有核验为原始文书、标题 exact/compatible 且 P2 登记机构与候选 issuer 一致时，direct evidence 才能成为 `primary_document`。Bing discovery 与其读取结果保持同一 `origin_group_id`，不会虚增独立来源数；重定向别名落到同一最终文档时只调用一次核验模型。
- 核验模型调用计入 `queries_executed`；原文 HTTP 读取受 evidence slot、citation 数量、单次正文大小及同文档去重约束，但不伪装成搜索／模型 query。审计只保留 URL、hash、类型、时间、状态和用量等白名单元数据，不保留原文或模型输出。
- citation-only 核验不信任上游自报的 checked 标签，因此模拟信号只能进入 `watch/unverifiable`，不能作为已核验事实入选。
- 超时、限流和完成状态未知时不重试；已经尝试的请求仍计入查询预算，避免隐藏可能已经产生的用量。

请求构造器返回不可变的 `FoundryResearchRequest` 元数据；`payload` 每次返回独立副本。调用方可以记录 `audit_record()`，但不得把私有 payload、后续原始模型回答或工具输出当作审计记录持久化。

请求字段形态依据 Microsoft Foundry 的 [Grounding with Bing Search 工具说明](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools) 和 [项目级 Responses REST 参考](https://learn.microsoft.com/rest/api/aifoundry/project/responses)。这只说明构造与文档及既有 P1 实测形态一致，不代表本阶段重新验证了云端兼容性。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_foundry_research -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

当前 P4-B 有 35 项测试，全仓库合计 195 项离线测试。测试使用假 token 与 `httpx.MockTransport`，没有真实认证或网络调用。覆盖正常信号、零结果、无原生引用、正文生成 URL、越界来源、Bing attribution、JSON/Schema 错误、工具未完成、限流、超时、未知执行状态、请求摘要绑定、预算保留、事件补搜身份锁定、manual-only、访问拒绝、空原文、冲突、标题不匹配、伪造 checked context／locator、重定向别名去重以及完整模拟控制器闭环。

## 下一步

1. 构造默认关闭、必须显式启用且可审计的手动运行／live transport 边界，同时保留完全 mock 的 dry-run 测试路径。
2. 明确一次真实运行的预算、截止时间、允许来源和失败后不自动重试规则；P2 组织审批和 P3 领域批准仍是生产门槛。
3. 只有用户单独授权且组织门槛允许时，才执行一次小规模真实运行并检查真实响应兼容性；不得为重复确认历史成功而调用。
