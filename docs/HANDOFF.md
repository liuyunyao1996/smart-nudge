# Smart Nudge：当前进度与交接

## 2026-09-30 update: optional Asia executive-news workflow

- Added `config/rules/asia-executive-news.json` as an opt-in workflow on the Custom Bing path only. The default remains `hk-regulatory-pulse.json`; legacy regional Rule Packs and the Foundry Agent path are unchanged.
- The rule targets three user-managed Custom Bing instances: `asia-news-regulatory-official`, `asia-news-corporate-exchange`, and `asia-news-authoritative-media`. No cloud resources or configurations were created or changed by this implementation.
- One run plans six searches (English and Chinese for each instance), accepts at most ten candidates per search, performs URL deduplication, and makes at most one no-tool Top-10 curation request. There are no automatic retries.
- `search-results.json` remains the technical audit artifact. The new `all-news.json` contains normalized cited candidates from the current run and labels them `in_window`, `out_of_window`, or `unknown`; only `in_window` candidates can reach `brief.json` and `brief.md`.
- Asia Rule Pack v1.2.0 uses brief schema v1.3.0. Each English brief item has a short concrete title, concise summary, normally two or three bullet points, attention level, topic and signal type; High-attention or unusually complex long-form items may use four or five bullets. Separate attention rationale and AIA impact sections were removed.
- The source catalogue explicitly includes all user-named media domains (Ming Pao, Oriental Daily, RTHK, Bastille Post, ETNet, HK01, InsuranceAsia News, Xinhua, SCMP, Bloomberg, Reuters, Financial Times and The Business Times) plus selected additional authoritative media. Primary official sources cover Hong Kong, Mainland China, Singapore, Thailand, Taiwan, India, and the Philippines.
- The first authorized live run completed on 2026-09-30 as `poc-20260930T055234Z-252d43`: all six searches and the summary succeeded, producing 33 deduplicated candidates, 20 in-window candidates and a Top-10 brief. The brief status was `partial` only because one unsupported High attention label was locally downgraded. The run used 202,463 known model tokens; native citation matching still does not independently verify page content.
- After that v1.0.0 live run, the Asia Rule Pack was advanced to v1.1.0 with article-specific URL preference. A second authorized live run, `poc-20260930T062245Z-169357`, completed all six searches and the summary: 33 deduplicated candidates, 27 in-window candidates and a Top-10 brief whose selected sources were all `specific_article`. It used 244,545 known model tokens. No listing/homepage candidate was returned, so live downgrade behavior was not exercised; offline tests cover it. Ten InsuranceAsia News root-level slug URLs were conservatively classified as `unknown` despite appearing article-like, identifying a possible classifier refinement. The run also filtered `www.ifsca.gov.in` and `cbr.irdai.gov.in` as unconfigured subdomains. No third live run was made.
- The two existing Asia live artifacts retain the brief contract used when they were generated. The v1.2.0/v1.3.0 presentation change has not been live-tested; a future live run still requires explicit authorization.

更新日期：2026-09-16（Asia/Shanghai）。项目已从严格的 P0–P4 研究／核验体系重构为轻量演示 PoC，默认路径只保留 rule-based web search 和 rule-based summarization。

## 当前实现

- 默认 Custom Bing 的云端配置和调用方式保持不变；新增显式 `--search-approach foundry-agent`。用户已要求回退刚新增的严格日期/具体来源验收，保留此前逐网站搜索、include 与引用诊断。
- Agent 路径使用 Rule Pack allowlist 生成 `site:` 查询，并严格丢弃站外原生引用；提示词域名控制不被表述为 Custom Bing 等价的检索端硬限制。

- 单个版本化 JSON Rule Pack 同时定义 Custom Bing configuration、允许域名、搜索和摘要规则。
- 香港是默认规则；澳门和中国大陆使用独立 Rule Pack、独立运行并分别生成简报。每个地区仍只有两个基础语言查询；Agent 路径按逻辑网站分别执行，英中候选查询共享每站工具预算。
- 使用现有 Azure Foundry Project、GPT-5-mini deployment 和 Bing Custom Search connection；请求通过 GPT-5-mini 支持的 `web_search` 工具绑定该配置。
- 只把带 Bing 原生、且属于所选地区允许域名的 URL citation 内容交给摘要阶段，不再抓取网页或调用 Verify Agent。
- 最终生成英文 Top-5 Markdown 与 JSON 简报；每条内容带 High／Medium／Low 管理层关注等级、监管信号类型和一句评级理由。
- 无 `--execute-live` 时只做离线 dry run；默认 Custom Bing 最多两次搜索和一次摘要。Agent 路径香港 5 个网站各一次 Agent 请求，每站最多 3 次工具调用（总配置预算 15 次），另最多一次摘要；澳门 2 站总工具预算 6 次，大陆 4 站总工具预算 12 次。全部零 HTTP 自动重试。工具预算不能保证服务不会超限，本地拒绝不能撤销已发生调用。
- 原始模型／工具内容和凭据不持久化。
- 当前规则恢复三份 v1.2.0 Rule Pack；`search.agent` 网站划分和每站最多 3 次工具调用预算保留。日期窗口仍由查询和提示约束，本地接受日期未知、超窗和带原生引用的索引页；无效日期标准化为 null。严格准入模块、source_rules、admission_diagnostics 及提前省略候选的提示已撤销。回退后 46 项测试、三份规则校验及 pip check 均通过。
- Agent 搜索记录新增 `citation_diagnostics`：原生引用/候选 URL 的脱敏对照、引用数量与固定字段结构统计、逐 URL 匹配原因及最终本地校验状态。仅显示当前网站 URL 的 scheme/host/path，隐藏查询值、fragment 和凭据；站外 URL 仅存哈希，未知类型合并为 `other`。不保留回答正文或标题。诊断的 URL 匹配不等于最终条目验证，且不放宽原有引用门槛。

