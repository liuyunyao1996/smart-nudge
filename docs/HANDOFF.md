# Smart Nudge：当前进度与跨设备交接

更新日期：2026-09-10（Asia/Shanghai）。P4-A 已完成严格限于合成数据的监管研究—分析—核验闭环；P4-B 已完成 mocked 与 live transport、短时一次性授权和角色组合；P4-C 已完成非生产 manual-live result 契约与完整控制器的离线端到端验收，见 [P4-C Manual-live 完整控制器](P4C_MANUAL_LIVE_CONTROLLER.md)。在用户明确授权并将组织／领域审批视为仅适用于 PoC 的已通过假设后，已完成一次最小真实 Foundry/Bing discovery 兼容性运行。下一步是真实端到端验收；生产审批、持久化和跨运行能力仍未完成。

## 1. 从这里继续

项目面向 AIA 集团 CEO，仅研究公开 Web 信息：决定搜什么、如何搜索和补搜、证据是否足够、如何总结与取舍。P0–P3 及 P4-A 离线闭环已交付：来源边界拒绝优先，Skill 只从版本控制的本地文件加载，控制器按覆盖计划和预算停止，并重新核验证据关系。P4-B 已把覆盖任务、固定 Skill 模板及事件证据缺口转换为有预算的 Foundry/Bing 初扫／补搜请求，并接入 P2 精确 URL 原文读取和独立核验；P4-C 将同一逻辑接入只接受 manual-live request／authorization／live role 的控制器，输出 `data_kind: live` 的 P0-valid 结果。下一步是在新的短时一次性授权下运行这个完整控制器，而不是重复 discovery-only 兼容性调用。

先阅读本文，再阅读 [实施计划](IMPLEMENTATION_PLAN.md) 和 [P0 Spec](P0_SPEC.md)。不要重新从 Portal 创建资源或恢复历史版本中的定时、对话、推送需求。

已确认的架构决策：

- 本地 Python 实现 Research、Analysis、Verification 三个逻辑角色，加一个代码控制器；负责指令、分离上下文、Skills、补搜、预算、停止、核验与取舍。
- 复用 Foundry Project、GPT-5-mini 模型部署和 Bing Custom Search 资源／项目连接／configuration。不调用或依赖已有 Portal 托管 Agent，不索取 Agent ID，不使用 `agent_reference`。
- 已通过 Foundry Project 的 Responses 入口直接传入 `model`、指令和工具配置完成实测；使用 Azure Identity + HTTPX REST。Bing 工具在云端执行，不将其视为原始搜索结果或全文接口；更换模型／配置后仍需验证兼容性。
- Skills 是本应用的可版本化领域方法，后续可接受部门专家贡献。首个监管 Skill 与通用 Loader 已实现；草稿必须显式允许，生产默认只加载领域批准版本，并固定版本及内容摘要。
- 结果独立持久化，不能只放在 Foundry 会话里。服务入口未来可被 Scheduler 复用，但当前不实现定时、聊天、通知、前端或业务 HTTP API。
- 重要事实必须有支持它的 URL citation；证据不足明确标注。仅处理获准公开信息，不绕过付费墙、登录或社媒授权，也不把搜索不到等同于没有事件。

## 2. 已完成与未完成

已完成：

