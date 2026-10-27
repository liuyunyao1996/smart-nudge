"""Small shared helpers for the two standalone search-path demonstrations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential, CredentialUnavailableError
from dotenv import dotenv_values
import httpx


ROOT = Path(__file__).resolve().parents[1]
SCOPE = "https://ai.azure.com/.default"
SEARCH_CALL_TYPES = {
    "web_search_call",
    "bing_custom_search_call",
    "bing_custom_search_preview_call",
}
INTERNAL_SEARCH_HOSTS = {"bing.com", "www.bing.com"}


class DemoError(RuntimeError):
    """A safe operator-facing error with no raw response or credentials."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.details = details

    def as_dict(self) -> dict:
        return {"code": self.code, "message": str(self), **self.details}


def read_json(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise DemoError("invalid_config", f"Could not read JSON file: {path.name}.") from exc
    if not isinstance(document, dict):
        raise DemoError("invalid_config", f"JSON file must contain one object: {path.name}.")
    return document


def read_environment(env_file: Path) -> dict:
    values = {}
    if env_file.is_file():
        values.update(dotenv_values(env_file, encoding="utf-8-sig", interpolate=False))
    values.update(os.environ)
    return values


def required_environment_value(values: dict, variable_name: str) -> str:
    value = values.get(variable_name)
    value = value.strip() if isinstance(value, str) else ""
    if not value:
        raise DemoError("configuration", f"Set {variable_name} before a live run.")
    return value


def validate_project_endpoint(value: str) -> str:
    endpoint = value.rstrip("/")
    if not re.fullmatch(
        r"https://[A-Za-z0-9-]+\.services\.ai\.azure\.com/api/projects/[A-Za-z0-9_-]+",
        endpoint,
    ):
        raise DemoError("configuration", "FOUNDRY_PROJECT_ENDPOINT is invalid.")
    return endpoint


def validate_identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise DemoError("configuration", f"{label} is invalid.")
    return value


def validate_agent_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", value):
        raise DemoError("configuration", "FOUNDRY_WEB_SEARCH_AGENT_NAME is invalid.")
    return value


def validate_agent_version(value: str) -> str:
    if not re.fullmatch(r"[1-9][0-9]{0,9}", value):
        raise DemoError("configuration", "FOUNDRY_WEB_SEARCH_AGENT_VERSION must be numeric.")
    return value


def validate_host(value) -> str | None:
    if not isinstance(value, str):
        return None
    host = value.strip().lower().rstrip(".")
    if re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,62}",
        host,
    ):
        return host
    return None


def validate_target_hosts(values) -> tuple[str, ...]:
    hosts = tuple(validate_host(value) for value in values) if isinstance(values, list) else ()
    if not hosts or any(host is None for host in hosts) or len(set(hosts)) != len(hosts):
        raise DemoError("invalid_config", "target_hosts must contain unique valid host names.")
    return hosts  # type: ignore[return-value]


def search_window(lookback_days: int, now: datetime | None = None) -> dict:
    if type(lookback_days) is not int or not 1 <= lookback_days <= 90:
        raise DemoError("invalid_config", "lookback_days must be an integer from 1 to 90.")
    hk_timezone = timezone(timedelta(hours=8), name="Asia/Hong_Kong")
    current = (now or datetime.now(timezone.utc)).astimezone(hk_timezone)
    return {
        "start_date": (current.date() - timedelta(days=lookback_days)).isoformat(),
        "end_date": current.date().isoformat(),
        "timezone": "Asia/Hong_Kong",
    }


def render_prompt(config: dict, window: dict, *, allow_site_expression: bool) -> str:
    search_input = config["search_input"]
    hosts = validate_target_hosts(search_input.get("target_hosts"))
    result_limit = search_input.get("result_limit")
    topic = search_input.get("topic")
    template = search_input.get("prompt_template")
    if (
        type(result_limit) is not int
        or not 1 <= result_limit <= 10
        or not isinstance(topic, str)
        or not topic.strip()
        or not isinstance(template, list)
        or not template
        or any(not isinstance(line, str) or not line.strip() for line in template)
    ):
        raise DemoError("invalid_config", "search_input contains an invalid value.")
    variables = {
        "result_limit": result_limit,
        "topic": topic.strip(),
        "start_date": window["start_date"],
        "end_date": window["end_date"],
        "target_hosts": ", ".join(hosts),
        "site_expression": " OR ".join(f"site:{host}" for host in hosts),
    }
    try:
        prompt = "\n".join(line.format(**variables) for line in template)
    except (KeyError, ValueError) as exc:
        raise DemoError("invalid_config", "prompt_template contains an invalid placeholder.") from exc
    if not allow_site_expression and re.search(r"\bsite:[A-Za-z0-9]", prompt):
        raise DemoError("invalid_config", "The Custom Search prompt must not contain a site: expression.")
    return prompt


def utc_timestamp(now: datetime | None = None) -> tuple[str, str]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generated_at = current.isoformat(timespec="seconds").replace("+00:00", "Z")
    suffix = current.strftime("%Y%m%dT%H%M%SZ")
    return generated_at, suffix


def get_token() -> str:
    logging.getLogger("azure.identity").setLevel(logging.CRITICAL)
    try:
        return AzureCliCredential(process_timeout=30).get_token(SCOPE).token
    except CredentialUnavailableError:
        raise DemoError("credential_unavailable", "Azure CLI is unavailable. Install it and run az login.") from None
    except ClientAuthenticationError:
        raise DemoError("authentication", "Could not use the current Azure CLI sign-in. Check az account show.") from None


