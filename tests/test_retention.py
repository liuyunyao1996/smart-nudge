"""Offline tests for the P1 deny-by-default data-use policy."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from smart_nudge.retention import DataUsePolicyError, load_data_use_policy, make_search_probe_audit


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "policies" / "p1-public-web-data-use.json"


class RetentionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_data_use_policy(POLICY_PATH)

    def write_policy(self, policy):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "policy.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        return path

    def test_checked_in_policy_is_valid_and_conservative(self):
        self.assertFalse(self.policy["bing_grounding"]["persist_raw_response"])
        self.assertFalse(self.policy["bing_grounding"]["use_for_model_evaluation"])
        self.assertEqual("approved_metadata_only",
                         self.policy["publisher_overrides"]["www.ia.org.hk"]["retention"])

    def test_audit_omits_generated_and_raw_content(self):
        result = {
            "ok": True,
            "check": "search",
            "code": "no_citations",
            "message": "safe diagnostic",
            "request_id": "req_test",
            "output_text": "copyrighted or Bing-generated answer",
            "raw_response": {"secret": "content"},
            "tool_output": ["snippet"],
            "citations": [{"url": "https://www.ia.org.hk/en/example", "title": "Example"}],
            "factual_verification": "pending_manual_review",
        }
        audit = make_search_probe_audit(result, self.policy)
        self.assertNotIn("output_text", audit)
        self.assertNotIn("raw_response", audit)
        self.assertNotIn("tool_output", audit)
        self.assertEqual(result["citations"], audit["citations"])
        self.assertEqual("no_citations", audit["code"])
        self.assertEqual("safe diagnostic", audit["message"])
        self.assertFalse(audit["output_text_retained"])
        self.assertFalse(audit["raw_response_retained"])
        self.assertFalse(audit["raw_tool_output_retained"])

    def test_audit_does_not_mutate_native_references(self):
        citation = {"url": "https://www.ia.org.hk/en/example", "title": "Official release",
                    "start_index": 1, "end_index": 8}
        result = {"citations": [citation]}
        audit = make_search_probe_audit(result, self.policy)
        audit["citations"][0]["title"] = "changed locally"
        self.assertEqual("Official release", result["citations"][0]["title"])

    def test_policy_cannot_enable_raw_response_persistence(self):
        changed = deepcopy(self.policy)
        changed["bing_grounding"]["persist_raw_response"] = True
        with self.assertRaises(DataUsePolicyError):
            load_data_use_policy(self.write_policy(changed))

    def test_policy_cannot_enable_model_evaluation(self):
        changed = deepcopy(self.policy)
        changed["bing_grounding"]["use_for_model_evaluation"] = True
        with self.assertRaises(DataUsePolicyError):
            load_data_use_policy(self.write_policy(changed))

    def test_policy_cannot_treat_snippet_as_original(self):
        changed = deepcopy(self.policy)
        changed["official_source"]["search_snippet_counts_as_original"] = True
        with self.assertRaises(DataUsePolicyError):
            load_data_use_policy(self.write_policy(changed))

    def test_policy_cannot_bypass_access_denial(self):
        changed = deepcopy(self.policy)
        changed["official_source"]["on_robots_or_access_denial"] = "retry_with_browser_impersonation"
        with self.assertRaises(DataUsePolicyError):
            load_data_use_policy(self.write_policy(changed))

    def test_output_text_cannot_be_whitelisted_for_audit(self):
        changed = deepcopy(self.policy)
        changed["local_probe_audit"]["allowed_fields"].append("output_text")
        with self.assertRaises(DataUsePolicyError):
            load_data_use_policy(self.write_policy(changed))

    def test_policy_cannot_enable_crawl_or_search_database(self):
        for field in ("use_as_crawl_seed_or_link_index", "build_search_output_database"):
            changed = deepcopy(self.policy)
            changed["bing_grounding"][field] = True
            with self.subTest(field=field), self.assertRaises(DataUsePolicyError):
                load_data_use_policy(self.write_policy(changed))

    def test_policy_requires_approved_answer_and_exact_reference_treatment(self):
        for field, value in (("persist_generated_answer", "always"),
                             ("persist_references", "rewritten")):
            changed = deepcopy(self.policy)
            changed["bing_grounding"][field] = value
            with self.subTest(field=field), self.assertRaises(DataUsePolicyError):
                load_data_use_policy(self.write_policy(changed))

    def test_policy_requires_public_input_exclusions(self):
        changed = deepcopy(self.policy)
        changed["query_policy"]["prohibited_inputs"].remove("credentials")
        with self.assertRaises(DataUsePolicyError):
            load_data_use_policy(self.write_policy(changed))

    def test_policy_requires_ia_metadata_only_override(self):
        changed = deepcopy(self.policy)
        changed["publisher_overrides"]["www.ia.org.hk"]["retention"] = "approved_excerpt"
        with self.assertRaises(DataUsePolicyError):
            load_data_use_policy(self.write_policy(changed))


if __name__ == "__main__":
    unittest.main()
