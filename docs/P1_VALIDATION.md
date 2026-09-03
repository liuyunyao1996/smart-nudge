# P1 最小接入验证记录

日期：2026-09-03，Asia/Shanghai。状态：**P1 工程验收完成：认证、直接模型、指定 Bing 搜索、原生引用结构、官方原文访问方案与保守留存边界均已落地；组织法律／隐私批准仍是生产门槛。**

访问顺序、发布方例外、允许留存的数据和生产批准门槛见 [P1 官方原文访问方案与数据留存边界](P1_ACCESS_RETENTION.md)。

## 已实现

- `smart_nudge/foundry.py`：配置加载、Azure CLI 凭据、项目 Responses REST 适配层，以及模型与搜索探针。
- `scripts/smoke_foundry.py`：`auth`、`model`、`search` 三个手动命令；默认只执行 `auth`。
- `.env` 从已有非敏感示例创建，仍被 Git 忽略；进程环境变量优先，不展开配置中的变量或执行 shell。
- `config/sources/hk-regulators-pilot.json`：用户提供的六个预期来源主机名。Blocked 规则和 Include subpages 开关未知，也未回读或更改云端配置。
- 原生引用保留输出项位置、内容位置和字符区间，检查来源主机名；模型正文中的裸 URL 不用来补造 citation。
- 缺失配置、凭据失败、HTTP 权限／限流／请求错误、网络、超时、响应不完整、无引用、工具失败及越界来源等情况返回明确失败。

运行环境：Windows，Python 3.11.9，Azure CLI 2.90.0。直接依赖固定于 `requirements.txt`：`azure-identity==1.25.3`、`httpx==0.28.1`、`python-dotenv==1.2.3`。P0 校验另使用 `jsonschema==4.26.0`。未使用 OpenAI 或 Azure AI Projects SDK，避免为此 REST 验证引入额外客户端层；未引入 Agent 框架。

## 真实调用证据

订阅 `2f7f01da-407f-4d68-b710-91938eb28b3b` 状态为 Enabled。`AzureCliCredential` 成功取得 `https://ai.azure.com/.default` 令牌，只显示过期时间，未显示或保存 token。当前助手进程 PATH 尚未刷新，执行时临时加入已验证的 Azure CLI 安装目录；用户新开的 PowerShell 已可直接使用 `az`。

实际入口：

```text
https://liuyunyao1996-5895-resource.services.ai.azure.com/api/projects/liuyunyao1996-5895/openai/v1/responses
```

使用文档中的无日期查询参数项目 Responses v1 路径。模型部署为 `gpt-5-mini`，未使用 `agent_reference`，未创建、修改或调用 Portal 托管 Agent。

第一次 Responses 请求为纯模型验证：

- 返回状态 `completed`，输出 `SMART_NUDGE_OK`。
- Request ID：`96a52a81-db81-4e47-bca6-1446589bd745`。
- Response ID：`resp_0ade87eaadb3a6da016a98e1fab520819599e269e9655b02fd`。
- 输入 21、输出 22、合计 43 token；输出上限 256，reasoning effort 为 `minimal`。

第二次 Responses 请求为指定来源搜索验证：

- 复用 `.env.example` 中的完整项目连接 ID，instance 为 `hk-financial-regulators-test`。
- 工具类型 `bing_custom_search_preview`，`tool_choice=required`，搜索配置 `count=3`，输出上限 1800，reasoning effort 为 `low`。
- 问题：查找香港保监局关于风险为本资本制度的一篇官方新闻稿，给出有证据支持的标题、日期和一句描述。本次没有施加“最新”日期过滤，历史文章仅用于接入测试。
- 返回状态 `completed`，观察到 1 个已完成的 `bing_custom_search_preview_call` 和对应的已完成 `bing_custom_search_preview_call_output`。
- 返回 1 条原生 URL citation，主机名为用户提供的保监局主机名，字符区间 `[413, 425)` 有效；这证明引用标记可定位，不证明该引用支持所有陈述。
- Request ID：`497957b5-6e87-4a5c-9b83-c8482cba00fa`。
- Response ID：`resp_084c812ffe1e939f016a98e2e1cf108197874b4d4712cdee41`。
- 输入 2123、输出 588、合计 2711 token。

