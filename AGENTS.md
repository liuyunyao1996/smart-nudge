# Smart Nudge project context

## Continue protocol

- When the user says “我们继续”, “继续”, or “continue”, resume this project.
- First read `docs/HANDOFF.md`, then check `git status --short --branch` and the recent commit log.
- Use the current worktree and tests as the source of truth when documentation is stale.
- Before changing code, summarize the current phase, uncommitted work, blockers, and the next concrete task.

## Purpose and scope

- Build a manually invoked public-Web demonstration PoC for the AIA Group CEO.
- Demonstrate two ideas only: rule-based search over the existing Hong Kong Grounding with Custom Bing Search configuration, followed by rule-based English executive summarization.
- Business behavior lives in versioned JSON Rule Packs under `config/rules/`.
- Reuse the existing Azure Foundry project, model deployment, and Bing connection. Do not create cloud resources or depend on a Portal-hosted Agent ID.
- Scheduling, notifications, frontend, database, actual push delivery, independent page fetching, and production governance are outside the current scope.

## Current continuation point

- The active runtime is `scripts/run_poc.py`.
- The default command is an offline dry run. `--execute-live` is required for external requests.
- A live run performs at most two Bing-grounded searches and one no-tool summarization request, with no automatic retries.
- Each displayed search item needs a native in-scope URL citation, but there is no Verify Agent or original-text retrieval.
- Output is written under `.tmp/poc-runs/<run_id>/` as search JSON, brief JSON, and Markdown.
- The previous P0–P4 architecture exists only in Git history.

## Safety and verification

- Never read, print, commit, or request secrets from `.env`, tokens, keys, or Azure login caches.
- Do not create or modify cloud resources unless the user explicitly asks.
- Do not execute real model or Bing calls merely to reconfirm connectivity. A specific live run requires explicit user authorization and may incur usage.
- Preserve native URL citations and label results as not independently verified.
- Offline baseline checks:
  - `.\.venv\Scripts\python.exe scripts\validate_poc.py`
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `.\.venv\Scripts\python.exe -m pip check`
- Preserve unrelated user changes. Review `git diff` before committing, and never commit or push unless requested.
