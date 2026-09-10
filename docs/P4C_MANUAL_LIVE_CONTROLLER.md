# P4-C Manual-live 完整控制器

更新日期：2026-09-10（Asia/Shanghai）。本阶段把 P4-B 已实现的 live discovery、P2 精确 URL 读取、locator-bound verification 和 P4-A analysis／停止逻辑接入同一个非生产控制器。实现先在离线方法 patch 下完成，随后执行了一次单独授权的真实验收尝试；该尝试暴露并促成修复了 manual-live 时间边界错误。

## 交付内容

- `schemas/manual-live-research-result.schema.json` 将 P0 输出专门化为 `data_kind: live`；`ManualLiveResearchResult` 同时执行完整 P0 Schema／跨字段校验，并绑定原始 manual-live request 的 run ID、request key、window 和 scope。请求 `as_of` 是运行开始时的下界，最终 live result 的 `as_of` 推进到控制器完成时间，并与 `generated_at` 一致，使真实返回／读取时间可被如实保留。离线历史回放仍固定原始 cutoff。
- `ResearchController` 提供受控的请求、结果和 `data_kind` 扩展点；基础类仍只接受 `offline_synthetic` 并输出 `synthetic`，不会因 live 实现而放宽 P4-A 边界。
- `ManualLiveResearchController` 只接收精确的 `LiveVerifiedResearchRole` 和 `ManualLiveResearchRequest`，固定使用 `direct_verification`，并要求 discovery、source fetch、verification 与 authorization 共用同一个请求和会话。
- `scripts/run_live_poc.py` 已从单批 discovery CLI 升级为完整手动闭环：验证请求／授权／Skill 摘要，构造 live discovery 与 source verification，原子消费 authorization ID，然后运行分析、核验、停止和 P0 result 校验。
- CLI 的业务输出与审计分离。`intelligence_result` 可以包含经契约允许的精选事实、分析和 URL evidence；`role_audit`／`live_run_audit` 只含白名单元数据，不保留 prompt、网页正文、原始模型／工具输出或凭据。

## 离线端到端验收

新增 happy-path 测试使用默认 live transport 对象，但在其内部网络方法上 patch 响应，因此不会联网。测试模拟：

1. 两个香港语言覆盖任务分别返回一个带原生官方 citation 的结构化信号和一个无事件的 checked 响应。
2. citation 精确 URL 通过 P2 registry；受控 fetch 返回 HTML，正文只在内存中解析。
3. verification 响应引用真实存在的 paragraph locator，并把唯一 claim 判为支持。
4. direct evidence 与 Bing discovery 共享 origin group，claim 重新计算为 `supported`，finding 变为 `selected`。
5. 控制器以 `sufficient_evidence` 停止，输出 `data_kind: live` 且通过 P0 和 manual-live 双重结果契约。
6. 会话账本记录 3 次 Foundry 尝试（2 次 discovery、1 次 verification）和 1 次 source evidence fetch；伪装成 synthetic 或篡改 request key 的结果均被拒绝。

当前全仓库有 220 项离线测试。happy path 现在显式模拟 discovery、原文读取和控制器完成依次晚于请求 `as_of`，证明真实网络延迟不会再被误判为历史 cutoff 违规；独立回归测试同时保证离线历史来源仍不能越过原始 cutoff。它仍不证明真实 Bing 一定返回候选、真实来源一定允许自动读取，也不证明模型核验的事实质量。

## 第一次完整控制器真实尝试

用户授权请求 `manual-live-poc-20260910T064031Z` 使用 `max_queries: 3`、`max_evidence_records: 1`、零自动重试。一个 Foundry research 请求返回后，旧转换器在解析响应前以 `response_post_cutoff_evidence` 保守终止：它错误地要求 live 响应接收时间不得晚于请求 `as_of`，这在存在正常网络延迟时无法成立。

本次会话只消费 1 个 query 尝试，没有执行原文读取或 verification；原始模型／工具内容未持久化，一次性 authorization ID 已消费，未自动重试。修复后，历史／mock 路径仍执行严格 cutoff，manual-live 路径把结果 cutoff 安全推进到完成时间。另确认 discovery citation 和独立原文是两个 evidence records，因此 `max_evidence_records: 1` 即使有候选也不足以完成原文核验。

## 第二次完整控制器真实尝试

用户授权请求 `manual-live-poc-20260910T065905Z` 使用 `max_queries: 3`、`max_evidence_records: 2`、零自动重试。香港双语 discovery 共消费 2 个 Foundry 尝试，响应通过了修复后的 live 时间边界，但其中一个候选的 `publication_date` 未满足本地严格 date 格式，控制器以 `response_response_schema` 保守失败。没有原文读取或 verification，第 3 个 query 未使用；原始模型／工具内容仍未持久化，一次性 authorization ID 已消费。

随后离线增强日期兼容边界：prompt 和发给 Azure 的 Schema description 均明确日期只能是 `null` 或精确 `YYYY-MM-DD`；对可严格解析的 ISO 8601 datetime，转换器只确定性保留其日期部分并审计归一化字段数量。本地化、模糊或部分日期仍被拒绝。

## 下一次真实验收

先在仓库根目录执行一条完整准备命令：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_live_poc.py --max-queries 3 --max-evidence 2
```

`scripts/prepare_live_poc.py` 不联网，也不读取 `.env`。它默认建立香港 `regulatory-change/final_rule` 最近 7 天的 request，自动绑定当前草稿 Skill bundle 摘要，从离线 Coverage Plan 推导 P2 trusted-registry source IDs，并生成与规范 request SHA-256 精确绑定、45 分钟有效、零自动重试的一次性 authorization。两个 JSON 文件先经过正式 request、Skill、source 和 authorization policy 校验，再原子写入 `.tmp/manual-live-runs/<run_id>/`；已有 `run_id` 不会被覆盖。

成功输出含 `run_command`，形式如下；只有显式执行它才会读取 `.env`、消费 authorization 并产生真实模型／Bing 用量：

```powershell
.\.venv\Scripts\python.exe scripts\run_live_poc.py --request ".tmp\manual-live-runs\<run_id>\request.json" --authorization ".tmp\manual-live-runs\<run_id>\authorization.json" --execute-live | Tee-Object -FilePath ".tmp\manual-live-runs\<run_id>\result.json"
```

若 45 分钟内未运行、authorization 已消费或需要改变窗口／预算，应重新执行准备命令生成新 ID，不能修改或重放旧文件。可用 `--help` 查看市场、事件类型、窗口、预算、审批引用和有效期参数；输出目录被限制在仓库 `.tmp` 下。

修复后的下一次真实运行需要一份新的短时一次性授权，预算至少覆盖香港双语 discovery、一个 discovery citation、一个独立原文 evidence 和一次 verification（建议 `max_queries: 3`、`max_evidence_records: 2`、零自动重试）。成功标准不是“HTTP 200”，而是以下二者之一：

- 返回合格的范围内原生 citation，完成获准原文读取和 locator-bound verification，并产出 P0-valid `selected`／`watch` 结果；或
- 没有候选或来源不可访问时，产出 P0-valid partial result，明确记录 coverage gap 和停止原因。

这次运行会产生模型／Bing 用量；只有用户明确确认新的具体授权后才执行。若要进入生产，仍需正式审批、持久化的一次性授权账本、跨运行事件历史、幂等恢复和评测。
