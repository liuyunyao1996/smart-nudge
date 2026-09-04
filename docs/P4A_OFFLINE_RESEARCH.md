# P4-A 离线监管研究闭环

更新日期：2026-09-04（Asia/Shanghai）

## 结论

P4-A 已完成一个严格限于合成数据的监管研究—分析—核验闭环。它生成市场 × 主题 × 来源类别 × 语言覆盖计划，按明确预算执行初扫和最多两轮补搜，加载固定版本的 `regulatory-change` Skill，重新核验证据关系，并输出通过 P0 契约的结构化结果。

本切片不联网，不调用 Azure、Foundry、Bing、真实网站或凭据，不读 `.env`，不写数据库，也不创建或修改云资源。它验证的是控制流、契约和拒绝优先行为，不是搜索质量、真实事实、法律意见、领域批准或生产就绪性。

## 交付物

- `schemas/research-request.schema.json`：P4-A 请求、时间窗口、监管范围和硬预算契约。
- `config/policies/p4-offline-research.json`：合成模式、允许主题／来源类别和预算上限。
- `smart_nudge/research.py`：覆盖规划、三个逻辑角色接口、合成 Research 角色、监管 Analysis、Contract Verification 和有界控制器。
- `evals/p4/regulatory-loop.synthetic.json`：有原文支持、证据不足、必检来源不可用三条虚构闭环案例。
- `scripts/validate_research.py`：不联网的 P4-A 场景验收。
- `tests/test_research.py`：请求、覆盖、预算、补搜、同源信息、证据重算和失败边界测试。

## 当前范围

请求必须显式声明：

- `mode=offline_synthetic`；
- `topic_id=regulatory-change`；
- 一个 P0 已定义的监管事件类型；
- 香港、中国内地或马来西亚中的一个或多个市场；
- 唯一来源类别 `official`；
- `allow_draft_skills=true`，明确表示这只是工程验证；
- 查询、证据条数和每事件补搜轮次硬上限。

Schema 和策略将补搜限制在每事件 0–2 轮、查询不超过 30 次、证据不超过 100 条。具体请求通常应使用更低预算。P4-A 没有真实 Provider，因此这些数字不是供应商调用或费用承诺。

控制器不信任 ResearchRole 自报的查询计数：`queries_executed` 必须是严格的非负整数且不超过当轮剩余额度；该检查适用于 Fixture 及未来所有协议实现。

## 覆盖计划

Coverage Planner 从 Watch Profile 取得市场必检语言，从 P2 Source Registry 取得该市场和主题的可信一手来源，再从 P3 Skill 取得对应语言的查询模板。计划按“市场 × `regulatory-change` × `official` × 语言”生成任务。

监管查询任务明确记录 `force_company_name=false`，避免因强制包含 AIA 名称而漏掉适用于整个行业的规则。计划只包含来源 ID、模板和范围，不包含真实搜索结果或正文。

## 三个逻辑角色

- Research：`ResearchRole` 接收剩余预算、覆盖计划和未解决事件，只返回一轮结果。当前唯一实现是 `FixtureResearchRole`，只能回放显式合成 JSON。
- Analysis：`RegulatoryAnalysisRole` 选择与市场／事件类型相符的固定 Skill bundle，并用 P3 Schema 与确定性规则校验监管候选。
- Verification：`ContractVerificationRole` 不信任 Research 自报的 verification 或 `primary_document_obtained`。它从 checked support/refute 链接重新计算每个 claim 的状态，并要求 `document_role=primary_document` 且 evidence publisher 与监管候选 issuer 一致，才可判定 `primary_supported`，再决定 `selected`、`watch` 或 `ignored`。

控制器只在版本控制的本地 Skill 上运行。Skill 版本、内容 SHA-256、控制器和三个角色版本进入结果的 `agent_versions`。

## 事件归并与独立性

