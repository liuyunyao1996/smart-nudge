"""Run the Bing Custom Search path and write one JSON result."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


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
    validate_identifier,
    validate_project_endpoint,
    validate_target_hosts,
    write_json,
)


DEFAULT_CONFIG = Path(__file__).with_name("custom_bing_search.json")


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
    if set(config) != expected or config.get("schema_version") != "1.0.0" or config.get("method_id") != "custom_bing_search":
        raise DemoError("invalid_config", "custom_bing_search.json has unexpected top-level fields.")
    azure_inputs = config.get("azure_inputs")
    if not isinstance(azure_inputs, dict) or set(azure_inputs) != {
        "project_endpoint_env",
        "model_deployment_env",
        "project_connection_id_env",
        "authentication",
        "token_scope",
        "endpoint_type",
    }:
        raise DemoError("invalid_config", "custom_bing_search.json has invalid Azure inputs.")
    search_input = config.get("search_input")
    if not isinstance(search_input, dict) or not isinstance(search_input.get("instructions"), str) or not search_input["instructions"].strip():
        raise DemoError("invalid_config", "custom_bing_search.json requires search instructions.")
    request = config.get("request")
    tool = request.get("tool") if isinstance(request, dict) else None
    custom = tool.get("custom_search_configuration") if isinstance(tool, dict) else None
    if (
        not isinstance(request, dict)
        or set(request) != {
            "tool",
            "tool_choice",
            "include",
            "reasoning",
            "max_output_tokens",
            "parallel_tool_calls",
            "store",
        }
        or not isinstance(tool, dict)
        or tool.get("type") != "web_search"
        or not isinstance(custom, dict)
        or set(custom) != {"project_connection_id_env", "instance_name"}
        or custom.get("project_connection_id_env") != azure_inputs.get("project_connection_id_env")
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", custom.get("instance_name", ""))
        or request.get("tool_choice") != "required"
        or request.get("include") != ["web_search_call.action.sources"]
        or request.get("reasoning") != {"effort": "low"}
        or type(request.get("max_output_tokens")) is not int
        or not 1 <= request["max_output_tokens"] <= 4000
        or request.get("parallel_tool_calls") is not False
        or request.get("store") is not False
    ):
        raise DemoError("invalid_config", "custom_bing_search.json has invalid request parameters.")
    if not isinstance(config.get("label"), str) or not isinstance(config.get("scope_control"), str):
        raise DemoError("invalid_config", "custom_bing_search.json requires display labels.")
    return config


def prepare(config_path: Path = DEFAULT_CONFIG, now: datetime | None = None) -> dict:
    config = load_config(config_path)
    window = search_window(config["search_input"].get("lookback_days"), now)
    prompt = render_prompt(config, window, allow_site_expression=False)
    target_hosts = validate_target_hosts(config["search_input"].get("target_hosts"))
    return {
        "config": config,
        "config_path": config_path,
        "window": window,
        "prompt": prompt,
        "target_hosts": target_hosts,
    }


def _sanitized_request(prepared: dict) -> dict:
    config = prepared["config"]
    request = config["request"]
    return {
        "model": f"env:{config['azure_inputs']['model_deployment_env']}",
        "instructions": config["search_input"]["instructions"],
        "input": prepared["prompt"],
        "tools": [request["tool"]],
        "tool_choice": request["tool_choice"],
        "include": request["include"],
        "reasoning": request["reasoning"],
        "max_output_tokens": request["max_output_tokens"],
        "parallel_tool_calls": request["parallel_tool_calls"],
        "store": request["store"],
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
        "resolved_request": _sanitized_request(prepared),
        "external_requests": 0,
        "live_request_limit": 1,
        "automatic_retries": 0,
    }


def _validate_connection(endpoint: str, connection: str) -> str:
    match = re.fullmatch(
        r"/subscriptions/[A-Fa-f0-9-]{36}/resourceGroups/[A-Za-z0-9_.-]+/providers/"
        r"Microsoft\.CognitiveServices/accounts/([A-Za-z0-9-]+)/projects/"
        r"([A-Za-z0-9_-]+)/connections/[A-Za-z0-9_-]+",
        connection,
    )
    parsed = urlsplit(endpoint)
    if (
        not match
        or parsed.hostname != match[1].lower() + ".services.ai.azure.com"
        or parsed.path != "/api/projects/" + match[2]
    ):
        raise DemoError("configuration", "The Custom Bing connection must belong to the configured Foundry project.")
    return connection


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
    model = validate_identifier(
        required_environment_value(values, azure_inputs["model_deployment_env"]),
        "FOUNDRY_MODEL_DEPLOYMENT_NAME",
    )
    connection = _validate_connection(
        endpoint,
        required_environment_value(
            values,
            config["request"]["tool"]["custom_search_configuration"]["project_connection_id_env"],
        ),
    )
    request = config["request"]
    configured_tool = request["tool"]
    payload = {
        "model": model,
        "instructions": config["search_input"]["instructions"],
        "input": prepared["prompt"],
        "tools": [
            {
                "type": configured_tool["type"],
                "custom_search_configuration": {
                    "project_connection_id": connection,
                    "instance_name": configured_tool["custom_search_configuration"]["instance_name"],
                },
            }
        ],
        "tool_choice": request["tool_choice"],
        "include": request["include"],
        "reasoning": request["reasoning"],
        "max_output_tokens": request["max_output_tokens"],
        "parallel_tool_calls": request["parallel_tool_calls"],
        "store": request["store"],
    }
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
            "model_deployment": model,
            "instructions": config["search_input"]["instructions"],
            "input": prepared["prompt"],
            "tool": {
                "type": configured_tool["type"],
                "instance_name": configured_tool["custom_search_configuration"]["instance_name"],
                "project_connection_id": "env:"
                + configured_tool["custom_search_configuration"]["project_connection_id_env"],
            },
            "parameters": {
                key: value
                for key, value in request.items()
                if key != "tool"
            },
            "note": "The attached Custom Search configuration enforces the website scope; the input does not use a site: expression for filtering.",
        },
    }
    try:
        body, metadata = post_foundry(endpoint + "/openai/v1/responses", payload, get_token())
        result = extract_search_result(body, metadata, prepared["target_hosts"])
    except DemoError as exc:
        result = failed_result(exc)
    return {**artifact, **result}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Bing Custom Search path and write normalized JSON."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Bing Custom Search configuration JSON.")
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
        output = Path(args.output) if args.output else ROOT / ".tmp" / "search-comparison" / f"custom-bing-search-{suffix}.json"
        write_json(output, artifact)
        print(json.dumps({"ok": artifact["status"] == "completed", "output": str(output)}, indent=2))
        return 0 if artifact["status"] == "completed" else 1
    except DemoError as exc:
        print(json.dumps({"ok": False, **exc.as_dict()}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
