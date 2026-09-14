# Smart Nudge

Smart Nudge 是一个面向 AIA Group CEO 的公开 Web 情报演示 PoC。它只展示两个核心能力：

1. 按版本化 Rule Pack 使用 Foundry Responses API 的 `web_search` 工具，并绑定现有 Bing Custom Search configuration 来搜索香港、澳门或中国大陆官方站点。
2. 按同一 Rule Pack 将带原生 URL 引用的搜索内容整理成英文管理层简报。

当前默认 Rule Pack 搜索最近 30 天的香港保险和金融监管动态，执行一次英文搜索、一次繁体中文搜索和最多一次英文摘要，最终选出不超过 5 条内容。项目不再包含 Verify Agent、独立网页抓取、claim/evidence 状态机或多轮补搜。

每条简报内容同时显示简短的 `Executive Attention Level`（High／Medium／Low）、监管信号类型和一句评级理由。该等级用于帮助管理层排序关注，不代表已经确认的法律适用性、损失概率或正式企业风险评级。

## Quick start

Python 3.11+：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts\validate_poc.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

先执行离线 dry run，检查规则、查询和最多三次真实请求的边界：

```powershell
.\.venv\Scripts\python.exe scripts\run_poc.py
```

只有显式增加 `--execute-live` 才会读取 `.env` 并调用 Foundry/Bing：

```powershell
.\.venv\Scripts\python.exe scripts\run_poc.py --execute-live
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

真实运行会把以下文件写入 `.tmp/poc-runs/<run_id>/`：

- `search-results.json`：两次 Grounding 搜索中通过最低引用门槛的规范化内容。
- `brief.json`：结构化英文简报。
- `brief.md`：可直接展示或转发的英文简报。

若所有搜索调用都失败，只写 `search-results.json` 和 `error.json`，并返回非零退出码。

## Configuration

首次使用时手动复制 `.env.example` 为 `.env`；已有 `.env` 不要覆盖。`.env` 只保存现有 Foundry Project、模型 deployment 和 Bing Custom Search project connection；具体 configuration/instance 名称来自所选 Rule Pack。因此切换地区不需要修改 `.env`，也不创建或修改云资源、不需要 Portal Agent ID。搜索请求使用 GPT-5-mini 支持的 `web_search` API surface，而不是该模型不支持的旧 `bing_custom_search_preview` 工具类型。

默认规则位于 `config/rules/hk-regulatory-pulse.json`；另有 `macao-regulatory-pulse.json` 和 `cn-mainland-regulatory-pulse.json`。通过 `--rule config/rules/<name>.json` 选择。一个 Rule Pack 同时定义：

- Custom Bing instance 和该地区允许的域名；
- 搜索主题、窗口、语言、查询模板和包含／排除规则；
- 摘要受众、语言、Top 5 排序、轻量关注等级和写作规则。

## Evidence boundary

每条进入简报的搜索内容必须至少带一个由 `web_search_call.action.sources` 原生返回的 `https` URL，候选的 `citation_urls` 必须规范化匹配该 URL，且域名属于 Rule Pack 的允许列表。`message.content[].annotations` 中的 `url_citation` 用于补充原生标题和字符偏移。除此之外不做独立原文下载、locator 匹配或 Verify Agent 判断。无引用或越界只丢弃对应条目，不使整轮失败。

因此结果应理解为“带来源链接的 Grounding 内容”，不是已经独立核验的原文结论。每份简报都会显示这一免责声明。原始模型／工具响应不落盘，外部请求不自动重试。

详细设计见 [PoC architecture](docs/POC_ARCHITECTURE.md)，续接状态见 [HANDOFF](docs/HANDOFF.md)。
