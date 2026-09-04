import copy
from datetime import datetime
import json
from pathlib import Path
import unittest

from scripts.validate_p0 import load_assets, validate_result
from smart_nudge.research import (
    ContractVerificationRole,
    CoveragePlanner,
    FixtureResearchRole,
    ResearchBatch,
    ResearchController,
    ResearchLoopError,
    ResearchRequest,
    load_offline_case,
    read_json,
)
from smart_nudge.skills import SkillLoader
from smart_nudge.sources import SourceRegistry


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "evals" / "p4" / "regulatory-loop.synthetic.json"
NOW = datetime.fromisoformat("2026-09-04T09:00:00+08:00")


def case(case_id):
    return load_offline_case(FIXTURE_PATH, case_id)


def run_case(document):
    return ResearchController(
        ROOT,
        FixtureResearchRole(document["rounds"]),
        clock=lambda: NOW,
    ).run(document["request"])


class RequestAndCoverageTests(unittest.TestCase):
    def test_request_requires_ordered_timezone_aware_window(self):
        document = case("P4A-01-supported-final-rule")["request"]
        document["window"]["start"] = document["window"]["end"]
        with self.assertRaises(ResearchLoopError) as error:
            ResearchRequest.validate(document, ROOT)
        self.assertEqual("invalid_request", error.exception.code)

    def test_offline_request_cannot_enable_live_or_unapproved_scope(self):
        for field, value in (("mode", "live"), ("allow_draft_skills", False)):
            document = case("P4A-01-supported-final-rule")["request"]
            document[field] = value
            with self.subTest(field=field), self.assertRaises(ResearchLoopError) as error:
                ResearchRequest.validate(document, ROOT)
            self.assertEqual("invalid_request", error.exception.code)
        document = case("P4A-01-supported-final-rule")["request"]
        document["scope"]["source_classes"] = ["professional_media"]
        with self.assertRaises(ResearchLoopError):
            ResearchRequest.validate(document, ROOT)

    def test_policy_caps_followups_queries_and_evidence(self):
        for key, value in (
            ("max_followup_rounds_per_event", 3),
            ("max_queries", 31),
            ("max_evidence_records", 101),
        ):
            document = case("P4A-01-supported-final-rule")["request"]
            document["budget"][key] = value
            with self.subTest(key=key), self.assertRaises(ResearchLoopError):
                ResearchRequest.validate(document, ROOT)

    def test_coverage_plan_is_market_topic_source_language_cross_product(self):
        document = case("P4A-01-supported-final-rule")["request"]
        document["scope"]["market_ids"] = ["HK", "CN", "MY"]
        request = ResearchRequest.validate(document, ROOT)
        loader = SkillLoader(ROOT)
        bundles = {
            market: loader.select(
                topic_id=request.topic_id,
                event_type=request.event_type,
                market_id=market,
                include_drafts=True,
            )
            for market in request.market_ids
        }
        registry = SourceRegistry.load(ROOT / "config" / "sources" / "source-registry.json")
        plan = CoveragePlanner(ROOT, registry).build(request, bundles)
        self.assertEqual(3, len(plan.cells))
        self.assertEqual(6, len(plan.tasks))
        self.assertEqual(
            {"HK:regulatory-change:official:zh-Hant", "HK:regulatory-change:official:en",
             "CN:regulatory-change:official:zh-Hans", "CN:regulatory-change:official:en",
             "MY:regulatory-change:official:en", "MY:regulatory-change:official:ms"},
            {task["task_id"] for task in plan.tasks},
        )
        self.assertTrue(all(task["force_company_name"] is False for task in plan.tasks))
        self.assertTrue(all(task["source_ids"] for task in plan.tasks))


class ClosedLoopFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = load_assets()
        cls.fixture = read_json(FIXTURE_PATH)

    def test_each_checked_in_case_matches_expected_and_p0_contract(self):
        self.assertEqual(3, len(self.fixture["cases"]))
        for document in self.fixture["cases"]:
            with self.subTest(case=document["case_id"]):
                outcome = run_case(document)
                result = outcome.result
                expected = document["expected"]
                decision = result["findings"][0]["decision"] if result["findings"] else None
                self.assertEqual(expected["status"], result["run"]["status"])
                self.assertEqual(expected["stop_reason"], result["run"]["stop_reason"])
                self.assertEqual(expected["decision"], decision)
                self.assertEqual(expected["queries_executed"], outcome.budget_usage["queries_executed"])
                self.assertEqual(expected["followup_rounds_executed"], outcome.budget_usage["followup_rounds_executed"])
                self.assertEqual([], validate_result(result, self.assets))

    def test_primary_support_is_recomputed_not_trusted_from_research(self):
        document = case("P4A-01-supported-final-rule")
        claims = document["rounds"][0]["discoveries"][0]["claims"]
        self.assertTrue(all(claim["verification"] == "unverified" for claim in claims))
        outcome = run_case(document)
        self.assertTrue(all(claim["verification"] == "supported" for claim in outcome.result["claims"]))
        self.assertEqual("primary_supported", outcome.result["findings"][0]["evidence_status"])

    def test_context_only_signal_is_downgraded_despite_upstream_label(self):
        document = case("P4A-02-insufficient-consultation")
        self.assertEqual("supported", document["rounds"][0]["discoveries"][0]["claims"][0]["verification"])
        outcome = run_case(document)
        self.assertEqual("unverified", outcome.result["claims"][0]["verification"])
        self.assertEqual("unverifiable", outcome.result["findings"][0]["evidence_status"])
        self.assertEqual("watch", outcome.result["findings"][0]["decision"])

    def test_trace_and_plan_contain_no_evidence_or_generated_text(self):
        outcome = run_case(case("P4A-01-supported-final-rule"))
        audit = json.dumps({"plan": outcome.coverage_plan, "trace": outcome.trace}, ensure_ascii=False)
        self.assertNotIn("Synthetic fixture text", audit)
        self.assertNotIn("claim-p4a-duty", audit)
        self.assertNotIn("e-p4a-primary-rule", audit)
        self.assertIn("queries_executed", audit)

    def test_checked_coverage_requires_every_planned_language(self):
        document = case("P4A-01-supported-final-rule")
        document["rounds"][0]["coverage_updates"][0]["languages_checked"] = ["en"]
        outcome = run_case(document)
        self.assertEqual("failed", outcome.result["run"]["status"])
        self.assertEqual("technical_failure", outcome.result["run"]["stop_reason"])
        self.assertEqual([], outcome.result["findings"])
        self.assertIn("coverage_contract", outcome.result["run"]["errors"][0])

    def test_no_findings_with_complete_coverage_is_a_valid_completed_run(self):
        document = case("P4A-01-supported-final-rule")
        document["rounds"] = [{
            "queries_executed": 2,
            "coverage_updates": document["rounds"][0]["coverage_updates"],
            "discoveries": [],
        }]
        outcome = run_case(document)
        self.assertEqual("completed", outcome.result["run"]["status"])
        self.assertEqual("no_new_independent_information", outcome.result["run"]["stop_reason"])
        self.assertEqual([], outcome.result["findings"])

    def test_complete_ignored_assessment_does_not_exhaust_followup_budget(self):
        document = case("P4A-01-supported-final-rule")
        document["request"]["budget"]["max_followup_rounds_per_event"] = 0
        document["rounds"][0]["discoveries"][0]["candidate"]["recommended_disposition"] = "ignore"
        outcome = run_case(document)
        self.assertEqual("completed", outcome.result["run"]["status"])
        self.assertEqual("sufficient_evidence", outcome.result["run"]["stop_reason"])
        self.assertEqual("ignored", outcome.result["findings"][0]["decision"])
        self.assertEqual(0, outcome.budget_usage["followup_rounds_executed"])

    def test_primary_status_is_derived_from_document_role_and_publisher(self):
        document = case("P4A-01-supported-final-rule")
        discovery = document["rounds"][0]["discoveries"][0]
        self.assertTrue(discovery["candidate"]["evidence_assessment"]["primary_document_obtained"])
        discovery["evidence"][0]["document_role"] = "discovery_signal"
        outcome = run_case(document)
        self.assertEqual("signal_only", outcome.result["findings"][0]["evidence_status"])
        self.assertEqual("watch", outcome.result["findings"][0]["decision"])

        document = case("P4A-01-supported-final-rule")
        document["rounds"][0]["discoveries"][0]["evidence"][0]["publisher"] = "Different Synthetic Issuer"
        outcome = run_case(document)
        self.assertEqual("signal_only", outcome.result["findings"][0]["evidence_status"])
        self.assertEqual("watch", outcome.result["findings"][0]["decision"])


