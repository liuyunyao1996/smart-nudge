"""Build the final comparison JSON and HTML from two search-path JSON files."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo.search_common import DemoError, read_json, utc_timestamp, write_json, write_text  # noqa: E402


DEFAULT_CONFIG = Path(__file__).with_name("comparison.json")


def load_report_config(path: Path = DEFAULT_CONFIG) -> dict:
    config = read_json(path)
    expected = {
        "schema_version",
        "title",
        "subtitle",
        "ordinary_web_search_config",
        "custom_bing_search_config",
        "limitations",
    }
    if (
        set(config) != expected
        or config.get("schema_version") != "1.0.0"
        or not isinstance(config.get("title"), str)
        or not isinstance(config.get("subtitle"), str)
        or not isinstance(config.get("limitations"), list)
        or not config["limitations"]
        or any(not isinstance(item, str) or not item.strip() for item in config["limitations"])
    ):
        raise DemoError("invalid_config", "comparison.json has invalid report settings.")
    return config


def load_search_result(path: Path, expected_method: str) -> dict:
    artifact = read_json(path)
    required = {
        "schema_version",
        "artifact_type",
        "method_id",
        "label",
        "scope_control",
        "generated_at",
        "config_file",
        "task",
        "request",
        "status",
        "answer",
        "tool_calls",
        "sources",
        "metrics",
    }
    if (
        not required.issubset(artifact)
        or artifact.get("schema_version") != "1.0.0"
        or artifact.get("artifact_type") != "search_path_result"
        or artifact.get("method_id") != expected_method
        or artifact.get("status") not in {"completed", "failed"}
        or not isinstance(artifact.get("task"), dict)
        or not isinstance(artifact.get("request"), dict)
        or not isinstance(artifact.get("sources"), list)
        or not isinstance(artifact.get("metrics"), dict)
    ):
        raise DemoError("invalid_result", f"{path.name} is not a valid {expected_method} result.")
    return artifact


def validate_comparable_inputs(ordinary: dict, custom: dict) -> None:
    for field in ("topic", "result_limit", "window", "target_hosts"):
        if ordinary["task"].get(field) != custom["task"].get(field):
            raise DemoError(
                "input_mismatch",
                f"The two result files cannot be compared because task.{field} differs.",
            )


def timestamp_suffix(generated_at: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", generated_at):
        raise DemoError("invalid_timestamp", "The report timestamp is invalid.")
    return generated_at.replace("-", "").replace(":", "")


def comparison_verdict(ordinary: dict, custom: dict) -> dict:
    if ordinary["status"] != "completed" or custom["status"] != "completed":
        return {
            "code": "incomplete",
            "label": "The comparison did not complete",
            "detail": "At least one path failed. Resolve the error before assessing search behavior.",
        }
    custom_metrics = custom["metrics"]
    ordinary_metrics = ordinary["metrics"]
    if custom_metrics["native_source_count"] == 0:
        return {
            "code": "inconclusive",
            "label": "This run is inconclusive",
            "detail": "Custom Bing returned no auditable native sources. An empty result does not prove that the configured websites contain no relevant content.",
        }
    if custom_metrics["out_of_scope_count"]:
        return {
            "code": "configuration_mismatch",
            "label": "Check the Custom Bing configuration",
            "detail": "The Custom path returned a source outside the locally recorded scope. Check the Portal configuration against demo/custom_bing_search.json.",
        }
    if ordinary_metrics["out_of_scope_count"] or ordinary_metrics["in_target_scope_count"] == 0:
        return {
            "code": "difference_observed",
            "label": "Source-scope difference observed",
            "detail": "Every Custom Bing native source is within the target websites, while ordinary Web Search returned an off-site source or no target-site source.",
        }
    return {
        "code": "boundary_difference_only",
        "label": "Different controls; similar results in this run",
        "detail": "Both paths returned target-site sources in this run. Ordinary Web Search still relies on prompt-level soft constraints, so one compliant run does not demonstrate configuration-level enforcement.",
    }


def build_document(
    ordinary: dict,
    custom: dict,
    report_config: dict,
    generated_at: str,
) -> dict:
    validate_comparable_inputs(ordinary, custom)
    suffix = timestamp_suffix(generated_at)
    return {
        "schema_version": "1.0.0",
        "run_id": "search-compare-" + suffix,
        "generated_at": generated_at,
        "mode": "live",
        "experiment": {
            "title": report_config["title"],
            "subtitle": report_config["subtitle"],
            **ordinary["task"],
            "request_limit": {
                "ordinary_web_search": 1,
                "custom_bing_search": 1,
                "automatic_retries": 0,
            },
            "comparison_scope": "Search-source boundary only; not model answer quality or factual verification",
        },
        "inputs": {
            "ordinary_web_search_config": ordinary["config_file"],
            "custom_bing_search_config": custom["config_file"],
        },
        "paths": {
            "ordinary_web_search": ordinary,
            "custom_bing_search": custom,
        },
        "verdict": comparison_verdict(ordinary, custom),
        "limitations": report_config["limitations"],
    }


def _render_path(path: dict) -> str:
    answer = (
        f"Request failed: {path['error']['message']}"
        if path["status"] == "failed"
        else path.get("answer") or "The service returned no displayable answer text."
    )
    source_rows = []
    for source in path["sources"]:
        scope = (
            "Within target website scope"
            if source["in_target_scope"]
            else "Non-compliant: outside target websites"
        )
        source_rows.append(
            "<li>"
            f"<strong class='{'compliant' if source['in_target_scope'] else 'non-compliant'}'>{scope}</strong><br>"
            f"<a href='{escape(source['url'], quote=True)}' target='_blank' rel='noopener noreferrer'>"
            f"{escape(source['title'])}</a>"
            f"<small>{escape(source['host'])}</small>"
            "</li>"
        )
    sources = "".join(source_rows) or "<li class='empty'>No auditable native source URL was returned</li>"
    request = path["request"]
    instructions = (
        "<h4>Instructions</h4><pre>"
        + escape(request["instructions"])
        + "</pre>"
        if request.get("instructions")
        else ""
    )
    tool = request.get("tool")
    tool_text = (
        "<h4>Tool binding</h4><pre>"
        + escape(json.dumps(tool, indent=2))
        + "</pre>"
        if isinstance(tool, dict)
        else ""
    )
    return f"""
    <section class="path">
      <h2>{escape(path['label'])}</h2>
      <p><strong>Scope control:</strong> {escape(path['scope_control'])}</p>
      <p><strong>Configuration:</strong> {escape(path['config_file'])}</p>
      <p>{escape(request['note'])}</p>
      <h3>How this path searches</h3>
      {instructions}<h4>Input</h4><pre>{escape(request['input'])}</pre>{tool_text}
      <h4>Request parameters</h4><pre>{escape(json.dumps(request['parameters'], indent=2))}</pre>
      <h3>Output</h3>
      <div class="answer">{escape(answer)}</div>
      <h3>Native search results</h3>
      <ul class="sources">{sources}</ul>
    </section>"""


def render_html(document: dict) -> str:
    experiment = document["experiment"]
    ordinary = document["paths"]["ordinary_web_search"]
    custom = document["paths"]["custom_bing_search"]
    hosts = ", ".join(escape(host) for host in experiment["target_hosts"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Search comparison</title>
  <style>
    body {{ margin:0; color:#222; background:#fff; font:15px/1.5 Arial,sans-serif; }}
    main {{ max-width:960px; margin:0 auto; padding:24px; }}
    h2 {{ margin:0 0 12px; padding-bottom:8px; border-bottom:1px solid #bbb; }}
    h3 {{ margin:24px 0 8px; }} h4 {{ margin:16px 0 6px; }} p {{ margin:6px 0; }}
    .task,.path {{ margin-bottom:28px; padding:18px; border:1px solid #bbb; }}
    pre {{ margin:6px 0 12px; padding:12px; border:1px solid #ccc; background:#f7f7f7; white-space:pre-wrap; overflow-wrap:anywhere; font:12px/1.5 Consolas,monospace; }}
    .answer {{ padding:12px; border:1px solid #ccc; white-space:pre-wrap; overflow-wrap:anywhere; }}
    .sources {{ padding-left:22px; }} .sources li {{ margin:12px 0; overflow-wrap:anywhere; }}
    .sources small {{ display:block; color:#555; }} .sources a {{ color:#0645ad; }}
    .compliant {{ color:#176b34; }} .non-compliant {{ color:#a12622; }} .empty {{ color:#555; }}
    @media print {{ main {{ max-width:none; padding:0; }} }}
  </style>
</head>
<body><main>
  <section class="task">
    <h2>What was searched</h2><p>{escape(experiment['topic'])}</p>
    <p><b>Publication window:</b> {escape(experiment['window']['start_date'])} through {escape(experiment['window']['end_date'])}</p>
    <p><b>Target websites:</b> {hosts}</p>
  </section>
  {_render_path(ordinary)}
  {_render_path(custom)}
</main></body></html>"""


