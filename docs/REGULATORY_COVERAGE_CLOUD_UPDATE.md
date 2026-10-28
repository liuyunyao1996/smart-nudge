# Regulatory coverage v1.6.0: cloud update checklist

Updated: 2026-10-28. Applies to `config/rules/asia-executive-news.json`, not the default Hong Kong-only rule or the standalone `demo/` comparison.

## Local changes

Rule Pack v1.6.0 retains the existing seven queries and adds five:

1. `regulatory-china-policy-zh`: Simplified Chinese policy, healthcare-financing and insurance-association discovery.
2. `regulatory-china-policy-forums`: Simplified Chinese public speeches, forums, meetings, strategy and policy priorities, including the Financial Street Forum. No hardcoded forum year or mandatory result.
3. `regulatory-hong-kong-policy-forums`: Traditional Chinese discovery of Hong Kong policy statements and speeches, including English official material.
4. `regulatory-singapore-policy-forums`: Singapore official policy directions and public speeches.
5. `regulatory-authoritative-media`: English and Chinese policy and forum reporting, without required AIA or competitor mentions.

The first four reuse `asia-news-regulatory-official`, with local source-market admission for mainland China, Hong Kong or Singapore. The fifth reuses `asia-news-authoritative-media`. The existing company-media restrictions are preserved. Policy intentions, consultations, binding rules and association self-regulation must be distinguished. Public statements can qualify on supported significance without a final rule or deadline; institutions and forums do not receive automatic inclusion.

The local source list adds `www.iachina.cn` (association), `www.nhsa.gov.cn` (government) and `www.financialstreetforum.com` (forum). Rule Pack schema v1.5.0 and all-news contract v1.3.0 support the forum publisher type. Model search/summary response contracts and final brief contract are unchanged.

Default dates remain unchanged: 14-day search lookback and 7-day brief eligibility, calculated from the Hong Kong date. `--days` overrides retrieval; `--brief-days` (1 to 90) overrides briefing eligibility for one run without editing the Rule Pack. On 28 October, `--brief-days 9` covers 19 to 28 October. No forum-specific date exception is applied.

## Required cloud change

Open the Bing Custom Search configuration editor for the existing Bing connection. Select the existing configuration named exactly:

`asia-news-regulatory-official`

Preserve the existing website set and add these three included/allowed website roots:

```text
https://www.iachina.cn/
https://www.nhsa.gov.cn/
https://www.financialstreetforum.com/
```

Use website roots rather than a single article, `/index.html` or a language subsection. Preserve the explicit host names above: local citation admission matches exact hosts. Do not enable arbitrary subdomains unless their actual hosts are reviewed and added locally. Save the changes and complete the editor's publish/apply step if provided. Ensure no existing exclusion blocks the new entries.

Confirm these existing entries remain included in the same configuration:

```text
https://www.nfra.gov.cn/
https://www.ia.org.hk/
https://www.mas.gov.sg/
```

The user reported applying these cloud edits on 28 October. The authorized live run `poc-20261028T064753Z-f8be4a` admitted native citations from all three new hosts. This confirms observed retrieval, not exhaustive source coverage or an independent inventory of cloud settings.

## Other cloud settings

- `asia-news-authoritative-media`: no new domains needed. Keep the existing approved media set, including `www.news.cn`, `www.xinhuanet.com` and `www.reuters.com`; the new regulatory query is supplied locally.
- `asia-news-aia-primary` and `asia-news-corporate-exchange`: no changes. Do not place the new mainland policy sources in the competitor-only configuration.
- Reuse the existing Foundry project, model deployment, Bing resource and connection. No new resource, configuration name, Portal Agent or `.env` edit is needed.
- Search remains low reasoning effort; summary remains medium; no automatic retries.

The plan increases from 7 searches + at most 1 summary to 12 searches + at most 1 summary. These are model request counts, not a fixed count of internal Bing tool calls or a price estimate. A live run may consume more time and usage. The authorized 28 October run completed 11 searches and the summary; the regulatory-media route timed out without retry. See `HANDOFF.md` for the full result and remaining citation-quality limitation.

## Offline check and later diagnostics

Inspect the plan without external requests:

```powershell
.\.venv\Scripts\python.exe scripts\run_poc.py --rule config/rules/asia-executive-news.json
```

Expected: 12 searches, at most 1 summary, total 13, zero automatic retries, same four configuration names.

After a separately authorized live run, `search-results.json` contains `source_coverage.sources` for every configured host:

- `query_ids`, `failed_query_ids`, `limited_coverage_query_ids`: request scope and observed query limitations; not proof each host was separately searched.
- `native_urls_observed`: distinct native action-source URL hashes observed for the host; may be a lower bound when `diagnostics_truncated` is true.
- `candidates_accepted`: unique source items admitted locally with a native citation to the host.
- `outside_brief_window`, `unknown_publication_date`: admitted sources excluded by unchanged date rules.
- `eligible_for_brief`: sources passed to assessment.
- `sources_in_brief`: sources used by final cards, not card or event counts.

One item citing several hosts contributes to each host; host counts are not additive global unique counts. Zero candidates does not mean an institution published no updates. Use query-level citation diagnostics and warnings to investigate rejection before admission. Native citation matching is not independent verification of content, dates or legal applicability.

References: [Microsoft Foundry Bing tools](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools), [Insurance Association of China](https://www.iachina.cn/index.html), [NHSA](https://www.nhsa.gov.cn/), [Financial Street Forum](https://www.financialstreetforum.com/cn/index.html).
