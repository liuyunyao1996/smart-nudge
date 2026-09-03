# P0：监控任务与输出契约

文档修订：0.1.3；对应配置与输出契约版本：0.1.0；日期：2026-09-03。

状态：配置与契约已实现，业务偏好、实体映射和预期案例等待领域专家复核。

## 交付范围

P0 不进行模型或搜索调用，也不验证实际搜索覆盖；不包含 Agent 编排、Skills 执行器或来源连接器。现有香港 Bing 配置可用是用户提供的背景，不等于本项目已经端到端接通。

- `config/watch_profiles/aia-group-ceo.json`：受众、假设、市场、语言、主题上线顺序、来源原则、停止条件和取舍规则。
- `config/topics/insurance-intelligence.json`：六类主题的研究问题、提取字段、查询意图、重要性信号与反例。
- `config/entities/aia-pilot.json`：根据所列官方公开资料建立的初始实体及关系种子；每项关系可追溯。
- `schemas/intelligence-result.schema.json`：严格 JSON Schema，供后续各角色对齐终态输出。
- `examples/intelligence-result.synthetic.json`：完整的虚构示例，`.example` URL 不是真实 citation。
- `evals/cases/p0-synthetic.json`：20 个助手拟定的合成案例及预期，尚未经专家审核，也未对模型执行。
- `scripts/validate_p0.py`、`tests/test_p0_contract.py`：本地静态和跨字段约束验证。

## Agent 实现与云端依赖

后续由本地 Python 实现 Research、Analysis、Verification 三个逻辑角色和代码控制器，管理角色指令、分离的上下文、Skills、查询与补搜、停止条件、核验和取舍。Skills 是应用层可版本化的业务方法，不是必须创建的 Foundry 资源。

云端复用现有 Foundry Project、GPT-5-mini 模型部署，以及 Bing Custom Search 资源、项目连接和 configuration。已配置的 Portal 托管 Agent 可保留作人工测试参考，但不属于本系统运行依赖；不需要其 ID 或名称，也不继承其中的指令、工具绑定或聊天历史。

默认路径是在 Foundry Project 的 Responses 请求中显式传入模型部署 `model`、本地指令与输入和所需 `tools`，不使用 `agent_reference`。Bing 工具以 `bing_custom_search_preview` 绑定搜索配置中的 `project_connection_id` 和 `instance_name`。这仍由 Foundry 执行模型和托管搜索工具，不等于直接取得原始 Bing 结果或网页全文。接口依据为 [Microsoft Foundry Bing 工具文档](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)，实际项目兼容性待 P1 验证。

本次仅澄清架构和接入前提，不修改 0.1.0 配置、输出 Schema、合成示例或案例定义。P0 契约不绑定托管 Agent 对象，结果须独立持久化。

## 初始业务范围

香港使用繁体中文与英文；中国内地使用简体中文与英文；马来西亚使用英文与马来语。配置中的语言是目标覆盖要求，不是已经验证的模型能力。来源、术语与本地含义应在 P2/P3 验证。

先启用监管、竞争渠道和健康险方法；随后加入公开网页声誉分析；资本与资产负债、增长与创新保留完整问题定义，在基线通过后实现。未来扩展主要通过市场／来源配置和业务 Skill，而不是按每个市场新增一个 Agent。

集团、法律实体、业务视图和共同持有关系分开建模。业务视图只是应用分组；共同持有不自动推断控制权或会计合并。竞争者候选在 P2 核实后单独加入，当前不将模糊名称直接映射为法律实体。

## 重要性与取舍

重要性不是热度，也不是对事件发生概率的估计。分别解释五个维度：AIA 关联性、潜在业务影响、紧迫性、新颖性和管理层行动价值。

- **critical**：有依据的潜在重大经营、资本、客户权益或信任影响，且存在急迫决策／核查需要。不得仅凭夸张标题赋级。
- **high**：可能改变主要产品、渠道、市场或集团关注事项，需要管理层了解或提出进一步问题。
- **medium**：有明确业务关联，适合观察或作为背景；只有给出特殊管理层价值理由才进入精选。
- **low**：无实质新变化、关联弱、重复推广或日常低影响事件，通常过滤。

证据等级独立记录：一手支持、独立交叉支持、仅线索、存在冲突、无法核验。

决策规则：

1. `select_verified_material`：重要事实已核验，分析可追溯，有实质新变化或有价值的更正。
2. `watch_material_unverified`：潜在重要，但主张仍未证实；可以描述实际观察到的公开信号。
3. `watch_conflicting_evidence`：存在尚未解决的实质冲突，保留双方及待核实问题。
4. `ignore_irrelevant`：实体、市场或业务不相关，且无已解释的传导。
5. `ignore_duplicate`：同源转载、旧闻或无实质变化的重复事件。
6. `ignore_low_value`：事实可能可信，但不足以占用集团 CEO 的阅读时间。

精选目标为约五条，不强制凑数，也不静默截断重要事件。所有取舍保留理由。严重但证据不足的信号进入待核查，不能提升为事实或因为低可信而直接消失。

## 输出规则

