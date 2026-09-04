"""P4-B request-construction tests; no credential or network access."""

from pathlib import Path
from datetime import datetime
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import httpx

from smart_nudge.foundry import BingConfig, FoundryAdapter, FoundryConfig, ProbeError
from smart_nudge.foundry_research import (
    FoundryResearchRequestBuilder,
    FoundryResearchRequestError,
    FoundryResearchResponseConverter,
    FoundryResearchResponseError,
    MockedFoundryResearchRole,
)
from smart_nudge.research import (
    ContractVerificationRole,
    CoveragePlanner,
    ResearchContext,
    ResearchController,
    ResearchLoopError,
    ResearchRequest,
)
from smart_nudge.skills import SkillLoader
from smart_nudge.sources import SourceRegistry


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://sample.services.ai.azure.com/api/projects/sample"
BING_ID = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test/providers/Microsoft.CognitiveServices/accounts/sample/projects/sample/connections/bing"
HK_HOSTS = (
    "www.ia.org.hk",
    "www.hkma.gov.hk",
    "www.sfc.hk",
    "apps.sfc.hk",
    "www.fstb.gov.hk",
    "www.gov.hk",
)
NOW = datetime.fromisoformat("2026-09-04T09:00:00+08:00")


def signal_document(url="https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/mock"):
    return {
        "schema_version": "0.1.0",
        "coverage_status": "checked",
        "signals": [
            {
                "signal_id": "mock-rule-1",
                "issuer": "Hong Kong Monetary Authority",
                "document_title": "Mock regulatory instrument for transport testing",
                "document_status": "final_rule",
                "jurisdiction": "Hong Kong",
                "instrument_id": "MOCK-2026-01",
                "publication_date": "2026-09-01",
                "effective_date": None,
                "consultation_deadline": None,
                "affected_entities": ["mock regulated entities"],
                "affected_products": [],
                "affected_channels": [],
                "obligation_changes": [
                    {
                        "subject": "mock regulated entities",
                        "action": "must review",
                        "object": "a mock control",
                        "timing": None,
                        "exception_notes": [],
                        "basis_claim_ids": ["status"],
                    }
                ],
                "change_from_prior_rule": None,
                "exceptions": [],
                "unknowns": ["This fixture is not a factual regulatory assertion."],
                "claims": [
                    {
                        "claim_id": "status",
                        "statement": "A mock instrument was published for transport-contract testing.",
                        "kind": "fact",
                        "citation_urls": [url],
                    }
                ],
            }
        ],
    }


def completed_response(document, *, url=None, call_status="completed"):
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    annotations = []
    if url is not None:
        start = text.find(url)
        if start < 0:
            start = 0
            end = min(1, len(text))
        else:
            end = start + len(url)
        annotations.append(
            {
                "type": "url_citation",
                "url": url,
                "title": "Mock native citation metadata",
                "start_index": start,
                "end_index": end,
            }
        )
    return {
        "id": "resp_mocked_research",
        "status": "completed",
        "output": [
            {"type": "bing_custom_search_preview_call", "status": call_status},
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": text, "annotations": annotations}
                ],
            },
        ],
        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    }


def request_document():
    return {
        "schema_version": "0.1.0",
        "mode": "offline_synthetic",
        "run_id": "p4b-request-test",
        "request_key": "p4b-request-test",
        "as_of": "2026-09-04T09:00:00+08:00",
        "window": {
            "start": "2026-08-01T00:00:00+08:00",
            "end": "2026-09-03T09:00:00+08:00",
            "timezone": "Asia/Hong_Kong",
        },
        "scope": {
            "market_ids": ["HK"],
            "topic_id": "regulatory-change",
            "event_type": "final_rule",
            "source_classes": ["official"],
        },
        "budget": {
            "max_followup_rounds_per_event": 2,
            "max_queries": 6,
            "max_evidence_records": 10,
        },
        "allow_draft_skills": True,
    }


