#!/usr/bin/env python3
"""Run the P4-A synthetic research loop and verify recorded expectations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smart_nudge.research import FixtureResearchRole, ResearchController, ResearchLoopError, read_json


FIXTURE = ROOT / "evals" / "p4" / "regulatory-loop.synthetic.json"
CLOCK = lambda: datetime.fromisoformat("2026-09-04T09:00:00+08:00")


def main() -> int:
    try:
        document = read_json(FIXTURE)
        if (document.get("data_kind") != "synthetic"
                or document.get("annotation_status") != "draft_pending_domain_review"):
            raise ResearchLoopError("invalid_fixture", "P4-A fixture must remain synthetic and pending review.")
        cases = document["cases"]
        for case in cases:
            outcome = ResearchController(
                ROOT, FixtureResearchRole(case["rounds"]), clock=CLOCK
            ).run(case["request"])
            expected = case["expected"]
            result = outcome.result
            decision = result["findings"][0]["decision"] if result["findings"] else None
            observed = {
                "status": result["run"]["status"],
                "stop_reason": result["run"]["stop_reason"],
                "decision": decision,
                "queries_executed": outcome.budget_usage["queries_executed"],
                "followup_rounds_executed": outcome.budget_usage["followup_rounds_executed"],
            }
            if observed != expected:
                raise ResearchLoopError("expectation_mismatch", f"Synthetic case {case['case_id']} did not match its expected result.")
    except (KeyError, TypeError, ResearchLoopError) as exc:
        code = getattr(exc, "code", "invalid_fixture")
        print(f"P4-A offline research: FAIL ({code}) {exc}")
        return 1
    print(f"P4-A offline research: PASS ({len(cases)} synthetic closed-loop cases)")
    print("The controller produced P0-valid results with bounded rounds and no external calls.")
    print("This is not live research, factual verification, model evaluation, domain approval, or legal advice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
