# P2 来源登记册与获准内容获取

更新日期：2026-09-03（Asia/Shanghai）

## 结论

P2 已完成工程实现：项目现在有机器可校验的 Source Registry、三市场首批来源能力矩阵、独立原文读取器和 HTML／PDF／JSON／RSS 定位解析器。策略仍为拒绝优先，状态是 `engineering_complete_pending_organizational_approval`；它不是 AIA 法务、隐私、信息安全或发布方的生产批准。

来源登记在 `config/sources/source-registry.json`，结构由 `schemas/source-registry.schema.json` 约束，运行时语义规则由 `smart_nudge/sources.py` 执行。登记册当前含 9 个来源组：6 个允许低频自动访问，3 个仅允许人工查看。香港试点的 6 个主机名均已登记，但“已登记”不等于每个主机都允许自动访问。

## 原文获取边界

P1 的访问顺序继续有效：发布方 API／RSS → 发布方公开 HTML／PDF → Bing 原生引用仅作发现与旁证。`direct_official_access` 和 `bing_grounding` 是不同的来源边界；Bing 返回的回答、摘要或 URL 不能伪装成程序独立取得的原文。

可信来源查询只使用 `search_mode=trusted_registry` 的记录。开放 Web 新发现和当前尚未核清主站条款的 AIA 页面使用 `search_mode=open_discovery_only`，不能被自动提升为可信来源，也不能交给独立读取器抓取。

读取器只接受登记的 HTTPS 精确主机和路径前缀，并执行以下检查：

- 禁止 URL 凭据、非 443 端口、片段、反斜杠和点路径；人工方法不能误走自动读取。
- 每个请求与每次重定向均重新核对来源、主机、路径和 DNS；拒绝私网、回环、链路本地及其他非公网地址，禁止跨来源重定向。
- 连接超时 10 秒、读取超时 30 秒、最多 3 次重定向、解压后正文最多 10 MiB；只接受该方法登记的 MIME 类型。
- HTTP 错误和网络异常不输出响应正文；403、登录页、验证码、付费墙或其他拒绝均停止，不尝试替换身份、绕过或批量重试。
- 正文只存在于调用进程内存中。`evidence_reference()` 仅产生 URL、获取时间、方法、内容类型、哈希、留存类别和定位，不包含正文。

HTML 以 `paragraph:N` 定位，PDF 以 `page:N` 定位；JSON 使用 JSON Pointer，RSS／XML 使用顺序元素定位。定位支持核验证据，不自动授予摘录或全文留存权。

## 初始市场能力与缺口

### 香港