- P0 Watch Profile：香港、中国内地、马来西亚作为首批验证切片，不代表内部市场重要性排序。
- 六类主题定义及首批实体映射；先实现监管、竞争渠道、健康险，随后公开网页声誉，资本与资产负债、增长与创新在基线后扩展。
- 严格输出 Schema、完整合成输出、20 个待专家复核的合成业务案例。
- 静态／跨字段校验和 48 项离线回归测试；本次交接重跑通过，`pip check` 无依赖冲突。
- 已根据用户反馈把计划从“调用现有托管 Agent”改成“本地自建 Agent 系统，复用云端模型及搜索能力”。
- 2026-09-03：Azure CLI 2.90.0 安装登录成功，Python 认证、直接模型和指定 Bing 搜索各项探针通过；已实现 `.env` 加载、最小适配层、CLI 和 18 项接入回归测试。
- 2026-09-03：完成 P1 官方原文访问与留存策略、IA 发布方覆盖规则、安全审计输出和 12 项策略回归测试。当前合计 78 项离线测试，P0 校验和 `pip check` 通过。
- 2026-09-03：完成 P2 Source Registry、三市场一手来源能力矩阵、安全原文读取器及 HTML／PDF／JSON／RSS 定位解析；香港试点六个主机名全部登记，获准路径与人工路径明确分离。新增 28 项回归测试，当前合计 106 项离线测试。
- P2 登记册含 9 个来源组：6 个允许低频自动访问，3 个仅限人工复核。保监局、FSTB、BNM 新闻正文和 AIA 主站没有被误标为可自动抓取。
- 2026-09-03：完成 P3 首个 `regulatory-change` Skill、通用 Loader、专用输出 Schema、确定性验证和 3 个合成案例；新增 19 项测试，当前合计 125 项离线测试。Skill 状态仍为 `draft_pending_domain_review`，默认不加载。
- 2026-09-04：完成 P4-A 合成监管研究闭环：请求／预算契约、六语言覆盖规划、三个角色接口、按事件最多两轮补搜、ResearchRole 查询计数信任边界、事件级 claim/evidence 归属、稳定监管文书身份与最早 first-seen 归并、一手原文身份推导、claim 状态重算、安全失败输出及 3 个闭环案例。三轮 Bugbot 共七项发现已修复并加入回归测试；新增 33 项测试，当前合计 158 项离线测试。
- 2026-09-04：完成 P4-B 第一步的纯请求构造接口：按覆盖任务和固定 Skill 模板生成 Foundry Responses/Bing Custom Search 请求，查询和候选结果分别受剩余预算约束；验证本地语言参数、P2 来源与 Bing scope 一致性，不强制加入 AIA，不允许宽泛补搜静默重复执行。新增 7 项离线测试，当前合计 165 项。
- 2026-09-04：完成 P4-B 模拟适配器：只有显式 `httpx.MockTransport` 才能执行研究请求；模型输出使用 Azure-compatible `text.format` Structured Outputs，并由更严格的本地 Schema 再校验。只把范围内原生 URL citation 转为 metadata-only、`not_checked` 草稿，Bing attribution 和正文 URL 不会晋升为证据；无结果、无引用、越界来源、超时、限流、未知状态和已尝试查询计费均有确定路径。控制器上下文与请求摘要绑定，事件型 mock 已接入控制器并只能形成 `watch/unverifiable`。P4-B 测试现为 19 项，全仓库合计 177 项。
- 2026-09-04：完成 P4-B 事件级补搜：控制器从结构化候选推导固定证据问题，不复制自由文本 unknowns；每事件每轮最多一个查询，锁定发布机构、P2 来源、稳定事件身份和首次发现语言，第二轮才轮换本地语言。响应最多返回同一事件的一个信号，不能改变已知身份或借补搜新增另一事件；实际尝试事件与覆盖复查分开计账。新增 4 项测试，P4-B 合计 23 项，全仓库合计 181 项。
- 2026-09-04：完成 P4-B 独立原文核验模拟闭环：只对 Bing 原生 citation 的精确 URL 走 P2 allowlist，逐跳校验重定向并仅在内存提取 HTML/PDF/API 文本；manual-only、401/403/429、空正文及策略拒绝均明确降级，不绕过访问控制。核验请求无工具、`store=false`、正文和 claims 有界，响应必须覆盖全部 claim 并引用真实提供的 locator；只有发布机构、标题和原始文书角色一致时才形成 direct primary evidence，且与 Bing discovery 共用 origin group，避免伪造独立来源。重复重定向到同一内容只核验一次；正文、模型原文和 token 均不进入审计。新增 12 项 P4-B 测试和 2 项 P2 时钟边界测试，P4-B 合计 35 项，全仓库合计 195 项。
- 2026-09-10：完成手动 live transport 授权边界。checked-in policy 仅对 `poc_non_production` 标记为 `approved_for_manual_live`，仍须另行提供最长 60 分钟、绑定请求哈希／P2 source IDs／query 与 evidence 预算、零自动重试的授权文件；缺少任一条件即拒绝。Foundry research／verification 和 P2 精确 URL 读取均在 I/O 前原子计费；live 拒绝注入 transport，mock 与 live API 分离；审计不保留审批文本、prompt、查询、模型／网页正文或凭据。新增 12 项离线测试。
- 2026-09-10：完成独立 manual-live request Schema、Skill bundle 摘要绑定、`LiveFoundryResearchRole`、`LiveVerifiedResearchRole` 和显式 `--execute-live` CLI；CLI 在外部 I/O 前原子写入只含安全元数据的一次性授权收据，同一 authorization ID 跨进程不能重复使用。新增 5 项离线测试，全仓库合计 212 项。用户明确授权一次最小非生产 PoC：请求 `manual-live-poc-20260910-01` 成功连接现有 Foundry 模型部署与 Bing Custom Search，Responses 状态为 `completed`；一个受控模型请求内观察到 2 次 Bing 工具调用，总用量 3,533 tokens。响应没有范围内原生 URL citation／候选，因此结果按设计降级为 `unavailable`，没有执行原文读取或核验，也没有形成 P0 情报结果。审计记录 request/response ID、用量、计数和哈希；原始模型／工具内容未持久化。第一次沙箱内尝试在取得 Azure token 前因本机 Azure cache 写权限失败，未到达云端；随后在获准的沙箱外路径执行成功，未自动重试。该次测试使用的临时 request／authorization 已删除；一次性收据机制在测试后补入，供后续授权使用。
- 2026-09-10：完成 P4-C manual-live 完整控制器。新增专用 live result Schema 与请求绑定校验；基础 `ResearchController` 保持 synthetic 默认，`ManualLiveResearchController` 只接受共享同一授权会话的 `LiveVerifiedResearchRole` 并固定 direct verification。手动 CLI 升级为 discovery、官方 URL 读取、locator 核验、analysis、停止和 P0 输出的完整闭环。新增一个无网络 happy-path 测试：双语 discovery、一次原文读取和一次 verification 共计 3 个 Foundry 预算单位，产出 `data_kind: live`、`selected`、`sufficient_evidence` 的 P0-valid 结果；伪造 synthetic 类型或篡改 request key 均拒绝。加上后续历史 cutoff 与日期格式回归测试，全仓库合计 215 项离线测试。
- 2026-09-10：用户授权请求 `manual-live-poc-20260910T064031Z` 以 `max_queries=3`、`max_evidence=1` 执行第一次完整控制器真实验收。一个 Foundry research 请求返回后，转换器因把正常网络返回时间误当成历史回放 cutoff 而保守失败，记录 `response_post_cutoff_evidence`；会话只消费 1 个 query 尝试，没有原文读取或 verification，一次性授权已消费且未重试。随后离线修复时间语义：历史／mock 仍拒绝 cutoff 后响应，manual-live result 的 `as_of` 则推进到控制器完成时，允许保留真实 discovery／retrieval 时间；延迟型完整 mock 回归通过。另确认 1 条 discovery citation 本身占用 1 个 evidence record，因此要容纳同一 URL 的独立原文证据，下一次完整验收需 `max_evidence=2`。
- 2026-09-10：用户以 `max_queries=3`、`max_evidence=2` 授权请求 `manual-live-poc-20260910T065905Z` 重试。香港双语 discovery 共消费 2 个 Foundry 尝试，真实响应通过了修复后的时间边界，但其中一个候选的 `publication_date` 未满足本地严格 date 格式，控制器以 `response_response_schema` 保守失败；没有原文读取或 verification，第 3 个 query 未使用，一次性授权未重试。随后离线增强日期契约：prompt 与 Azure Schema description 明确只允许 `null` 或 `YYYY-MM-DD`；转换器只把可严格解析的 ISO 8601 datetime 确定性降为 date，并在安全审计中记录归一化字段数量，仍拒绝本地化、模糊或部分日期。

