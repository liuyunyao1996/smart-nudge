# Smart Nudge：当前进度与跨设备交接

更新日期：2026-09-02（Asia/Shanghai）。这是项目状态快照，不代表目标设备状态或实时 Azure 验证结果。

## 1. 从这里继续

项目面向 AIA 集团 CEO，仅研究公开 Web 信息：决定搜什么、如何搜索和补搜、证据是否足够、如何总结与取舍。当前交付到 P0；P1 的非敏感连接信息已齐，下一步是新设备环境恢复、本机认证及直接模型／Bing 工具接入验证。

先阅读本文，再阅读 [实施计划](IMPLEMENTATION_PLAN.md) 和 [P0 Spec](P0_SPEC.md)。不要重新从 Portal 创建资源或恢复历史版本中的定时、对话、推送需求。

已确认的架构决策：

- 本地 Python 实现 Research、Analysis、Verification 三个逻辑角色，加一个代码控制器；负责指令、分离上下文、Skills、补搜、预算、停止、核验与取舍。
- 复用 Foundry Project、GPT-5-mini 模型部署和 Bing Custom Search 资源／项目连接／configuration。不调用或依赖已有 Portal 托管 Agent，不索取 Agent ID，不使用 `agent_reference`。
- 计划通过 Foundry Project 的 Responses 入口直接传入 `model`、指令和工具配置；Bing 工具在云端执行，并非本地取得原始 Bing 搜索结果或全文。直接路径及工具兼容性必须在 P1 实测；不支持时记录限制并讨论，不静默改用托管 Agent。
- Skills 是本应用的可版本化领域方法，后续可接受部门专家贡献。P0 只有主题／规则定义，尚无 Skill Loader 或领域 Skill 执行器。
- 结果独立持久化，不能只放在 Foundry 会话里。服务入口未来可被 Scheduler 复用，但当前不实现定时、聊天、通知、前端或业务 HTTP API。
- 重要事实必须有支持它的 URL citation；证据不足明确标注。仅处理获准公开信息，不绕过付费墙、登录或社媒授权，也不把搜索不到等同于没有事件。

## 2. 已完成与未完成

已完成：

- P0 Watch Profile：香港、中国内地、马来西亚作为首批验证切片，不代表内部市场重要性排序。
- 六类主题定义及首批实体映射；先实现监管、竞争渠道、健康险，随后公开网页声誉，资本与资产负债、增长与创新在基线后扩展。
- 严格输出 Schema、完整合成输出、20 个待专家复核的合成业务案例。
- 静态／跨字段校验和 48 项离线回归测试；本次交接重跑通过，`pip check` 无依赖冲突。
- 已根据用户反馈把计划从“调用现有托管 Agent”改成“本地自建 Agent 系统，复用云端模型及搜索能力”。

尚未完成：

- P0 业务偏好和案例的领域专家审核；20 个案例不是已批准金标准，也未作为 Agent 评测执行。
- Azure 本机认证、项目访问权限、模型直接调用、Bing 配置绑定和 citations 解析的实测。
- P1 Adapter、运行 CLI、Agent 编排、Skills、来源连接器、数据库、研究闭环及综合评测。
- 香港以外来源验证和社媒接入；香港已有配置的具体允许／禁止域名列表尚未取得，不得据此宣称完整覆盖。

中国内地实体治理关系的一项来源当前只取得官方搜索摘要，原文核验缺口已写入实体配置；后续不能把它当作已完成原文核验的生产依据。

本项目尚未发起真实 Azure 模型／Bing 搜索调用，尚未生成真实情报。用户已在门户验证 Web Search 和香港 Custom Search 的历史结果，不等于本地路径通过。

## 3. 已提供的连接信息

配置值以仓库根目录 [.env.example](../.env.example) 为集中记录。它只含非敏感标识，不含凭据；P1 尚未实现 `.env` 加载，复制文件不会自动接通服务。

