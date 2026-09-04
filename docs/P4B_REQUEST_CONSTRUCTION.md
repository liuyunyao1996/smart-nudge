# P4-B Foundry/Bing 模拟适配器

更新日期：2026-09-04（Asia/Shanghai）。本阶段实现初扫请求构造、mocked transport 执行、受控响应转换和控制器接入；不读取 `.env`、不获取真实 Azure 凭据、不发起网络请求，也不创建或修改云资源。

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
- 当前只构造初扫请求。补搜轮若没有事件级发现上下文会明确失败，避免再次执行宽泛扫描。
- 输出使用 `text.format` 下的严格 JSON Schema。发送给 Azure 的副本移除官方文档列明的不支持关键词，本地转换器仍使用完整 Schema 校验长度、格式、数量和唯一性。
- 转换器要求一个已完成的可识别 Bing 调用、唯一的结构化文本输出和范围内的原生 URL citation；模型正文中的 URL 不能自行成为证据。
- citation 只转换为 `bing_grounding`、`approved_metadata_only`、`discovery_signal` evidence；excerpt 固定为 `null`，claim 固定为 `not_checked/unverified`。
- citation-only 核验不信任上游自报的 checked 标签，因此模拟信号只能进入 `watch/unverifiable`，不能作为已核验事实入选。
- 超时、限流和完成状态未知时不重试；已经尝试的请求仍计入查询预算，避免隐藏可能已经产生的用量。

请求构造器返回不可变的 `FoundryResearchRequest` 元数据；`payload` 每次返回独立副本。调用方可以记录 `audit_record()`，但不得把私有 payload、后续原始模型回答或工具输出当作审计记录持久化。

请求字段形态依据 Microsoft Foundry 的 [Grounding with Bing Search 工具说明](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools) 和 [项目级 Responses REST 参考](https://learn.microsoft.com/rest/api/aifoundry/project/responses)。这只说明构造与文档及既有 P1 实测形态一致，不代表本阶段重新验证了云端兼容性。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_foundry_research -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

当前 P4-B 有 19 项测试，全仓库合计 177 项离线测试。测试使用假 token 与 `httpx.MockTransport`，没有真实认证或网络调用。覆盖正常信号、零结果、无原生引用、正文生成 URL、越界来源、Bing attribution、JSON/Schema 错误、工具未完成、限流、超时、未知执行状态、请求摘要绑定、预算保留以及完整模拟控制器闭环。

## 下一步

1. 根据 citation-only 信号和明确未决问题构造事件级补搜；不得重复市场级初扫。
2. 对 P2 允许自动访问的精确 URL 编排独立原文读取；manual-only 或拒绝访问的来源保持人工复核。
3. 新增 verification-agent 的受控输入／输出，让直接原文支持与 Bing discovery provenance 保持分离。
4. 在 mock 中验证补搜、原文缺失、拒绝访问、证据冲突和停止条件。
5. 完成上述离线路径后，再由用户单独授权一次小规模真实运行。