class FoundryResearchRequestTests(unittest.TestCase):
    def setUp(self):
        self.request = ResearchRequest.validate(request_document(), ROOT)
        loader = SkillLoader(ROOT)
        self.bundles = {
            "HK": loader.select(
                topic_id="regulatory-change",
                event_type="final_rule",
                market_id="HK",
                include_drafts=True,
            )
        }
        registry = SourceRegistry.load(ROOT / "config" / "sources" / "source-registry.json")
        self.plan = CoveragePlanner(ROOT, registry).build(self.request, self.bundles).record()
        self.builder = FoundryResearchRequestBuilder(
            ROOT,
            FoundryConfig(ENDPOINT, "gpt-5-mini"),
            BingConfig(BING_ID, "hk-test", HK_HOSTS),
        )
        self.converter = FoundryResearchResponseConverter(ROOT)

    def context(self, **changes):
        values = {
            "round_index": 0,
            "followup": False,
            "remaining_queries": 6,
            "remaining_evidence_records": 10,
            "coverage_plan": self.plan,
            "unresolved_event_ids": (),
            "request_key": self.request.request_key,
            "request_sha256": self.request.content_sha256,
        }
        values.update(changes)
        return ResearchContext(**values)

    def test_builds_one_bounded_request_per_language_task(self):
        requests = self.builder.build_initial(
            self.request, self.context(), self.bundles
        )
        self.assertEqual(2, len(requests))
        self.assertEqual(2, sum(item.query_cost for item in requests))
        self.assertEqual(10, sum(item.result_limit for item in requests))
        self.assertEqual({"en", "zh-Hant"}, {item.language for item in requests})
        self.assertTrue(all(item.source_ids for item in requests))
        self.assertTrue(all(item.source_hosts for item in requests))

    def test_payload_uses_direct_responses_contract_and_native_search_tool(self):
        built = next(
            item
            for item in self.builder.build_initial(
                self.request, self.context(remaining_evidence_records=2), self.bundles
            )
            if item.language == "en"
        )
        payload = built.payload
        self.assertEqual("gpt-5-mini", payload["model"])
        self.assertFalse(payload["store"])
        self.assertEqual("required", payload["tool_choice"])
        self.assertNotIn("agent_reference", payload)
        self.assertNotIn("previous_response_id", payload)
        search = payload["tools"][0]["bing_custom_search_preview"]["search_configurations"][0]
        self.assertEqual(BING_ID, search["project_connection_id"])
        self.assertEqual("hk-test", search["instance_name"])
        self.assertEqual(1, search["count"])
        self.assertEqual("en-HK", search["market"])
        self.assertEqual("en", search["set_lang"])
        self.assertIn("2026-08-01T00:00:00+08:00", payload["input"])
        self.assertIn("2026-09-03T09:00:00+08:00", payload["input"])
        self.assertFalse(payload["parallel_tool_calls"])
        output_format = payload["text"]["format"]
        self.assertEqual("json_schema", output_format["type"])
        self.assertTrue(output_format["strict"])
        self.assertFalse(output_format["schema"]["additionalProperties"])
        encoded_schema = json.dumps(output_format["schema"])
        for unsupported in (
            "minLength", "maxLength", "pattern", "format", "minItems", "maxItems", "uniqueItems"
        ):
            self.assertNotIn(f'"{unsupported}"', encoded_schema)

    def test_regulatory_query_is_local_skill_derived_and_does_not_force_aia(self):
        requests = self.builder.build_initial(
            self.request, self.context(), self.bundles
        )
        english = next(item for item in requests if item.language == "en")
        self.assertIn("final rule", english.query_text)
        self.assertIn("Insurance Authority (Hong Kong)", english.query_text)
        self.assertIn("2026-08-01", english.query_text)
        self.assertIn("2026-09-03", english.query_text)
        self.assertNotIn("AIA", english.query_text.upper())

    def test_query_and_evidence_budgets_cap_the_batch(self):
        requests = self.builder.build_initial(
            self.request,
            self.context(remaining_queries=1, remaining_evidence_records=1),
            self.bundles,
        )
        self.assertEqual(1, len(requests))
        self.assertEqual(1, requests[0].query_cost)
        self.assertEqual(1, requests[0].result_limit)
        self.assertEqual((), self.builder.build_initial(
            self.request,
            self.context(remaining_queries=0),
            self.bundles,
        ))

    def test_context_is_bound_to_the_exact_validated_request(self):
        for changed in (
            {"request_key": "another-request"},
            {"request_sha256": "0" * 64},
        ):
            with self.subTest(changed=changed), self.assertRaises(
                FoundryResearchRequestError
            ) as error:
                self.builder.build_initial(
                    self.request, self.context(**changed), self.bundles
                )
            self.assertEqual("invalid_context", error.exception.code)

    def test_payload_and_audit_records_are_detached_and_do_not_expose_prompt(self):
        built = self.builder.build_initial(
            self.request, self.context(), self.bundles
        )[0]
        changed = built.payload
        changed["model"] = "mutated"
        self.assertEqual("gpt-5-mini", built.payload["model"])
        audit = built.audit_record()
        self.assertNotIn("query_text", audit)
        self.assertNotIn("input", audit)
        self.assertNotIn("instructions", audit)

    def test_followup_cannot_repeat_a_broad_initial_scan(self):
        with self.assertRaises(FoundryResearchRequestError) as error:
            self.builder.build_initial(
                self.request,
                self.context(
                    round_index=1,
                    followup=True,
                    unresolved_event_ids=("evt-local-1",),
                ),
                self.bundles,
            )
        self.assertEqual("followup_context_required", error.exception.code)

    def test_tampered_template_and_bing_scope_are_rejected(self):
        changed_plan = {**self.plan, "tasks": [dict(task) for task in self.plan["tasks"]]}
        changed_plan["tasks"][0]["query_templates"] = ["AIA {term}"]
        with self.assertRaises(FoundryResearchRequestError) as error:
            self.builder.build_initial(
                self.request,
                self.context(coverage_plan=changed_plan),
                self.bundles,
            )
        self.assertEqual("template_mismatch", error.exception.code)

        narrow_builder = FoundryResearchRequestBuilder(
            ROOT,
            FoundryConfig(ENDPOINT, "gpt-5-mini"),
            BingConfig(BING_ID, "hk-test", ("www.ia.org.hk",)),
        )
        with self.assertRaises(FoundryResearchRequestError) as error:
            narrow_builder.build_initial(self.request, self.context(), self.bundles)
        self.assertEqual("bing_scope_mismatch", error.exception.code)

    def built_english(self):
        return next(
            item
            for item in self.builder.build_initial(
                self.request, self.context(), self.bundles
            )
            if item.language == "en"
        )

    def convert(self, body):
        return self.converter.convert(
            self.built_english(),
            body,
            {
                "request_id": "req_mock",
                "response_id": "resp_mocked_research",
                "status": "completed",
                "usage": {"total_tokens": 150},
            },
            self.request,
            self.bundles["HK"],
            observed_at=NOW,
        )

    def test_completed_empty_search_becomes_checked_coverage_without_evidence(self):
        body = completed_response(
            {"schema_version": "0.1.0", "coverage_status": "checked", "signals": []}
        )
        result = self.convert(body)
        self.assertEqual("checked", result.coverage_status)
        self.assertEqual((), result.discoveries)
        self.assertEqual(0, result.audit["native_source_citations"])
        self.assertFalse(result.audit["output_text_retained"])

    def test_response_observed_after_cutoff_is_rejected(self):
        body = completed_response(
            {"schema_version": "0.1.0", "coverage_status": "checked", "signals": []}
        )
        with self.assertRaises(FoundryResearchResponseError) as error:
            self.converter.convert(
                self.built_english(),
                body,
                {"status": "completed"},
                self.request,
                self.bundles["HK"],
                observed_at=datetime.fromisoformat("2026-09-04T09:00:01+08:00"),
            )
        self.assertEqual("post_cutoff_evidence", error.exception.code)

    def test_native_citation_converts_to_unchecked_metadata_only_drafts(self):
        url = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/mock"
        result = self.convert(completed_response(signal_document(url), url=url))
        discovery = result.discoveries[0]
        evidence = discovery["evidence"][0]
        claim = discovery["claims"][0]
        self.assertEqual("bing_grounding", evidence["origin"])
        self.assertEqual("approved_metadata_only", evidence["retention"])
        self.assertIsNone(evidence["excerpt"])
        self.assertEqual("discovery_signal", evidence["document_role"])
        self.assertEqual("not_checked", claim["supports"][0]["checked_by"])
        self.assertEqual("unverified", claim["verification"])
        self.assertEqual("signal_only", discovery["candidate"]["evidence_assessment"]["state"])
        self.assertFalse(discovery["candidate"]["evidence_assessment"]["primary_document_obtained"])

    def test_signal_without_native_citations_fails_closed(self):
        with self.assertRaises(FoundryResearchResponseError) as error:
            self.convert(completed_response(signal_document()))
        self.assertEqual("no_citations", error.exception.code)

    def test_bing_attribution_annotation_is_not_promoted_to_evidence(self):
        url = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/mock"
        body = completed_response(signal_document(url), url=url)
        text = body["output"][1]["content"][0]["text"]
        body["output"][1]["content"][0]["annotations"].append(
            {
                "type": "url_citation",
                "url": "https://www.bing.com/search?q=mock",
                "title": "Bing search attribution",
                "start_index": 0,
                "end_index": min(1, len(text)),
            }
        )
        result = self.convert(body)
        self.assertEqual(1, len(result.discoveries[0]["evidence"]))
        self.assertEqual(1, result.audit["native_source_citations"])

    def test_citation_only_verifier_does_not_trust_upstream_checked_labels(self):
        url = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/mock"
        converted = self.convert(completed_response(signal_document(url), url=url))
        discovery = copy.deepcopy(converted.discoveries[0])
        discovery["claims"][0]["supports"][0]["checked_by"] = "verification_agent"
        evidence = {item["evidence_id"]: item for item in discovery["evidence"]}
        claims = {item["claim_id"]: item for item in discovery["claims"]}
        with self.assertRaises(ResearchLoopError) as error:
            ContractVerificationRole(evidence_policy="citation_only").verify(
                (discovery,), evidence, claims
            )
        self.assertEqual("verification_contract", error.exception.code)

    def test_generated_or_out_of_scope_urls_cannot_become_evidence(self):
        official = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/mock"
        generated = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/generated"
        document = signal_document(generated)
        with self.assertRaises(FoundryResearchResponseError) as error:
            self.convert(completed_response(document, url=official))
        self.assertEqual("generated_url", error.exception.code)

        outside = "https://outside.example/mock"
        with self.assertRaises(FoundryResearchResponseError) as error:
            self.convert(completed_response(signal_document(outside), url=outside))
        self.assertEqual("source_out_of_scope", error.exception.code)

    def test_malformed_json_schema_and_unknown_tool_status_fail_closed(self):
        malformed = completed_response(
            {"schema_version": "0.1.0", "coverage_status": "checked", "signals": []}
        )
        malformed["output"][1]["content"][0]["text"] = "{not-json"
        with self.assertRaises(FoundryResearchResponseError) as error:
            self.convert(malformed)
        self.assertEqual("invalid_json", error.exception.code)

        wrong_schema = completed_response(
            {"schema_version": "0.1.0", "coverage_status": "checked"}
        )
        with self.assertRaises(FoundryResearchResponseError) as error:
            self.convert(wrong_schema)
        self.assertEqual("response_schema", error.exception.code)

        incomplete = completed_response(
            {"schema_version": "0.1.0", "coverage_status": "checked", "signals": []},
            call_status="in_progress",
        )
        with self.assertRaises(FoundryResearchResponseError) as error:
            self.convert(incomplete)
        self.assertEqual("tool_incomplete", error.exception.code)

    def test_mocked_execution_requires_mock_transport(self):
        credential = Mock()
        credential.get_token.return_value = SimpleNamespace(
            token="secret-test-token", expires_on=2000000000
        )
        adapter = FoundryAdapter(
            FoundryConfig(ENDPOINT, "gpt-5-mini"), credential=credential
        )
        with self.assertRaises(ProbeError) as error:
            adapter.execute_mocked_research(self.built_english().payload)
        self.assertEqual("mock_transport_required", error.exception.result["code"])
        credential.get_token.assert_not_called()

    def test_mocked_foundry_role_runs_an_eventful_controller_loop_as_watch(self):
        document = request_document()
        document["budget"]["max_followup_rounds_per_event"] = 0
        document["as_of"] = NOW.isoformat()
        request = ResearchRequest.validate(document, ROOT)
        url = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/mock"
        calls = []

        def handler(http_request):
            payload = json.loads(http_request.content)
            calls.append(payload)
            if "language: en;" in payload["input"]:
                body = completed_response(signal_document(url), url=url)
            else:
                body = completed_response(
                    {"schema_version": "0.1.0", "coverage_status": "checked", "signals": []}
                )
            return httpx.Response(200, json=body, headers={"apim-request-id": "req_mock"})

        credential = Mock()
        credential.get_token.return_value = SimpleNamespace(
            token="secret-test-token", expires_on=2000000000
        )
        adapter = FoundryAdapter(
            FoundryConfig(ENDPOINT, "gpt-5-mini"),
            credential=credential,
            transport=httpx.MockTransport(handler),
        )
        role = MockedFoundryResearchRole(
            self.builder,
            adapter,
            request,
            self.bundles,
            clock=lambda: NOW,
        )
        outcome = ResearchController(
            ROOT,
            role,
            verification_role=ContractVerificationRole(evidence_policy="citation_only"),
            clock=lambda: NOW,
        ).run(document)
        self.assertEqual(2, len(calls))
        self.assertEqual(2, outcome.budget_usage["queries_executed"])
        self.assertEqual("partial", outcome.result["run"]["status"], outcome.result)
        self.assertEqual("budget_exhausted", outcome.result["run"]["stop_reason"])
        self.assertEqual("watch", outcome.result["findings"][0]["decision"])
        self.assertEqual("unverifiable", outcome.result["findings"][0]["evidence_status"])
        self.assertEqual("unverified", outcome.result["claims"][0]["verification"])
        self.assertEqual(2, len(role.audit_records))
        self.assertNotIn("secret-test-token", json.dumps(role.audit_records))

    def test_timeout_rate_limit_and_unknown_execution_preserve_attempted_budget(self):
        document = request_document()
        request = ResearchRequest.validate(document, ROOT)

        for response, expected_code in (
            (httpx.Response(429, json={"error": {"code": "RateLimit"}}), "foundry_rate_limited"),
            (httpx.Response(200, json={**completed_response({"schema_version": "0.1.0", "coverage_status": "checked", "signals": []}), "status": "in_progress"}), "foundry_incomplete_response"),
        ):
            with self.subTest(expected_code=expected_code):
                credential = Mock()
                credential.get_token.return_value = SimpleNamespace(
                    token="secret-test-token", expires_on=2000000000
                )
                adapter = FoundryAdapter(
                    FoundryConfig(ENDPOINT, "gpt-5-mini"),
                    credential=credential,
                    transport=httpx.MockTransport(lambda _: response),
                )
                role = MockedFoundryResearchRole(
                    self.builder, adapter, request, self.bundles, clock=lambda: NOW
                )
                outcome = ResearchController(ROOT, role, clock=lambda: NOW).run(document)
                self.assertEqual("failed", outcome.result["run"]["status"])
                self.assertIn(expected_code, outcome.result["run"]["errors"][0])
                self.assertEqual(1, outcome.budget_usage["queries_executed"])

        credential = Mock()
        credential.get_token.return_value = SimpleNamespace(
            token="secret-test-token", expires_on=2000000000
        )

        def timeout(http_request):
            raise httpx.ReadTimeout("secret-test-token", request=http_request)

        role = MockedFoundryResearchRole(
            self.builder,
            FoundryAdapter(
                FoundryConfig(ENDPOINT, "gpt-5-mini"),
                credential=credential,
                transport=httpx.MockTransport(timeout),
            ),
            request,
            self.bundles,
            clock=lambda: NOW,
        )
        outcome = ResearchController(ROOT, role, clock=lambda: NOW).run(document)
        self.assertEqual("failed", outcome.result["run"]["status"])
        self.assertIn("foundry_timeout", outcome.result["run"]["errors"][0])
        self.assertNotIn("secret-test-token", json.dumps(outcome.result))
        self.assertEqual(1, outcome.budget_usage["queries_executed"])


if __name__ == "__main__":
    unittest.main()