尚未完成：

- P0 业务偏好和案例的领域专家审核；20 个案例不是已批准金标准，也未作为 Agent 评测执行。
- P3 其余领域／共用 Skills；首个监管 Skill 在文件中仍是 draft，用户授权的领域批准假设只适用于本次非生产 PoC，尚未转为生产批准状态。
- 使用新的短时一次性授权重试完整 live 控制器验收；建议 `max_queries=3`、`max_evidence=2`。真实 Bing 必须返回范围内原生 citation 才能进入原文读取和 verification，否则输出明确 coverage gap。
- 数据库、跨运行事件历史、幂等恢复、通用研究 CLI 及综合评测。
- 保监局、FSTB、BNM 新闻正文和 AIA 主站的明确自动访问／留存授权；当前保留人工复核或开放发现状态。
- 其余目标市场、当地 AIA 经营实体来源和社媒接入；Blocked 规则与 Include subpages 开关未取得，也未回读云端配置。

中国内地实体治理关系的一项来源当前只取得官方搜索摘要，原文核验缺口已写入实体配置；后续不能把它当作已完成原文核验的生产依据。

本项目已发起六次真实 Responses 请求：P1 纯模型一次、P1 Bing 搜索一次、P4-B manual-live discovery 一次，以及两次 P4-C 完整控制器尝试中的 1 次和 2 次 discovery。前三次可观测累计用量为 6,287 tokens；后三次因在转换审计形成前被本地契约拒绝，未保留可安全报告的 token 用量。P1 搜索曾获得原生引用；P4-B 响应未返回可接受引用，两次 P4-C 尝试分别暴露时间与日期格式兼容问题。尚未生成经过 live 研究、原文读取、分析和核验闭环的正式情报。P1 请求标识、用量和限制见 [P1 验证记录](P1_VALIDATION.md)，P4-B／P4-C 记录见本文里程碑和对应阶段文档。

