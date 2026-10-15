# Asia Executive News：细分搜索实施计划与单次运行成本预测

更新时间：2026-10-15（Asia/Shanghai）

## 1. 文档状态与目标

本文记录 Asia Executive News 工作流的下一阶段设计。目标是在不提高单次搜索最多返回 10 条候选、也不逐站穷举全部新闻的前提下，通过缩小每个 Custom Bing configuration 的来源范围并增加搜索调用次数，提高 AIA、监管和主要竞争者重要事件的召回率。

本文主要记录最终的 25-configuration / 44-query 目标设计。2026-10-14 已先落地一个低风险的中间阶段：

- 当前实现使用 4 个 Custom Bing configurations、7 次搜索和最多 1 次总结请求。Rule Pack v1.5.7 以运行时香港系统日期为共同基准，使用滚动 14 天搜索回看期和滚动 7 天 brief 入选期，不再依赖日历周边界；两个窗口分别写入审计产物。每条 brief 新闻使用更完整的事件摘要和 2–4 个具体细节 bullet，时间事实并入这些内容，不单设 timing/action，也不给 AIA 提行动建议。
- 两个 AIA query 采用 recall-first 发现：使用完整市场名称以及中性的官方文档形态和事件类别召回潜在相关候选，重要性统一留到后续评估阶段判断。监管和竞争者 query 继续避免写入反馈历史、具体案例、命名监管机构或案例衍生的优先类别。最终 brief 必须包含所有 High/Medium 且没有最高条数上限；不足 10 条时用最高价值的 eligible Low 补至 10 条或补完为止，全部 eligible 事件不足 10 条时允许最终少于 10 条。
- 新增 `asia-news-aia-primary`，把两个 AIA 专题从共享的 corporate configuration 中独立出来；同时增加一个只覆盖六家主要竞争者的官方来源 query。
- 当前三个监管 query 虽共享 `asia-news-regulatory-official` 云端 configuration，但分别声明本地来源市场组。运行时会按查询缩小允许域名，并在候选准入时再次检查来源市场，避免 India/regional 查询接纳纯香港来源等跨组泄漏。此项不要求修改云端 configuration。
- 最终 brief 的 `topic`、`signal_type` 和 `content_type` 由规范化源事件确定；总结模型的冲突分类会被本地替换并留下 warning。任一成功查询返回 `partial` 或 `unavailable` coverage 时，search 和 brief 均标记为 partial，并在 JSON 与 Markdown 中显示 checked/partial/unavailable/failed 计数。
- 多次端到端运行已完成 7/7 搜索和总结，因此云端已删除 `asia-news-corporate-exchange` 中与新 AIA 配置重复的 AIA、Amplify Health 和直接 HKEX news 域名。
- `asia-news-aia-primary` 现在独占 AIA 官方来源、`www.amplifyhealth.com` 和 `www.hkexnews.hk` / `www1.hkexnews.hk` / `www2.hkexnews.hk`；`asia-news-corporate-exchange` 保留六家主要竞争者、`www.hkex.com.hk`、其他交易所和保险协会来源。当前云端分组已与本地 Rule Pack 一致。
- v1.5.0 真实运行 `poc-20261015T020451Z-f004a9` 完成 7/7 搜索，得到 16 条去重候选、12 条时间窗内候选和 8 条最终事件，使用 170,490 tokens。两个 AIA query 各只接纳 1 条且是同一证券事件，说明过于抽象的 materiality 搜索词压低了 AIA 召回；这是 v1.5.1 的直接比较基线。
- v1.5.1 真实运行 `poc-20261015T022219Z-f64a51` 完成 7/7 搜索和总结，得到 25 条 query-level 候选、23 条去重候选、19 条时间窗内候选、14 个评估事件和 11 条最终事件，使用 222,105 tokens。两个 AIA query 分别接纳 3 条和 2 条，去重后得到 4 条直接 AIA 搜索结果，最终 brief 包含 3 个 AIA 事件，说明 recall-first 调整改善了 AIA 召回。
- v1.5.2 真实运行 `poc-20261015T025605Z-d5f4c6` 完成 7/7 搜索和总结：14 天搜索接纳 25 条 query-level 候选并得到 24 条去重候选，本周窗口在本地筛出 3 个评估事件，最终保留 2 条 Medium 事件并排除 1 条 Low 事件，共使用 222,777 tokens。结果验证了扩大召回窗口、收紧 brief 窗口的两层日期策略。
- v1.5.3 真实运行 `poc-20261015T030758Z-60d217` 完成 7/7 搜索和总结：14 天搜索接纳 26 条 query-level 候选并得到 24 条去重候选，滚动 7 天窗口筛出 10 条来源并合并为 8 个评估事件，最终保留 2 条 High 和 3 条 Medium、排除 3 条 Low，共使用 254,211 tokens。产物正确记录 10 月 1–15 日搜索窗口和 10 月 8–15 日 brief 窗口。
- v1.5.7 真实运行 `poc-20261015T074602Z-9e446d` 完成 7/7 搜索和总结，用时约 4 分 24 秒、共使用 235,503 tokens。运行得到 24 条去重候选、12 条滚动 7 天 eligible 来源和 11 个评估事件；最终 brief 包含 3 条 High、6 条 Medium 和 1 条补位 Low。六个 query 为 checked，`aia-corporate-markets` 为 partial，因此 search 与 brief 正确标记为 partial。India/regional query 没有接纳香港或 Greater China 新闻，最终分类也保持源事件字段，验证了 v1.5.7 的三项确定性修复。
- 目标实现使用 25 个 Custom Bing configurations、44 次搜索，并把分析改为分组评估和最终合并两个层级。
- 云端 configuration 由用户管理；代码不得自行创建或修改 Azure 资源。
- 实施和离线验证不授权真实模型或 Bing 调用。每次 live run 仍需用户明确授权。
- 继续保留原生 URL citation，并继续声明内容未经过独立原文抓取或核验。