架构与失败行为见 [POC_ARCHITECTURE.md](POC_ARCHITECTURE.md)。运行方法见仓库根目录 README。

## 续接步骤

1. 阅读 README 和本文件。
2. 检查 `git status --short --branch` 与最近提交。
3. 运行离线验证：

   ```powershell
   .\.venv\Scripts\python.exe scripts\validate_poc.py
   .\.venv\Scripts\python.exe -m unittest discover -s tests -v
   .\.venv\Scripts\python.exe -m pip check
   ```

4. 真实演示前先运行不带开关的 dry run；只有用户明确授权当次调用后才增加 `--execute-live`。
5. 已按用户要求回退 v1.3.0 严格验收，并完成回退后的香港、澳门、大陆各一次 Foundry Agent 真实测试，详见下节。当前保留宽松日期/索引页接受行为，不代表结果质量已解决。
6. 下一具体任务：先补充实际工具查询、动作类型及停止/候选省略原因的受限诊断，再处理澳门空候选。澳门中文候选查询仍使用英文 topic，仅搭配中文关键词；Agent 空候选后只被允许、并未被要求使用剩余预算改写。可考虑预算内短中文查询、AMCM CDN 与 BO 公告搜索，但这些方案尚未实施或验证，不能声称是已确认根因。`search.bo.dsaj.gov.mo` 未在 allowlist 中，不未经核对直接放行。真实测试仍需当次授权，不自动修改 Agent、fallback 或重试。

## 最新真实测试（回退后 v1.2.0）

以下均为 2026-09-16、30 天窗口 `[2026-08-17, 2026-09-16]`、`foundry-agent` 路径，无自动重试；产物只在忽略的 `.tmp/poc-runs/` 中，不提交。原生引用匹配不等于日期、内容或监管结论已核验。

- 香港：`poc-20260916T094804Z-9f5f02`。IA/HKMA/FSTB 各接受 3 个候选，工具调用分别 2/1/3；gov.hk 为 2 次、空候选；SFC timeout，实际工具数及 usage 未知。去重后 6 条、摘要成功 5 条，整体 partial。已知用量 58,339 tokens（搜索 55,062 + 摘要 3,277），不含超时请求。IA 本轮未超时。结果仍有索引页、未知日期及 FSTB 2026-08-01 超窗内容，不能称为严格有效结果。
- 澳门：`poc-20260916T095110Z-54fb84`。AMCM 与 BO 请求均成功，各 1 次 search，范围内原生 URL 分别 9/2 个，但两个响应本身均为空 items、coverage unavailable；不是本地删除候选。总用量 19,927 tokens，brief empty，摘要未运行，无超时/超限。AMCM 来源主要为业务/监管目录等常设页面；BO 来源包括首页、`/bo/i/97/26/declei27_cn.asp` 及被过滤的站外 `search.bo.dsaj.gov.mo`。无法追溯实际查询及省略原因，不证明窗口内无更新，也不能确认站外过滤造成空结果。
- 中国大陆：`poc-20260916T095303Z-503c10`。NFRA 接受 3 个候选、1 次 search；PBC 返回 4 次工具调用（2 search + 1 open_page + 1 find_in_page），超过每站 3 次而拒绝；gov.cn/SAFE 各 1 次 search、空候选。去重 2 条、摘要成功 2 条，整体 partial；总用量 45,162 tokens（搜索 42,963 + 摘要 2,199），无超时/重试。两条最终引用均为索引页，其中一条标题与 note 主题不一致、日期字段 2026-08-21 而 note 提到 2026-08-28，不能作为已核验监管结论。

