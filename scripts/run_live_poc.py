"""Run one explicitly authorized, non-production live research loop."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smart_nudge.foundry import BingConfig, FoundryAdapter, FoundryConfig, ProbeError
from smart_nudge.foundry_research import (
    FoundryResearchRequestBuilder,
    LiveFoundryResearchRole,
)
from smart_nudge.live_run import (
    LiveRunBoundaryError,
    ManualLiveRunAuthorization,
    ManualLiveRunSession,
    ManualLiveSourceClient,
    claim_live_authorization,
)
from smart_nudge.manual_research import (
    ManualLiveResearchController,
    ManualLiveResearchRequest,
)
from smart_nudge.research import ResearchLoopError, read_json
from smart_nudge.skills import SkillLoader, SkillSelectionError
from smart_nudge.source_verification import LiveVerifiedResearchRole
from smart_nudge.sources import ApprovedSourceClient, SourceRegistry


def main():
    parser = argparse.ArgumentParser(
        description="Execute one bounded, non-production manual-live research loop."
    )
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--source-scope",
        type=Path,
        default=ROOT / "config/sources/hk-regulators-pilot.json",
    )
    args = parser.parse_args()
    if not args.execute_live:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "live_confirmation_required",
                    "message": "Pass --execute-live together with a checked short-lived authorization.",
                },
                indent=2,
            )
        )
        return 2

    session = None
    source_client = None
    research_role = None
    try:
        request = ManualLiveResearchRequest.validate(read_json(args.request), ROOT)
        authorization = ManualLiveRunAuthorization.load(ROOT, args.authorization)
        session = ManualLiveRunSession(authorization)
        foundry = FoundryConfig.load(args.env_file)
        bing = BingConfig.load(args.env_file, args.source_scope, foundry)
        loader = SkillLoader(ROOT)
        bundles = {
            market_id: loader.select(
                topic_id=request.topic_id,
                event_type=request.event_type,
                market_id=market_id,
                include_drafts=True,
            )
            for market_id in request.market_ids
        }
        registry = SourceRegistry.load(ROOT / "config/sources/source-registry.json")
        adapter = FoundryAdapter(foundry)
        discovery_role = LiveFoundryResearchRole(
            FoundryResearchRequestBuilder(ROOT, foundry, bing),
            adapter,
            request,
            bundles,
            session,
            clock=lambda: datetime.now(timezone.utc),
        )
        source_client = ApprovedSourceClient(registry)
        research_role = LiveVerifiedResearchRole(
            ROOT,
            discovery_role,
            ManualLiveSourceClient(
                source_client,
                session,
                request_key=request.request_key,
                request_sha256=request.content_sha256,
            ),
            adapter,
            request,
            session,
        )
        controller = ManualLiveResearchController(
            ROOT,
            research_role,
            clock=lambda: datetime.now(timezone.utc),
        )
        claim_live_authorization(ROOT, authorization)
        outcome = controller.run(request.document)
        terminal_status = outcome.result["run"]["status"]
        result = {
            "ok": terminal_status != "failed",
            "mode": "manual_live",
            "environment": "poc_non_production",
            "run_id": request.run_id,
            "request_key": request.request_key,
            "intelligence_result": outcome.result,
            "budget_usage": outcome.budget_usage,
            "trace": list(outcome.trace),
            "role_audit": list(research_role.audit_records),
            "live_run_audit": session.audit_record(),
            "raw_response_retained": False,
            "output_text_retained": False,
        }
    except ResearchLoopError as exc:
        result = {"ok": False, "code": exc.code, "message": str(exc)}
    except LiveRunBoundaryError as exc:
        result = {"ok": False, "code": exc.code, "message": str(exc)}
    except ProbeError as exc:
        result = exc.result
    except SkillSelectionError as exc:
        result = {"ok": False, "code": exc.code, "message": str(exc)}
    except Exception:
        result = {
            "ok": False,
            "code": "unexpected_failure",
            "message": "The manual-live PoC failed without retaining raw external content.",
        }
    finally:
        if source_client is not None:
            source_client.close()
    if session is not None and not result.get("ok"):
        result["live_run_audit"] = session.audit_record()
    if research_role is not None and not result.get("ok"):
        result["role_audit"] = list(research_role.audit_records)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