## 2. 为什么采用“25 个配置、44 次搜索”

当前一个 configuration 包含大量网站，一个宽泛 query 又同时覆盖多个市场或主题。即使增加网站，搜索模型仍会在有限结果和上下文内优先选择少量高相关来源，新增网站不会线性增加候选数。

目标设计把两个概念分开：

- Custom Bing configuration 决定允许检索的来源边界。
- Query 决定在该来源边界内寻找什么事件。

将来源按业务对象和市场拆小，可以减少大型网站、热门市场和重复内容对其他来源的挤压；在每个小范围内再运行一到两个明确主题的 query，可以增加长尾但重要事件进入候选集的机会。

本方案仍不追求逐网站全量覆盖：

- 每次搜索最多接受 10 条候选。
- 不单独抓取或遍历网站栏目、RSS、sitemap 或页面正文。
- 不为每个域名单独运行 query。
- 理论上最多获得 440 条搜索候选，实际会因空结果、重复 URL、同一事件多源报道、日期过滤和引用门槛明显少于该上限。

## 3. 目标搜索矩阵

### 3.1 AIA 官方来源：7 个 configurations，14 次搜索

每个 configuration 执行两个主题：

1. `corporate-market`: 使用官方新闻、新闻稿、公告和披露等文档形态，搜索业绩、资本或融资、交易、治理、组织、领导层、市场进入或退出以及重大运营变化。
2. `business-publications-initiatives`: 使用官方新闻稿、报告、出版物和公告等文档形态，搜索产品、服务、客户主张、分销、合作、技术、运营以及面向行业的项目。

两个主题采用 recall-first 方式返回潜在相关并带引用的候选，仅用于覆盖不同的信息形态，不在搜索阶段要求模型判断 executive materiality，也不为任何子类型设置自动优先级、配额或必选项。所有事件统一在后续阶段按照实质内容和潜在影响判断。

拟议 configurations：

1. `asia-news-aia-group-capital`
   - `www.aia.com`
   - `aia.gcs-web.com`
   - 与 AIA 披露有关的已验证 HKEX 官方域名
2. `asia-news-aia-greater-china`
   - `www.aia.com.hk`
   - `www.aia.com.cn`
   - `www.aia.com.tw`
   - 澳门来源只有在确认官方域名并加入本地 allowlist 后才加入
3. `asia-news-aia-singapore-malaysia-brunei`
   - `www.aia.com.sg`
   - `www.aia.com.my`
   - `www.aia.com.bn`
4. `asia-news-aia-thailand-vietnam-cambodia-myanmar`
   - `www.aia.co.th`
   - `www.aia.com.vn`
   - `www.aia.com.kh`
   - `www.aia.com.mm`
5. `asia-news-aia-indonesia-philippines`
   - `www.aia-financial.co.id`
   - `www.aia.com.ph`
