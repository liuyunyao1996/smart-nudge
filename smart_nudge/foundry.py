"""Small Azure Foundry Responses client for search and summarization."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential, CredentialUnavailableError
from dotenv import dotenv_values
import httpx

from smart_nudge.rules import RulePack


SCOPE = "https://ai.azure.com/.default"


def read_settings(env_file, environ=None):
    values = {}
    if Path(env_file).is_file():
        values.update(dotenv_values(env_file, encoding="utf-8-sig", interpolate=False))
    values.update(os.environ if environ is None else environ)
    return values


class ProbeError(RuntimeError):
    """Expose only curated error messages, never raw service responses."""

    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.result = {"ok": False, "code": code, "message": message, **details}


@dataclass(frozen=True)
class FoundryConfig:
    endpoint: str
    model: str

    @classmethod
    def load(cls, env_file, environ=None):
        values = read_settings(env_file, environ)
        endpoint = (values.get("FOUNDRY_PROJECT_ENDPOINT") or "").strip().rstrip("/")
        model = (values.get("FOUNDRY_MODEL_DEPLOYMENT_NAME") or "").strip()
        if not re.fullmatch(
            r"https://[a-zA-Z0-9-]+\.services\.ai\.azure\.com/api/projects/[a-zA-Z0-9_-]+",
            endpoint,
        ):
            raise ProbeError(
                "configuration",
                "Set FOUNDRY_PROJECT_ENDPOINT to the Azure Foundry project endpoint.",
            )
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", model):
            raise ProbeError("configuration", "Set a valid FOUNDRY_MODEL_DEPLOYMENT_NAME.")
        return cls(endpoint, model)

    @property
    def responses_url(self):
        return self.endpoint + "/openai/v1/responses"

    def agent_responses_url(self, agent_name):
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", agent_name):
            raise ProbeError("configuration", "The Prompt Agent name is invalid.")
        return (
            f"{self.endpoint}/agents/{agent_name}/endpoint/protocols/"
            "openai/responses?api-version=v1"
        )


@dataclass(frozen=True)
class BingConfig:
    connection_id: str
    instance_name: str
    allowed_hosts: tuple[str, ...]

    @classmethod
    def load(cls, env_file, rule: RulePack, foundry: FoundryConfig, environ=None):
        values = read_settings(env_file, environ)
        connection = (values.get("BING_CUSTOM_SEARCH_PROJECT_CONNECTION_ID") or "").strip()
        instance = rule.document["bing"]["instance_name"]
        match = re.fullmatch(
            r"/subscriptions/[a-fA-F0-9-]{36}/resourceGroups/[a-zA-Z0-9_.-]+/providers/"
            r"Microsoft\.CognitiveServices/accounts/([a-zA-Z0-9-]+)/projects/"
            r"([a-zA-Z0-9_-]+)/connections/[a-zA-Z0-9_-]+",
            connection,
        )
        if not match or not re.fullmatch(r"[a-zA-Z0-9_-]+", instance):
            raise ProbeError(
                "configuration",
                "Set the full Bing project connection ID and a valid Rule Pack instance name.",
            )
        endpoint = urlsplit(foundry.endpoint)
        if (
            endpoint.hostname != match[1].lower() + ".services.ai.azure.com"
            or endpoint.path != "/api/projects/" + match[2]
        ):
            raise ProbeError(
                "configuration",
                "The Bing connection must belong to the configured Foundry project.",
            )
        return cls(connection, instance, rule.allowed_hosts)

    def tool(self):
        return {
            "type": "web_search",
            "custom_search_configuration": {
                "project_connection_id": self.connection_id,
                "instance_name": self.instance_name,
            },
        }


@dataclass(frozen=True)
class AgentSearchConfig:
    name: str
    version: str
    allowed_hosts: tuple[str, ...]

    @classmethod
    def load(cls, env_file, rule: RulePack, environ=None):
        values = read_settings(env_file, environ)
        name = (values.get("FOUNDRY_WEB_SEARCH_AGENT_NAME") or "").strip()
        version = (values.get("FOUNDRY_WEB_SEARCH_AGENT_VERSION") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", name):
            raise ProbeError(
                "configuration",
                "Set FOUNDRY_WEB_SEARCH_AGENT_NAME to the existing Prompt Agent name.",
            )
        if not re.fullmatch(r"[1-9][0-9]{0,9}", version):
            raise ProbeError(
                "configuration",
                "Set FOUNDRY_WEB_SEARCH_AGENT_VERSION to a pinned numeric Agent version.",
            )
        return cls(name, version, rule.allowed_hosts)

def get_cli_token(credential=None):
    logging.getLogger("azure.identity").setLevel(logging.CRITICAL)
    credential = credential or AzureCliCredential(process_timeout=30)
    try:
        return credential.get_token(SCOPE)
    except CredentialUnavailableError:
        raise ProbeError(
            "credential_unavailable",
            "Azure CLI is unavailable to Python. Install it and run az login.",
        ) from None
    except ClientAuthenticationError:
        raise ProbeError(
            "authentication",
            "Python could not use the Azure CLI login. Check az account show and sign in again.",
        ) from None


def safe_identifier(value):
    if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.:/-]{1,200}", value):
        return value
    return None


def text_parts(body):
    output = body.get("output")
    if not isinstance(output, list):
        return
    for item_index, item in enumerate(output):
        if not isinstance(item, dict) or item.get("type") != "message" or item.get("role") != "assistant":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part_index, part in enumerate(content):
            if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                yield item_index, part_index, part


class FoundryAdapter:
    """Execute only explicit pipeline calls and never retry automatically."""

    def __init__(self, config: FoundryConfig, *, credential=None, transport=None):
        self.config = config
        self.credential = credential
        self.transport = transport

    def execute_search(self, payload: dict, bing: BingConfig):
        self._validate_payload(payload, kind="custom_bing", bing=bing)
        return self._request(payload, "search")

    def execute_agent_search(self, payload: dict, agent: AgentSearchConfig):
        self._validate_payload(payload, kind="foundry_agent", agent=agent)
        return self._request(
            payload,
            "search",
            url=self.config.agent_responses_url(agent.name),
        )

    def execute_summary(self, payload: dict):
        self._validate_payload(payload, kind="summary")
        return self._request(payload, "summary")

    def _validate_payload(self, payload, *, kind: str, bing=None, agent=None):
        if not isinstance(payload, dict):
            raise ProbeError("invalid_request", "Foundry payload must be an object.")
        common = {
            "model", "instructions", "input", "reasoning", "max_output_tokens",
            "parallel_tool_calls", "text", "store",
        }
        expected = {
            "input", "tool_choice", "max_tool_calls",
            "max_output_tokens", "parallel_tool_calls", "store",
        } if kind == "foundry_agent" else common | (
            {"tools", "tool_choice", "include"} if kind == "custom_bing" else set()
        )
        if (
            set(payload) != expected
            or payload.get("store") is not False
            or payload.get("parallel_tool_calls") is not False
            or type(payload.get("max_output_tokens")) is not int
            or not 1 <= payload["max_output_tokens"] <= 4000
        ):
            raise ProbeError("invalid_request", "Foundry payload violates the PoC request boundary.")
        if kind == "foundry_agent":
            input_items = payload.get("input")
            message = input_items[0] if isinstance(input_items, list) and len(input_items) == 1 else None
            if (
                not isinstance(agent, AgentSearchConfig)
                or not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message.get("role") != "user"
                or not isinstance(message.get("content"), str)
                or not message["content"].strip()
                or payload.get("tool_choice") != "required"
                or payload.get("max_tool_calls") != 1
            ):
                raise ProbeError(
                    "invalid_request",
                    "Search requires the dedicated Foundry Web Search Prompt Agent endpoint.",
                )
            return
        text_format = payload.get("text", {}).get("format") if isinstance(payload.get("text"), dict) else None
        if (
            payload.get("model") != self.config.model
            or payload.get("reasoning") != {"effort": "low"}
            or not isinstance(payload.get("instructions"), str)
            or not payload["instructions"].strip()
            or not isinstance(payload.get("input"), str)
            or not payload["input"].strip()
            or not isinstance(text_format, dict)
            or text_format.get("type") != "json_schema"
            or text_format.get("strict") is not True
            or not isinstance(text_format.get("schema"), dict)
        ):
            raise ProbeError("invalid_request", "Foundry payload violates the PoC request boundary.")
        if kind == "summary":
            return
        tools = payload.get("tools")
        tool = tools[0] if isinstance(tools, list) and len(tools) == 1 else None
        config = tool.get("custom_search_configuration") if isinstance(tool, dict) else None
        if (
            not isinstance(bing, BingConfig)
            or not isinstance(tool, dict)
            or set(tool) != {"type", "custom_search_configuration"}
            or tool.get("type") != "web_search"
            or payload.get("tool_choice") != "required"
            or payload.get("include") != ["web_search_call.action.sources"]
            or not isinstance(config, dict)
            or set(config) != {"project_connection_id", "instance_name"}
            or config.get("project_connection_id") != bing.connection_id
            or config.get("instance_name") != bing.instance_name
        ):
            raise ProbeError(
                "invalid_request",
                "Search requires Web Search bound to the configured Bing Custom Search instance.",
            )

    def _request(self, payload, kind, *, url=None):
        token = get_cli_token(self.credential)
        try:
            with httpx.Client(
                timeout=httpx.Timeout(60, connect=15),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = client.post(
                    url or self.config.responses_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {token.token}"},
                )
        except httpx.TimeoutException:
            raise ProbeError(
                "timeout",
                "Foundry request timed out and was not retried; the service may still have processed it.",
            ) from None
        except httpx.RequestError:
            raise ProbeError(
                "network",
                "Could not reach Foundry. Check DNS, proxy and TLS connectivity.",
            ) from None
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
                403: ("permission_denied", "Foundry denied access to the project or deployment."),
                404: ("not_found", "The project endpoint or model deployment was not found."),
                429: ("rate_limited", "Foundry rate or quota limit was reached; not retried."),
            }.get(response.status_code, ("service_error", "Foundry returned an unsuccessful status; not retried."))
            details = {
                "http_status": response.status_code,
                "request_id": request_id,
            }
            service_code = safe_identifier(service_error.get("code"))
            service_param = safe_identifier(service_error.get("param"))
            if service_code:
                details["service_code"] = service_code
            if service_param:
                details["service_param"] = service_param
            raise ProbeError(code, message, **details)
        if not isinstance(body, dict):
            raise ProbeError("invalid_response", "Foundry returned a non-object JSON response.")
        summary = {
            "kind": kind,
            "request_id": request_id,
            "response_id": safe_identifier(body.get("id")),
            "status": safe_identifier(body.get("status")),
        }
        usage = body.get("usage")
        if isinstance(usage, dict):
            summary["usage"] = {
                key: usage[key]
                for key in ("input_tokens", "output_tokens", "total_tokens")
                if type(usage.get(key)) is int and usage[key] >= 0
            }
        if body.get("status") != "completed":
            raise ProbeError("incomplete_response", "Foundry response did not complete.", **summary)
        return body, summary
