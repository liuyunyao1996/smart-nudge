# Smart Nudge

Smart Nudge 是一个面向 AIA Group CEO 的公开 Web 情报演示 PoC。它只展示两个核心能力：

1. 按版本化 Rule Pack 使用 Foundry Responses API 的 `web_search` 工具，并绑定现有 Bing Custom Search configuration 来搜索香港、澳门或中国大陆官方站点。
2. 按同一 Rule Pack 将带原生 URL 引用的搜索内容整理成英文管理层简报。

另有一个显式选择的实验性搜索后端，可调用现有 Microsoft Foundry Prompt Agent 的普通 Web Search。它不会改变默认 Custom Bing 路径；域名定向由 `site:` 查询、提示词和本地引用白名单共同实施，其中只有最后一层是硬性输出边界。

当前默认 Rule Pack 搜索最近 30 天的香港保险和金融监管动态。默认 Custom Bing 路径执行一次英文搜索、一次繁体中文搜索和最多一次英文摘要。Agent 路径按网站分别请求，英中候选查询共享每站最多 3 次 Web Search 工具调用的预算：香港 IA、HKMA、SFC（含 apps.sfc.hk）、FSTB、gov.hk 共 5 次 Agent 请求，配置工具调用上限共 15 次，另有最多一次摘要。两条路径最终都只选出不超过 5 条内容。项目不再包含 Verify Agent、独立网页抓取、claim/evidence 状态机或 HTTP 自动重试。

每条简报内容同时显示简短的 `Executive Attention Level`（High／Medium／Low）、监管信号类型和一句评级理由。该等级用于帮助管理层排序关注，不代表已经确认的法律适用性、损失概率或正式企业风险评级。

## Quick start

Python 3.11+：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts\validate_poc.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

先执行离线 dry run，检查规则、查询和默认 Custom Bing 最多三次真实请求的边界：

```powershell
.\.venv\Scripts\python.exe scripts\run_poc.py
```

只有显式增加 `--execute-live` 才会读取 `.env` 并调用 Foundry/Bing：

```powershell
.\.venv\Scripts\python.exe scripts\run_poc.py --execute-live
```

使用已有 Prompt Agent 的普通 Web Search 时显式选择第二个后端。先执行 dry run，确认每个网站的 site-scoped queries、Agent 请求数和工具调用预算；真实调用仍需要单独增加 `--execute-live`：

```powershell
.\.venv\Scripts\python.exe scripts\run_poc.py --search-approach foundry-agent
.\.venv\Scripts\python.exe scripts\run_poc.py --search-approach foundry-agent --execute-live
```

可覆盖默认主题和时间窗口：

```powershell
.\.venv\Scripts\python.exe scripts\run_poc.py --topic "consumer protection and digital distribution" --days 14 --execute-live
```

澳门和中国大陆使用独立 Rule Pack、独立运行并分别生成简报。先省略 `--execute-live` 检查查询计划；确认后再为特定运行显式添加该开关：

```powershell
.\.venv\Scripts\python.exe scripts\run_poc.py --rule config/rules/macao-regulatory-pulse.json
.\.venv\Scripts\python.exe scripts\run_poc.py --rule config/rules/cn-mainland-regulatory-pulse.json
```

澳门和大陆的 Agent 路径与香港使用相同的逐网站搜索策略、`include` 原生来源获取和引用诊断。以下命令仅做离线 dry run：

```powershell
.\.venv\Scripts\python.exe scripts\run_poc.py --rule config/rules/macao-regulatory-pulse.json --search-approach foundry-agent
.\.venv\Scripts\python.exe scripts\run_poc.py --rule config/rules/cn-mainland-regulatory-pulse.json --search-approach foundry-agent
```

澳门分 AMCM（`www.amcm.gov.mo` / `cdn.amcm.gov.mo`）和公报（`bo.dsaj.gov.mo` / `www.bo.dsaj.gov.mo`）两站，最多 2 次 Agent 请求、配置工具预算 6 次；大陆分 NFRA、PBC、gov.cn、SAFE 四站，最多 4 次 Agent 请求、配置工具预算 12 次。每站英中合计最多 3 次工具调用，结果不足时允许预算内同站改写；另每地区最多一次摘要。这里对齐搜索方式而非强行凑齐香港的五站数量；域名仍来自各地区现有 allowlist，不新增云端配置。真实测试仍需当次授权并增加 `--execute-live`。

真实运行会把以下文件写入 `.tmp/poc-runs/<run_id>/`：

- `search-results.json`：通过原生范围内引用匹配的规范化内容，以及引用诊断。
- `brief.json`：结构化英文简报。
- `brief.md`：可直接展示或转发的英文简报。

若所有搜索调用都失败，只写 `search-results.json` 和 `error.json`，并返回非零退出码。

## Configuration