6. `asia-news-aia-australia-new-zealand`
   - `www.aia.com.au`
   - `www.aia.co.nz`
7. `asia-news-aia-india-korea-srilanka`
   - `www.tataaia.com`
   - `www.aia.co.kr`
   - `www.aialife.com.lk`
   - `www.amplifyhealth.com`

`www.amplifyhealth.com` 在这里仅作为一个已知的 AIA 关联健康平台来源，与其他允许来源适用相同的检索和重要性规则，不保证其内容被返回或收录。

这 14 次搜索全部是 AIA 专题，但仍以重要性而非内容类型或名称决定是否进入 brief。普通宣传、低信息量活动和通用奖项继续判为 Low；有明确规模、研究结论、战略承诺、管理层意义或行业影响的事件可判为 Medium 或 High。

### 3.2 监管官方来源：9 个 configurations，18 次搜索

每个市场执行两个泛化发现 query，而不按用户反馈中的政策细节拆主题：

1. `regulatory-material-developments`: 搜索对保险机构具有潜在市场或行业影响的拟议、正式或新近生效的要求、咨询、监管预期、执法发展和实施变化。
2. `regulatory-material-developments-local`: 使用市场适用的本地语言或等价的第二种宽口径表达执行同一发现任务，不增加具体政策关键词。

拟议 configurations：

1. `asia-news-reg-hong-kong`
2. `asia-news-reg-mainland-china`
3. `asia-news-reg-singapore`
4. `asia-news-reg-malaysia`
5. `asia-news-reg-thailand`
6. `asia-news-reg-taiwan`
7. `asia-news-reg-india`
8. `asia-news-reg-philippines`
9. `asia-news-reg-asia-standards`

前八个 configuration 使用当前 Rule Pack 中相应市场的监管机构、中央银行、政府、公报和数据保护机构域名。`asia-news-reg-asia-standards` 使用 IAIS、IMF、ADB、BIS、FSB、FATF 和 IFRS 等区域或国际标准来源。

监管搜索和分析的责任分开：

- 搜索 query 只表达市场、日期、保险监管范围和广义的行业影响，不写入反馈案例、命名机构或董事独立性、fact finding、可负担性等具体政策机制。
- 搜索阶段不预先排除个案执法。分析阶段再将缺乏行业先例或系统性意义的个案判为 Low；如具有更广泛影响，则仍可按证据评估。
- 所有再保险公司和再保险市场新闻继续排除。

### 3.3 主要竞争者官方来源：6 个 configurations，6 次搜索

只覆盖当前确认的六家主要竞争者，不再保留“本地龙头”名单：

1. `asia-news-competitor-axa`
2. `asia-news-competitor-manulife`
3. `asia-news-competitor-pingan`
4. `asia-news-competitor-fwd`
5. `asia-news-competitor-sunlife`
6. `asia-news-competitor-prudential`

每个 configuration 执行一个 `material-moves` query，统一搜索对亚洲保险业务具有潜在战略、财务、组织、运营或市场意义的重大变化，不把某一类交易、产品或人事事件固定为优先类别。

来源应限于经过验证的集团、投资者关系、当地官方站点和适用的交易所披露域名。新增域名必须先验证确为官方来源，再同时加入云端 configuration 和本地 Rule Pack allowlist。

以下内容不进入竞争者搜索范围：

- 六家名单以外的公司，包括本地保险公司或所谓本地龙头。
- 再保险公司及再保险市场动态。
- 普通任命、常规推广、通用奖项和缺乏结构性意义的产品新闻。

### 3.4 权威媒体补充来源：3 个 configurations，6 次搜索

媒体用于发现官方来源可能遗漏的重大事件和外部行业影响，不替代官方证据，也不自动提高事件重要性。

拟议 configurations：

1. `asia-news-media-greater-china`
   - 明报、东方日报、RTHK、巴士的报、ETNet、HK01、新华社、SCMP
2. `asia-news-media-asia-insurance`
   - InsuranceAsia News、Asia Insurance Review、The Business Times、Channel NewsAsia、Nikkei Asia
3. `asia-news-media-global-financial`
   - Reuters、Bloomberg、Financial Times、InsuranceERM

每个 configuration 执行两个主题：

1. `aia-material`: 只搜索 AIA 及其业务、研究、健康生态和可验证行业影响。
2. `competitor-industry-material`: 搜索六家主要竞争者及具有亚洲保险行业影响的重大监管或结构性变化。