class BudgetAndStoppingTests(unittest.TestCase):
    def test_query_budget_stops_before_accepting_oversized_batch(self):
        document = case("P4A-01-supported-final-rule")
        document["request"]["budget"]["max_queries"] = 1
        outcome = run_case(document)
        self.assertEqual("partial", outcome.result["run"]["status"])
        self.assertEqual("budget_exhausted", outcome.result["run"]["stop_reason"])
        self.assertEqual(0, outcome.budget_usage["queries_executed"])
        self.assertEqual([], outcome.result["evidence"])
        self.assertEqual([], outcome.result["findings"])

    def test_evidence_budget_stops_before_accepting_oversized_batch(self):
        document = case("P4A-01-supported-final-rule")
        document["request"]["budget"]["max_evidence_records"] = 1
        discovery = document["rounds"][0]["discoveries"][0]
        second = copy.deepcopy(discovery["evidence"][0])
        second.update(evidence_id="e-p4a-second", origin_group_id="synthetic-origin-second")
        discovery["evidence"].append(second)
        outcome = run_case(document)
        self.assertEqual("budget_exhausted", outcome.result["run"]["stop_reason"])
        self.assertEqual(0, outcome.budget_usage["evidence_records"])

    def test_round_cap_produces_partial_watch_result(self):
        document = case("P4A-02-insufficient-consultation")
        document["request"]["budget"]["max_followup_rounds_per_event"] = 0
        outcome = run_case(document)
        self.assertEqual("partial", outcome.result["run"]["status"])
        self.assertEqual("budget_exhausted", outcome.result["run"]["stop_reason"])
        self.assertEqual("watch", outcome.result["findings"][0]["decision"])
        self.assertEqual(0, outcome.budget_usage["followup_rounds_executed"])

    def test_same_origin_republication_is_not_new_independent_information(self):
        document = case("P4A-02-insufficient-consultation")
        discovery = copy.deepcopy(document["rounds"][0]["discoveries"][0])
        repeated = copy.deepcopy(discovery["evidence"][0])
        repeated["evidence_id"] = "e-p4a-republication"
        discovery["evidence"] = [repeated]
        document["rounds"][1]["discoveries"] = [discovery]
        outcome = run_case(document)
        self.assertEqual("no_new_independent_information", outcome.result["run"]["stop_reason"])
        self.assertEqual(2, len(outcome.result["evidence"]))
        self.assertEqual(0, outcome.trace[-1]["new_origin_groups"])

    def test_followup_can_promote_signal_when_primary_support_arrives(self):
        document = case("P4A-02-insufficient-consultation")
        initial = document["rounds"][0]["discoveries"][0]
        followup = copy.deepcopy(initial)
        candidate = followup["candidate"]
        candidate.update(
            document_status="consultation",
            publication_date="2026-09-02",
            change_from_prior_rule="A fictional consultation proposes a synthetic change; it is not in force.",
            recommended_disposition="proceed_to_verification",
        )
        candidate["evidence_assessment"].update(state="primary_supported", primary_document_obtained=True)
        primary = copy.deepcopy(followup["evidence"][0])
        primary.update(
            evidence_id="e-p4a-consultation-primary",
            origin_group_id="synthetic-consultation-primary",
            url="https://fictional-mainland-regulator.example/consultations/syn-original",
            title="Synthetic original consultation",
            document_role="primary_document",
            excerpt="Synthetic original consultation fixture text.",
        )
        followup["evidence"] = [primary]
        claim = copy.deepcopy(followup["claims"][0])
        claim["supports"].append({
            "evidence_id": primary["evidence_id"],
            "relation": "supports",
            "locator": "paragraph:2",
            "checked_by": "fixture_author",
            "note": "Synthetic original supports consultation publication status.",
        })
        followup["claims"] = [claim]
        document["rounds"][1]["discoveries"] = [followup]
        outcome = run_case(document)
        self.assertEqual("sufficient_evidence", outcome.result["run"]["stop_reason"])
        self.assertEqual("selected", outcome.result["findings"][0]["decision"])
        self.assertEqual(1, outcome.budget_usage["followup_rounds_executed"])

    def test_followup_limit_is_tracked_per_event(self):
        document = case("P4A-02-insufficient-consultation")
        document["request"]["budget"]["max_followup_rounds_per_event"] = 1
        second = copy.deepcopy(document["rounds"][0]["discoveries"][0])
        second["event"]["event_id"] = "event-p4a-consultation-002"
        second["presentation"]["finding_id"] = "finding-p4a-consultation-002"
        second["evidence"][0].update(
            evidence_id="e-p4a-event2-index",
            origin_group_id="synthetic-index-entry-002",
            url="https://fictional-mainland-regulator.example/index/syn-consultation-2",
        )
        second["claims"][0].update(claim_id="claim-p4a-event2-signal")
        second["claims"][0]["supports"][0]["evidence_id"] = "e-p4a-event2-index"
        second["candidate"]["evidence_assessment"]["supporting_claim_ids"] = ["claim-p4a-event2-signal"]
        document["rounds"] = [
            document["rounds"][0],
            {"queries_executed": 1, "coverage_updates": [], "discoveries": [second]},
            {"queries_executed": 1, "coverage_updates": [], "discoveries": []},
        ]
        outcome = run_case(document)
        self.assertEqual(2, outcome.budget_usage["followup_rounds_executed"])
        self.assertEqual(
            {"event-p4a-consultation-001": 1, "event-p4a-consultation-002": 1},
            outcome.budget_usage["event_followup_rounds"],
        )

    def test_research_role_cannot_return_an_exhausted_event(self):
        document = case("P4A-02-insufficient-consultation")
        document["request"]["budget"]["max_followup_rounds_per_event"] = 1
        first = document["rounds"][0]["discoveries"][0]
        second = copy.deepcopy(first)
        second["event"]["event_id"] = "event-p4a-consultation-budget-002"
        second["presentation"]["finding_id"] = "finding-p4a-consultation-budget-002"
        second["evidence"][0].update(
            evidence_id="e-p4a-budget-event2-index",
            origin_group_id="synthetic-budget-index-002",
            url="https://fictional-mainland-regulator.example/index/syn-budget-2",
        )
        second["claims"][0].update(claim_id="claim-p4a-budget-event2-signal")
        second["claims"][0]["supports"][0]["evidence_id"] = "e-p4a-budget-event2-index"
        second["candidate"]["evidence_assessment"]["supporting_claim_ids"] = [
            "claim-p4a-budget-event2-signal"
        ]
        document["rounds"] = [
            document["rounds"][0],
            {"queries_executed": 1, "coverage_updates": [], "discoveries": [second]},
            {"queries_executed": 1, "coverage_updates": [], "discoveries": [first]},
        ]
        outcome = run_case(document)
        self.assertEqual("failed", outcome.result["run"]["status"])
        self.assertEqual([], outcome.result["findings"])
        self.assertIn("followup_budget", outcome.result["run"]["errors"][0])