- `run.agent_versions` 记录本地 Agent 角色与指令版本，不是 Foundry 托管 Agent ID。P1 另记录实际模型部署、SDK／API 版本及搜索配置；若需纳入输出 Schema，另行版本化，不在此次文档修订中隐式增加字段。
- `claim` 是原子主张，`event` 聚合一次业务事件，`finding` 表达编辑判断。不能把每一篇文章当作一个事件。
- `claim.kind=fact` 是主张本身可核验；`reported_allegation` 是底层指控；“某人公开提出指控”可以另建 `observation`，不要混淆两者。
- `supports` 指向证据，并记录支持、反证或仅背景、定位与复核者。URL 存在不构成语义支持。
- `analysis` 明确列出依据、假设和未知，不能把缺少公开数据的 AIA 财务影响写成数字。
- `headline`、`what_changed` 中的事实同样必须由关联主张支持；静态校验无法判断这项自然语言关系，后续需核验 Agent 和人工检查。
- `primary_supported` 针对具体主张，不表示整个域名上的所有内容都可靠。当前检查只能验证声明的一手来源类别，不能证明来源真实性。
- `independently_corroborated` 必须在每个相关主张上具备不同原始来源组；转载不能重复计数。分组准确性需后续验证。
- `native_citation` 保存供应商原生引用对象，不自行重写为看似相同的新引用；Bing 正文、引用位置和归属的展示／留存依 P1 确认的条款处理。
- `retention` 是依据已确认权限填写的声明，不是模型自行授权。仅元数据许可不得保存正文片段。
- `data_kind=synthetic` 必须清楚标识，不能把测试来源或 fixture 核验者用于真实报告。

## 时间与覆盖

窗口采用 `[start, end)`，所有时间戳显式携带时区，要求 `start < end <= as_of <= generated_at`。背景材料可以早于窗口；发布日期和实质变化判断不能只依赖检索新鲜度。

- `published_at`：文档公开发布日期，未知时为 null。
- `available_at`：该证据版本已可用的时间；历史回放须有相应依据，不得凭当前搜索猜测。
- `retrieved_at`：实际获取时点，可晚于历史观察截止点，但不得把之后才公开的版本用于当时结论。
- `event_date`、`effective_date`：分别表示事件和生效日期，允许未知；未来生效日不等于未来信息泄漏。
- `first_seen_at`：本系统第一次记录该事件的时间，不等于事件发生日。

每次运行声明具体 scope。覆盖表必须完整列出所请求的市场 × 主题 × 来源类别，并记录实际检查语言：`checked`、`partial`、`unavailable` 或 `not_attempted`。配置的其余市场不能被自动认为已覆盖。

- `completed`：请求覆盖已完成，允许零条发现；不等于全网已搜完。
- `partial`：预算、来源、语言或执行步骤有缺口，应明确指出；仍可保留已核实的局部发现。
- `failed`：无法形成可信的终态交付，需要错误记录，不发布 findings。

## 测试边界与人工评审

静态测试验证 JSON、schema、引用 ID、版本、时间关系、覆盖矩阵、保留策略声明及部分编辑约束；不能验证网页事实、语义支持、来源独立性判断、真实授权、检索召回或 CEO 偏好。

20 个合成案例是供专家讨论的预期，不称为“人工标注金标准”。P6 前由指定领域人员逐项复核，记录审核者、日期和修订；未完成前保持 `draft_pending_domain_review`。不把测试通过次数当作模型准确率。

## 下一阶段所需信息

最新状态（2026-09-03）：下列四项资源／配置标识已由用户提供并记录在 [.env.example](../.env.example)，无需重新索取。已通过本地 Azure CLI 登录配合 `AzureCliCredential` 完成 Python 认证、直接模型调用及指定 Bing 搜索与原生引用结构验证。P1 已按保守策略明确独立原文访问和数据留存边界；工程验收完成，组织法律／隐私批准仍是生产门槛，详见 [P1 验证记录](P1_VALIDATION.md)与[P1 访问和留存说明](P1_ACCESS_RETENTION.md)。下一步进入 P2 来源登记册，当前进度及恢复步骤见 [HANDOFF](HANDOFF.md)。

P1 需要以下连接信息，不需要托管 Agent ID 或名称：

- 现有 Foundry Project endpoint。
- GPT-5-mini 的实际模型部署名称，而不只是模型系列名称。
- Bing Custom Search 项目连接名称或完整 connection ID；若提供名称，由适配层解析为调用所需 ID。
- 现有 Custom Search configuration 的 instance name；按实际资源及 API 核对其对应值。
- 本地 Azure 认证方式与所需访问权限。

P1 验收要求在不引用托管 Agent 的情况下，直接模型调用成功，显式绑定指定 Bing configuration，确认工具实际执行并解析原生 citations。同时核实 API 代际、SDK／API 版本、模型部署与区域的工具兼容性，以及引用和留存边界。若直接路径不受支持，记录接入限制并讨论替代方案，不自动回退到现有托管 Agent。

敏感值在本地环境中配置，不要求在聊天中提供密钥。连接标识来自用户提供的门户信息；未获取或保存 API Key、access token 或登录缓存，未执行 Azure 模型／搜索调用或云配置变更。本次记录连接信息不代表 P1 已接通。

实体事实参考 URL 已逐项记录于实体配置，来自公开官网；研究日期不代表已获得抓取或长期留存授权。中国内地治理页面的相关表述本次仅在官方页面搜索摘要中取得，已记录原文验证缺口；该映射不应当作已完成原文核验的生产依据。后续使用前仍需核实。
