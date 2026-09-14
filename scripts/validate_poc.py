"""Offline validation for every checked-in Smart Nudge PoC Rule Pack."""

from datetime import date
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smart_nudge.rules import RulePack, RulePackError  # noqa: E402


def main() -> int:
    failed = False
    for path in sorted((ROOT / "config" / "rules").glob("*.json")):
        try:
            rule = RulePack.load(path, ROOT)
            queries = rule.render_queries(rule.default_topic, date.today(), rule.default_days)
        except RulePackError as exc:
            print(f"FAIL file={path.name} {exc.code}: {exc}")
            failed = True
            continue
        print(
            f"PASS rule={rule.rule_id}@{rule.version} queries={len(queries)} "
            f"max_items={rule.max_items} hosts={len(rule.allowed_hosts)}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