## 4. Query 生成方式

Rule Pack 不需要手写 44 段完全重复的长提示，而应保存可审计的 query group 和少量模板，再在 dry run 中展开成 44 个确定性 query。

每个展开后的 query 必须包含：

- 唯一 `query_id`。
- 对应的 `configuration_id` 和云端 `instance_name`。
- 市场或公司范围。
- 明确的主题关键词。
- `{date_from}` 和 `{date_to}`。
- 排除再保险、普通推广和低影响内容的规则。
- 对监管 query，排除没有行业先例的个别从业人员执法。
- 对竞争者 query，只允许 AXA、Manulife、Ping An、FWD、Sun Life 和 Prudential plc；使用版本化的规范公司名和精确别名校验，Prudential Financial, Inc. 及其子公司不属于该竞争者范围。

建议的 query ID 规则：

- AIA：`<configuration-id>-corporate-market` 和 `<configuration-id>-business-publications-initiatives`
- 监管：`<configuration-id>-regulatory-material-developments` 和 `<configuration-id>-regulatory-material-developments-local`
- 竞争者：`<configuration-id>-material-moves`
- 媒体：`<configuration-id>-aia-material` 和 `<configuration-id>-competitor-industry-material`

`scripts/run_poc.py` 的 dry run 应输出完整的 44-query 执行计划，便于在任何 live run 前检查配置名、域名、日期范围和调用预算。

## 5. 云端具体操作

云端操作由用户在现有 Grounding with Bing Custom Search 资源中完成：

1. 保留现有 Azure Foundry project、GPT-5-mini deployment 和 Bing connection，不创建新的 Foundry project 或 Portal-hosted Agent ID。
2. 按第 3 节创建并发布 25 个 Custom Bing configurations。
3. 每个 configuration 只加入对应分组的官方或媒体域名，不混入其他组来源。
4. 记录每个 configuration 的准确 instance name；名称必须与 Rule Pack 完全一致。
5. 确认所有 configuration 已发布且现有 Foundry connection 有权访问。
6. 不把密钥、token、connection secret 或 Azure 登录缓存写入 Rule Pack、文档或运行产物。

为了能够安全回退，25-configuration 目标仍应使用新的 instance name，而不是原地覆盖当前四个 configuration。新流程验证完成前，当前四个配置作为已验证的回退基线保留；不应为了建立 25 个新配置而提前删除它们。

如果 Azure 对 configuration 数量或命名存在租户级限制，应先记录实际限制，再合并相邻的小组；不能静默删除市场或回到一个超大 configuration。

## 6. 本地代码实施步骤

### 阶段 A：先增加计量能力

在扩大调用前先修改 Foundry adapter 和运行产物：

1. 从每个 Responses API 返回中读取并保存 `tool_usage.web_search.num_requests`。
2. 保存每次调用的开始时间、结束时间和 wall-clock duration。
3. 分别累计搜索、分组评估和最终汇总的 input、output 和 total tokens。
4. 保存 attempted、succeeded、failed、timeout 的调用数量。
5. 保存 raw candidates、citation-admitted、URL-deduplicated、in-window、evaluated、High、Medium 和最终事件数量。
6. 可根据显式配置的价格参数生成估算费用，但必须标记为 estimate，不能称为 Azure invoice 金额。

敏感内容仍不得保存：原始凭据、完整原始模型响应、Azure 登录缓存和未脱敏的诊断信息。

### 阶段 B：扩展 Rule Pack 和 schema

1. 将 `config/rules/asia-executive-news.json` 更新为新的 25-configuration/44-query 设计，并提升版本号。
2. 为重复模板引入 query group 或等价的结构化展开方式，避免 44 个 query 之间发生静默规则漂移。
3. 更新 `schemas/poc-rule.schema.json` 和验证器，使其检查：
   - configuration ID、instance name 和 query ID 唯一；
   - 每个 query 引用已定义的 configuration；
   - 预期配置数为 25、展开调用数为 44；
   - 所有来源 host 均存在于本地 allowlist；
   - competitor 值只能来自六家名单；
   - 没有 reinsurance source/category；
   - 每个 AIA 和监管 configuration 的两个预期主题都存在。
4. dry run 必须只生成计划，不发送外部请求。

### 阶段 C：执行 44 次搜索