class FailureBoundaryTests(unittest.TestCase):
    def test_controller_rejects_invalid_query_count_from_any_research_role(self):
        class InvalidQueryCountRole:
            role_version = "invalid-query-count-role@test"

            def __init__(self, value):
                self.value = value

            def research(self, context):
                return ResearchBatch(self.value, (), ())

        document = case("P4A-01-supported-final-rule")["request"]
        for value in (-1, True):
            controller = ResearchController(
                ROOT,
                InvalidQueryCountRole(value),
                clock=lambda: NOW,
            )
            with self.subTest(value=value):
                outcome = controller.run(document)
                self.assertEqual("failed", outcome.result["run"]["status"])
                self.assertEqual(0, outcome.budget_usage["queries_executed"])
                self.assertIn("research_contract", outcome.result["run"]["errors"][0])

    def test_controlled_research_failure_publishes_no_findings(self):
        document = case("P4A-01-supported-final-rule")
        document["rounds"] = [{"error": "synthetic secret detail"}]
        outcome = run_case(document)
        self.assertEqual("failed", outcome.result["run"]["status"])
        self.assertEqual("technical_failure", outcome.result["run"]["stop_reason"])
        self.assertEqual([], outcome.result["findings"])
        self.assertNotIn("synthetic secret detail", json.dumps(outcome.result))

    def test_live_or_nonofficial_evidence_is_rejected(self):
        for field, value in (("origin", "independent_public_source"), ("source_class", "professional_media")):
            document = case("P4A-01-supported-final-rule")
            document["rounds"][0]["discoveries"][0]["evidence"][0][field] = value
            with self.subTest(field=field):
                outcome = run_case(document)
                self.assertEqual("failed", outcome.result["run"]["status"])
                self.assertEqual([], outcome.result["findings"])
                self.assertIn("offline_boundary", outcome.result["run"]["errors"][0])

    def test_real_url_cannot_be_disguised_as_synthetic_evidence(self):
        document = case("P4A-01-supported-final-rule")
        document["rounds"][0]["discoveries"][0]["evidence"][0]["url"] = "https://www.ia.org.hk/real"
        outcome = run_case(document)
        self.assertEqual("failed", outcome.result["run"]["status"])
        self.assertEqual([], outcome.result["evidence"])
        self.assertIn("offline_boundary", outcome.result["run"]["errors"][0])

    def test_candidate_cannot_borrow_claims_from_another_event(self):
        document = case("P4A-01-supported-final-rule")
        borrower = copy.deepcopy(document["rounds"][0]["discoveries"][0])
        borrower["event"]["event_id"] = "event-p4a-borrower"
        borrower["presentation"]["finding_id"] = "finding-p4a-borrower"
        borrower["claims"] = []
        borrower["evidence"] = []
        document["rounds"][0]["discoveries"].append(borrower)
        outcome = run_case(document)
        self.assertEqual("failed", outcome.result["run"]["status"])
        self.assertEqual([], outcome.result["findings"])
        self.assertIn("verification_contract", outcome.result["run"]["errors"][0])

    def test_technical_failure_preserves_accepted_evidence_usage(self):
        document = case("P4A-02-insufficient-consultation")
        document["rounds"][1] = {"error": "synthetic second-round failure"}
        outcome = run_case(document)
        self.assertEqual("failed", outcome.result["run"]["status"])
        self.assertEqual([], outcome.result["evidence"])
        self.assertEqual(1, outcome.budget_usage["evidence_records"])
        self.assertEqual(2, outcome.budget_usage["queries_executed"])

    def test_invalid_candidate_becomes_technical_failure_not_a_finding(self):
        document = case("P4A-01-supported-final-rule")
        document["rounds"][0]["discoveries"][0]["candidate"]["document_status"] = "consultation"
        outcome = run_case(document)
        self.assertEqual("failed", outcome.result["run"]["status"])
        self.assertEqual([], outcome.result["findings"])
        self.assertIn("analysis_contract", outcome.result["run"]["errors"][0])

    def test_refuting_checked_link_prevents_selection(self):
        document = case("P4A-01-supported-final-rule")
        claim = document["rounds"][0]["discoveries"][0]["claims"][0]
        refute = copy.deepcopy(claim["supports"][0])
        refute.update(relation="refutes", locator="paragraph:3", note="Synthetic conflicting passage.")
        claim["supports"].append(refute)
        outcome = run_case(document)
        self.assertEqual("watch", outcome.result["findings"][0]["decision"])
        self.assertEqual("conflicted", outcome.result["findings"][0]["evidence_status"])
        self.assertEqual("no_new_independent_information", outcome.result["run"]["stop_reason"])

    def test_same_event_id_cannot_change_identity_across_rounds(self):
        document = case("P4A-02-insufficient-consultation")
        repeated = copy.deepcopy(document["rounds"][0]["discoveries"][0])
        repeated["presentation"]["finding_id"] = "finding-different"
        document["rounds"][1]["discoveries"] = [repeated]
        outcome = run_case(document)
        self.assertEqual("failed", outcome.result["run"]["status"])
        self.assertEqual([], outcome.result["findings"])
        self.assertIn("research_contract", outcome.result["run"]["errors"][0])

    def test_same_event_id_cannot_change_regulatory_identity_or_history(self):
        mutations = (
            ("candidate", "issuer", "Different Synthetic Authority"),
            ("candidate", "document_title", "Different Synthetic Instrument"),
            ("candidate", "jurisdiction", "Different Synthetic Jurisdiction"),
            ("candidate", "instrument_id", "SYN-DIFFERENT-INSTRUMENT"),
            ("candidate", "publication_date", None),
            ("candidate", "effective_date", "2028-01-01"),
            ("event", "entity_ids", ["aia-cn-business"]),
            ("event", "change_type", "updated"),
            ("event", "previous_event_id", "event-different-history"),
        )
        for section, field, value in mutations:
            document = case("P4A-01-supported-final-rule")
            first = document["rounds"][0]["discoveries"][0]
            first["evidence"][0]["document_role"] = "discovery_signal"
            repeated = copy.deepcopy(first)
            repeated[section][field] = value
            document["rounds"].append({
                "queries_executed": 1,
                "coverage_updates": [],
                "discoveries": [repeated],
            })
            with self.subTest(section=section, field=field):
                outcome = run_case(document)
                self.assertEqual("failed", outcome.result["run"]["status"])
                self.assertEqual([], outcome.result["findings"])
                self.assertIn("research_contract", outcome.result["run"]["errors"][0])

    def test_repeated_event_allows_only_monotonic_identity_enrichment_and_keeps_earliest_seen(self):
        document = case("P4A-02-insufficient-consultation")
        repeated = copy.deepcopy(document["rounds"][0]["discoveries"][0])
        repeated["candidate"].update(
            document_status="consultation",
            instrument_id="SYN-CONSULTATION-001",
            publication_date="2026-09-02",
            consultation_deadline="2026-10-01",
            transition_period={
                "start_date": None,
                "end_date": None,
                "description": "Synthetic timing remains to be established.",
            },
        )
        repeated["event"]["first_seen_at"] = "2026-09-03T07:40:00+08:00"
        document["rounds"][1]["discoveries"] = [repeated]
        outcome = run_case(document)
        self.assertEqual("completed", outcome.result["run"]["status"])
        self.assertEqual("2026-09-03T07:40:00+08:00", outcome.result["events"][0]["first_seen_at"])
        self.assertEqual("2026-09-02", outcome.result["events"][0]["event_date"])

    def test_final_result_contract_failure_is_returned_safely(self):
        document = case("P4A-01-supported-final-rule")
        document["rounds"][0]["discoveries"][0]["presentation"]["importance"] = "impossible"
        outcome = run_case(document)
        self.assertEqual("failed", outcome.result["run"]["status"])
        self.assertEqual("technical_failure", outcome.result["run"]["stop_reason"])
        self.assertEqual([], outcome.result["evidence"])
        self.assertEqual([], outcome.result["findings"])
        self.assertIn("result_contract", outcome.result["run"]["errors"][0])

    def test_naive_controller_clock_is_rejected(self):
        document = case("P4A-01-supported-final-rule")
        controller = ResearchController(
            ROOT, FixtureResearchRole(document["rounds"]), clock=lambda: datetime(2026, 9, 4, 9, 0, 0)
        )
        with self.assertRaises(ResearchLoopError) as error:
            controller.run(document["request"])
        self.assertEqual("invalid_clock", error.exception.code)

    def test_fixture_collection_must_remain_synthetic(self):
        document = read_json(FIXTURE_PATH)
        document["data_kind"] = "live"
        self.assertNotEqual("synthetic", document["data_kind"])
        verifier = ContractVerificationRole()
        with self.assertRaises(ResearchLoopError) as error:
            verifier.verify((), {"e": {"origin": "independent_public_source"}}, {})
        self.assertEqual("offline_boundary", error.exception.code)


if __name__ == "__main__":
    unittest.main()
