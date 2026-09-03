"""Offline transport tests: never acquire real tokens or call Azure."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from azure.core.exceptions import ClientAuthenticationError
import httpx

from smart_nudge.foundry import BingConfig, FoundryAdapter, FoundryConfig, ProbeError, PROBE_TEXT, inspect_search


ENDPOINT = "https://sample.services.ai.azure.com/api/projects/sample"
ENV = {"FOUNDRY_PROJECT_ENDPOINT": ENDPOINT, "FOUNDRY_MODEL_DEPLOYMENT_NAME": "gpt-5-mini"}
BING_ID = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test/providers/Microsoft.CognitiveServices/accounts/sample/projects/sample/connections/bing"


def grounded(url="https://www.ia.org.hk/en/news.html"):
    body = completed("An official release. [1]")
    body["output"][0]["content"][0]["annotations"] = [
        {"type": "url_citation", "url": url, "title": "Official release", "start_index": 0, "end_index": 20}]
    body["output"].insert(0, {"type": "bing_custom_search_preview_call", "status": "completed"})
    return body


def completed(text=PROBE_TEXT):
    return {"id": "resp_test", "status": "completed", "output": [
        {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}],
        "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}}


class FoundryTests(unittest.TestCase):
    def adapter(self, handler):
        credential = Mock()
        credential.get_token.return_value = SimpleNamespace(token="secret-test-token", expires_on=2000000000)
        return FoundryAdapter(FoundryConfig(ENDPOINT, "gpt-5-mini"), credential=credential,
                              transport=httpx.MockTransport(handler))

    def test_env_file_loading_and_environment_precedence(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / ".env"
            path.write_text(f'FOUNDRY_PROJECT_ENDPOINT="{ENDPOINT}/"\nFOUNDRY_MODEL_DEPLOYMENT_NAME=old\n', encoding="utf-8-sig")
            self.assertEqual("override", FoundryConfig.load(path, {"FOUNDRY_MODEL_DEPLOYMENT_NAME": "override"}).model)
            self.assertEqual(ENDPOINT + "/openai/v1/responses", FoundryConfig.load(path, {}).responses_url)

    def test_missing_config_does_not_fall_back_to_example(self):
        with self.assertRaises(ProbeError) as error:
            FoundryConfig.load("does-not-exist.env", {})
        self.assertEqual("configuration", error.exception.result["code"])

    def test_endpoint_rejects_wrong_hosts_credentials_and_response_suffix(self):
        for endpoint in ("http://sample.services.ai.azure.com/api/projects/sample", ENDPOINT + "/openai/v1/responses",
                         "https://sample.services.ai.azure.com.evil.test/api/projects/sample",
                         "https://user:password@sample.services.ai.azure.com/api/projects/sample", ENDPOINT + "?key=secret"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ProbeError):
                FoundryConfig.load("missing.env", {**ENV, "FOUNDRY_PROJECT_ENDPOINT": endpoint})

    def test_direct_request_and_usage(self):
        calls = []
        def handle(request):
            calls.append(request)
            self.assertEqual(ENDPOINT + "/openai/v1/responses", str(request.url))
            body = json.loads(request.content)
            self.assertEqual("gpt-5-mini", body["model"])
            self.assertFalse(body["store"])
            self.assertNotIn("agent_reference", body)
            self.assertNotIn("tools", body)
            self.assertEqual(256, body["max_output_tokens"])
            return httpx.Response(200, json=completed(), headers={"apim-request-id": "test-request"})
        result = self.adapter(handle).probe_model()
        self.assertTrue(result["ok"])
        self.assertEqual(20, result["usage"]["total_tokens"])
        self.assertEqual(1, len(calls))

    def test_authentication_output_never_contains_token(self):
        adapter = self.adapter(lambda _: self.fail("No HTTP expected"))
        self.assertNotIn("secret-test-token", json.dumps(adapter.authenticate()))
        adapter.credential.get_token.side_effect = ClientAuthenticationError("secret-test-token")
        with self.assertRaises(ProbeError) as error:
            adapter.authenticate()
        self.assertEqual("authentication", error.exception.result["code"])
        self.assertNotIn("secret-test-token", str(error.exception))

    def test_error_classification_and_no_retries_or_raw_error_logging(self):
        for status, code in ((400, "request_rejected"), (401, "authentication"), (403, "permission_denied"),
                             (404, "not_found"), (429, "rate_limited"), (500, "service_error")):
            calls = []
            def handle(request):
                calls.append(request)
                return httpx.Response(status, json={"error": {"code": "UpstreamError", "message": "secret-test-token"}})
            with self.subTest(status=status), self.assertRaises(ProbeError) as error:
                self.adapter(handle).probe_model()
            self.assertEqual(code, error.exception.result["code"])
            self.assertEqual(1, len(calls))
            self.assertNotIn("secret-test-token", json.dumps(error.exception.result))

    def test_redirect_does_not_forward_credentials(self):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(307, headers={"location": "https://evil.test"})
        with self.assertRaises(ProbeError):
            self.adapter(handle).probe_model()
        self.assertEqual(1, len(calls))

    def test_timeout_and_network_errors(self):
        for exception, code in ((httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "network")):
            def handle(request):
                raise exception("secret-test-token", request=request)
            with self.subTest(code=code), self.assertRaises(ProbeError) as error:
                self.adapter(handle).probe_model()
            self.assertEqual(code, error.exception.result["code"])
            self.assertNotIn("secret-test-token", str(error.exception))

    def test_non_json_and_malformed_responses(self):
        for body in (None, [], {"status": "completed", "output": None}):
            with self.subTest(body=body), self.assertRaises(ProbeError):
                self.adapter(lambda _: httpx.Response(200, json=body)).probe_model()

    def test_incomplete_or_wrong_output_cannot_pass(self):
        for body, code in (({**completed(), "status": "incomplete"}, "incomplete_response"),
                           (completed("another answer"), "unexpected_output")):
            with self.subTest(code=code), self.assertRaises(ProbeError) as error:
                self.adapter(lambda _: httpx.Response(200, json=body)).probe_model()
            self.assertEqual(code, error.exception.result["code"])

    def test_bing_configuration_matches_project_and_reviewed_scope(self):
        with TemporaryDirectory() as temp:
            scope = Path(temp) / "scope.json"
            scope.write_text(json.dumps({"instance_name": "hk-test", "expected_source_hosts": ["www.ia.org.hk"]}))
            env = {"BING_CUSTOM_SEARCH_PROJECT_CONNECTION_ID": BING_ID, "BING_CUSTOM_SEARCH_INSTANCE_NAME": "hk-test"}
            config = FoundryConfig(ENDPOINT, "gpt-5-mini")
            self.assertEqual("hk-test", BingConfig.load("missing.env", scope, config, env).instance_name)
            for changed in ({"BING_CUSTOM_SEARCH_PROJECT_CONNECTION_ID": BING_ID.replace("/projects/sample/", "/projects/other/")},
                            {"BING_CUSTOM_SEARCH_INSTANCE_NAME": "other"}):
                with self.assertRaises(ProbeError):
                    BingConfig.load("missing.env", scope, config, {**env, **changed})

    def test_search_binds_configuration_and_keeps_native_citations(self):
        def handle(request):
            body = json.loads(request.content)
            self.assertNotIn("agent_reference", body)
            self.assertEqual("required", body["tool_choice"])
            self.assertFalse(body["store"])
            config = body["tools"][0]["bing_custom_search_preview"]["search_configurations"][0]
            self.assertEqual(BING_ID, config["project_connection_id"])
            self.assertEqual("hk-test", config["instance_name"])
            return httpx.Response(200, json=grounded())
        result = self.adapter(handle).probe_search(BingConfig(BING_ID, "hk-test", ("www.ia.org.hk",)))
        self.assertTrue(result["ok"])
        self.assertEqual(1, result["observed_search_calls"])
        self.assertEqual(1, result["citations"][0]["output_index"])
        self.assertEqual("pending_manual_review", result["factual_verification"])

    def test_generated_url_is_not_a_native_citation(self):
        with self.assertRaises(ProbeError) as error:
            inspect_search(completed("See https://www.ia.org.hk/news"), {}, ("www.ia.org.hk",))
        self.assertEqual("no_citations", error.exception.result["code"])

    def test_unobservable_and_failed_search_calls_do_not_pass(self):
        for calls, code in (([], "search_execution_unverified"),
                            ([{"type": "web_search_call", "status": "failed"}], "tool_incomplete")):
            body = grounded()
            body["output"] = calls + body["output"][1:]
            with self.subTest(code=code), self.assertRaises(ProbeError) as error:
                inspect_search(body, {}, ("www.ia.org.hk",))
            self.assertEqual(code, error.exception.result["code"])

    def test_out_of_scope_citations_and_domain_lookalikes(self):
        for url in ("https://www.ia.org.hk.evil.test/news", "https://other.test/news"):
            with self.subTest(url=url), self.assertRaises(ProbeError) as error:
                inspect_search(grounded(url), {}, ("www.ia.org.hk",))
            self.assertEqual("source_out_of_scope", error.exception.result["code"])

    def test_bing_attribution_is_preserved_but_not_counted_as_source(self):
        with self.assertRaises(ProbeError) as error:
            inspect_search(grounded("https://www.bing.com/search?q=insurance"), {}, ("www.ia.org.hk",))
        self.assertEqual("no_source_citations", error.exception.result["code"])
        self.assertTrue(error.exception.result["citations"][0]["bing_attribution"])

    def test_invalid_citation_offsets_do_not_pass(self):
        body = grounded()
        body["output"][1]["content"][0]["annotations"][0]["end_index"] = 99999
        with self.assertRaises(ProbeError) as error:
            inspect_search(body, {}, ("www.ia.org.hk",))
        self.assertEqual("invalid_citation_offsets", error.exception.result["code"])

    def test_failed_native_tool_output_cannot_pass_with_completed_call(self):
        body = grounded()
        body["output"].insert(1, {"type": "bing_custom_search_preview_call_output", "status": "failed"})
        with self.assertRaises(ProbeError) as error:
            inspect_search(body, {}, ("www.ia.org.hk",))
        self.assertEqual("tool_incomplete", error.exception.result["code"])


if __name__ == "__main__":
    unittest.main()