第一版保持顺序执行，沿用当前零自动重试行为，避免并发后难以解释 token、限额和失败归属：

1. 按 AIA、监管、竞争者、媒体的稳定顺序执行 query。
2. 每个 query 最多接受 10 条候选。
3. 只接受 Responses API 返回的原生、范围内 URL citation。
4. 对失败或 timeout 记录 query 级错误，但继续执行剩余独立 query。
5. 完成所有搜索后先做 canonical URL deduplication。
6. 在进入模型分析前执行本地日期分类；只有 `in_window` 候选可以进入最终 brief。
7. `all-news.json` 保留全部规范化候选及其日期状态和查询来源，便于审计覆盖情况。

第一版不并发。获得一到两次真实 TPM、延迟和计费数据后，才考虑以小并发度运行不同 configuration；并发只能缩短 wall time，通常不会降低 token 或 Bing 费用。

### 阶段 D：分组重要性评估

单次总结不再直接接收全部候选。先将所有 `in_window` 候选按每批约 30–40 条确定性分组：

1. URL 去重在分组前完成，确保同一候选不会被多个批次重复评估。
2. 每个候选分配稳定 `candidate_id`。
3. 每个批次必须为每个 candidate 恰好输出一条紧凑 evaluation：
   - `candidate_id`
   - `attention_level`: High、Medium 或 Low
   - `include_in_final`
   - `decision_reason`
   - `event_key`，用于识别多来源报道的同一事件
   - `topic` 和 `signal_type`
4. 批次阶段只做重要性判断和事件归一，不撰写完整 brief，以控制输出 token。
5. 本地校验必须证明每个日期合格候选被评估恰好一次；缺失、重复或未知 candidate ID 使该批次失败。
6. Low 候选的 evaluation 留在审计产物中；除再保险和名单外竞争者等硬排除项外，Low 可在 High/Medium 少于 10 条时参与最终补位。

分组优先采用稳定输入顺序或稳定 hash，而不是让模型自行决定批次。这样相同输入可以重现相同分组，便于比较不同运行。

### 阶段 E：最终事件合并与 brief 写作

最终请求接收所有 High/Medium，以及用于比较补位价值的 eligible Low evaluations 及其 grounded notes：

1. 按 `event_key` 合并同一事件的多来源报道，同时保留所有合格 native citations。
2. 再次检查竞争者名单、再保险排除和日期资格。
3. 不设置最终 10 条或 6–8 条上限；所有 High/Medium 事件都进入 brief，即使总数超过 10 条也不得截断。
4. 10 条是软目标而不是最低保证。High/Medium 少于 10 条时，按价值选择 eligible Low 补到 10 条或直到 Low 用完；全部 eligible 事件不足 10 条时全部进入并允许少于 10 条，不虚构或拆分事件凑数，也不把 Low 改标为 Medium。
5. 每个最终事件应包括：
   - 简明标题；
   - 用两至四句话说明发生了什么、变化实质、范围及受影响对象；
   - 两至四个不重复的具体细节，包括有来源支持的机制、产品或流程、交易条款、实施状态以及日期或 deadline；
   - 对 AIA 或行业的潜在影响；
   - native URL citation。
6. 不单设 timing/action 字段，不建议 AIA 应该采取什么行动；来源明确规定的义务只作为新闻事实陈述。
7. AIA 官方或赞助来源可以支持重要 AIA 事件，但不能表述为独立第三方确认。
8. 输出继续包含“未独立抓取或核验原文”的限制说明。

如果 High/Medium 事件本身超过单次最终上下文安全范围，应按 `event_key` 再做确定性写作分批，随后执行只负责排序和去重的轻量合并；不得因为上下文不足静默丢弃重要事件。

## 7. 产物和审计建议

目标运行目录继续位于 `.tmp/poc-runs/<run_id>/`，建议包含：

- `search-results.json`：44 个 query 的状态、引用诊断、token、duration 和 `num_requests`。
- `all-news.json`：规范化、去重前后和日期分类后的候选。
- `evaluations.json`：每个候选恰好一次的重要性判断及 event key。
- `brief.json`：最终结构化事件、引用和阶段汇总。
- `brief.md`：面向 AIA Group CEO 的英文 briefing。
- `run-metrics.json`：各阶段调用数、tokens、Bing transactions、耗时和估算费用。

`run-metrics.json` 中的价格参数应记录为本次估算快照，例如：

