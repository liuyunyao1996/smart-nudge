# P4-B Foundry/Bing 模拟适配器与手动 live 边界

更新日期：2026-09-10（Asia/Shanghai）。本阶段已实现初扫、事件级补搜、获准精确 URL 原文读取和 locator-bound 核验的 mocked transport 闭环，并增加非生产 manual-live request、显式短时授权、discovery／verification 角色和手动 CLI。用户将组织／领域审批视为仅适用于 PoC 的已通过假设，并明确授权后，已完成一次最小真实 Foundry/Bing discovery 兼容性运行；没有创建或修改云资源，也没有持久化 prompt、原始模型／工具输出或凭据。

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

## 手动 live transport 边界

`smart_nudge.live_run` 提供运行级授权与预算会话，`FoundryAdapter` 提供受该会话约束的 research／verification 单次执行入口，`ManualLiveSourceClient` 在 P2 精确 URL 读取前执行相同授权和 evidence 计费。`smart_nudge.manual_research` 定义独立的 manual-live request，固定非生产 PoC 标记并校验 Skill bundle SHA-256。`LiveFoundryResearchRole` 和 `LiveVerifiedResearchRole` 复用已经测试的请求转换与核验规则，但只能走默认验证 TLS 的真实 transport。

当前 checked-in `config/policies/p4-manual-live-run.json` 仅对 `poc_non_production` 标记为 `approved_for_manual_live`。它记录用户允许本次 PoC 假设组织／领域门槛已通过，并不代表生产批准；policy 本身仍不能触发外部 I/O，每次实际运行还必须提供与精确请求哈希绑定的短时授权，并显式传入 `--execute-live`。CLI 会在外部 I/O 前原子创建 `.tmp/manual-live-authorizations/` 下的一次性消费收据；同一 authorization ID 再次运行会拒绝，收据只含授权／请求哈希、ID 和时间。

边界具有以下性质：

- 缺少授权文件、策略未获批、授权未生效或已过期时全部拒绝；单次授权最长 60 分钟。
- authorization ID 必须一次性使用；本地原子收据防止同一工作区内并发或跨进程重放。生产仍需把这类消费记录放入受控持久化存储，不能依赖可删除的 `.tmp` 目录。
- 授权绑定一个 `request_key`、一个规范请求 SHA-256、明确 P2 source IDs、查询上限和 evidence 上限。
- 组织审批与领域审批引用是授权 Schema 的必填字段，但授权文件本身不能打开 checked-in 禁用策略。
- 每个外部动作在 I/O 前原子计费；失败、超时或状态未知不退回预算，自动重试固定为零。`max_queries` 计的是 Foundry Responses research／verification 尝试数；一个 Responses 请求内部由模型触发的原生 Bing 调用数在返回后另行审计，不能由这个本地计数器事前精确限制。
- live Foundry 入口拒绝任何注入 transport，只允许默认验证 TLS 的 HTTPS transport；mock 路径继续使用原有专用方法，二者不能混用。
- live research 再次固定模型、`store=false`、单个 Bing Custom Search 工具、connection ID、instance、单次 count 上限及无托管 Agent／会话字段；verification 不得携带工具。
- live 原文读取仍必须通过 P2 allowlist、自动访问状态、DNS／SSRF、重定向、类型和大小护栏。
- 审计保存授权／请求／payload 哈希、source IDs、通道、时点和已尝试预算，不保存审批文本、prompt、查询、响应正文、网页正文或凭据。

`scripts/run_live_poc.py` 最初只用于显式 discovery 兼容性验证；P4-C 已将它升级为完整 manual-live 运行器。它加载 request 和授权，选择绑定摘要的 Skill，并在同一有预算会话中执行 discovery、精确 URL 原文读取、verification、analysis、停止决策和 P0-valid live 输出；它仍不会写入数据库。完整边界与离线验收见 [P4-C Manual-live 完整控制器](P4C_MANUAL_LIVE_CONTROLLER.md)。本次已记录的真实响应没有合格候选，所以当时没有实际调用原文读取或核验。

请求字段形态依据 Microsoft Foundry 的 [Grounding with Bing Search 工具说明](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools) 和 [项目级 Responses REST 参考](https://learn.microsoft.com/rest/api/aifoundry/project/responses)。这只说明构造与文档及既有 P1 实测形态一致，不代表本阶段重新验证了云端兼容性。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_foundry_research -v
.\.venv\Scripts\python.exe -m unittest tests.test_live_run -v
.\.venv\Scripts\python.exe -m unittest tests.test_manual_research -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

当前全仓库合计 215 项离线测试。测试使用假 token、方法 patch 或 `httpx.MockTransport`，覆盖 PoC policy、显式授权 Schema、manual-live request 与 Skill 摘要绑定、有效期、来源／请求绑定、授权快照不可变、跨进程一次性消费、原子预算、审计最小化、Bing 身份固定、失败仍计费、CLI 二次确认、完整 live 结果契约、历史 cutoff 防回退，以及 mock／live transport 隔离。

同日执行了一次单独授权的真实兼容性运行 `manual-live-poc-20260910-01`：一个 Foundry Responses 请求成功完成，在响应结构中观察到 2 次 Bing 工具调用，总用量 3,533 tokens。没有返回可接受的范围内原生 URL citation 或候选，coverage 因此保守标记为 `unavailable`，没有继续原文读取／核验。这证明当前模型部署、项目连接、Bing configuration 和新 live discovery 路径可协同执行，不证明搜索覆盖率、事实准确性或完整闭环验收通过。

## 下一步

1. 正式 live result Schema、完整控制器和“有合格原生 citation”的 mock 编排验收已由 P4-C 完成。
2. 后续维护继续先走 mock dry-run，确认同一授权会话的 query／evidence 计费、失败降级和结果契约；不要为了重复证明连接而调用真实服务。
3. 只有新端到端验收确有必要、用户再次确认具体短时一次性授权时，才执行下一次真实完整运行。PoC 审批假设不延伸为生产批准。
