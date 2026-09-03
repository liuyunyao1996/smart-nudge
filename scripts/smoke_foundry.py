"""Usage: python scripts/smoke_foundry.py --check auth|model|search."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smart_nudge.foundry import BingConfig, FoundryAdapter, FoundryConfig, ProbeError
from smart_nudge.retention import DataUsePolicyError, load_data_use_policy, make_search_probe_audit


def main():
    parser = argparse.ArgumentParser(description="Check CLI authentication or make one small direct Foundry model request.")
    parser.add_argument("--check", choices=("auth", "model", "search"), default="auth")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--source-scope", type=Path, default=ROOT / "config" / "sources" / "hk-regulators-pilot.json")
    parser.add_argument("--data-use-policy", type=Path,
                        default=ROOT / "config" / "policies" / "p1-public-web-data-use.json")
    args = parser.parse_args()
    policy = None
    try:
        adapter = FoundryAdapter(FoundryConfig.load(args.env_file))
        if args.check == "auth":
            result = adapter.authenticate()
        elif args.check == "model":
            result = adapter.probe_model()
        else:
            bing = BingConfig.load(args.env_file, args.source_scope, adapter.config)
            policy = load_data_use_policy(args.data_use_policy)
            result = make_search_probe_audit(adapter.probe_search(bing), policy)
    except (ProbeError, DataUsePolicyError) as exc:
        if isinstance(exc, DataUsePolicyError):
            print(json.dumps({"ok": False, "code": "data_use_policy", "message": str(exc)},
                             ensure_ascii=True, indent=2))
            return 1
        result = exc.result
        if args.check == "search" and policy is not None:
            result = make_search_probe_audit(result, policy)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
