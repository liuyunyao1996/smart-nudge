# Smart Nudge project context

## Continue protocol

- When the user says “我们继续”, “继续”, or “continue”, treat it as a request to resume this project.
- First read `docs/HANDOFF.md`, then check `git status --short --branch` and the recent commit log.
- Use the current worktree and tests as the source of truth when documentation is stale.
- Before changing code, summarize the current phase, uncommitted work, blockers, and the next concrete task.

## Project purpose and scope

- Build a manually invoked public-Web intelligence research agent for the AIA Group CEO.
- The local Python application owns research, analysis, verification, orchestration, budgets, stopping, and evidence decisions.
- Reuse the existing Azure Foundry project, model deployment, and Bing Custom Search connection; do not depend on a Portal-hosted agent or request an Agent ID.
- Scheduling, chat UI, notifications, frontend, and a business HTTP API are outside the current scope.
- Important facts require native URL citations. Mark insufficient evidence explicitly; do not bypass paywalls, logins, or access controls.

## Current continuation point

- P0 contracts and synthetic fixtures are complete; the synthetic cases still require domain-expert review and are not gold labels.
- P1 is engineering-complete under the deny-by-default policy in `docs/P1_ACCESS_RETENTION.md`; organizational legal/privacy approval remains a production gate.
- P2 source registry, approved-access capability matrix, guarded fetcher, and HTML/PDF/API extraction are engineering-complete; organizational approval remains a production gate.
- The first P3 `regulatory-change` skill, generic loader, output contract, and synthetic fixtures are engineering-complete but remain draft pending domain review; draft loading must be explicit.
- Resume with the P4 regulatory research-analysis-verification loop; the remaining P3 domain/common skills can expand after the first closed-loop baseline.
- Treat `docs/HANDOFF.md` as the detailed living status record and update it after material milestones.

## Safety and verification

- Never read, print, commit, or request secrets from `.env`, tokens, keys, or Azure login caches.
- Do not create or modify cloud resources unless the user explicitly asks.
- Do not repeat live model or search probes merely to re-confirm recorded success; they may incur usage. Run them only when needed and authorized by the task.
- Offline baseline checks:
  - `.\.venv\Scripts\python.exe scripts\validate_p0.py`
  - `.\.venv\Scripts\python.exe scripts\validate_sources.py`
  - `.\.venv\Scripts\python.exe scripts\validate_skills.py`
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - `.\.venv\Scripts\python.exe -m pip check`
- Preserve unrelated user changes. Review `git diff` before committing, and never commit or push unless requested.