- Foundry resource：`liuyunyao1996-5895-resource`。
- Project：`liuyunyao1996-5895`。
- 模型部署名称：`gpt-5-mini`，来自用户提供的门户示例，尚未本机调用验证。
- Bing connection name：`webcustomsearchpoc5f602i`。
- Bing connection category：`GroundingWithCustomSearch`。
- Bing connection target URI：`https://api.bing.microsoft.com/`，不是要直接拿来调用的原始搜索 API 地址。
- Bing configuration / instance name：`hk-financial-regulators-test`。
- Subscription ID：`2f7f01da-407f-4d68-b710-91938eb28b3b`。
- Resource group：`rg-liuyunyao1996-6111`。

用户从连接 Properties 复制的 Resource ID 以 `/projects/liuyunyao1996-5895/connections/webcustomsearchpoc5f602i` 结尾，因此它就是所需的项目连接 ID；完整值已保存在 `.env.example`，不是 Bing 资源自身的 ID。

### Endpoint 区别

计划用于 P1 工具调用的 Project endpoint：

```text
https://liuyunyao1996-5895-resource.services.ai.azure.com/api/projects/liuyunyao1996-5895
```

按当前官方 REST 示例派生、尚待实测的 Responses 请求 URL：

```text
https://liuyunyao1996-5895-resource.services.ai.azure.com/api/projects/liuyunyao1996-5895/openai/v1/responses
```

若直接构造 OpenAI 客户端，base URL 应对应上面项目级 `/openai/v1/`，由 SDK 追加 `responses`；具体客户端方式与版本在 P1 核实。不能把完整 `/responses` URL 再作为 base URL。

用户另提供了两个资源级模型入口，保留作参考，但不能假定它们支持相同的项目搜索工具：

```text
https://liuyunyao1996-5895-resource.services.ai.azure.com/openai/v1
https://liuyunyao1996-5895-resource.openai.azure.com/openai/v1
```

门户复制的示例使用 `OpenAI`、`DefaultAzureCredential` 和 `get_bearer_token_provider`，令牌 scope 为 `https://ai.azure.com/.default`。用户明确表示该示例尚未在本机执行。

### 两层认证不可混淆

- 本地程序 → Foundry：计划使用 Microsoft Entra 认证；本地阶段通过 Azure CLI 登录供 Python 凭据使用。
- Foundry → Bing：现有项目连接显示 `Authentication method: API Key`，密钥由连接配置使用。不需要索取、复制到聊天或提交到 Git。

已知资源标识不属于密码，但可能暴露环境结构。如果准备公开仓库，先评估并替换具体账号资源标识。不要上传任何 key、token、密码、完整认证调试日志或 Azure 登录缓存。

## 4. 在新设备恢复并推进 P1

### A. 恢复 P0 环境

原设备目录为 `D:\Work\smart-nudge`，新设备不必使用同一路径。原设备使用 Python 3.11.9；开发依赖仅有 `jsonschema==4.26.0`，未安装 `azure-identity`、`azure-ai-projects`、`openai`。不要复制原设备 `.venv`，在仓库根目录重建。

Windows / PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/validate_p0.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

macOS / Linux 使用 Python 3.11+：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/validate_p0.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

预期：P0 校验 PASS、48 项测试通过、依赖无冲突。这只验证离线契约，不验证检索质量、事实或云权限。

需要本地配置时，先确认 `.env` 不存在，再手动复制 `.env.example` 为 `.env`；已有文件不要覆盖。P1 必须实现并测试配置加载，不能假定 Python 自动读取 `.env`。

### B. 安装／确认 Azure CLI 并登录

原设备只读检查结果：PATH 中找不到 `az` 和 `winget`，两个常见 Azure CLI 安装目录也不存在。这不是新设备的检查结果，也不能据此判断其他凭据方式绝对不存在。新设备先执行 `az version`；可用时无需重装。

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

### C. 实现 P1 最小验证链路