可用的一手机器路径包括 HKMA 官方 press-release API、SFC 公布页／文档入口，以及 DATA.GOV.HK 的政府新闻稿 feed/API。HKMA 官方文档列出了 `https://api.hkma.gov.hk/public/press-releases` 及语言参数；其条款也明确 API 属适用范围。为避免把“可分析”扩大解释为企业可任意复制，登记册仍默认只留元数据。[HKMA API 文档](https://apidocs.hkma.gov.hk/chi/documentation/press-releases/)；[HKMA 条款](https://brdr.hkma.gov.hk/eng/terms-and-conditions)。

SFC 官方提供新闻、通函、咨询文件和 RSS 入口。其免责声明允许在单一机构内部查看材料，但第三方分发和商业再利用受限，因此自动读取可用于临时核验，默认仍只留元数据；少量段落摘录也必须经过具体工作产品检查并注明来源。[SFC RSS](https://www.sfc.hk/en/RSS-Feeds)；[SFC 免责声明](https://www.sfc.hk/en/Quick-links/Others/Disclaimer)。

GovHK 文本允许非商业的个人／机构内部使用，但第三方材料除外；企业场景是否符合该条件不能由代码决定。项目因此优先使用 DATA.GOV.HK 官方 feed/API 做发现，默认元数据留存，并要求逐条确认发布部门和原文。[政府新闻稿数据集](https://data.gov.hk/en-data/dataset/hk-isd-gnmis-gnmis)；[新闻稿搜索 API 数据集](https://data.gov.hk/en-data/dataset/hk-dpo-datagovhk1-pressrelease-search)；[GovHK 版权说明](https://www.gov.hk/en/about/copyright.htm)。

保监局仍保留 P1 覆盖规则：代表性页面返回 403，发布方政策未支持当前企业用途的自动正文取得或留存，所以只能人工复核并保留元数据／原生 URL。不得使用代理、浏览器伪装或第三方转载替代目标原文。[IA 政策](https://www.ia.org.hk/en/policies/policies.html)。

FSTB 官网已登记，但没有在本轮建立可批准的直接机器路径；先从 HKSARG 官方 feed/API 发现，再人工回到 FSTB 原页核对。SFC 的稳定直连 RSS 地址也尚未核实，故没有猜测或硬编码 feed URL。

### 中国内地

金融监管总局中文官网是监管事实的一手路径，登记的范围限于公开信息栏目，不做目录枚举。官方公开指南说明主动公开范围，年度报告记录了规章、政策、统计、许可和处罚等公开内容；网站版权声明要求转载注明来源。项目仅把总局原创内容视为一手证据，转载／汇编内容只能作发现线索，中文原文优先于不完整英文页面。[公开指南](https://www.nfra.gov.cn/cn/view/pages/zhengwuxinxi/gongkaizhinan.html)；[2025 年政府信息公开年度报告](https://www.nfra.gov.cn/cn/view/pages/zhengwuxinxi/zhengfuxinxi.html?docId=1244287&signIndex=3&year=2025)；[英文入口](https://www.nfra.gov.cn/en/view/pages/index/index.html)。

本轮未建立官方 API 或稳定 RSS，`robots.txt` 也未能可靠取得。因此只批准低频、串行、精确 URL 的公开 GET；出现 403、挑战页或动态内容缺失时转人工复核，不宣称完整覆盖。

### 马来西亚

BNM OpenAPI 是当前批准的一手机器路径。官方门户说明 API 用于取得 BNM 数据集，FAQ 说明无需付费并要求 `application/vnd.BNM.API.v1+json`；数据集条款允许在署名和其他条件下复制、发布、分发和改编 BNM 标识的数据。[BNM OpenAPI](https://apikijangportal.bnm.gov.my/)；[OpenAPI FAQ](https://apikijangportal.bnm.gov.my/faq)；[BNM 数据集条款](https://www.bnm.gov.my/terms-of-use-bnm-datasets)。

该许可只覆盖 BNM 标识的数据集，不自动扩展到新闻、通告、第三方数据或网站全文。BNM 一般网站条款把材料用途限制得更窄，因此新闻／监管正文保持人工查看和元数据留存；部分 RSS 链接在评审时还出现登录／访问跳转。[BNM RSS](https://www.bnm.gov.my/rss)；[BNM 网站条款](https://www.bnm.gov.my/terms-of-use)；[BNM robots.txt](https://www.bnm.gov.my/robots.txt)。

### 公司与专业来源

AIA Group 新闻稿、业绩和年报入口已登记为公司自述候选，但本轮没有找到适用于 `www.aia.com` 主站且足以支持自动企业用途的条款，因此保持 `open_discovery_only` 和人工复核。公司自述不能独立证明重大市场事实。[AIA 新闻稿](https://www.aia.com/en/media-centre/press-releases)；[业绩与演示](https://www.aia.com/en/investor-relations/overview/results-presentations)。

World Bank Indicators API 作为三市场的专业宏观背景来源，不作为监管义务或 AIA 暴露的一手证据。API 无需密钥；数据通常适用 CC BY 4.0，但每个数据集的元数据若另有条款，以具体条款为准。[Indicators API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation)；[World Bank 数据使用条款](https://data.worldbank.org/summary-terms-of-use)。

## 留存决策

`approved_metadata_only` 允许保存发布者、标题、原生 URL、发布时间／可用时间／获取时间、取得方法、内容类型、哈希、许可类别、覆盖限制和段落／页码定位；摘录必须为 `null`。

`approved_excerpt` 当前只用于 BNM 标识的数据集和符合具体数据集许可的 World Bank 数据。即使登记为该类别，也只保存支持主张所需的最小数据或摘录，并附署名及许可说明；它不是保存整个网站、新闻库或任意全文的许可。

原始响应、页面全文和 PDF 不进入数据库、日志、测试夹具或模型训练／评测集。若以后需要全文存档、向第三方分发、建立索引或批量抓取，必须新增明确授权类别、组织审批和相应测试，不能通过修改调用参数绕过。

## 验证方法与运行命令

来源入口、条款、公开指南和代表性文档于 2026-09-03 使用发布方或政府官方页面评审。该评审确认了来源身份、公开入口和工程策略，不等同于对所有 API 做持续连通性监控，也不证明完整覆盖。网络状态和条款会变化，生产前必须按登记的 `last_verified` 重新复核。

离线检查：

```powershell
.\.venv\Scripts\python.exe scripts\validate_sources.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

`scripts/validate_sources.py` 只检查 schema、主题引用、初始市场一手路径、香港六站登记和拒绝优先规则；不联网、不产生模型或 Bing 用量。28 项 P2 测试用模拟 HTTP 验证可信／开放搜索池隔离、SSRF、重定向、超时错误、体积、类型、错误正文泄漏及各类定位解析。

## P3 前仍需保留的门槛

- AIA 法务／隐私／信息安全确认登记册和具体工作产品的企业用途；生产状态不得因测试通过自动切换。
- 为保监局、FSTB、BNM 新闻正文和 AIA 主站取得明确机器访问／留存依据，或继续保持人工路径。
- 在 P3 监管 Skill 中使用登记册的市场、语言、信任范围和缺口；不能把 `not_retrievable`、`manual_review_only` 或开放发现结果计入已完成覆盖。
- P4 再接入 `search_trusted_web`／`search_open_web` 和完整研究循环；P2 没有创建定时器、数据库、云资源或 Portal 托管 Agent。
