"""Run both standalone search paths and build the final comparison report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo.build_report import load_report_config, write_report  # noqa: E402
from demo.run_custom_bing_search import dry_run as custom_dry_run  # noqa: E402
from demo.run_custom_bing_search import run_live as custom_run_live  # noqa: E402
from demo.run_ordinary_web_search import dry_run as ordinary_dry_run  # noqa: E402
from demo.run_ordinary_web_search import run_live as ordinary_run_live  # noqa: E402
from demo.search_common import DemoError, utc_timestamp, write_json  # noqa: E402


DEFAULT_CONFIG = DEMO_ROOT / "comparison.json"


def _config_path(report_config_path: Path, value: str) -> Path:
    candidate = (report_config_path.parent / value).resolve()
    try:
        candidate.relative_to(DEMO_ROOT.resolve())
    except ValueError:
        raise DemoError("invalid_config", "Search configuration files must remain under demo/.") from None
    return candidate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run ordinary Web Search, run Bing Custom Search, then build the report."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Comparison configuration JSON.")
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="Issue one real request per search path; the default is an offline dry run.",
    )
    return parser


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        report_config_path = Path(args.config).resolve()
        report_config = load_report_config(report_config_path)
        ordinary_config = _config_path(
            report_config_path,
            report_config["ordinary_web_search_config"],
        )
        custom_config = _config_path(
            report_config_path,
            report_config["custom_bing_search_config"],
        )
        if not args.execute_live:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "mode": "dry_run",
                        "message": "Both search configurations are valid. Add --execute-live to issue external requests.",
                        "steps": [
                            ordinary_dry_run(ordinary_config),
                            custom_dry_run(custom_config),
                            {
                                "step": "build_report",
                                "input": "the two normalized search-path JSON files",
                                "external_requests": 0,
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        generated_at, suffix = utc_timestamp()
        output_directory = ROOT / ".tmp" / "search-comparison" / f"search-compare-{suffix}"
        output_directory.mkdir(parents=True, exist_ok=False)

        ordinary = ordinary_run_live(ordinary_config, generated_at=generated_at)
        ordinary_path = output_directory / f"ordinary-web-search-{suffix}.json"
        write_json(ordinary_path, ordinary)

        custom = custom_run_live(custom_config, generated_at=generated_at)
        custom_path = output_directory / f"custom-bing-search-{suffix}.json"
        write_json(custom_path, custom)

        outputs = write_report(
            ordinary,
            custom,
            report_config,
            output_directory,
            generated_at,
        )
        ok = ordinary["status"] == "completed" and custom["status"] == "completed"
        print(
            json.dumps(
                {
                    "ok": ok,
                    "run_id": outputs["document"]["run_id"],
                    "ordinary_result": str(ordinary_path),
                    "custom_result": str(custom_path),
                    "comparison": str(outputs["comparison"]),
                    "report": str(outputs["report"]),
                },
                indent=2,
            )
        )
        return 0 if ok else 1
    except DemoError as exc:
        print(json.dumps({"ok": False, **exc.as_dict()}, ensure_ascii=False, indent=2))
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "unexpected_failure",
                    "message": "The demo failed without exposing raw responses or credentials.",
                },
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
