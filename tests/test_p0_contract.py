"""P0 contract regression tests. Synthetic cases are specifications, not model scores."""

import copy
import unittest

from scripts.validate_p0 import ROOT, load_assets, read_json, unique_pairs, validate_assets, validate_result


class P0ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = load_assets()
        cls.example = read_json(ROOT / "examples/intelligence-result.synthetic.json")

    def setUp(self):
        self.result = copy.deepcopy(self.example)

    def assert_valid(self):
        self.assertEqual([], validate_result(self.result, self.assets))

    def assert_invalid(self, text):
        errors = validate_result(self.result, self.assets)
        self.assertTrue(any(text in error for error in errors), errors)

    def make_watch(self):
        finding = self.result["findings"][0]
        finding.update(decision="watch", decision_code="watch_material_unverified", evidence_status="signal_only")
        self.result["claims"][0]["verification"] = "unverified"
        self.result["claims"][0]["supports"][0]["checked_by"] = "not_checked"

    def test_assets_are_consistent(self):
        self.assertEqual([], validate_assets(self.assets))

    def test_synthetic_example_is_valid(self):
        self.assert_valid()

    def test_all_six_topics_have_research_questions(self):
        topics = self.assets["taxonomy"]["topics"]
        self.assertEqual(6, len(topics))
        for topic in topics:
            self.assertGreaterEqual(len(topic["questions"]), 3)

    def test_twenty_cases_are_not_misrepresented_as_expert_labels(self):
        cases = self.assets["cases"]
        self.assertEqual(20, len(cases["cases"]))
        self.assertEqual("assistant", cases["annotation_author"])
        self.assertEqual("not_run_against_agent", cases["execution_status"])
        self.assertEqual("draft_pending_domain_review", cases["annotation_status"])

    def test_scope_excludes_product_features(self):
        excluded = set(self.assets["profile"]["excluded_features"])
        self.assertTrue({"scheduler", "chat", "notifications", "frontend"} <= excluded)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ValueError):
            unique_pairs([("key", 1), ("key", 2)])

    def test_unknown_fields_rejected(self):
        self.result["confidence_probability"] = 0.99
        self.assert_invalid("Additional properties")

    def test_blank_text_rejected(self):
        self.result["findings"][0]["why_aia"] = "   "
        self.assert_invalid("schema/")

    def test_naive_datetime_rejected(self):
        self.result["run"]["as_of"] = "2026-09-02T09:00:00"
        self.assert_invalid("schema/run/as_of")

    def test_invalid_calendar_date_rejected(self):
        self.result["events"][0]["effective_date"] = "2026-02-30"
        self.assert_invalid("schema/events")

    def test_empty_or_reversed_time_window_rejected(self):
        self.result["run"]["window"]["start"] = self.result["run"]["window"]["end"]
        self.assert_invalid("invalid run time ordering")

    def test_config_version_mismatch_rejected(self):
        self.result["profile_version"] = "0.0.0"
        self.assert_invalid("version mismatch")

    def test_unknown_market_rejected(self):
        self.result["run"]["scope"]["market_ids"] = ["ZZ"]
        self.assert_invalid("unknown requested scope")

    def test_omitted_mandatory_source_rejected(self):
        self.result["run"]["scope"]["source_classes"] = ["professional_media"]
        self.assert_invalid("mandatory source class omitted")

    def test_unknown_entity_rejected(self):
        self.result["events"][0]["entity_ids"] = ["unknown-company"]
        self.assert_invalid("unresolved entity")

    def test_cross_market_event_rejected(self):
        self.result["events"][0]["market_ids"] = ["CN"]
        self.assert_invalid("event outside requested scope")

    def test_unresolved_evidence_reference_rejected(self):
        self.result["claims"][0]["supports"][0]["evidence_id"] = "missing"
        self.assert_invalid("unknown evidence")

    def test_duplicate_ids_rejected(self):
        self.result["evidence"].append(copy.deepcopy(self.result["evidence"][0]))
        self.assert_invalid("duplicate evidence_id")

    def test_unsupported_claim_cannot_be_selected(self):
        self.result["claims"][0]["verification"] = "unverified"
        self.assert_invalid("selected finding contains unverified")

    def test_context_link_is_not_support(self):
        self.result["claims"][0]["supports"][0]["relation"] = "context_only"
        self.assert_invalid("lacks checked supporting evidence")

    def test_unchecked_link_is_not_verification(self):
        self.result["claims"][0]["supports"][0]["checked_by"] = "not_checked"
        self.assert_invalid("lacks checked supporting evidence")

    def test_reported_allegation_cannot_be_presented_as_selected_fact(self):
        self.result["claims"][0]["kind"] = "reported_allegation"
        self.assert_invalid("or allegations")

    def test_material_unverified_signal_is_valid_watch_item(self):
        self.make_watch()
        self.assert_valid()

    def test_conflict_cannot_be_silently_called_supported(self):
        self.result["claims"][0]["supports"].append({
            "evidence_id": "e-synthetic-1", "relation": "refutes", "locator": "different paragraph",
            "checked_by": "fixture_author", "note": "Unresolved contradiction in synthetic evidence."
        })
        self.assert_invalid("unresolved counterevidence")

    def test_claim_must_belong_to_finding_event(self):
        self.result["findings"][0]["analysis"]["basis_claim_ids"] = ["unknown-claim"]
        self.assert_invalid("claims outside its event")

    def test_corroboration_not_inferred_from_link_count(self):
        second = copy.deepcopy(self.result["evidence"][0])
        second.update(evidence_id="e-synthetic-2", url="https://syndication.example/story")
        self.result["evidence"].append(second)
        link = copy.deepcopy(self.result["claims"][0]["supports"][0])
        link["evidence_id"] = second["evidence_id"]
        self.result["claims"][0]["supports"].append(link)
        self.result["findings"][0]["evidence_status"] = "independently_corroborated"
        self.assert_invalid("independent origins")
        second["origin_group_id"] = "independent-origin-2"
        self.assert_valid()

    def test_social_post_cannot_be_marked_primary_support(self):
        self.result["evidence"][0]["source_class"] = "public_social_sample"
        self.assert_invalid("declared primary source")

    def test_reason_code_must_match_decision(self):
        self.result["findings"][0]["decision_code"] = "ignore_low_value"
        self.assert_invalid("decision and reason code disagree")

    def test_low_materiality_cannot_be_selected(self):
        self.result["findings"][0]["importance"] = "low"
        self.assert_invalid("low-importance")

    def test_old_event_is_not_selected_as_new(self):
        self.result["events"][0].update(change_type="unchanged", previous_event_id="historical-record-1")
        self.assert_invalid("unchanged event")

    def test_correction_must_link_to_previous_record(self):
        self.result["events"][0]["change_type"] = "corrected"
        self.assert_invalid("consistent history reference")
        self.result["events"][0]["previous_event_id"] = "historical-record-1"
        self.assert_valid()

    def test_future_available_evidence_cannot_enter_backtest(self):
        self.result["evidence"][0]["available_at"] = "2026-09-03T00:00:00+08:00"
        self.assert_invalid("historical cutoff")

    def test_future_effective_date_is_allowed(self):
        self.result["events"][0]["effective_date"] = "2027-01-01"
        self.assert_valid()

    def test_unknown_effective_date_is_allowed(self):
        self.result["events"][0]["effective_date"] = None
        self.assert_valid()

    def test_live_result_cannot_contain_synthetic_evidence(self):
        self.result["data_kind"] = "live"
        self.assert_invalid("synthetic evidence")
        self.assert_invalid("fixture author")

    def test_metadata_only_source_cannot_store_excerpt(self):
        self.result["evidence"][0]["retention"] = "approved_metadata_only"
        self.assert_invalid("must not store excerpts")

    def test_bing_source_requires_native_citation(self):
        self.result["evidence"][0]["origin"] = "bing_grounding"
        self.assert_invalid("native citation provenance")

    def test_non_http_citations_rejected(self):
        self.result["evidence"][0]["url"] = "javascript:alert(1)"
        self.assert_invalid("schema/evidence")

    def test_local_citations_rejected(self):
        for url in ("http://localhost/", "http://127.0.0.1/", "http://169.254.169.254/"):
            with self.subTest(url=url):
                self.result["evidence"][0]["url"] = url
                self.assert_invalid("must not target")

    def test_citation_credentials_rejected(self):
        self.result["evidence"][0]["url"] = "https://user:password@regulator.example/"
        self.assert_invalid("without credentials")

    def test_missing_coverage_cell_rejected(self):
        self.result["run"]["scope"]["market_ids"].append("CN")
        self.assert_invalid("coverage matrix incomplete")

    def test_duplicate_coverage_cell_rejected(self):
        self.result["coverage"].append(copy.deepcopy(self.result["coverage"][0]))
        self.assert_invalid("coverage matrix incomplete")

    def test_missing_language_not_complete_coverage(self):
        self.result["coverage"][0]["languages_checked"] = ["en"]
        self.assert_invalid("omits required languages")

    def test_coverage_gap_requires_partial_status(self):
        self.result["coverage"][0].update(status="unavailable", languages_checked=[], detail="Synthetic source inaccessible")
        self.assert_invalid("cannot conceal coverage gaps")
        self.result["run"].update(status="partial", stop_reason="required_source_unavailable")
        self.assert_valid()

    def test_partial_requires_explanation(self):
        self.result["run"]["status"] = "partial"
        self.assert_invalid("must explain")

    def test_completed_can_have_zero_findings(self):
        for key in ("evidence", "claims", "events", "findings"):
            self.result[key] = []
        self.result["run"]["stop_reason"] = "no_new_independent_information"
        self.assert_valid()

    def test_failed_cannot_publish_findings(self):
        self.result["run"].update(status="failed", stop_reason="technical_failure", errors=["synthetic provider error"])
        self.assert_invalid("must not publish findings")
        self.result["findings"] = []
        self.assert_valid()

    def test_exhausted_budget_not_called_completed(self):
        self.result["run"]["stop_reason"] = "budget_exhausted"
        self.assert_invalid("incomplete stop reason")


if __name__ == "__main__":
    unittest.main()
