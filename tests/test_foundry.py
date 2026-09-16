import json
from pathlib import Path
import unittest

import httpx

from smart_nudge.foundry import (
    AgentSearchConfig,
    BingConfig,
    FoundryAdapter,
    FoundryConfig,
    ProbeError,
)
from smart_nudge.rules import RulePack


ROOT = Path(__file__).resolve().parents[1]


class _Token:
    token = "test-token"
    expires_on = 2_000_000_000


class _Credential:
    def get_token(self, _scope):
        return _Token()


def summary_payload(model="gpt-5-mini"):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {"ok": {"type": "string"}},
    }
    return {
        "model": model,
        "instructions": "Summarize.",
        "input": "Input",
        "reasoning": {"effort": "low"},
        "max_output_tokens": 100,
        "parallel_tool_calls": False,
        "text": {"format": {"type": "json_schema", "name": "summary", "schema": schema, "strict": True}},
        "store": False,
    }


class FoundryTests(unittest.TestCase):
    def test_agent_configuration_requires_a_pinned_version(self):
        rule = RulePack.load(ROOT / "config/rules/hk-regulatory-pulse.json", ROOT)
        agent = AgentSearchConfig.load(
            ROOT / "missing.env",
            rule,
            {
                "FOUNDRY_WEB_SEARCH_AGENT_NAME": "regulatory-web-search",
                "FOUNDRY_WEB_SEARCH_AGENT_VERSION": "3",
            },
        )
        self.assertEqual(agent.name, "regulatory-web-search")
        self.assertEqual(agent.version, "3")
        self.assertEqual(agent.allowed_hosts, rule.allowed_hosts)

        with self.assertRaises(ProbeError) as error:
            AgentSearchConfig.load(
                ROOT / "missing.env",
                rule,
                {"FOUNDRY_WEB_SEARCH_AGENT_NAME": "regulatory-web-search"},
            )
        self.assertEqual(error.exception.code, "configuration")

    def test_configuration_binds_bing_to_rule_and_project(self):
        endpoint = "https://resource.services.ai.azure.com/api/projects/project"
        connection = (
            "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/"
            "Microsoft.CognitiveServices/accounts/resource/projects/project/connections/bing"
        )
        environ = {
            "FOUNDRY_PROJECT_ENDPOINT": endpoint,
            "FOUNDRY_MODEL_DEPLOYMENT_NAME": "gpt-5-mini",
            "BING_CUSTOM_SEARCH_PROJECT_CONNECTION_ID": connection,
            "BING_CUSTOM_SEARCH_INSTANCE_NAME": "legacy-value-is-ignored",
        }
        foundry = FoundryConfig.load(ROOT / "missing.env", environ)
        selections = {
            "hk-regulatory-pulse.json": "hk-financial-regulators-test",
            "macao-regulatory-pulse.json": "macao-financial-regulators-test",
            "cn-mainland-regulatory-pulse.json": "cn-mainland-financial-regulators-test",
        }
        for filename, instance in selections.items():
            with self.subTest(filename=filename):
                rule = RulePack.load(ROOT / "config" / "rules" / filename, ROOT)
                bing = BingConfig.load(ROOT / "missing.env", rule, foundry, environ)
                self.assertEqual(bing.instance_name, instance)
                self.assertEqual(bing.allowed_hosts, rule.allowed_hosts)

    def test_summary_request_uses_https_and_returns_safe_audit(self):
        def handler(request):
            self.assertEqual(request.url.path, "/api/projects/project/openai/v1/responses")
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            return httpx.Response(
                200,
                headers={"x-request-id": "req-1"},
                json={
                    "id": "resp-1",
                    "status": "completed",
                    "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                    "output": [],
                },
            )

        config = FoundryConfig(
            "https://resource.services.ai.azure.com/api/projects/project", "gpt-5-mini"
        )
        adapter = FoundryAdapter(
            config, credential=_Credential(), transport=httpx.MockTransport(handler)
        )
        body, audit = adapter.execute_summary(summary_payload())
        self.assertEqual(body["status"], "completed")
        self.assertEqual(audit["request_id"], "req-1")
        self.assertEqual(audit["usage"]["total_tokens"], 14)

    def test_search_requires_web_search_bound_to_custom_configuration(self):
        payload = summary_payload()
        payload.update(
            {
                "tools": [
                    {
                        "type": "web_search",
                        "custom_search_configuration": {
                            "project_connection_id": "connection",
                            "instance_name": "instance",
                        },
                    }
                ],
                "tool_choice": "required",
                "include": ["web_search_call.action.sources"],
            }
        )
        bing = BingConfig("connection", "instance", ("www.example.com",))
        adapter = FoundryAdapter(
            FoundryConfig(
                "https://resource.services.ai.azure.com/api/projects/project",
                "gpt-5-mini",
            ),
            credential=_Credential(),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200, json={"id": "resp-1", "status": "completed", "output": []}
                )
            ),
        )

        body, _audit = adapter.execute_search(payload, bing)

        self.assertEqual(body["status"], "completed")

        payload.pop("include")
        with self.assertRaises(ProbeError) as error:
            adapter.execute_search(payload, bing)
        self.assertEqual(error.exception.code, "invalid_request")

    def test_summary_rejects_search_tools(self):
        payload = summary_payload()
        payload["tools"] = []
        adapter = FoundryAdapter(
            FoundryConfig("https://resource.services.ai.azure.com/api/projects/project", "gpt-5-mini"),
            credential=_Credential(),
        )
        with self.assertRaises(ProbeError) as error:
            adapter.execute_summary(payload)
        self.assertEqual(error.exception.code, "invalid_request")

    def test_agent_search_uses_dedicated_endpoint_and_bounded_tool_calls(self):
        payload = summary_payload()
        for key in ("model", "instructions", "reasoning", "text"):
            payload.pop(key)
        payload["input"] = [{"role": "user", "content": "Search."}]
        payload.update(
            {
                "tool_choice": "required",
                "max_tool_calls": 3,
                "include": ["web_search_call.action.sources"],
            }
        )
        agent = AgentSearchConfig(
            "regulatory-web-search", "3", ("www.example.com",)
        )
        def handler(request):
            self.assertEqual(
                request.url.path,
                "/api/projects/project/agents/regulatory-web-search/endpoint/protocols/openai/responses",
            )
            self.assertEqual(request.url.params["api-version"], "v1")
            request_body = json.loads(request.content)
            self.assertNotIn("agent_reference", request_body)
            self.assertNotIn("text", request_body)
            self.assertEqual(request_body["include"], ["web_search_call.action.sources"])
            return httpx.Response(
                200, json={"id": "resp-1", "status": "completed", "output": []}
            )

        adapter = FoundryAdapter(
            FoundryConfig(
                "https://resource.services.ai.azure.com/api/projects/project",
                "gpt-5-mini",
            ),
            credential=_Credential(),
            transport=httpx.MockTransport(handler),
        )

        body, _audit = adapter.execute_agent_search(payload, agent)
        self.assertEqual(body["status"], "completed")

        for limit in (1, 2):
            payload["max_tool_calls"] = limit
            adapter.execute_agent_search(payload, agent)
        for limit in (0, 4, True, 2.0):
            with self.subTest(limit=limit):
                payload["max_tool_calls"] = limit
                with self.assertRaises(ProbeError) as error:
                    adapter.execute_agent_search(payload, agent)
                self.assertEqual(error.exception.code, "invalid_request")

        payload["max_tool_calls"] = 3
        for include in (None, [], ["web_search_call.results"], ["web_search_call.action.sources", "reasoning.encrypted_content"]):
            with self.subTest(include=include):
                payload["include"] = include
                with self.assertRaises(ProbeError) as error:
                    adapter.execute_agent_search(payload, agent)
                self.assertEqual(error.exception.code, "invalid_request")
        payload.pop("include")
        with self.assertRaises(ProbeError):
            adapter.execute_agent_search(payload, agent)
        payload["include"] = ["web_search_call.action.sources"]
        payload["text"] = {"format": {"type": "json_schema"}}
        with self.assertRaises(ProbeError) as error:
            adapter.execute_agent_search(payload, agent)
        self.assertEqual(error.exception.code, "invalid_request")

    def test_service_rejection_keeps_only_safe_error_details(self):
        adapter = FoundryAdapter(
            FoundryConfig(
                "https://resource.services.ai.azure.com/api/projects/project",
                "gpt-5-mini",
            ),
            credential=_Credential(),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    400,
                    headers={"x-request-id": "req-safe"},
                    json={
                        "error": {
                            "code": "unsupported_parameter",
                            "param": "text.format",
                            "message": "raw service detail must not be exposed",
                        }
                    },
                )
            ),
        )

        with self.assertRaises(ProbeError) as error:
            adapter.execute_summary(summary_payload())

        self.assertEqual(error.exception.result["service_code"], "unsupported_parameter")
        self.assertEqual(error.exception.result["service_param"], "text.format")
        self.assertNotIn("raw service detail", json.dumps(error.exception.result))


if __name__ == "__main__":
    unittest.main()