## 3. 已提供的连接信息

配置值以仓库根目录 [.env.example](../.env.example) 为集中记录。它只含非敏感标识，不含凭据；CLI 默认读取根目录 `.env`，进程环境变量优先。当前本机 `.env` 已从示例创建且被 Git 忽略。

- Foundry resource：`liuyunyao1996-5895-resource`。
- Project：`liuyunyao1996-5895`。
- 模型部署名称：`gpt-5-mini`，已在本机通过直接模型和 Bing 搜索调用验证。
- Bing connection name：`webcustomsearchpoc5f602i`。
- Bing connection category：`GroundingWithCustomSearch`。
- Bing connection target URI：`https://api.bing.microsoft.com/`，不是要直接拿来调用的原始搜索 API 地址。
- Bing configuration / instance name：`hk-financial-regulators-test`。
- Subscription ID：`2f7f01da-407f-4d68-b710-91938eb28b3b`。
- Resource group：`rg-liuyunyao1996-6111`。

用户从连接 Properties 复制的 Resource ID 以 `/projects/liuyunyao1996-5895/connections/webcustomsearchpoc5f602i` 结尾，因此它就是所需的项目连接 ID；完整值已保存在 `.env.example`，不是 Bing 资源自身的 ID。

### Endpoint 区别

已通过 P1 工具调用的 Project endpoint：

```text
https://liuyunyao1996-5895-resource.services.ai.azure.com/api/projects/liuyunyao1996-5895
```

已实测成功的 Responses 请求 URL：

```text
https://liuyunyao1996-5895-resource.services.ai.azure.com/api/projects/liuyunyao1996-5895/openai/v1/responses
```

若未来改用 OpenAI 客户端，base URL 应对应上面项目级 `/openai/v1/`，由 SDK 追加 `responses`；当前 P1 实现已固定为 Azure Identity + HTTPX REST。不能把完整 `/responses` URL 再作为 base URL。

用户另提供了两个资源级模型入口，保留作参考，但不能假定它们支持相同的项目搜索工具：

```text
https://liuyunyao1996-5895-resource.services.ai.azure.com/openai/v1
https://liuyunyao1996-5895-resource.openai.azure.com/openai/v1
```

门户复制的示例使用 `OpenAI`、`DefaultAzureCredential` 和 `get_bearer_token_provider`。当前实现明确使用 `AzureCliCredential` 和 HTTPX REST；scope 为 `https://ai.azure.com/.default`，已完成实测。

### 两层认证不可混淆

- 本地程序 → Foundry：使用 Microsoft Entra 认证；本地通过 Azure CLI 登录供 Python `AzureCliCredential` 使用，已验证。
- Foundry → Bing：现有项目连接显示 `Authentication method: API Key`，密钥由连接配置使用。不需要索取、复制到聊天或提交到 Git。

已知资源标识不属于密码，但可能暴露环境结构。如果准备公开仓库，先评估并替换具体账号资源标识。不要上传任何 key、token、密码、完整认证调试日志或 Azure 登录缓存。

## 4. 在新设备恢复并推进 P4-B

### A. 恢复 P0 环境

当前设备目录为 `D:\Work\smart-nudge`，新设备不必使用同一路径。使用 Python 3.11.9；依赖由 `requirements-dev.txt` 引入 `requirements.txt`，包含 Azure Identity、HTTPX、python-dotenv、pypdf 及 jsonschema。不要复制原设备 `.venv`，在仓库根目录重建。

Windows / PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/validate_p0.py
.\.venv\Scripts\python.exe scripts/validate_sources.py
.\.venv\Scripts\python.exe scripts/validate_skills.py
.\.venv\Scripts\python.exe scripts/validate_research.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

