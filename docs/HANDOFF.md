# Smart Nudge：当前进度与交接

更新日期：2026-09-16（Asia/Shanghai）。项目已从严格的 P0–P4 研究／核验体系重构为轻量演示 PoC，默认路径只保留 rule-based web search 和 rule-based summarization。

## 当前实现

- 默认 Custom Bing search approach 保持不变；新增显式 `--search-approach foundry-agent`，可通过固定名称和版本引用同一 Foundry Project 内已有的普通 Web Search Prompt Agent。
- Agent 路径使用 Rule Pack allowlist 生成 `site:` 查询，并严格丢弃站外原生引用；提示词域名控制不被表述为 Custom Bing 等价的检索端硬限制。

- 单个版本化 JSON Rule Pack 同时定义 Custom Bing configuration、允许域名、搜索和摘要规则。
- 香港是默认规则；澳门和中国大陆使用独立 Rule Pack、独立运行并分别生成简报。每个地区仍只有两个基础语言查询；Agent 路径再按每两个允许域名拆分执行。
- 使用现有 Azure Foundry Project、GPT-5-mini deployment 和 Bing Custom Search connection；请求通过 GPT-5-mini 支持的 `web_search` 工具绑定该配置。
- 只把带 Bing 原生、且属于所选地区允许域名的 URL citation 内容交给摘要阶段，不再抓取网页或调用 Verify Agent。
- 最终生成英文 Top-5 Markdown 与 JSON 简报；每条内容带 High／Medium／Low 管理层关注等级、监管信号类型和一句评级理由。
- 无 `--execute-live` 时只做离线 dry run；默认 Custom Bing 完整 live 运行最多两次搜索和一次摘要，Agent 路径香港最多六次搜索和一次摘要、澳门或中国大陆最多四次搜索和一次摘要，全部零自动重试。
- 原始模型／工具内容和凭据不持久化。
- 当前离线基线为三份 v1.1.0 Rule Pack 校验通过、28 项测试通过、`pip check` 无依赖冲突。

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
5. 拆分版完整 Agent pipeline 已真实运行：6 个搜索请求中 4 个成功、2 个本地契约失败，仍没有合格条目，因此摘要未运行。下一步应先解决 Agent 原生 citation 与 JSON `citation_urls` 未对齐、超出单工具调用上限和提示式 schema 偶发失配；未经用户明确授权不要再次 live 重试。

## 已知边界

- Grounding 内容没有经过独立原文核验，简报固定披露此限制。
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
