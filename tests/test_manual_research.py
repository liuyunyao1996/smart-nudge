"""Manual-live request and discovery-role tests; no external calls."""

from datetime import datetime, timedelta
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from smart_nudge.foundry import BingConfig, FoundryAdapter, FoundryConfig
from smart_nudge.foundry_research import (
    FoundryResearchRequestBuilder,
    LiveFoundryResearchRole,
)
from smart_nudge.live_run import (
    ManualLiveRunAuthorization,
    ManualLiveRunSession,
    ManualLiveSourceClient,
)
from smart_nudge.manual_research import (
    ManualLiveResearchController,
    ManualLiveResearchRequest,
    ManualLiveResearchResult,
)
from smart_nudge.research import CoveragePlanner, ResearchContext, ResearchLoopError
from smart_nudge.skills import SkillLoader
from smart_nudge.source_verification import LiveVerifiedResearchRole
from smart_nudge.sources import ApprovedSourceClient, FetchedSource, SourceRegistry
from scripts.run_live_poc import main as live_poc_main
from tests.test_foundry_research import completed_response, signal_document
from tests.test_source_verification import verification_response


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-09-10T09:05:00+08:00")
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


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def completed_empty_response():
    document = {"schema_version": "0.1.0", "coverage_status": "checked", "signals": []}
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return {
        "id": "resp_live_test",
        "status": "completed",
        "output": [
            {"type": "bing_custom_search_preview_call", "status": "completed"},
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": text, "annotations": []}
                ],
            },
        ],
        "usage": {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130},
    }


