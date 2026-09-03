# P1：官方原文访问方案与数据留存边界

版本：1.0.0；评审日期：2026-09-03（Asia/Shanghai）。

状态：**P1 工程验收完成**。本项目已按“未明确授权即不保存正文、遇到访问限制即停止”的保守边界实现代码、配置和测试。本文件是工程控制说明，不是法律意见；投入生产前仍须由组织的法律、隐私与合规负责人批准，尤其要接受 Bing 数据处理不适用 Microsoft DPA、可能离开 Azure 合规与地理边界这一事实。

机器可执行的策略位于 `config/policies/p1-public-web-data-use.json`，由 `smart_nudge/retention.py` 校验。策略状态明确标为 `engineering_guardrail_pending_organizational_legal_approval`。

## 1. 决策摘要

- Bing Custom Search 只用于发现公开页面并生成带原生引用的回答，不是官方原文读取器，也不是原始搜索结果或网页全文接口。
- 任何拟作为事实依据的官方原文，都必须脱离 Bing 回答独立访问和核验；搜索摘要、标题或模型转述不能代替原文。
- 默认只保留来源元数据、链接、访问状态和原生引用。网页正文、搜索摘要、Bing 原始工具输出默认不保留。
- 不把 Bing 输出用于模型训练、评估或改进，不建立搜索数据库、链接索引，不把引用 URL 当作批量抓取种子。
- 遇到 `robots.txt` 禁止、HTTP 401/403/429、登录、付费墙、CAPTCHA 或其他访问控制时立即停止，不规避限制；改为人工核验、获批接口或同一发布方的其他一手资料。

## 2. 官方原文访问顺序

每条候选材料按以下顺序处理：

1. 查询只包含已经公开的主题，不发送凭据、内部资料、机密信息、客户或员工标识，以及并非有意公开的个人信息。
2. 从 Bing 响应保留原生引用对象的原样字段，用于定位候选官方页面；不得根据模型正文自行补造引用。
3. 独立访问来源，优先顺序为：发布方公开 API、RSS 或 feed；发布方公开 HTML/PDF；人工浏览器核验；同一发布方的其他一手出版物。
4. 自动访问被拒绝时，记录实际状态和 HTTP/访问限制，不重试绕过，不使用搜索摘要填补正文。
5. 核验结果使用下列状态：
   - `citation_only` / `pending_manual_review`：仅有引用线索，尚未读到原文；
   - `verified_direct`：通过获准的自动路径直接读取并核对原文；
   - `verified_manual`：由人员在可正常使用的浏览器中核对原文；
   - `corroborated_alternate_first_party`：同一发布方的另一份材料支持一般事实，但不证明目标页面的确切标题、日期或正文。

不得把“搜索不到”写成“事件不存在”，也不得把同一机构的另一份材料误写成已核验目标原文。

## 3. 香港保险业监管局试点结论

Bing 原生引用指向保险业监管局新闻稿：

`https://www.ia.org.hk/en/infocenter/press_releases/20240701.html`

本次独立 Web 读取返回 HTTP 403，因而没有取得新闻稿正文。桌面自动化环境当时没有可用浏览器，本机 `curl` 又受代理/Windows TLS 凭据问题影响；这些结果不能泛化为普通用户浏览器一定无法访问，只能证明当前自动路径未获原文。

保险业监管局网站政策允许满足条件的超链接，但要求链接到相关页面、清楚注明来源、不以框架展示；其版权声明同时规定，未经事先书面同意不得复制、改编、分发或传播网站材料。因此当前对 `ia.org.hk` 采用更严格的发布方覆盖规则：

- 可以保存清楚标注来源的链接和必要元数据；
- 自动正文访问保持禁用，直至取得明确许可或验证出发布方允许的公开路径；
- 不保存新闻稿摘要、正文摘录或全文；摘录或全文需要书面许可或其他明确授权；
- 当前页面被拒绝时，只能安排人工核验或查找同一发布方的另一份一手材料。

保险业监管局 2024–25 年报 PDF 可公开访问，其中支持“风险为本资本制度的量化支柱于 2024 年 7 月 1 日实施”这一一般事实。它只能记为 `corroborated_alternate_first_party`，不能证明上述新闻稿的确切标题或全文。