1. 核对当前 Microsoft 文档、项目 API 代际、模型部署／区域和 Bing 工具支持；选择 SDK／API 并记录实际版本。不要仅根据门户代码宣称兼容。
2. 在项目虚拟环境添加并固定所需依赖，实现连接配置验证和 Foundry Adapter。不得依赖托管 Agent ID／名称，也不自动创建、修改云资源。
3. 验证实际 Python 凭据可用；如果 `DefaultAzureCredential` 选中了非预期账号，排查凭据链，必要时在本地验证中显式使用 `AzureCliCredential`，不要把 token 写入日志。
4. 先做一次小型直接模型请求，再显式绑定 Bing 工具：`bing_custom_search_preview` → `search_configurations` → `project_connection_id` 与 `instance_name`，使用已记录配置。
5. 取得或只读核对该 configuration 的域名范围，再选择一个香港监管官方网站查询；不先扩大云端配置。限制调用量和时间，记录可能产生模型及搜索费用。
6. 检查是否真实触发搜索、原生输出结构和 URL citation annotations，验证引用与内容的对应关系；不得用模型自行生成的 URL 补足缺失的原生引用。
7. 增加无配置、认证失败、权限不足、工具不支持、无结果、无引用、超时和限流的明确错误路径；记录请求标识及可观测用量，不记录密钥。
8. 形成 P1 能力记录：哪些验证通过、哪些不支持、允许展示／留存什么数据。验证前不批量保存 Bing 输出或抓取链接，不假定能获取原始工具结果。

若项目不支持直接模型与该工具组合，停止该接入路径并报告实际错误及替代方案；不静默调用已有托管 Agent。P1 通过后，按计划进入 P2 来源登记册、P3 Skills、P4 研究闭环，而非立即加入调度、聊天或通知。

## 5. Git 提交与迁移检查

此次交接只更新本地文件，没有执行 `git add`、`commit` 或 `push`。交接前检查显示只有 README 已被 Git 跟踪，P0 目录等仍未跟踪；上传时不要只提交文档，否则新设备缺少配置、Schema 和测试。

`.gitignore` 排除 `.venv`、Python 缓存、`.env`、数据库、运行数据，并新增根目录 `.tmp` 和 `.azure` 排除项。原有 `.tmp` 内容未查看、修改或删除；该忽略规则不等于审查其中内容。`.env.example` 明确保留为可跟踪文件。

用户准备提交时，可在仓库根目录执行以下显式暂存与检查命令；这只是操作说明，本次未执行：

```powershell
git status --short
git add -- README.md .gitignore .env.example requirements-dev.txt docs config schemas examples evals scripts tests
git diff --cached --stat
git diff --cached --check
git diff --cached
```

确认暂存内容符合预期且无凭据，再由用户选择分支／远端执行 commit 和 push。不要直接 `git add .`，也不要使用 `git add -f` 绕过忽略规则。忽略规则不会移除已经跟踪的秘密；如果后续检查发现敏感内容已进入 Git 历史，应停止上传并处理泄露，不仅添加忽略规则。

## 6. 可交给新设备上助手的接续说明

> 请先读取 README.md、docs/HANDOFF.md、docs/IMPLEMENTATION_PLAN.md、docs/P0_SPEC.md 和 .env.example。P0 已实现并有 48 项离线测试；云端连接标识已齐，但本机认证、真实模型和 Bing 调用未验证。先检查本机环境并重跑 P0，再协助完成 Azure 认证，推进 P1 的最小直接模型＋现有 Bing Custom Search 验证。Agent 编排由本地实现，不调用 Portal 托管 Agent，不索取 Agent ID，不自动修改云资源。不得扩展到定时、对话、推送、前端；不得索取或提交密钥。遇到 API／模型不兼容时报告证据，不静默切换架构。

## 7. 实施时核对的官方资料

- [Foundry Bing 工具：直接 REST 请求、连接标识及引用边界](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)
- [Azure Python 本地开发认证](https://learn.microsoft.com/en-us/azure/developer/python/sdk/authentication/local-development-dev-accounts)
- [Windows Azure CLI 安装](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows)
- [Azure CLI account 与 get-access-token](https://learn.microsoft.com/en-us/cli/azure/account#az-account-get-access-token)

这些是交接时使用的资料入口，SDK、API 和权限要求仍需在 P1 实施当天核实；文档样例不是本项目的通过记录。
