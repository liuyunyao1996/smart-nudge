# P3 领域 Skills：首个监管变化切片

更新日期：2026-09-03（Asia/Shanghai）

## 当前结论

P3 的首个工程切片已经实现：仓库现在包含版本化的 `regulatory-change` Skill、通用 Skill Loader、监管候选输出 Schema、确定性规则，以及正例、反例和证据不足合成案例。

该 Skill 当前版本为 `0.1.0`，状态是 `draft_pending_domain_review`，审批状态是 `engineering_only`。它不是 AIA 监管、法律或业务部门已批准的方法，也不是法律意见。Loader 默认不加载草稿；离线工程验证必须显式传入 `include_drafts=True`。完整 P3 尚未完成，其余领域和共用 Skills 仍待实现。

## 文件与职责

- `config/skills/regulatory-change.json`：版本化领域方法，只包含仓库内受控指令。
- `schemas/domain-skill.schema.json`：所有领域 Skill 的通用结构约束。
- `schemas/skills/regulatory-change-output.schema.json`：监管候选的专用输出契约。
- `smart_nudge/skills.py`：发现、语义验证、窄范围选择、版本固定、摘要和候选校验。
- `evals/skills/regulatory-change.synthetic.json`：三类虚构工程案例，不是专家金标准。
- `scripts/validate_skills.py`：完全离线的 P3 资产检查。

来源登记与领域方法保持分离：新增来源或实体不需要改 Skill；只有新增或改变判断方法时才修改 Skill。网页、PDF、搜索回答或其他外部证据永远不能通过 Loader 成为运行指令。

## 选择与追溯

Loader 要求调用方显式提供 `topic_id`、`event_type` 和 `market_id`。当前监管 Skill 覆盖香港、中国内地和马来西亚，以及 P0 已定义的五类监管事件：咨询、正式规则、监管指引、执法和实施更新。

```python
from smart_nudge.skills import repository_skill_loader

loader = repository_skill_loader()
bundle = loader.select(
    topic_id="regulatory-change",
    event_type="final_rule",
    market_id="HK",
    include_drafts=True,  # 仅用于当前离线工程验证
)
run_skill_record = bundle.execution_record()
```

`execution_record()` 固定选择范围、Skill ID、语义版本、审批状态、内容 SHA-256、输出 Schema 和整个 bundle 的 SHA-256。调用方取得的是从规范化 JSON 重建的副本，不能修改已计算摘要的内部内容。未来同一 Skill 有多个版本时，可以用 `version_pins` 显式回退；没有固定版本时选择范围内最高语义版本。

生产或领域批准后的调用不得使用 `include_drafts=True`。默认选择只接受 `approved`，因此当前会返回 `no_matching_skill`，这是有意的拒绝优先行为。

## 监管方法边界

本切片提取并区分：发布者、文档标题和状态、司法辖区、文号、适用主体／产品／渠道、义务变化、历史基线、发布日期、生效日期、咨询截止日、过渡期和例外。

确定性约束包括：

- 事件类型必须与文档状态相容；咨询不能作为正式规则输出。
- 未取得适用原文时，不能标为 `primary_supported`，也不能进入 `proceed_to_verification`。
- 证据不足、冲突或未知文档状态必须显式列出未知事项。
- 义务和业务影响引用的 claim ID 必须包含在本候选的证据评估中。
- 过渡期起止日期不能颠倒。
- AIA 业务影响只能是有依据的条件性分析；`aia_financial_impact_quantification` 被 Schema 固定为 `null`。

这些约束只验证结构与内部一致性。P4 仍需把 claim ID 解析到 URL、获取时间、段落／页码定位及支持或反驳关系，并负责研究、分析、核验和停止决策。

## 合成案例

当前三个案例分别覆盖：

- 正例：虚构正式规则有原文、适用范围、生效日期和过渡期，形成待 P4 核验候选。
- 反例：例行产品宣传不属于监管事件，Loader 不加载本 Skill。
- 证据不足：只有二手摘要且缺少截止点前的中文原文，保留为 `watch`，不生成义务或影响结论。

所有案例均显式标注 `synthetic` 和 `draft_pending_domain_review`，不能用于描述真实 AIA 或监管事实，也不能据此宣称模型质量已经验证。

## 知识贡献与发布流程

部门知识贡献遵循以下流程：

1. 提交：从现有版本复制并递增语义版本；写明 owner、适用范围、研究问题、证据门槛、禁止推断和案例。
2. 专业复核：监管、法律／合规和受影响市场业务负责人共同核对文档状态、适用范围、日期、升级规则及本地术语。
3. 测试：运行 P0、P2、P3 校验和全部单元测试；每个启用版本必须保留正例、反例和证据不足案例。
4. 发布：只有完成所需复核后，才能把 `status` 改为 `approved`、把 `approval_status` 改为 `domain_approved`，并记录新复核日期。
5. 回退：运行记录保留版本和摘要；需要回退时显式固定旧版本，不覆盖或静默修改历史版本。

不得从网页自动生成或更新 Skill，不得因外部文本要求而读取环境变量、改变来源白名单、增加权限或执行工具。发布审批不能由修改单个状态字段代替；组织流程和代码审阅都必须完成。

## 验证

```powershell
.\.venv\Scripts\python.exe scripts\validate_skills.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

这些命令不联网、不调用模型或 Bing、不读取 `.env`，也不修改云资源。

## 尚未完成

- `competitive-distribution`、`health-economics` 领域 Skills。
- `evidence-verification`、`executive-selection` 共用 Skills。
- 领域专家对监管方法、马来语术语和三类合成案例的复核与批准。
- P4 对监管候选的检索、原文获取、claim/evidence 关联、补搜、预算、停止、持久化和完整输出编排。