def safe_identifier(value) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", value):
        return value
    return None


def post_foundry(url: str, payload: dict, token: str) -> tuple[dict, dict]:
    try:
        with httpx.Client(timeout=httpx.Timeout(90, connect=15), follow_redirects=False) as client:
            response = client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
    except httpx.TimeoutException:
        raise DemoError("timeout", "The request timed out and was not retried; the service may still have processed it.") from None
    except httpx.RequestError:
        raise DemoError("network", "Could not reach Azure Foundry. Check network, proxy, and TLS settings.") from None
    request_id = safe_identifier(
        response.headers.get("x-request-id") or response.headers.get("apim-request-id")
    )
    try:
        body = response.json()
    except ValueError:
        body = None
    if not response.is_success:
        service_error = body.get("error") if isinstance(body, dict) else None
        service_error = service_error if isinstance(service_error, dict) else {}
        code, message = {
            400: ("request_rejected", "Foundry rejected the request parameters."),
            401: ("authentication", "Foundry rejected the access token."),
            403: ("permission_denied", "The current identity cannot access the project or deployment."),
            404: ("not_found", "The project, model deployment, or Agent endpoint was not found."),
            429: ("rate_limited", "The Foundry rate or quota limit was reached; the request was not retried."),
        }.get(response.status_code, ("service_error", "Foundry returned an error; the request was not retried."))
        details = {"http_status": response.status_code, "request_id": request_id}
        service_code = safe_identifier(service_error.get("code"))
        if service_code:
            details["service_code"] = service_code
        raise DemoError(code, message, **details)
    if not isinstance(body, dict) or body.get("status") != "completed":
        raise DemoError("incomplete_response", "The Foundry response did not complete.", request_id=request_id)
    metadata = {
        "request_id": request_id,
        "response_id": safe_identifier(body.get("id")),
        "status": "completed",
    }
    usage = body.get("usage")
    if isinstance(usage, dict):
        metadata["usage"] = {
            key: usage[key]
            for key in ("input_tokens", "output_tokens", "total_tokens")
            if type(usage.get(key)) is int and usage[key] >= 0
        }
    return body, metadata


def canonical_url(value) -> str | None:
    if not isinstance(value, str) or len(value) > 4000:
        return None
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        parsed_port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        return None
    port = f":{parsed_port}" if parsed_port and parsed_port != 443 else ""
    return urlunsplit(("https", host + port, parsed.path or "/", parsed.query, ""))


def _add_source(source_map: dict, raw_url, raw_title, evidence_type: str, target_hosts: tuple[str, ...]) -> None:
    url = canonical_url(raw_url)
    if not url:
        return
    host = (urlsplit(url).hostname or "").lower()
    if host in INTERNAL_SEARCH_HOSTS:
        return
    record = source_map.setdefault(
        url,
        {
            "title": raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else "Source page",
            "url": url,
            "host": host,
            "in_target_scope": host in target_hosts,
            "evidence_types": [],
        },
    )
    if evidence_type not in record["evidence_types"]:
        record["evidence_types"].append(evidence_type)


def source_metrics(sources: list[dict]) -> dict:
    in_scope = sum(item.get("in_target_scope") is True for item in sources)
    total = len(sources)
    return {
        "native_source_count": total,
        "in_target_scope_count": in_scope,
        "out_of_scope_count": total - in_scope,
        "in_target_scope_percent": round(in_scope * 100 / total) if total else None,
        "source_hosts": sorted({item["host"] for item in sources if isinstance(item.get("host"), str)}),
    }


def extract_search_result(body: dict, metadata: dict, target_hosts: tuple[str, ...]) -> dict:
    source_map: dict[str, dict] = {}
    answer_parts: list[str] = []
    call_count = 0
    completed_call_count = 0
    output = body.get("output")
    for item in output if isinstance(output, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type") in SEARCH_CALL_TYPES:
            call_count += 1
            completed_call_count += item.get("status") == "completed"
            action = item.get("action")
            sources = action.get("sources") if isinstance(action, dict) else None
            for source in sources if isinstance(sources, list) else []:
                if isinstance(source, dict) and source.get("type") == "url":
                    _add_source(source_map, source.get("url"), source.get("title"), "action_source", target_hosts)
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        content = item.get("content")
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            if isinstance(part.get("text"), str):
                answer_parts.append(part["text"].strip())
            annotations = part.get("annotations")
            for annotation in annotations if isinstance(annotations, list) else []:
                if isinstance(annotation, dict) and annotation.get("type") == "url_citation":
                    _add_source(
                        source_map,
                        annotation.get("url"),
                        annotation.get("title"),
                        "url_citation",
                        target_hosts,
                    )
    sources = sorted(
        source_map.values(),
        key=lambda item: (not item["in_target_scope"], item["host"], item["url"]),
    )
    return {
        "status": "completed",
        **metadata,
        "answer": "\n\n".join(part for part in answer_parts if part),
        "tool_calls": {"total": call_count, "completed": completed_call_count},
        "sources": sources,
        "metrics": source_metrics(sources),
    }


def failed_result(error: DemoError) -> dict:
    return {
        "status": "failed",
        "error": error.as_dict(),
        "answer": "",
        "tool_calls": {"total": 0, "completed": 0},
        "sources": [],
        "metrics": source_metrics([]),
    }


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
