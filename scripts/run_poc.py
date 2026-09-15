"""Run the Smart Nudge search-to-brief demonstration pipeline."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smart_nudge.foundry import (  # noqa: E402
    AgentSearchConfig,
    BingConfig,
    FoundryAdapter,
    FoundryConfig,
    ProbeError,
)
from smart_nudge.pipeline import (  # noqa: E402
    CUSTOM_BING_APPROACH,
    FOUNDRY_AGENT_APPROACH,
    PocError,
    PocPipeline,
)
from smart_nudge.rules import RulePack, RulePackError  # noqa: E402


DEFAULT_RULE = ROOT / "config" / "rules" / "hk-regulatory-pulse.json"


def _parser():
    parser = argparse.ArgumentParser(
        description="Search the official sites selected by a Rule Pack and create an English executive brief."
    )
    parser.add_argument("--rule", default=str(DEFAULT_RULE), help="Rule Pack under config/rules.")
    parser.add_argument("--topic", help="Optional natural-language topic override.")
    parser.add_argument("--days", type=int, help="Optional search window override (1-90).")
    parser.add_argument(
        "--search-approach",
        choices=(CUSTOM_BING_APPROACH, FOUNDRY_AGENT_APPROACH),
        default=CUSTOM_BING_APPROACH,
        help="Search backend; the existing Custom Bing approach remains the default.",
    )
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="Actually call Azure Foundry/Bing. Without this flag the command is an offline dry run.",
    )
    return parser


def _rule_path(value: str) -> Path:
    path = Path(value)
    resolved = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    rule_root = (ROOT / "config" / "rules").resolve()
    try:
        resolved.relative_to(rule_root)
    except ValueError:
        raise RulePackError("invalid_rule_path", "Rule Pack must be under config/rules.") from None
    return resolved


def _write_atomic(path: Path, content: str):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _dry_run(
    rule: RulePack,
    topic: str | None,
    days: int | None,
    search_approach: str,
) -> dict:
    selected_topic = topic or rule.default_topic
    selected_days = rule.default_days if days is None else days
    regional_time = timezone(timedelta(hours=8), name="UTC+08:00")
    today = datetime.now(timezone.utc).astimezone(regional_time).date()
    queries = rule.render_queries(selected_topic, today, selected_days)
    domain_expression = " OR ".join(f"site:{host}" for host in rule.allowed_hosts)
    return {
        "ok": True,
        "mode": "dry_run",
        "message": "Configuration is valid. Add --execute-live to issue external requests.",
        "rule": {"rule_id": rule.rule_id, "version": rule.version, "sha256": rule.sha256},
        "search_approach": search_approach,
        "topic": selected_topic,
        "days": selected_days,
        "allowed_hosts": list(rule.allowed_hosts),
        "live_request_limit": {
            "search": len(queries),
            "summarization": 1,
            "total": len(queries) + 1,
            "automatic_retries": 0,
            **(
                {"max_tool_calls_per_search": 1}
                if search_approach == FOUNDRY_AGENT_APPROACH
                else {}
            ),
        },
        "queries": [
            {
                "query_id": query.query_id,
                "language": query.language,
                "market": query.market,
                "query": query.text,
                **(
                    {"site_scoped_query": f"({query.text}) ({domain_expression})"}
                    if search_approach == FOUNDRY_AGENT_APPROACH
                    else {}
                ),
            }
            for query in queries
        ],
    }


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        rule = RulePack.load(_rule_path(args.rule), ROOT)
        if not args.execute_live:
            print(
                json.dumps(
                    _dry_run(rule, args.topic, args.days, args.search_approach),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        foundry = FoundryConfig.load(ROOT / ".env")
        search_config = (
            BingConfig.load(ROOT / ".env", rule, foundry)
            if args.search_approach == CUSTOM_BING_APPROACH
            else AgentSearchConfig.load(ROOT / ".env", rule)
        )
        pipeline = PocPipeline(ROOT, rule, FoundryAdapter(foundry), search_config)
        run = pipeline.run(topic=args.topic, days=args.days)
        run_directory = ROOT / ".tmp" / "poc-runs" / run.search_results["run_id"]
        run_directory.mkdir(parents=True, exist_ok=False)
        _write_atomic(
            run_directory / "search-results.json",
            json.dumps(run.search_results, ensure_ascii=False, indent=2) + "\n",
        )
        if not run.ok:
            error = {
                "ok": False,
                "code": "search_failed",
                "message": "No configured search completed; no briefing was generated.",
                "run_id": run.search_results["run_id"],
            }
            _write_atomic(run_directory / "error.json", json.dumps(error, indent=2) + "\n")
            print(json.dumps({**error, "output_directory": str(run_directory)}, indent=2))
            return 1

        _write_atomic(
            run_directory / "brief.json",
            json.dumps(run.brief, ensure_ascii=False, indent=2) + "\n",
        )
        _write_atomic(run_directory / "brief.md", run.markdown)
        print(run.markdown)
        print(f"Artifacts: {run_directory}")
        return 0
    except (RulePackError, PocError, ProbeError) as exc:
        print(
            json.dumps(
                {"ok": False, "code": exc.code, "message": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "unexpected_failure",
                    "message": "The PoC failed without exposing raw external content or credentials.",
                },
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
