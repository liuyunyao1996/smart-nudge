"""Run the ordinary AI Foundry Web Search path and write one JSON result."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo.search_common import (  # noqa: E402
    DemoError,
    extract_search_result,
    failed_result,
    get_token,
    post_foundry,
    read_environment,
    read_json,
    render_prompt,
    required_environment_value,
    search_window,
    utc_timestamp,
    validate_agent_name,
    validate_agent_version,
    validate_project_endpoint,
    validate_target_hosts,
    write_json,
)


DEFAULT_CONFIG = Path(__file__).with_name("ordinary_web_search.json")


def load_config(path: Path) -> dict:
    config = read_json(path)
    expected = {
        "schema_version",
        "method_id",
        "label",
        "scope_control",
        "azure_inputs",
        "search_input",
        "request",
    }
    if set(config) != expected or config.get("schema_version") != "1.0.0" or config.get("method_id") != "ordinary_web_search":
        raise DemoError("invalid_config", "ordinary_web_search.json has unexpected top-level fields.")
    azure_inputs = config.get("azure_inputs")
    if not isinstance(azure_inputs, dict) or set(azure_inputs) != {
        "project_endpoint_env",
        "agent_name_env",
        "agent_version_env",
        "authentication",
        "token_scope",
        "endpoint_type",
    }:
        raise DemoError("invalid_config", "ordinary_web_search.json has invalid Azure inputs.")
    request = config.get("request")
    if (
        not isinstance(request, dict)
        or set(request) != {
            "input_role",
            "tool_choice",
            "max_tool_calls",
            "include",
            "max_output_tokens",
            "parallel_tool_calls",
            "store",
        }
        or request.get("input_role") != "user"
        or request.get("tool_choice") != "required"
        or request.get("max_tool_calls") != 1
        or request.get("include") != ["web_search_call.action.sources"]
        or type(request.get("max_output_tokens")) is not int
        or not 1 <= request["max_output_tokens"] <= 4000
        or request.get("parallel_tool_calls") is not False
        or request.get("store") is not False
    ):
        raise DemoError("invalid_config", "ordinary_web_search.json has invalid request parameters.")
    if not isinstance(config.get("label"), str) or not isinstance(config.get("scope_control"), str):
        raise DemoError("invalid_config", "ordinary_web_search.json requires display labels.")
    return config


def prepare(config_path: Path = DEFAULT_CONFIG, now: datetime | None = None) -> dict:
    config = load_config(config_path)
    window = search_window(config["search_input"].get("lookback_days"), now)
    prompt = render_prompt(config, window, allow_site_expression=True)
    target_hosts = validate_target_hosts(config["search_input"].get("target_hosts"))
    request = config["request"]
    payload = {
        "input": [{"role": request["input_role"], "content": prompt}],
        "tool_choice": request["tool_choice"],
        "max_tool_calls": request["max_tool_calls"],
        "include": request["include"],
        "max_output_tokens": request["max_output_tokens"],
        "parallel_tool_calls": request["parallel_tool_calls"],
        "store": request["store"],
    }
    return {
        "config": config,
        "config_path": config_path,
        "window": window,
        "prompt": prompt,
        "target_hosts": target_hosts,
        "payload": payload,
    }


def dry_run(config_path: Path = DEFAULT_CONFIG, now: datetime | None = None) -> dict:
    prepared = prepare(config_path, now)
    config = prepared["config"]
    return {
        "ok": True,
        "mode": "dry_run",
        "method_id": config["method_id"],
        "config_file": config_path.name,
        "endpoint_type": config["azure_inputs"]["endpoint_type"],
        "target_hosts": list(prepared["target_hosts"]),
        "window": prepared["window"],
        "resolved_request": prepared["payload"],
        "external_requests": 0,
        "live_request_limit": 1,
        "automatic_retries": 0,
    }


def run_live(
    config_path: Path = DEFAULT_CONFIG,
    env_file: Path = ROOT / ".env",
    *,
    generated_at: str | None = None,
    now: datetime | None = None,
) -> dict:
    prepared = prepare(config_path, now)
    config = prepared["config"]
    azure_inputs = config["azure_inputs"]
    values = read_environment(env_file)
    endpoint = validate_project_endpoint(
        required_environment_value(values, azure_inputs["project_endpoint_env"])
    )
    agent_name = validate_agent_name(
        required_environment_value(values, azure_inputs["agent_name_env"])
    )
    agent_version = validate_agent_version(
        required_environment_value(values, azure_inputs["agent_version_env"])
    )
    url = (
        f"{endpoint}/agents/{agent_name}/endpoint/protocols/"
        "openai/responses?api-version=v1"
    )
    generated_at = generated_at or utc_timestamp()[0]
    artifact = {
        "schema_version": "1.0.0",
        "artifact_type": "search_path_result",
        "method_id": config["method_id"],
        "label": config["label"],
        "scope_control": config["scope_control"],
        "generated_at": generated_at,
        "config_file": config_path.name,
        "task": {
            "topic": config["search_input"]["topic"],
            "result_limit": config["search_input"]["result_limit"],
            "window": prepared["window"],
            "target_hosts": list(prepared["target_hosts"]),
        },
        "request": {
            "endpoint_type": azure_inputs["endpoint_type"],
            "agent_name": agent_name,
            "agent_version": agent_version,
            "instructions": None,
            "input": prepared["prompt"],
            "parameters": {key: value for key, value in prepared["payload"].items() if key != "input"},
            "note": "The Prompt Agent may also apply instructions stored in the Azure Portal; this script does not read or display them.",
        },
    }
    try:
        body, metadata = post_foundry(url, prepared["payload"], get_token())
        result = extract_search_result(body, metadata, prepared["target_hosts"])
    except DemoError as exc:
        result = failed_result(exc)
    return {**artifact, **result}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the ordinary AI Foundry Web Search path and write normalized JSON."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Ordinary Web Search configuration JSON.")
    parser.add_argument("--output", help="Output JSON path; defaults to a UTC-timestamped file under .tmp/search-comparison.")
    parser.add_argument("--execute-live", action="store_true", help="Issue one real external request; default is dry run.")
    return parser


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    config_path = Path(args.config)
    try:
        if not args.execute_live:
            print(json.dumps(dry_run(config_path), ensure_ascii=False, indent=2))
            return 0
        generated_at, suffix = utc_timestamp()
        artifact = run_live(config_path, generated_at=generated_at)
        output = Path(args.output) if args.output else ROOT / ".tmp" / "search-comparison" / f"ordinary-web-search-{suffix}.json"
        write_json(output, artifact)
        print(json.dumps({"ok": artifact["status"] == "completed", "output": str(output)}, indent=2))
        return 0 if artifact["status"] == "completed" else 1
    except DemoError as exc:
        print(json.dumps({"ok": False, **exc.as_dict()}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