- `model_input_usd_per_million`
- `model_output_usd_per_million`
- `bing_custom_search_usd_per_1000`
- `pricing_source`
- `pricing_checked_at`
- `estimated_cost_usd`

价格参数不应硬编码为永久事实；Azure 区域、币种和企业协议可能改变实际价格。

## 8. 离线测试与验收标准

实现后、任何 live run 前执行：

```powershell
.\.venv\Scripts\python.exe scripts\validate_poc.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

至少新增以下测试：

- 25 个 configuration 和 44 个展开 query 的数量、ID 和映射测试。
- 云端 instance name 重复、未知 configuration、空 source group 的拒绝测试。
- competitor allowlist、名单外公司排除和 reinsurance 全局排除测试。
- 每个候选恰好评估一次的 completeness 测试。
- High/Medium 超过 10 条时全部进入且不截断的测试。
- High/Medium 少于 10 条时以 eligible Low 恰好补到 10 条，以及全部 eligible 事件不足 10 条时全部进入且允许少于 10 条的测试。
- 再保险和名单外竞争者等硬排除 Low 不得用于补位的测试。
- 跨批次相同 `event_key` 的合并测试。
- `tool_usage.web_search.num_requests` 缺失、为零和正常返回的诊断测试。
- 搜索、评估、汇总 token 和 duration 的聚合测试。
- 费用公式测试，确保未知价格或未知 `num_requests` 时输出 `unknown`，而不是伪造为零。
- 部分 query timeout 时其余 query 继续、最终状态为 `partial` 的测试。
- dry run 零网络调用测试。

目标 live 验收标准：

- 44 个计划 query 均有独立状态，未发生未记录的调用。
- 所有接受候选都具有 native in-scope citation。
- 每个 `in_window` 候选被评估恰好一次。
- 每个 High/Medium 事件在最终 brief 中恰好出现一次；Low 补位数量符合 10 条软目标和候选耗尽规则。
- 没有名单外公司或再保险内容。
- AIA、监管和六家竞争者的覆盖可按 configuration/query 追溯。
- 实际 Bing 计费请求数可由 `tool_usage.web_search.num_requests` 汇总，而不是由 action 数猜测。

## 9. 单次运行 Token、费用和耗时预测

### 9.1 已知真实基线

2026-10-14 清理云端重复站点后的运行 `poc-20261014T090848Z-8e84b6` 是当前基线：

- 7 次搜索和 1 次总结全部成功。
- 搜索阶段：175,971 input、10,509 output，合计 186,480 tokens。
- 总结阶段：5,755 input、4,207 output，合计 9,962 tokens。
- 整体：181,726 input、14,716 output，合计 196,442 tokens。
- 用时约 261 秒，即约 4 分 21 秒。
- URL 去重后 23 条候选，窗口内 20 条，19 个事件完成评估，16 个 High/Medium 事件进入 brief。
- 7 个搜索请求产生 25 个 `search` 和 7 个 `open_page` action，共 32 个 Web Search actions。Action 数不是可计费请求数；产物仍未保存 `tool_usage.web_search.num_requests`，因此不能精确还原 Bing 账单。
- 同日另一次 7/7 完整运行使用 212,429 tokens；一次 6/7 运行因单个 AIA query 超时使用 213,219 个已知 tokens。因此单次基线具有明显波动，不应只用一次最低值外推。

### 9.2 搜索阶段外推

按最新搜索阶段的平均 token 将 7 次放大到 44 次：

- Input：约 1,106,104 tokens。
- Output：约 66,057 tokens。
- 合计：约 1,172,160 tokens。
- 如保守地按整个 7-search-plus-summary 运行的平均 wall time 线性放大，约为 1,640 秒，即 27.3 分钟；因该基线包含一次总结，实际 44-search 阶段可能略短。规划时仍应使用约 24–28 分钟的搜索阶段范围。

细分 configuration 可能减少单次返回的网页上下文，但更明确的 query 也可能让模型执行多个内部搜索动作，因此不假设单次 token 一定下降。

合理的搜索阶段范围是约 90 万–180 万 tokens；如果大量调用接近本次最高的 50,524 tokens，压力场景可能超过 220 万 tokens。

### 9.3 两级分析阶段外推

假设 URL 去重后产生约 100–250 条候选：

- 约 4–8 次分组 evaluation。
- 1 次最终合并与写作。
- 额外约 15 万–40 万 tokens。
- 额外约 4–8 分钟。

因此一次完整 end-to-end 测试的中心预测为：

- Token：约 130 万–160 万。
- Wall time：约 30–40 分钟。
- 安全压力预算：230 万 tokens、60 分钟。

该预测假定顺序执行、零自动重试。并发可以缩短 wall time，但可能触发 deployment TPM/RPM 限额，也不会自然减少费用。

### 9.4 模型费用

通用计算公式：

```text
model_cost = input_tokens / 1,000,000 * input_rate
           + output_tokens / 1,000,000 * output_rate
