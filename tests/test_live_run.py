"""Manual live-run boundary tests; no credential or network access."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch, sentinel

import httpx

from smart_nudge.foundry import BingConfig, FoundryAdapter, FoundryConfig, ProbeError
from smart_nudge.live_run import (
    LiveRunBoundaryError,
    ManualLiveRunAuthorization,
    ManualLiveRunSession,
    ManualLiveSourceClient,
    claim_live_authorization,
)
from smart_nudge.sources import ApprovedSourceClient, SourceRegistry


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-09-10T09:00:00+08:00")
ENDPOINT = "https://sample.services.ai.azure.com/api/projects/sample"
REQUEST_KEY = "manual-live-test"
REQUEST_SHA256 = "a" * 64
SOURCE_ID = "hk-hkma-publications"
BING = BingConfig("/subscriptions/test/connections/bing", "hk-test", ("www.hkma.gov.hk",))


def authorization_document(**changes):
    document = {
        "schema_version": "0.1.0",
        "mode": "manual_live",
        "enabled": True,
        "authorization_id": "approval-manual-live-001",
        "request_key": REQUEST_KEY,
        "request_sha256": REQUEST_SHA256,
        "issued_at": "2026-09-10T08:55:00+08:00",
        "expires_at": "2026-09-10T09:30:00+08:00",
        "organizational_approval_ref": "org-approval-001",
        "domain_approval_ref": "domain-approval-001",
        "allowed_source_ids": [SOURCE_ID],
        "budget": {"max_queries": 2, "max_evidence_records": 2},
        "retry_policy": {"automatic_retries": 0},
    }
    document.update(changes)
    return document


def enabled_policy():
    policy = json.loads(
        (ROOT / "config/policies/p4-manual-live-run.json").read_text(encoding="utf-8")
    )
    policy.update(status="approved_for_manual_live", live_enabled=True)
    return policy


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class ManualLiveRunBoundaryTests(unittest.TestCase):
    def approved_root(self, directory):
        root = Path(directory)
        schema = root / "schemas/manual-live-run-authorization.schema.json"
        schema.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "schemas/manual-live-run-authorization.schema.json", schema)
        policy = root / "config/policies/p4-manual-live-run.json"
        write_json(policy, enabled_policy())
        registry = root / "config/sources/source-registry.json"
        registry.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "config/sources/source-registry.json", registry)
        return root

    def load_approved(self, root, document=None):
        authorization = root / "authorization.json"
        write_json(authorization, document or authorization_document())
        return ManualLiveRunAuthorization.load(
            root, authorization, clock=lambda: NOW
        )

    def test_missing_authorization_is_disabled_and_checked_in_poc_policy_is_explicit(self):
        with self.assertRaises(LiveRunBoundaryError) as error:
            ManualLiveRunAuthorization.load(ROOT, None, clock=lambda: NOW)
        self.assertEqual("live_disabled", error.exception.code)

        with self.assertRaises(LiveRunBoundaryError) as error:
            ManualLiveRunAuthorization("{}", "0.1.0")
        self.assertEqual("invalid_authorization", error.exception.code)

        with TemporaryDirectory() as directory:
            authorization = Path(directory) / "authorization.json"
            write_json(authorization, authorization_document())
            loaded = ManualLiveRunAuthorization.load(ROOT, authorization, clock=lambda: NOW)
        self.assertEqual("approval-manual-live-001", loaded.authorization_id)

    def test_schema_requires_explicit_enablement_and_zero_retries(self):
        for changes in (
            {"enabled": False},
            {"retry_policy": {"automatic_retries": 1}},
        ):
            with self.subTest(changes=changes), TemporaryDirectory() as directory:
                root = self.approved_root(directory)
                with self.assertRaises(LiveRunBoundaryError) as error:
                    self.load_approved(root, authorization_document(**changes))
                self.assertEqual("invalid_authorization", error.exception.code)

    def test_policy_must_be_consistently_enabled(self):
        for status, live_enabled in (
            ("approved_for_manual_live", False),
            ("disabled_pending_organizational_and_domain_approval", True),
        ):
            with self.subTest(status=status), TemporaryDirectory() as directory:
                root = self.approved_root(directory)
                policy = enabled_policy()
                policy.update(status=status, live_enabled=live_enabled)
                write_json(root / "config/policies/p4-manual-live-run.json", policy)
                with self.assertRaises(LiveRunBoundaryError) as error:
                    self.load_approved(root)
                self.assertEqual("invalid_live_policy", error.exception.code)

    def test_authorization_is_short_lived_and_uses_registered_sources(self):
        with TemporaryDirectory() as directory:
            root = self.approved_root(directory)
            expired = authorization_document(
                issued_at="2026-09-10T07:00:00+08:00",
                expires_at="2026-09-10T08:00:00+08:00",
            )
            with self.assertRaises(LiveRunBoundaryError) as error:
                self.load_approved(root, expired)
            self.assertEqual("authorization_inactive", error.exception.code)

            unknown = authorization_document(allowed_source_ids=["unknown-source"])
            with self.assertRaises(LiveRunBoundaryError) as error:
                self.load_approved(root, unknown)
            self.assertEqual("source_not_allowed", error.exception.code)

    def test_session_binds_request_sources_and_charges_before_io(self):
        with TemporaryDirectory() as directory:
            root = self.approved_root(directory)
            authorization = self.load_approved(
                root,
                authorization_document(
                    budget={"max_queries": 1, "max_evidence_records": 1}
                ),
            )
            session = ManualLiveRunSession(authorization, clock=lambda: NOW)
            attempt = session.authorize(
                channel="foundry_bing_research",
                request_key=REQUEST_KEY,
                request_sha256=REQUEST_SHA256,
                source_ids=(SOURCE_ID,),
                query_cost=1,
                payload_sha256="b" * 64,
            )
            self.assertEqual(1, attempt["attempt_index"])
            self.assertEqual(1, session.queries_attempted)
            with self.assertRaises(LiveRunBoundaryError) as error:
                session.authorize(
                    channel="foundry_bing_research",
                    request_key=REQUEST_KEY,
                    request_sha256=REQUEST_SHA256,
                    source_ids=(SOURCE_ID,),
                    query_cost=1,
                    payload_sha256="c" * 64,
                )
            self.assertEqual("query_budget_exhausted", error.exception.code)
            self.assertEqual(1, len(session.attempts))

            with self.assertRaises(LiveRunBoundaryError) as error:
                session.authorize(
                    channel="approved_source_fetch",
                    request_key="different-request",
                    request_sha256=REQUEST_SHA256,
                    source_ids=(SOURCE_ID,),
                    evidence_cost=1,
                    payload_sha256="d" * 64,
                )
            self.assertEqual("request_mismatch", error.exception.code)

    def test_audit_excludes_approval_text_and_contains_only_attempt_metadata(self):
        with TemporaryDirectory() as directory:
            root = self.approved_root(directory)
            authorization = self.load_approved(root)
            session = ManualLiveRunSession(authorization, clock=lambda: NOW)
            session.authorize(
                channel="foundry_source_verification",
                request_key=REQUEST_KEY,
                request_sha256=REQUEST_SHA256,
                source_ids=(SOURCE_ID,),
                query_cost=1,
                payload_sha256="e" * 64,
            )
            audit = session.audit_record()
            encoded = json.dumps(audit)
            self.assertNotIn("organizational_approval_ref", encoded)
            self.assertNotIn("domain_approval_ref", encoded)
            self.assertNotIn("org-approval-001", encoded)
            self.assertEqual(0, audit["automatic_retries"])
            self.assertEqual(1, audit["queries_attempted"])

    def test_authorization_document_is_an_immutable_snapshot(self):
        with TemporaryDirectory() as directory:
            root = self.approved_root(directory)
            authorization = self.load_approved(root)
            original_hash = authorization.content_sha256
            detached = authorization.document
            detached["budget"]["max_queries"] = 30
            detached["allowed_source_ids"].append("unknown-source")
            self.assertEqual(2, authorization.max_queries)
            self.assertEqual((SOURCE_ID,), authorization.allowed_source_ids)
            self.assertEqual(original_hash, authorization.content_sha256)

    def test_authorization_id_is_atomically_consumed_once_without_sensitive_text(self):
        with TemporaryDirectory() as directory:
            root = self.approved_root(directory)
            authorization = self.load_approved(root)
            receipt = claim_live_authorization(root, authorization, clock=lambda: NOW)
            self.assertEqual(authorization.authorization_id, receipt["authorization_id"])
            receipt_files = list(
                (root / ".tmp/manual-live-authorizations").glob("*.json")
            )
            self.assertEqual(1, len(receipt_files))
            encoded = receipt_files[0].read_text(encoding="utf-8")
            self.assertNotIn("organizational_approval_ref", encoded)
            self.assertNotIn("domain_approval_ref", encoded)
            with self.assertRaises(LiveRunBoundaryError) as error:
                claim_live_authorization(root, authorization, clock=lambda: NOW)
            self.assertEqual("authorization_already_used", error.exception.code)

    def test_foundry_live_entry_rejects_injected_transport_before_authentication(self):
        credential = Mock()
        adapter = FoundryAdapter(
            FoundryConfig(ENDPOINT, "gpt-5-mini"),
            credential=credential,
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        )
        with self.assertRaises(ProbeError) as error:
            adapter.execute_live_research(
                self.research_payload(),
                Mock(),
                BING,
                request_key=REQUEST_KEY,
                request_sha256=REQUEST_SHA256,
                source_ids=(SOURCE_ID,),
            )
        self.assertEqual("live_transport_required", error.exception.result["code"])
        credential.get_token.assert_not_called()

        default_adapter = FoundryAdapter(FoundryConfig(ENDPOINT, "gpt-5-mini"))
        with self.assertRaises(ProbeError) as error:
            default_adapter.execute_live_research(
                self.research_payload(),
                Mock(),
                BING,
                request_key=REQUEST_KEY,
                request_sha256=REQUEST_SHA256,
                source_ids=(SOURCE_ID,),
            )
        self.assertEqual("live_authorization_required", error.exception.result["code"])

    def test_foundry_live_entry_charges_once_and_retains_no_payload(self):
        with TemporaryDirectory() as directory:
            root = self.approved_root(directory)
            session = ManualLiveRunSession(self.load_approved(root), clock=lambda: NOW)
            adapter = FoundryAdapter(FoundryConfig(ENDPOINT, "gpt-5-mini"))
            response = {"id": "resp_live", "status": "completed", "output": []}
            summary = {"request_id": "req_live", "status": "completed"}
            with patch.object(adapter, "_request", return_value=(response, summary)) as call:
                body, observed = adapter.execute_live_research(
                    self.research_payload(),
                    session,
                    BING,
                    request_key=REQUEST_KEY,
                    request_sha256=REQUEST_SHA256,
                    source_ids=(SOURCE_ID,),
                )
            self.assertIs(response, body)
            self.assertEqual(1, call.call_count)
            self.assertEqual(1, session.queries_attempted)
            self.assertEqual("foundry_bing_research", observed["live_run"]["channel"])
            self.assertNotIn("input", json.dumps(session.audit_record()))

    def test_foundry_failure_stays_charged_and_bing_identity_is_pinned(self):
        with TemporaryDirectory() as directory:
            root = self.approved_root(directory)
            session = ManualLiveRunSession(self.load_approved(root), clock=lambda: NOW)
            adapter = FoundryAdapter(FoundryConfig(ENDPOINT, "gpt-5-mini"))
            changed = self.research_payload()
            changed["tools"][0]["bing_custom_search_preview"][
                "search_configurations"
            ][0]["instance_name"] = "different-instance"
            with self.assertRaises(ProbeError) as error:
                adapter.execute_live_research(
                    changed,
                    session,
                    BING,
                    request_key=REQUEST_KEY,
                    request_sha256=REQUEST_SHA256,
                    source_ids=(SOURCE_ID,),
                )
            self.assertEqual("invalid_request", error.exception.result["code"])
            self.assertEqual(0, session.queries_attempted)

            failure = ProbeError("timeout", "Model request timed out; not retried.")
            with patch.object(adapter, "_request", side_effect=failure) as call:
                with self.assertRaises(ProbeError):
                    adapter.execute_live_research(
                        self.research_payload(),
                        session,
                        BING,
                        request_key=REQUEST_KEY,
                        request_sha256=REQUEST_SHA256,
                        source_ids=(SOURCE_ID,),
                    )
            self.assertEqual(1, call.call_count)
            self.assertEqual(1, session.queries_attempted)
            self.assertEqual(1, len(session.attempts))

    def test_verification_rejects_tools_before_charging_budget(self):
        with TemporaryDirectory() as directory:
            root = self.approved_root(directory)
            session = ManualLiveRunSession(self.load_approved(root), clock=lambda: NOW)
            adapter = FoundryAdapter(FoundryConfig(ENDPOINT, "gpt-5-mini"))
            with self.assertRaises(ProbeError) as error:
                adapter.execute_live_verification(
                    self.research_payload(),
                    session,
                    request_key=REQUEST_KEY,
                    request_sha256=REQUEST_SHA256,
                    source_ids=(SOURCE_ID,),
                )
            self.assertEqual("invalid_request", error.exception.result["code"])
            self.assertEqual(0, session.queries_attempted)

            payload = self.research_payload()
            del payload["tools"]
            del payload["tool_choice"]
            response = {"id": "resp_verify", "status": "completed", "output": []}
            with patch.object(
                adapter,
                "_request",
                return_value=(response, {"status": "completed"}),
            ):
                body, observed = adapter.execute_live_verification(
                    payload,
                    session,
                    request_key=REQUEST_KEY,
                    request_sha256=REQUEST_SHA256,
                    source_ids=(SOURCE_ID,),
                )
            self.assertIs(response, body)
            self.assertEqual("foundry_source_verification", observed["live_run"]["channel"])
            self.assertEqual(1, session.queries_attempted)

    def test_source_fetch_boundary_rejects_mock_and_charges_exact_url(self):
        registry = SourceRegistry.load(ROOT / "config/sources/source-registry.json")
        mocked = ApprovedSourceClient(
            registry,
            client=httpx.Client(
                transport=httpx.MockTransport(lambda _: httpx.Response(200))
            ),
        )
        with self.assertRaises(LiveRunBoundaryError) as error:
            ManualLiveSourceClient(
                mocked,
                Mock(),
                request_key=REQUEST_KEY,
                request_sha256=REQUEST_SHA256,
            )
        self.assertEqual("live_transport_required", error.exception.code)
        mocked.client.close()

        with TemporaryDirectory() as directory:
            root = self.approved_root(directory)
            session = ManualLiveRunSession(self.load_approved(root), clock=lambda: NOW)
            source_client = ApprovedSourceClient(registry)
            with self.assertRaises(LiveRunBoundaryError) as error:
                ManualLiveSourceClient(
                    source_client,
                    Mock(),
                    request_key=REQUEST_KEY,
                    request_sha256=REQUEST_SHA256,
                )
            self.assertEqual("invalid_authorization", error.exception.code)
            live_client = ManualLiveSourceClient(
                source_client,
                session,
                request_key=REQUEST_KEY,
                request_sha256=REQUEST_SHA256,
            )
            url = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/mock"
            with patch.object(source_client, "fetch", return_value=sentinel.fetched) as fetch:
                result = live_client.fetch(url)
            source_client.close()
            self.assertIs(sentinel.fetched, result)
            fetch.assert_called_once_with(url)
            self.assertEqual(1, session.evidence_records_attempted)
            self.assertNotIn(url, json.dumps(session.audit_record()))

    @staticmethod
    def research_payload():
        return {
            "model": "gpt-5-mini",
            "instructions": "bounded test",
            "input": "bounded test",
            "tools": [
                {
                    "type": "bing_custom_search_preview",
                    "bing_custom_search_preview": {
                        "search_configurations": [
                            {
                                "project_connection_id": BING.connection_id,
                                "instance_name": BING.instance_name,
                                "count": 1,
                                "market": "en-HK",
                                "set_lang": "en",
                            }
                        ]
                    },
                }
            ],
            "tool_choice": "required",
            "reasoning": {"effort": "low"},
            "max_output_tokens": 100,
            "parallel_tool_calls": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "bounded_test",
                    "schema": {"type": "object"},
                    "strict": True,
                }
            },
            "store": False,
        }


if __name__ == "__main__":
    unittest.main()
