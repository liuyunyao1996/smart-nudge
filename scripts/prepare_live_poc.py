"""Prepare one validated manual-live PoC request and authorization offline."""

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smart_nudge.live_preparation import (  # noqa: E402
    DEFAULT_OUTPUT_DIRECTORY,
    LivePreparationError,
    prepare_manual_live_run,
)
from smart_nudge.live_run import LiveRunBoundaryError  # noqa: E402
from smart_nudge.research import ResearchLoopError  # noqa: E402
from smart_nudge.skills import SkillSelectionError  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a checked non-production request and short-lived authorization; "
            "this command does not access Azure or execute the live run."
        )
    )
    parser.add_argument(
        "--market-id",
        action="append",
        choices=("HK", "CN", "MY"),
        dest="market_ids",
        help="Repeat for multiple markets; defaults to HK.",
    )
    parser.add_argument(
        "--event-type",
        choices=(
            "consultation",
            "final_rule",
            "supervisory_guidance",
            "enforcement",
            "implementation_update",
        ),
        default="final_rule",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help="Used when --window-start is omitted.",
    )
    parser.add_argument(
        "--window-start",
        help="Optional ISO 8601 timestamp with offset; overrides --lookback-days.",
    )
    parser.add_argument(
        "--window-end",
        help="Optional ISO 8601 timestamp with offset; defaults to preparation time.",
    )
    parser.add_argument("--max-followups", type=int, default=0)
    parser.add_argument("--max-queries", type=int, default=3)
    parser.add_argument("--max-evidence", type=int, default=2)
    parser.add_argument("--authorization-ttl-minutes", type=int, default=45)
    parser.add_argument(
        "--organizational-approval-ref", default="user-poc-assumption"
    )
    parser.add_argument("--domain-approval-ref", default="user-poc-assumption")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help="Must be inside the repository .tmp directory.",
    )
    return parser


def main(argv=None, *, clock=None):
    args = _parser().parse_args(argv)
    try:
        prepared = prepare_manual_live_run(
            ROOT,
            market_ids=args.market_ids or ("HK",),
            event_type=args.event_type,
            lookback_days=args.lookback_days,
            window_start=args.window_start,
            window_end=args.window_end,
            max_followups=args.max_followups,
            max_queries=args.max_queries,
            max_evidence_records=args.max_evidence,
            authorization_ttl_minutes=args.authorization_ttl_minutes,
            organizational_approval_ref=args.organizational_approval_ref,
            domain_approval_ref=args.domain_approval_ref,
            output_directory=args.output_dir,
            run_id=args.run_id,
            clock=clock,
        )
        result = prepared.record(ROOT)
    except (
        LivePreparationError,
        LiveRunBoundaryError,
        ResearchLoopError,
        SkillSelectionError,
    ) as exc:
        result = {
            "ok": False,
            "code": getattr(exc, "code", "preparation_failed"),
            "message": str(exc),
            "live_executed": False,
            "authorization_consumed": False,
        }
    except Exception:
        result = {
            "ok": False,
            "code": "unexpected_failure",
            "message": "Could not safely prepare the manual-live PoC artifacts.",
            "live_executed": False,
            "authorization_consumed": False,
        }
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