首次使用时手动复制 `.env.example` 为 `.env`；已有 `.env` 不要覆盖。`.env` 只保存现有 Foundry Project、模型 deployment 和 Bing Custom Search project connection；具体 configuration/instance 名称来自所选 Rule Pack。因此切换地区不需要修改 `.env`，也不创建或修改云资源、不需要 Portal Agent ID。搜索请求使用 GPT-5-mini 支持的 `web_search` API surface，而不是该模型不支持的旧 `bing_custom_search_preview` 工具类型。

可选的 Agent 后端还需要 `FOUNDRY_WEB_SEARCH_AGENT_NAME` 和固定的 `FOUNDRY_WEB_SEARCH_AGENT_VERSION`。两者均为非敏感标识；Agent 名称用于调用其 dedicated Responses endpoint，版本用于产物审计，并应与 Portal 中该 endpoint 的 Active version 一致。运行时不创建、修改或删除 Agent。该 Agent 应位于同一个 Foundry Project，且只启用普通 Web Search 工具。不要把 key、token 或 Portal 登录缓存写入 `.env`。

默认规则位于 `config/rules/hk-regulatory-pulse.json`；另有 `macao-regulatory-pulse.json` 和 `cn-mainland-regulatory-pulse.json`。通过 `--rule config/rules/<name>.json` 选择。一个 Rule Pack 同时定义：

- Custom Bing instance 和该地区允许的域名；
- 搜索主题、窗口、语言、查询模板和包含／排除规则；
- Agent 网站划分（同站主域名与子域名可归为一站）和每站最多 1–3 次工具调用；
- 摘要受众、语言、Top 5 排序、轻量关注等级和写作规则。

## Evidence boundary

每条进入简报的搜索内容必须至少带一个由 `web_search_call.action.sources` 原生返回的 `https` URL，候选的 `citation_urls` 必须规范化匹配该 URL，且域名属于 Rule Pack 的允许列表。`message.content[].annotations` 中的 `url_citation` 用于补充原生标题和字符偏移。除此之外不做独立原文下载、locator 匹配或 Verify Agent 判断。无引用或越界只丢弃对应条目，不使整轮失败。

在 Agent 后端中，原生 `url_citation` annotation 也可作为引用证据，因为该 API surface 不保证返回 action source 列表；若 action sources 存在也会一并校验。Prompt Agent 不接受请求级 `text.format`，所以 Agent 输出结构由运行时 JSON Schema 提示和严格本地解析共同约束，而不是由服务端 Structured Outputs 保证。每个网站独立调用一次 Agent，提供英中候选查询；结果不足时可在剩余工具预算内改写同站查询，不扩大日期或域名。每站配置 `max_tool_calls` 最多 3 次，跨语言共享该上限，足够时应提前停止；本地引用过滤只接受当前网站配置的主域名与同站别名。两种后端都严格丢弃站外、非 HTTPS 或非原生引用的候选。普通 Web Search 的提示词不能保证检索过程只接触 allowlist 网站，因此产物会明确标注该限制。

工具预算同时写入提示词和 `max_tool_calls`；超过预算的响应被本地拒绝并记录实际返回调用数。此前 Foundry 曾返回超限调用，因此本地检查不是已发生计费的硬性上限，也不能撤销工具调用。`search-results.json` 会记录每站实际返回的 Web Search 调用数；已收到响应但本地解析失败时也保留脱敏 usage 和 request ID。

Agent 请求现在显式发送 `include=["web_search_call.action.sources"]` 获取原生来源；不发送 `text.format`，也不改变 dedicated endpoint。香港 v1.2.0 真实运行已验证四个成功站点返回来源，其他站点不作保证；服务若拒绝不会自动重试或 fallback。每站 `citation_diagnostics` 记录 requested include、引用类型/结构数量、脱敏 URL 对照、逐 URL 失配原因、envelope 固定字段检查和最终本地校验结果。普通 URL 文本不是原生引用；即使请求了 include，服务没有返回可用原生引用时仍拒绝采用候选。

已按用户要求回退 v1.3.0 严格准入，三地区规则恢复 v1.2.0：日期窗口仍由查询和提示约束，但本地不拒绝日期未知、超窗或索引页引用；无效日期标准化为 null。原生 HTTPS、允许域名、完整 URL 匹配和工具调用预算检查保持不变。结果可能包含旧内容或索引页，不能声称日期窗口已严格核验。

因此结果应理解为“带来源链接的 Grounding 内容”，不是已独立核验的原文结论；本地引用匹配也不能证明模型返回日期真实。每份简报会显示免责声明。原始模型／工具响应不落盘，外部请求不自动重试。

详细设计见 [PoC architecture](docs/POC_ARCHITECTURE.md)，续接状态见 [HANDOFF](docs/HANDOFF.md)。