```

以 2026-10-14 OpenAI 公布的 GPT-5-mini 标准价格作为代理值：input US$0.25/百万 tokens、output US$2.00/百万 tokens。Azure 的实际区域、币种和企业协议价格可能不同，最终应以 Azure 账单或已登录的 Pricing Calculator 为准。

按该代理价格：

- 44 次搜索的直接外推模型费约 US$0.42。
- 包含两级分析后的中心模型费约 US$0.55–0.80。
- 高 token 压力场景建议按不低于 US$1.20 预留。

模型参考价格：https://developers.openai.com/api/docs/models/gpt-5-mini

### 9.5 Bing Custom Search 费用

Microsoft 说明 Web Search 费用以响应中的 `tool_usage.web_search.num_requests` 为计费请求数，不能通过统计 `search` action 或 `web_search_call` 输出项准确推导。

计费公式：

```text
bing_cost = tool_usage.web_search.num_requests / 1,000
          * bing_custom_search_rate_per_1,000
```

当前 7 次搜索包含 32 个 Web Search actions（25 `search` + 7 `open_page`）。虽然 action 不是计费数，但若仅用它做容量代理并按比例放大，44 次模型调用约对应 201 个 Web Search actions。

规划时可以先假设约 90–220 个可计费请求。如果用户 Azure 订阅显示的价格为 US$35/1,000 transactions，则：

- 90 个请求约 US$3.15。
- 201 个请求约 US$7.04。
- 220 个请求约 US$7.70。

US$35 只是预算示例，不应写死为实际价格。公开 Azure 页面会按区域、币种和协议显示不同价格，当前项目必须在保存 `num_requests` 后结合用户订阅价格计算。

Microsoft billing 说明：https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search#web-search-usage-and-billing

Azure Foundry Agent Service pricing：https://azure.microsoft.com/en-us/pricing/details/foundry-agent-service/

### 9.6 单次测试的推荐预算

在拿到第一轮真实 `num_requests` 前，建议按以下口径安排一次完整测试：

- 最可能：130 万–160 万 tokens、US$6–9、30–40 分钟。
- 搜索返回偏少：约 100 万 tokens、US$3–5、约 25–30 分钟。
- 安全上限：230 万 tokens、US$15、60 分钟。

费用区间主要由 Bing transactions 决定，而不是 GPT-5-mini token。第一次扩大测试完成后，应使用实际 `num_requests`、token 和 duration 更新本文预测。

## 10. 推荐实施顺序

当前 4-configuration / 7-search 中间阶段已完成：本地路由、主体／实体准入、云端去重和清理后的端到端运行均已验证。以下步骤只针对未来 25-configuration / 44-query 扩展，不需要重做当前 AIA 拆分：

1. 先实现 `num_requests`、token 和 duration 遥测及其离线测试。
2. 再实现 Rule Pack query groups、25 个配置映射和 44-query dry run。
3. 实现分组 evaluation、完整性校验和最终 event merge。
4. 运行全部离线验证，人工检查 dry-run 执行计划。
5. 用户在云端创建并发布 25 个 configurations，将准确 instance name 回填 Rule Pack。
6. 先选择每类一个 configuration 做受控 smoke test，验证名称、citation、`num_requests` 和费用记录。
7. 经用户再次明确授权后执行一次完整 44-search end-to-end live run。
8. 用真实运行指标替换成本假设，再决定是否引入有限并发或进一步细分来源。

## 11. 明确不在本阶段做的事项

- 不提高单次最多 10 条候选的上限。
- 不逐网站穷举全部新闻。
- 不抓取页面正文、RSS 或 sitemap。
- 不创建自动重试。
- 不实现定时任务、通知、数据库、前端或生产治理。
- 不自动创建或修改 Azure 资源。
- 不扩展竞争者名单，不恢复本地龙头名单。
- 不纳入任何再保险内容。