同一 `event_id` 在补搜轮次中可以补充 evidence、claim 或升级候选，但 Skill、版本、主题、事件类型、市场、issuer、document title、jurisdiction、实体集合、change type、previous event 和 finding ID 必须保持不变。instrument、发布日期、生效日期和咨询期限只允许从 `null` 补全为已知值，document status 只允许从 `unknown` 升级；`first_seen_at` 始终保留跨轮次最早时间。相同 evidence ID 不得改变内容，相同 claim ID 不得改变含义。控制器按事件累计本地 evidence/claim，并拒绝候选借用其他事件的 claim 或 evidence。

`max_followup_rounds_per_event` 按事件分别计数；补搜轮中新发现的事件从零开始获得自己的额度。全局查询和证据条数上限仍覆盖整个 run。

独立信息按 `origin_group_id`、新 claim 和新事件判断。新增 URL 若仍属于已有 origin group，不能仅因转载或换链接被算作新独立来源。当前跨语言事件归并依赖 Research 角色提供稳定 `event_id`；自动实体／标题聚类和历史事件匹配属于后续 P4/P5 工作。

## 停止与结果状态

控制器按以下顺序停止：

- 候选均已得到明确处置（包括全部 `ignored`），且覆盖计划全部完成：`sufficient_evidence`／`completed`。
- 完整覆盖后没有发现，或补搜没有新增独立信息：`no_new_independent_information`；有未证重大信号时保留 `watch`，不写成事实。
- 必检来源／语言不可用：`required_source_unavailable`／`partial`。
- 查询、证据或轮次达到硬上限：`budget_exhausted`／`partial`。
- 角色、覆盖或结果契约失败：`technical_failure`／`failed`，清空可发布的 evidence、claims、events 和 findings，只返回安全错误及覆盖状态；预算审计仍保留失败前已接收的证据条数。

没有发现不等于没有事件；输出只说明本次计划和检查状态。`completed` 可以有零条 findings，不能为满足条数而凑摘要。

## 合成证据边界

P4-A 只接受：

- `origin=synthetic`；
- `retention=synthetic`；
- `source_class=official`；
- 保留的 `.example` URL；
- `native_citation=null`；
- 内部 `document_role` 明确区分 `primary_document`、`discovery_signal` 和 `context`；该字段用于核验，输出 P0 evidence 前移除；
- 由 `fixture_author` 明确检查的支持／反驳关系。

真实 URL 不能通过把标签改成 `synthetic` 混入。运行 trace 和 coverage plan 只保存轮次、数量、来源 ID、模板和状态，不保存 evidence、claim、摘录或模型文本。

## 验证

```powershell
.\.venv\Scripts\python.exe scripts\validate_research.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

当前 P4-A 有 33 项专项测试；加上后续 P4-B 模拟适配器测试，全仓库合计 177 项离线测试。

## 下一步

P4-B 的初扫请求构造、模拟传输执行、响应转换与控制器接入已经完成，见 [P4-B Foundry/Bing 模拟适配器](P4B_REQUEST_CONSTRUCTION.md)。后续继续保持先离线、后授权实测：

1. 已把 coverage task 和 Skill 查询模板转换为有预算的 Foundry/Bing 请求，并保持监管查询不强制 AIA。
2. 已只接收原生 URL citation，形成 metadata-only、`not_checked` 的 evidence 与 claim 草稿；P2 原文引用仍待独立获取和核验。
3. 已将模型输出限制在受控 JSON Schema，并在进入控制器前校验；原始回答和工具输出不得进入数据库或评测集。
4. 已覆盖无结果、无引用、来源越界、限流、超时、未知执行状态和可能重复计费的失败路径。
5. 下一步构造事件级补搜并编排获准的 P2 原文读取；完成后再由用户单独授权一次小规模真实运行，不得为重复确认 P1 成功而调用。

P4-A 尚未实现真实检索、自动原文读取编排、数据库、跨运行历史、幂等恢复、通用 CLI 或其余领域 Skills。
