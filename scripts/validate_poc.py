"""Offline validation for the default Smart Nudge PoC Rule Pack."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smart_nudge.rules import RulePack, RulePackError  # noqa: E402


def main() -> int:
    try:
        rule = RulePack.load(ROOT / "config/rules/hk-regulatory-pulse.json", ROOT)
        queries = rule.render_queries(rule.default_topic, __import__("datetime").date.today(), rule.default_days)
    except RulePackError as exc:
        print(f"FAIL {exc.code}: {exc}")
        return 1
    print(
        f"PASS rule={rule.rule_id}@{rule.version} queries={len(queries)} "
        f"max_items={rule.max_items} hosts={len(rule.allowed_hosts)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