诊断边界：当前 citation_diagnostics 保留原生来源和候选 URL 脱敏对照，不保存工具实际 query、完整正文或 Agent 逐项省略原因。`max_tool_calls` 统计 search/open_page/find_in_page 等全部 Web Search 调用，不是仅搜索次数；服务仍可能超限，本地拒绝不能撤销费用。超时异常统一记为 timeout，未细分连接/读取阶段；连接超时 15 秒、其余阶段 60 秒，超时服务端仍可能处理。尚未提高超时或新增重试。

## 已知边界

- 2026-09-16 v1.3.0 香港 Agent 真实测试位于 `.tmp/poc-runs/poc-20260916T093722Z-dc78e1/`：五个响应均返回空 items。IA 本轮未超时；IA/HKMA/FSTB 各 1 次工具调用，SFC 为 2 次 search + 2 次 open_page，gov.hk 为 3 次 search + 1 次 open_page，后两站因每站超过 3 次被拒绝。共 11 个工具调用记录、58,556 tokens，摘要未运行，brief empty。不能确认 Agent 提前省略候选的逐项原因。测试产物保留，不因回退改写。

- Grounding 内容没有经过独立原文核验，简报固定披露此限制。
- 2026-09-16 include 香港 v1.2.0 真实运行位于 `.tmp/poc-runs/poc-20260916T090317Z-709e9c/`：IA timeout 未重试，HKMA/SFC/FSTB/gov.hk 均返回 action.sources，分别 11/11/11/10 个原生范围内唯一 URL；调用记录 1/1/1/2（IA 未知）。接受候选 3/3/2/0，去重后 7 条、摘要 5 条、整体 partial。发现 FSTB 2026-08-01 超窗、HKMA 日期未知、多条索引页；旧产物不重写。不能将这些结果视为严格窗口有效结果；曾新增的 v1.3.0 严格验收现已按用户要求回退。原生 URL 匹配成功仍不等于独立核验。
- 2026-09-16 带引用诊断真实运行位于 `.tmp/poc-runs/poc-20260916T085619Z-8daa55/`：5 个响应、每站 1 个工具调用记录；IA `invalid_search_schema`，其余四站 envelope 校验通过，候选 HKMA 3 / SFC 3 / FSTB 2 / gov.hk 2 均无原生对照可用，最终 0 条、无摘要、52,620 tokens。诊断只确认预期字段没有来源列表与文本引用记录，不证明 URL 编造，也未排除其他服务字段位置。查阅 [微软 Responses Web Search 文档](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search#domain-filtering-and-source-retrieval)，其明确要求 `include` 返回 `action.sources`；[Agent server 请求模型](https://learn.microsoft.com/en-us/python/api/azure-ai-agentserver-responses/azure.ai.agentserver.responses.createresponse?view=azure-python-preview) 也列出该 include 值。dedicated endpoint 对当前 Prompt Agent 的支持仍待 live 验证，不能仅凭通用文档认定云端已修复。
- 2026-09-16 网站版真实运行位于 `.tmp/poc-runs/poc-20260916T084546Z-c7d861/`：5/5 搜索成功、实际返回 5 个 Web Search 调用记录（无超限），HKMA 3 个、SFC 5 个、FSTB 3 个候选均未通过原生引用匹配；IA 与 gov.hk 空结果。接受 0 条、摘要未调用、总用量 52,470 tokens。本次旧产物没有引用诊断，不能追溯两边 URL；新增诊断不能事后还原它们。
- 2026-09-15 使用 Prompt Agent `web-search-m3dbbkxpg2` version `6` 做了首次真实 Agent 路径测试。沙箱外 Azure CLI 凭据可用，请求已到达 Foundry，但英文和繁体中文两次请求均返回 HTTP 400／`request_rejected`，因此没有搜索结果、没有摘要调用，也没有自动重试。脱敏产物位于 `.tmp/poc-runs/poc-20260915T103549Z-3a5efc/`；原始服务响应未保留。后续 probe 已确认主要问题是调用了共享 project Responses endpoint 并发送 `agent_reference`，而当前 Agent 应通过 dedicated endpoint 调用。
- 2026-09-16 对 Agent dedicated Responses endpoint 做了一次最小真实 contract probe，仅发送 `input`。请求返回 HTTP 200／`completed`，产生 1 条 `www.hkma.gov.hk` 原生 citation，证明 Agent、认证、Web Search 与 dedicated endpoint 可用；未保存或显示回答正文。该最小请求内部产生了 3 个 `web_search_call`，因此提示词本身不能保证调用上限。本地实现现已改用 dedicated endpoint、发送 `max_tool_calls=1`，并在解析时拒绝多调用响应。
- 2026-09-16 随后执行了一次完整 payload、单查询 Agent live test。请求到达 dedicated endpoint，但返回 HTTP 400／`invalid_payload`，服务参数为 `text`，request ID 为 `46bbf8c74306fbc70a9ff7198d18778b`；没有搜索结果、没有第二次搜索或摘要请求，也未保存或显示原始响应。该结果与 Foundry Prompt Agent 在指定 Agent 时不允许请求级 `text`／response format 的已知行为一致。本地实现已移除 Agent payload 的 `text.format`，在运行时提示中嵌入 JSON Schema，并继续对返回 JSON、schema、原生引用、allowlist 和 Web Search 调用数做严格本地校验；尚待一次单查询 live 复测。
- 2026-09-16 修复后再次执行单查询 Agent live test。请求返回 `completed`，request ID 为 `78e746df-f905-45b6-a1d2-85a82c52615a`，且只产生 1 个 `web_search_call`；返回文本通过本地 JSON 与 envelope 校验，coverage 为 `partial`，items 为空，因此接受条目和 citation host 均为 0。该结果证明移除请求级 `text.format` 后的 dedicated endpoint、单工具调用上限和提示式 JSON 契约可用，但没有在同一响应中覆盖合格原生引用条目的正向路径。没有第二次搜索或摘要请求，也未保存或显示原始响应。
- 2026-09-16 随后执行了一次 30 天窗口的完整 Agent pipeline。英文和繁体中文两次搜索均成功完成且没有失败，coverage 分别为 `partial` 和 `unavailable`，但接受条目均为 0，因此生成合法的 `empty` brief，摘要请求未运行。英文请求使用 5,747 tokens，繁体中文请求使用 5,969 tokens；脱敏产物位于 `.tmp/poc-runs/poc-20260916T021606Z-f93488/`，原始响应未保留。该运行验证了双查询完整控制流，但仍未覆盖合格引用条目和摘要正向路径。
- 2026-09-16 将每个语言查询按两个域名一组拆分后执行完整 Agent pipeline。6 个搜索请求中 4 个成功、2 个失败：`en-sites-3` 因响应包含多个 Web Search call 被本地 `search_call_limit_exceeded` 拒绝，`zh-hant-sites-2` 因提示式 JSON 不符合 envelope 被 `invalid_search_schema` 拒绝。`en-sites-2` 返回 3 个结构化候选，但其 `citation_urls` 没有匹配响应中的原生、当前域名组 citation，均被安全过滤；其余成功请求返回空 items。最终没有合格条目，摘要未运行。脱敏产物位于 `.tmp/poc-runs/poc-20260916T030414Z-093796/`，原始响应未保留。
- 本地允许域名列表来自已知 Custom Bing 配置记录，不表示本次重构重新读取了云端配置。
- 2026-09-14 的真实运行已确认迁移后的 `web_search` 请求、Structured Outputs schema 和 `web_search_call.action.sources` 引用链可被 Foundry 接受。修复后的端到端运行完成两次搜索（零失败），去重后保留 7 条搜索结果，并成功生成 5 条 no-tool 英文摘要；原生来源域名均在允许范围内，原始响应未保留。解析器仅接受候选 citation URL 与原生、范围内 action source URL 的匹配，并将 annotation 降为标题和 offset 元数据。结果仍未经过独立原文核验；后续 live 调用仍需用户逐次授权。
- 澳门 `macao-financial-regulators-test` 与中国大陆 `cn-mainland-financial-regulators-test` 已完成 Rule Pack、dry run 和真实调用验证；两地均为 2/2 搜索成功并完成摘要。澳门 Rule Pack 与 Portal configuration 已同时加入 `www.bo.dsaj.gov.mo`；修正后的目标运行得到 2 条简报，合格引用来自 `bo.dsaj.gov.mo` 和 `www.amcm.gov.mo`，不再出现该域名的越界 warning。中国大陆目标运行得到 3 条简报，合格引用来自 `www.nfra.gov.cn`。现有 `.env` 中若仍保留旧的 `BING_CUSTOM_SEARCH_INSTANCE_NAME`，该值会被忽略；configuration/instance 以所选 Rule Pack 为准。后续 live 调用仍需用户逐次授权。
- v1.1.0 新增轻量 `Executive Attention Level`。评分只依据 grounded notes，不代表正式风险评级；本地仅允许 `final_rule`／`enforcement` 保持 High，其他 High 会降为 Medium，fallback 为 `MEDIUM | UNCLASSIFIED`。该新版输出尚未 live 验证，已有 `demo/` 快照仍是此前 v1.0.0 运行结果。
- 定时、通知、前端、数据库、生产治理和实际推送不在当前范围。
- `.env`、`.tmp`、Azure 登录缓存和访问令牌不得提交。

## 当前工作区说明

本次重构删除的旧 P0–P4 模块、Schemas、fixtures、测试和阶段文档仍可从 Git 历史恢复；它们不再属于活动架构。是否已经提交以 `git status` 和提交日志为准，未经用户明确要求不要 commit 或 push。