## 4. 数据留存边界

### 4.1 输入

只允许公开主题查询。下列内容不得有意发送到 Bing：密码、密钥或 token；内部或机密内容；客户/员工标识；并非有意公开的个人信息。原因是 Bing Grounding 适用独立条款和 Microsoft Privacy Statement，不属于 Azure 的常规 DPA/合规地理边界。

### 4.2 Bing 数据

- 原始工具输出：Microsoft 不向开发者或最终用户暴露；本系统也不得尝试获取或持久化。
- 模型生成的搜索回答：CLI 默认不打印、不写文件。只有在版权允许范围内、经组织批准并整合进本方工作成果时才可保存，同时须把 Bing 返回的引用以原样形式放在对应内容附近。
- 原生引用：可以作为工作成果的一部分原样保留，不改写、不隐藏，并保留其与对应内容的邻接关系。
- 禁止用途：模型训练、评估或改进；独立搜索服务；搜索数据库；链接索引；批量抓取种子；替代原网页的内容集合。

`scripts/smoke_foundry.py --check search` 现在只输出安全审计记录，不输出 Bing 生成的回答文本；成功和失败路径均执行相同脱敏。允许的字段包括请求/响应 ID、状态、安全错误说明、用量、输出项类型、搜索调用次数、原生引用、来源范围检查和事实核验状态；记录同时明确 `output_text_retained=false`、`raw_response_retained=false` 与 `raw_tool_output_retained=false`。

### 4.3 独立访问的官方资料

默认只保留下列元数据：规范化 URL、标题、发布方、发布日期、访问时间、访问方法、HTTP/访问状态、内容类型、核验状态和必要的校验标识。默认不保存网页正文。

只有来源的许可、许可证或组织批准明确允许时，才可保存必要摘录或全文，并须在证据记录中声明实际权限类别。`retention=approved_metadata_only` 时，正文摘录必须为 `null`；这一约束已由现有 P0 schema 校验器执行。

### 4.4 本方分析和最终报告

本方独立分析与最终工作成果可在明确启用持久化后，按组织的记录保留计划保存；必须与来源正文区分，并保留支撑主张的原生引用。当前应用尚未实现数据库，默认持久化模式为 `explicit_only`，不会因为一次 smoke probe 自动形成历史档案。

## 5. P1 验收边界

P1 可以在工程层面关闭，因为：

- 直接模型调用、指定 Bing configuration、工具执行和原生引用解析已经实测通过；
- 不支持或未获批准的全文读取、批量抓取、索引、训练/评估和原始输出留存路径已明确禁用；
- 搜索 smoke 输出已经缩减为符合白名单的审计记录；
- 策略由代码在运行时校验，并有离线回归测试防止放宽关键边界；
- IA 的 403 与版权/链接边界已作为发布方覆盖规则记录，不冒充原文核验成功。

以下仍是生产门槛，而不是未完成的 P1 代码：组织法律、隐私与合规批准；业务记录保留期限；获准保存的工作成果存储位置和访问控制。

P2 将建立六个试点来源的来源登记册和连接器能力矩阵，逐个记录允许的访问方法、robots/条款、正文权限、失败回退与人工复核路径。除 IA 外，其余发布方尚未完成逐站政策评审，不能从本文件推定为已批准。

## 6. 权威依据

- [Microsoft Foundry：Bing 工具、引用、数据流与原始输出限制](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)
- [Microsoft：Grounding with Bing Search 企业条款](https://www.microsoft.com/en-us/bing/apis/grounding-legal-enterprise)
- [Microsoft Licensing FAQ：Bing Grounding 的 DPA 与地理边界](https://www.microsoft.com/licensing/faqs/123)
- [Microsoft Foundry：Agent Service 数据隐私与外部工具](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/agents/data-privacy-security)
- [保险业监管局网站政策](https://www.ia.org.hk/en/policies/policies.html)
- [保险业监管局免责声明](https://www.ia.org.hk/en/disclaimer/disclaimer.html)
- [保险业监管局 2024–25 年报 PDF](https://www.ia.org.hk/en/infocenter/files/Insurance_Authority-AR24_25_eng.pdf)