两次请求总计 2754 token。搜索实际计费金额及 Bing 内部请求数量未查询；可见工具调用数不等于全部底层搜索操作数。

## 原文访问结论

搜索返回的引用指向 [保监局公告](https://www.ia.org.hk/en/infocenter/press_releases/20240701.html)。随后通过 Web 读取工具单独打开该公开页面，返回 HTTP 403；本次未取得目标新闻稿原文，也未绕过访问限制。不能将搜索输出中的标题、日期和事实直接当成已核验结论，也不能把该访问结果泛化为用户浏览器或所有客户端都无法访问。

CLI 始终将 `factual_verification` 标为 `pending_manual_review`；自动的 `ok` 只表示接入、工具状态和引用结构检查通过。保险业监管局 2024–25 年报 PDF 可作为同一发布方的另一份一手材料，支持风险为本资本制度量化支柱于 2024 年 7 月 1 日实施这一一般事实，但只能记为 `corroborated_alternate_first_party`，不能证明目标新闻稿的确切标题或正文。

## 运行方法

在项目虚拟环境安装 `requirements-dev.txt`，首次创建 `.env`，并在本机完成 Azure CLI 登录后：

```powershell
.\.venv\Scripts\python.exe scripts/smoke_foundry.py --check auth
.\.venv\Scripts\python.exe scripts/smoke_foundry.py --check model
.\.venv\Scripts\python.exe scripts/smoke_foundry.py --check search
```

可用 `--env-file PATH` 指定配置文件，`--source-scope PATH` 指定与 Bing instance 对应的来源范围记录。搜索探针问题固定为香港保监局，尚不是通用研究 CLI。`--check model` 和 `--check search` 每执行一次都会产生真实调用用量；无需重复本次成功测试。

没有自动重试、重定向、后台执行或历史会话复用。凭据子进程超时 30 秒，HTTP connect 超时 15 秒，其他 HTTP 阶段超时 60 秒；这些是阶段超时，不是严格的端到端截止时间。请求超时后云端仍可能已经处理。每次探针只发送一次 Responses 请求；`count=3` 不是内部工具调用硬上限。

## 数据与能力边界

- `store=false` 已在两次真实请求中接受，不写本地响应文件；这不构成供应商零留存保证，也不证明任何后续保存方式被许可。
- 搜索 CLI 现在仅显示白名单审计元数据与原生引用，不显示 Bing 生成的回答正文，也不写响应文件。
- 观察到工具输出项的存在，不等于已验证可取得原始搜索结果或全文。没有查看、批量保存或复用工具原始内容，没有建立抓取／索引／评测流水线。
- Bing 查询链接若由原生 annotations 返回则保留，不作为监管来源计数；本次原生 URL annotations 仅有一条保监局来源。
- [微软 Bing 工具说明](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)及其适用条款要求按原样展示引用，并明确原始工具输出限制。策略禁止批量留存、索引、抓取种子及模型训练／评测用途；未获批准的路径保持禁用。
- 六个主机名来自用户说明，仅验证了一次保监局来源；没有证明其余五个主机名可用、Blocked 规则完整或全网覆盖。

## 离线验证与下一步

P0 资产校验通过；78 项离线测试通过（48 项 P0 + 18 项接入回归 + 12 项留存策略回归），`pip check` 无依赖冲突。错误路径使用 MockTransport／合成响应验证，没有为了测试主动制造云端限流、权限错误或批量调用。无引用不能区分“没有搜索结果”和“模型没有给引用”，因此不得报告无事件。

下一步进入 P2：为六个试点来源建立来源登记册和获准访问能力矩阵；然后实现 P3 监管 Skill、P4 搜索—分析—核验闭环。完整 Agent 研究能力、输出持久化、业务评测及 P0 专家复核仍未完成。

认证与网络实现依据：[AzureCliCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.azureclicredential)、[HTTPX 客户端接口](https://www.python-httpx.org/api/)。