def write_report(
    ordinary: dict,
    custom: dict,
    report_config: dict,
    output_directory: Path,
    generated_at: str,
) -> dict:
    document = build_document(ordinary, custom, report_config, generated_at)
    suffix = timestamp_suffix(generated_at)
    comparison_path = output_directory / f"comparison-{suffix}.json"
    report_path = output_directory / f"report-{suffix}.html"
    write_json(comparison_path, document)
    write_text(report_path, render_html(document))
    return {"document": document, "comparison": comparison_path, "report": report_path}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an offline HTML comparison from ordinary and Custom Search JSON results."
    )
    parser.add_argument("--ordinary", required=True, help="Ordinary Web Search result JSON.")
    parser.add_argument("--custom", required=True, help="Bing Custom Search result JSON.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Report configuration JSON.")
    parser.add_argument("--output-directory", help="Output directory; defaults to a UTC-timestamped directory.")
    return parser


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        ordinary = load_search_result(Path(args.ordinary), "ordinary_web_search")
        custom = load_search_result(Path(args.custom), "custom_bing_search")
        config = load_report_config(Path(args.config))
        generated_at, suffix = utc_timestamp()
        output_directory = (
            Path(args.output_directory)
            if args.output_directory
            else ROOT / ".tmp" / "search-comparison" / f"search-compare-{suffix}"
        )
        outputs = write_report(ordinary, custom, config, output_directory, generated_at)
        print(
            json.dumps(
                {
                    "ok": True,
                    "comparison": str(outputs["comparison"]),
                    "report": str(outputs["report"]),
                },
                indent=2,
            )
        )
        return 0
    except DemoError as exc:
        print(json.dumps({"ok": False, **exc.as_dict()}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
