#!/usr/bin/env python3
"""Offline validation for versioned P3 skills, fixtures, and output contracts."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smart_nudge.skills import SkillDefinitionError, SkillSelectionError, SkillLoader


def main() -> int:
    try:
        loader = SkillLoader(ROOT)
        bundle = loader.select(
            topic_id="regulatory-change", event_type="final_rule", market_id="HK", include_drafts=True
        )
    except (SkillDefinitionError, SkillSelectionError) as exc:
        print(f"P3 skills: FAIL ({exc.code}) {exc}")
        return 1
    records = bundle.execution_record()["skills"]
    print(f"P3 skills: PASS ({len(loader.revisions)} revision; {len(records)} selected for regulatory-change/final_rule/HK)")
    print("Versions and SHA-256 content digests are fixed in the selection record.")
    print("This is an offline contract check, not domain approval, model evaluation, legal advice, or live research.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