class ManualLiveResearchTests(unittest.TestCase):
    def setUp(self):
        self.bundle = SkillLoader(ROOT).select(
            topic_id="regulatory-change",
            event_type="final_rule",
            market_id="HK",
            include_drafts=True,
        )

    def document(self, **changes):
        document = {
            "schema_version": "0.1.0",
            "mode": "manual_live",
            "run_id": "manual-live-poc-test",
            "request_key": "manual-live-poc-test",
            "as_of": "2026-09-10T09:30:00+08:00",
            "window": {
                "start": "2026-09-01T00:00:00+08:00",
                "end": "2026-09-10T09:00:00+08:00",
                "timezone": "Asia/Hong_Kong",
            },
            "scope": {
                "market_ids": ["HK"],
                "topic_id": "regulatory-change",
                "event_type": "final_rule",
                "source_classes": ["official"],
            },
            "budget": {
                "max_followup_rounds_per_event": 0,
                "max_queries": 1,
                "max_evidence_records": 1,
            },
            "allow_draft_skills": True,
            "skill_bundle_sha256s": {"HK": self.bundle.bundle_sha256},
            "poc": {
                "non_production": True,
                "approval_basis": "user_authorized_assumption",
            },
        }
        document.update(changes)
        return document

    def test_request_is_non_production_and_bound_to_skill_digest(self):
        request = ManualLiveResearchRequest.validate(self.document(), ROOT)
        self.assertEqual("manual_live", request.document["mode"])
        self.assertTrue(request.document["poc"]["non_production"])
        changed = self.document(skill_bundle_sha256s={"HK": "0" * 64})
        with self.assertRaises(ResearchLoopError) as error:
            ManualLiveResearchRequest.validate(changed, ROOT)
        self.assertEqual("skill_bundle_mismatch", error.exception.code)

    def test_offline_or_unmarked_request_cannot_enter_manual_live(self):
        for changes in (
            {"mode": "offline_synthetic"},
            {"poc": {"non_production": False, "approval_basis": "user_authorized_assumption"}},
        ):
            with self.subTest(changes=changes), self.assertRaises(ResearchLoopError) as error:
                ManualLiveResearchRequest.validate(self.document(**changes), ROOT)
            self.assertEqual("invalid_live_request", error.exception.code)

    def test_cli_requires_explicit_execute_flag_before_reading_inputs(self):
        output = StringIO()
        with patch(
            "sys.argv",
            [
                "run_live_poc.py",
                "--request",
                "missing-request.json",
                "--authorization",
                "missing-authorization.json",
            ],
        ), redirect_stdout(output):
            status = live_poc_main()
        self.assertEqual(2, status)
        self.assertEqual("live_confirmation_required", json.loads(output.getvalue())["code"])

    def test_live_role_runs_one_bounded_discovery_through_checked_session(self):
        request = ManualLiveResearchRequest.validate(self.document(), ROOT)
        bundles = {"HK": self.bundle}
        registry = SourceRegistry.load(ROOT / "config/sources/source-registry.json")
        plan = CoveragePlanner(ROOT, registry).build(request, bundles).record()
        source_ids = sorted(
            {source_id for task in plan["tasks"] for source_id in task["source_ids"]}
        )
        authorization_document = {
            "schema_version": "0.1.0",
            "mode": "manual_live",
            "enabled": True,
            "authorization_id": "manual-live-poc-auth-test",
            "request_key": request.request_key,
            "request_sha256": request.content_sha256,
            "issued_at": "2026-09-10T09:00:00+08:00",
            "expires_at": "2026-09-10T09:30:00+08:00",
            "organizational_approval_ref": "user-poc-assumption",
            "domain_approval_ref": "user-poc-assumption",
            "allowed_source_ids": source_ids,
            "budget": {"max_queries": 1, "max_evidence_records": 1},
            "retry_policy": {"automatic_retries": 0},
        }
        with TemporaryDirectory() as directory:
            authorization_file = Path(directory) / "authorization.json"
            write_json(authorization_file, authorization_document)
            authorization = ManualLiveRunAuthorization.load(
                ROOT, authorization_file, clock=lambda: NOW
            )
        session = ManualLiveRunSession(authorization, clock=lambda: NOW)
        foundry = FoundryConfig(ENDPOINT, "gpt-5-mini")
        bing = BingConfig(BING_ID, "hk-test", HK_HOSTS)
        builder = FoundryResearchRequestBuilder(ROOT, foundry, bing)
        adapter = FoundryAdapter(foundry)
        role = LiveFoundryResearchRole(
            builder,
            adapter,
            request,
            bundles,
            session,
            clock=lambda: NOW,
        )
        context = ResearchContext(
            round_index=0,
            followup=False,
            remaining_queries=1,
            remaining_evidence_records=1,
            coverage_plan=plan,
            unresolved_event_ids=(),
            request_key=request.request_key,
            request_sha256=request.content_sha256,
        )
        with patch.object(
            adapter,
            "_request",
            return_value=(
                completed_empty_response(),
                {
                    "request_id": "req_live_test",
                    "response_id": "resp_live_test",
                    "status": "completed",
                    "usage": {"total_tokens": 130},
                },
            ),
        ) as execute:
            batch = role.research(context)
        self.assertEqual(1, execute.call_count)
        self.assertEqual(1, batch.queries_executed)
        self.assertEqual(1, session.queries_attempted)
        self.assertEqual(1, len(role.audit_records))
        self.assertEqual((), batch.discoveries)
        self.assertIn("Live Foundry/Bing", batch.coverage_updates[0]["detail"])
        self.assertNotIn("mocked", batch.coverage_updates[0]["detail"].lower())

        approved_source_client = ApprovedSourceClient(registry)
        try:
            live_source_client = ManualLiveSourceClient(
                approved_source_client,
                session,
                request_key=request.request_key,
                request_sha256=request.content_sha256,
            )
            composed = LiveVerifiedResearchRole(
                ROOT,
                role,
                live_source_client,
                adapter,
                request,
                session,
            )
            self.assertIn("manual-live", composed.role_version)
        finally:
            approved_source_client.close()

    def test_live_controller_produces_a_p0_valid_directly_verified_result(self):
        discovery_time = NOW + timedelta(seconds=1)
        retrieval_time = NOW + timedelta(seconds=2)
        completion_time = NOW + timedelta(seconds=3)
        document = self.document()
        document["as_of"] = NOW.isoformat()
        document["budget"] = {
            "max_followup_rounds_per_event": 0,
            "max_queries": 3,
            "max_evidence_records": 2,
        }
        request = ManualLiveResearchRequest.validate(document, ROOT)
        bundles = {"HK": self.bundle}
        registry = SourceRegistry.load(ROOT / "config/sources/source-registry.json")
        plan = CoveragePlanner(ROOT, registry).build(request, bundles).record()
        source_ids = sorted(
            {source_id for task in plan["tasks"] for source_id in task["source_ids"]}
        )
        authorization_document = {
            "schema_version": "0.1.0",
            "mode": "manual_live",
            "enabled": True,
            "authorization_id": "manual-live-controller-auth-test",
            "request_key": request.request_key,
            "request_sha256": request.content_sha256,
            "issued_at": "2026-09-10T09:00:00+08:00",
            "expires_at": "2026-09-10T09:30:00+08:00",
            "organizational_approval_ref": "user-poc-assumption",
            "domain_approval_ref": "user-poc-assumption",
            "allowed_source_ids": source_ids,
            "budget": {"max_queries": 3, "max_evidence_records": 2},
            "retry_policy": {"automatic_retries": 0},
        }
        with TemporaryDirectory() as directory:
            authorization_file = Path(directory) / "authorization.json"
            write_json(authorization_file, authorization_document)
            authorization = ManualLiveRunAuthorization.load(
                ROOT, authorization_file, clock=lambda: NOW
            )
        session = ManualLiveRunSession(authorization, clock=lambda: NOW)
        foundry = FoundryConfig(ENDPOINT, "gpt-5-mini")
        adapter = FoundryAdapter(foundry)
        discovery_role = LiveFoundryResearchRole(
            FoundryResearchRequestBuilder(
                ROOT,
                foundry,
                BingConfig(BING_ID, "hk-test", HK_HOSTS),
            ),
            adapter,
            request,
            bundles,
            session,
            clock=lambda: discovery_time,
        )
        approved_source_client = ApprovedSourceClient(registry, clock=lambda: NOW)
        verified_role = LiveVerifiedResearchRole(
            ROOT,
            discovery_role,
            ManualLiveSourceClient(
                approved_source_client,
                session,
                request_key=request.request_key,
                request_sha256=request.content_sha256,
            ),
            adapter,
            request,
            session,
        )
        discovery_calls = 0
        url = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/mock"

        def foundry_response(payload, _check):
            nonlocal discovery_calls
            if "tools" in payload:
                discovery_calls += 1
                body = (
                    completed_response(signal_document(url), url=url)
                    if discovery_calls == 1
                    else completed_empty_response()
                )
                return body, {
                    "request_id": f"req-live-{discovery_calls}",
                    "response_id": body["id"],
                    "status": "completed",
                    "usage": body["usage"],
                }
            claim_ids = [
                item["claim_id"] for item in json.loads(payload["input"])["claims"]
            ]
            body = verification_response(claim_ids)
            return body, {
                "request_id": "req-live-verification",
                "response_id": body["id"],
                "status": "completed",
                "usage": body["usage"],
            }

        fetched = FetchedSource(
            source_id="hk-hkma-publications",
            url=url,
            retrieved_at=retrieval_time.isoformat(),
            acquisition_method="direct_html",
            content_type="text/html",
            content_sha256="a" * 64,
            retention="approved_metadata_only",
            body=(
                b"<html><title>Mock regulatory instrument</title><body>"
                b"<h1>MOCK-2026-01</h1><p>A mock instrument was published "
                b"for transport-contract testing.</p></body></html>"
            ),
        )
        try:
            with patch.object(
                adapter, "_request", side_effect=foundry_response
            ), patch.object(
                approved_source_client, "fetch", return_value=fetched
            ) as source_fetch:
                outcome = ManualLiveResearchController(
                    ROOT, verified_role, clock=lambda: completion_time
                ).run(document)
        finally:
            approved_source_client.close()

        self.assertEqual("live", outcome.result["data_kind"])
        self.assertEqual(completion_time.isoformat(), outcome.result["run"]["as_of"])
        self.assertEqual("completed", outcome.result["run"]["status"])
        self.assertEqual("sufficient_evidence", outcome.result["run"]["stop_reason"])
        self.assertEqual("selected", outcome.result["findings"][0]["decision"])
        self.assertEqual("supported", outcome.result["claims"][0]["verification"])
        self.assertEqual(3, outcome.budget_usage["queries_executed"])
        self.assertEqual(3, session.queries_attempted)
        self.assertEqual(1, session.evidence_records_attempted)
        self.assertEqual(1, source_fetch.call_count)
        ManualLiveResearchResult.validate(outcome.result, ROOT, request=request)

        wrong_kind = deepcopy(outcome.result)
        wrong_kind["data_kind"] = "synthetic"
        with self.assertRaises(ResearchLoopError) as error:
            ManualLiveResearchResult.validate(wrong_kind, ROOT, request=request)
        self.assertEqual("invalid_live_result", error.exception.code)

        wrong_request = deepcopy(outcome.result)
        wrong_request["run"]["request_key"] = "another-request"
        with self.assertRaises(ResearchLoopError) as error:
            ManualLiveResearchResult.validate(wrong_request, ROOT, request=request)
        self.assertEqual("live_result_request_mismatch", error.exception.code)


if __name__ == "__main__":
    unittest.main()
