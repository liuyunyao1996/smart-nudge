# Search-Scope Comparison Demo

This demonstration is split into three explicit stages so the implementation can be explained directly during a presentation.

## Files to show during the presentation

### 1. Ordinary Web Search

- Inputs: [ordinary_web_search.json](ordinary_web_search.json)
- Implementation: [run_ordinary_web_search.py](run_ordinary_web_search.py)
- Output: `ordinary-web-search-<UTC timestamp>.json`

The configuration shows the target websites, rolling date window, complete prompt template, Prompt Agent environment inputs, and every request parameter. The implementation resolves the prompt, calls the existing Prompt Agent's dedicated Responses endpoint, and preserves every native source returned by that one Web Search call.

Offline preview:

```powershell
.\.venv\Scripts\python.exe demo\run_ordinary_web_search.py
```

Authorized live run:

```powershell
.\.venv\Scripts\python.exe demo\run_ordinary_web_search.py --execute-live
```

### 2. Bing Custom Search

- Inputs: [custom_bing_search.json](custom_bing_search.json)
- Implementation: [run_custom_bing_search.py](run_custom_bing_search.py)
- Output: `custom-bing-search-<UTC timestamp>.json`

The configuration shows the same search task and target websites, plus the model input, instructions, Custom Search instance, connection environment input, tool binding, and request parameters. The implementation calls the project Responses endpoint with a `web_search` tool bound to that Custom Search configuration.

Offline preview:

```powershell
.\.venv\Scripts\python.exe demo\run_custom_bing_search.py
```

Authorized live run:

```powershell
.\.venv\Scripts\python.exe demo\run_custom_bing_search.py --execute-live
```

### 3. Offline report builder

- Comparison and report settings: [comparison.json](comparison.json)
- Implementation: [build_report.py](build_report.py)

This stage makes no external request. It checks that the two JSON inputs used the same topic, date window, result limit, and target websites, then produces the comparison JSON and a deliberately plain HTML report. The HTML keeps only the search task, how each path searched, each path's answer, and its native sources with website-scope labels:

```powershell
.\.venv\Scripts\python.exe demo\build_report.py `
  --ordinary <ordinary-result.json> `
  --custom <custom-result.json>
```

## One-command orchestration

[compare_search.py](compare_search.py) remains available as a thin convenience wrapper. It runs the two standalone search modules, saves their separate JSON outputs, and passes them to the offline report builder:

```powershell
# Offline validation only
.\.venv\Scripts\python.exe demo\compare_search.py

# One authorized request per search path, followed by offline report generation
.\.venv\Scripts\python.exe demo\compare_search.py --execute-live
```

A combined run writes four timestamped artifacts under a directory such as `.tmp/search-comparison/search-compare-20261020T031245Z/`:

- `ordinary-web-search-20261020T031245Z.json`
- `custom-bing-search-20261020T031245Z.json`
- `comparison-20261020T031245Z.json`
- `report-20261020T031245Z.html`

## Presentation talk track

- Open the two method-specific JSON configuration files first. They make every non-secret input and the exact prompt template visible without reading application code.
- Open the two short runner scripts next. Point out the different endpoints and payloads: a Prompt Agent endpoint for ordinary Web Search, versus a project Responses endpoint with `custom_search_configuration` for Bing Custom Search.
- Show the two independent result JSON files. They retain answer text, native source URLs, scope metrics, safe request identifiers, and token usage, but never raw service responses or credentials.
- Open the final HTML report. Every native source is marked either "Within target website scope" or "Non-compliant: outside target websites."
- The marker checks the source hostname only. It does not independently verify relevance, publication date, or page content.

## Security and execution boundaries

All commands default to dry run and do not read `.env`. `--execute-live` is required for external calls. A combined live run makes at most one external request per path, with one search tool call per path and no automatic retries.

Live search scripts read only the existing project-root `.env` identifiers needed by their own path. They do not create or modify cloud resources. Do not place tokens, keys, or Azure sign-in caches in demo files, screenshots, or reports.
