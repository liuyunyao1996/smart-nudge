# Smart Nudge：当前进度与交接

更新日期：2026-09-14（Asia/Shanghai）。项目已从严格的 P0–P4 研究／核验体系重构为轻量演示 PoC，默认路径只保留 rule-based web search 和 rule-based summarization。

## 当前实现

- 单个版本化 JSON Rule Pack 同时定义搜索和摘要规则。
- 默认搜索香港最近 30 天监管动态，覆盖英文和繁体中文。
- 使用现有 Azure Foundry Project、GPT-5-mini deployment 和 Bing Custom Search connection；请求通过 GPT-5-mini 支持的 `web_search` 工具绑定该配置。
- 只把带 Bing 原生、范围内 HK URL citation 的内容交给摘要阶段，不再抓取网页或调用 Verify Agent。
- 最终生成英文 Top-5 Markdown 与 JSON 简报。
- 无 `--execute-live` 时只做离线 dry run；完整 live 运行最多两次搜索和一次摘要，零自动重试。
- 原始模型／工具内容和凭据不持久化。
- 当前离线基线为 Rule Pack 校验通过、17 项测试通过、`pip check` 无依赖冲突。

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

## 已知边界

- Grounding 内容没有经过独立原文核验，简报固定披露此限制。
- 本地允许域名列表来自已知 Custom Bing 配置记录，不表示本次重构重新读取了云端配置。
- 2026-09-14 的真实运行已确认迁移后的 `web_search` 请求、Structured Outputs schema 和 `web_search_call.action.sources` 引用链可被 Foundry 接受。修复后的端到端运行完成两次搜索（零失败），去重后保留 7 条搜索结果，并成功生成 5 条 no-tool 英文摘要；原生来源域名均在允许范围内，原始响应未保留。解析器仅接受候选 citation URL 与原生、范围内 action source URL 的匹配，并将 annotation 降为标题和 offset 元数据。结果仍未经过独立原文核验；后续 live 调用仍需用户逐次授权。
- 定时、通知、前端、数据库、生产治理和实际推送不在当前范围。
- `.env`、`.tmp`、Azure 登录缓存和访问令牌不得提交。

## 当前工作区说明

本次重构删除的旧 P0–P4 模块、Schemas、fixtures、测试和阶段文档仍可从 Git 历史恢复；它们不再属于活动架构。是否已经提交以 `git status` 和提交日志为准，未经用户明确要求不要 commit 或 push。
