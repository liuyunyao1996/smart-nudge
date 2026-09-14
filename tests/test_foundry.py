import json
from pathlib import Path
import unittest

import httpx

from smart_nudge.foundry import BingConfig, FoundryAdapter, FoundryConfig, ProbeError
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
    def test_configuration_binds_bing_to_rule_and_project(self):
        rule = RulePack.load(ROOT / "config/rules/hk-regulatory-pulse.json", ROOT)
        endpoint = "https://resource.services.ai.azure.com/api/projects/project"
        connection = (
            "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/"
            "Microsoft.CognitiveServices/accounts/resource/projects/project/connections/bing"
        )
        environ = {
            "FOUNDRY_PROJECT_ENDPOINT": endpoint,
            "FOUNDRY_MODEL_DEPLOYMENT_NAME": "gpt-5-mini",
            "BING_CUSTOM_SEARCH_PROJECT_CONNECTION_ID": connection,
            "BING_CUSTOM_SEARCH_INSTANCE_NAME": "hk-financial-regulators-test",
        }
        foundry = FoundryConfig.load(ROOT / "missing.env", environ)
        bing = BingConfig.load(ROOT / "missing.env", rule, foundry, environ)
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


if __name__ == "__main__":
    unittest.main()
