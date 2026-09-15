# Smart Nudge：当前进度与交接

更新日期：2026-09-15（Asia/Shanghai）。项目已从严格的 P0–P4 研究／核验体系重构为轻量演示 PoC，默认路径只保留 rule-based web search 和 rule-based summarization。

## 当前实现

- 默认 Custom Bing search approach 保持不变；新增显式 `--search-approach foundry-agent`，可通过固定名称和版本引用同一 Foundry Project 内已有的普通 Web Search Prompt Agent。
- Agent 路径使用 Rule Pack allowlist 生成 `site:` 查询，并严格丢弃站外原生引用；提示词域名控制不被表述为 Custom Bing 等价的检索端硬限制。

- 单个版本化 JSON Rule Pack 同时定义 Custom Bing configuration、允许域名、搜索和摘要规则。
- 香港是默认规则；澳门和中国大陆使用独立 Rule Pack、独立运行并分别生成简报。每个地区仍只有两个语言查询。
- 使用现有 Azure Foundry Project、GPT-5-mini deployment 和 Bing Custom Search connection；请求通过 GPT-5-mini 支持的 `web_search` 工具绑定该配置。
- 只把带 Bing 原生、且属于所选地区允许域名的 URL citation 内容交给摘要阶段，不再抓取网页或调用 Verify Agent。
- 最终生成英文 Top-5 Markdown 与 JSON 简报；每条内容带 High／Medium／Low 管理层关注等级、监管信号类型和一句评级理由。
- 无 `--execute-live` 时只做离线 dry run；完整 live 运行最多两次搜索和一次摘要，零自动重试。
- 原始模型／工具内容和凭据不持久化。
- 当前离线基线为三份 v1.1.0 Rule Pack 校验通过、25 项测试通过、`pip check` 无依赖冲突。

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
5. Agent 路径下一步是在用户再次明确授权后，使用 Portal 示例的最小 `agent_reference` 请求做一次单调用 contract probe；不要直接重复完整 pipeline。

## 已知边界

- Grounding 内容没有经过独立原文核验，简报固定披露此限制。
- 2026-09-15 使用 Prompt Agent `web-search-m3dbbkxpg2` version `6` 做了首次真实 Agent 路径测试。沙箱外 Azure CLI 凭据可用，请求已到达 Foundry，但英文和繁体中文两次请求均返回 HTTP 400／`request_rejected`，因此没有搜索结果、没有摘要调用，也没有自动重试。脱敏产物位于 `.tmp/poc-runs/poc-20260915T103549Z-3a5efc/`；原始服务响应未保留。高概率问题位于 `agent_reference` 与 response-level Structured Outputs／调用限制参数的组合，尚未通过最小请求隔离。
- 本地允许域名列表来自已知 Custom Bing 配置记录，不表示本次重构重新读取了云端配置。
- 2026-09-14 的真实运行已确认迁移后的 `web_search` 请求、Structured Outputs schema 和 `web_search_call.action.sources` 引用链可被 Foundry 接受。修复后的端到端运行完成两次搜索（零失败），去重后保留 7 条搜索结果，并成功生成 5 条 no-tool 英文摘要；原生来源域名均在允许范围内，原始响应未保留。解析器仅接受候选 citation URL 与原生、范围内 action source URL 的匹配，并将 annotation 降为标题和 offset 元数据。结果仍未经过独立原文核验；后续 live 调用仍需用户逐次授权。
- 澳门 `macao-financial-regulators-test` 与中国大陆 `cn-mainland-financial-regulators-test` 已完成 Rule Pack、dry run 和真实调用验证；两地均为 2/2 搜索成功并完成摘要。澳门 Rule Pack 与 Portal configuration 已同时加入 `www.bo.dsaj.gov.mo`；修正后的目标运行得到 2 条简报，合格引用来自 `bo.dsaj.gov.mo` 和 `www.amcm.gov.mo`，不再出现该域名的越界 warning。中国大陆目标运行得到 3 条简报，合格引用来自 `www.nfra.gov.cn`。现有 `.env` 中若仍保留旧的 `BING_CUSTOM_SEARCH_INSTANCE_NAME`，该值会被忽略；configuration/instance 以所选 Rule Pack 为准。后续 live 调用仍需用户逐次授权。
- v1.1.0 新增轻量 `Executive Attention Level`。评分只依据 grounded notes，不代表正式风险评级；本地仅允许 `final_rule`／`enforcement` 保持 High，其他 High 会降为 Medium，fallback 为 `MEDIUM | UNCLASSIFIED`。该新版输出尚未 live 验证，已有 `demo/` 快照仍是此前 v1.0.0 运行结果。
- 定时、通知、前端、数据库、生产治理和实际推送不在当前范围。
- `.env`、`.tmp`、Azure 登录缓存和访问令牌不得提交。

## 当前工作区说明

本次重构删除的旧 P0–P4 模块、Schemas、fixtures、测试和阶段文档仍可从 Git 历史恢复；它们不再属于活动架构。是否已经提交以 `git status` 和提交日志为准，未经用户明确要求不要 commit 或 push。