macOS / Linux 使用 Python 3.11+：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/validate_p0.py
.venv/bin/python scripts/validate_sources.py
.venv/bin/python scripts/validate_skills.py
.venv/bin/python scripts/validate_research.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

预期：P0、P2、P3、P4-A 校验 PASS、215 项测试通过、依赖无冲突。这只验证离线契约、请求／响应转换、完整 manual-live 控制器的模拟搜索／原文／核验行为、live 授权边界和策略护栏，不验证新设备云权限、实时来源连通性、检索质量、事实或生产审批。

需要本地配置时，先确认 `.env` 不存在，再手动复制 `.env.example` 为 `.env`；已有文件不要覆盖。已实现并测试显式配置加载，默认不使用 `.env.example` 作为隐式回退。

### B. 安装／确认 Azure CLI 并登录

当前设备 Azure CLI 2.90.0 已安装在 `C:\Program Files\Microsoft SDKs\Azure\CLI2`，用户已登录；新设备先执行 `az version`，可用时无需重装。当前助手进程仍持有旧 PATH，本次调用仅临时补入 CLI 的 `wbin` 目录。

Windows 如未安装，可用微软 [64 位 MSI 安装包](https://aka.ms/installazurecliwindowsx64)。安装后重开 PowerShell；如开发工具仍持有旧 PATH，也重启开发工具。其他系统使用 [Azure CLI 官方安装指南](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)。

在目标设备本机终端执行，不是在网页 Cloud Shell：

```powershell
az login
az account set --subscription "2f7f01da-407f-4d68-b710-91938eb28b3b"
az account show --query "{subscription:name,id:id,state:state}" -o json
az account get-access-token --scope "https://ai.azure.com/.default" --query expiresOn -o tsv
```

浏览器／系统登录界面由用户完成，选择有项目权限的账号。最后一条只输出过期时间，不输出 token；成功表明该登录方式能取得令牌，不证明 Foundry 模型、Bing 工具或项目权限全部可用。若订阅不可见，先核实账号和租户，不直接增加权限或创建替代资源。

登录状态留在本机，新设备需重新认证；不要通过 Git 搬迁 `.azure` 缓存。当前项目级 `.gitignore` 不能控制用户目录中的缓存。

### C. P1–P3、P4-A、P4-B 与 P4-C 下一步

当前认证、直接模型、Bing 工具调用及引用结构已通过，不需要在本机重复成功请求。可运行 `scripts/smoke_foundry.py --check auth|model|search`（从三者中选择一个）；`model` 和 `search` 会产生真实用量。完整记录见 [P1_VALIDATION](P1_VALIDATION.md)。访问与留存边界已写入 [P1_ACCESS_RETENTION](P1_ACCESS_RETENTION.md)，不是从零重做接入或条款调研。

以下 1–8 项是已经完成的 P1 记录，不是 P2 待办：

1. 已核对 Microsoft 文档、项目 API 代际、模型部署／区域和 Bing 工具支持，并记录实际 API 与依赖版本。
2. 在项目虚拟环境添加并固定所需依赖，实现连接配置验证和 Foundry Adapter。不得依赖托管 Agent ID／名称，也不自动创建、修改云资源。
3. 验证实际 Python 凭据可用；如果 `DefaultAzureCredential` 选中了非预期账号，排查凭据链，必要时在本地验证中显式使用 `AzureCliCredential`，不要把 token 写入日志。
4. 先做一次小型直接模型请求，再显式绑定 Bing 工具：`bing_custom_search_preview` → `search_configurations` → `project_connection_id` 与 `instance_name`，使用已记录配置。
5. 取得或只读核对该 configuration 的域名范围，再选择一个香港监管官方网站查询；不先扩大云端配置。限制调用量和时间，记录可能产生模型及搜索费用。
6. 检查是否真实触发搜索、原生输出结构和 URL citation annotations，验证引用与内容的对应关系；不得用模型自行生成的 URL 补足缺失的原生引用。
7. 增加无配置、认证失败、权限不足、工具不支持、无结果、无引用、超时和限流的明确错误路径；记录请求标识及可观测用量，不记录密钥。
8. P1 能力记录已形成：搜索 CLI 只输出白名单审计字段与原生引用，不保存回答正文或原始工具输出；未获批准的抓取、索引和评测路径保持禁用。

P2 已将来源边界固化在登记册和安全读取器。P3 已固化首个监管 Skill。P4-A 已用 `.example` 合成证据打通覆盖规划、初扫、补搜、分析、claim/evidence 核验、取舍、停止和 P0 输出，并拒绝真实 URL、真实来源标签及超预算批次；完整说明见 [P4-A 离线研究闭环](P4A_OFFLINE_RESEARCH.md)。P4-B mocked 适配器、manual-live request／授权／角色和最小真实 discovery 已完成。P4-C 又交付了正式 live result 契约和完整 manual-live 控制器，并以 mock 打通“发现 → 原文读取 → 核验 → 分析 → P0 输出”，见 [P4-C Manual-live 完整控制器](P4C_MANUAL_LIVE_CONTROLLER.md)。下一步只是在确有验收需要且用户重新确认短时一次性授权后，运行一次真实完整控制器；不立即加入数据库、调度、聊天或通知，也不为重复确认连接而再次调用付费服务。

## 5. Git 提交与迁移检查

P0 提交 `2916e38`、P1 提交 `a6d6274`、P2 提交 `4a47b98`、P3 提交 `f5a8526`、P4-A 提交 `cd624b9`、P4-B 初扫模拟适配器提交 `226ce35`，以及 P4-B 事件级补搜／独立原文核验提交 `55713db` 已推送到 `origin/develop`。`7303b40` 更新了跨设备交接记录。当前 manual-live request／授权／角色／完整控制器／CLI、PoC policy、测试及文档变更尚未提交；本地 `develop` 仍指向 `origin/develop`，不要覆盖这些工作区变更。

`.gitignore` 排除 `.venv`、Python 缓存、`.env`、数据库、运行数据，并新增根目录 `.tmp` 和 `.azure` 排除项。原有 `.tmp` 内容未查看、修改或删除；该忽略规则不等于审查其中内容。`.env.example` 明确保留为可跟踪文件。

用户准备提交时，可在仓库根目录执行以下显式暂存与检查命令；这只是操作说明，本次未执行：

```powershell
git status --short
git add -- README.md .gitignore .env.example requirements.txt requirements-dev.txt docs config schemas examples evals scripts smart_nudge tests
git diff --cached --stat
git diff --cached --check
git diff --cached
```

确认暂存内容符合预期且无凭据，再由用户选择分支／远端执行 commit 和 push。不要直接 `git add .`，也不要使用 `git add -f` 绕过忽略规则。忽略规则不会移除已经跟踪的秘密；如果后续检查发现敏感内容已进入 Git 历史，应停止上传并处理泄露，不仅添加忽略规则。

## 6. 可交给新设备上助手的接续说明

> 请先读取 README.md、docs/HANDOFF.md、docs/P4A_OFFLINE_RESEARCH.md、docs/P4B_REQUEST_CONSTRUCTION.md、docs/P4C_MANUAL_LIVE_CONTROLLER.md、docs/P3_SKILLS.md、docs/P2_SOURCE_REGISTRY.md、docs/P1_VALIDATION.md、docs/P1_ACCESS_RETENTION.md、docs/IMPLEMENTATION_PLAN.md、docs/P0_SPEC.md 和 .env.example。P0–P3、P4-A 合成监管闭环、P4-B 模拟闭环及 P4-C manual-live result／完整控制器／CLI 已交付，当前总计 215 项离线测试；一次最小真实 Foundry/Bing discovery 已成功完成，两次完整控制器真实尝试分别暴露了已离线修复的 live cutoff 和日期格式问题，不要为确认连接重复产生用量。用户将组织／领域审批视为仅适用于 PoC 的已通过假设，生产门槛没有因此移除，草稿 Skill 的生产默认仍不加载。下一步只在用户对新的 `max_queries=3`、`max_evidence=2` 短时一次性授权再次确认时，重试真实完整控制器；Agent 编排由本地实现，不调用 Portal 托管 Agent，不索取 Agent ID，不自动修改云资源。不得扩展到定时、对话、推送、前端；不得索取或提交密钥。

## 7. 实施时核对的官方资料

- [Foundry Bing 工具：直接 REST 请求、连接标识及引用边界](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)
- [Azure Python 本地开发认证](https://learn.microsoft.com/en-us/azure/developer/python/sdk/authentication/local-development-dev-accounts)
- [Windows Azure CLI 安装](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows)
- [Azure CLI account 与 get-access-token](https://learn.microsoft.com/en-us/cli/azure/account#az-account-get-access-token)

这些是交接时使用的资料入口，SDK、API 和权限要求仍需在 P1 实施当天核实；文档样例不是本项目的通过记录。
