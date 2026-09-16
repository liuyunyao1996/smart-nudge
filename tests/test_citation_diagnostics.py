import json
import unittest

from smart_nudge.citation_diagnostics import LIMIT, build_citation_diagnostics
from smart_nudge.pipeline import _canonical_url


URL = "https://www.hkma.gov.hk/eng/update"


def body(candidate=URL, sources=None, annotations=None):
    return {"output": [
        {"type": "web_search_call", "status": "completed", "action": {
            "type": "search", "sources": sources if sources is not None else [{"type": "url", "url": URL}],
        }},
        {"type": "message", "role": "assistant", "content": [{
            "type": "output_text",
            "text": json.dumps({"items": [{"citation_urls": [candidate], "title": "DO_NOT_RETAIN_TITLE"}]}),
            "annotations": annotations or [],
        }]},
    ]}


def diagnose(value):
    return build_citation_diagnostics(value, ["www.hkma.gov.hk"], _canonical_url, use_annotations=True)


class CitationDiagnosticsTests(unittest.TestCase):
    def test_exact_source_and_annotation_matches(self):
        for value in [body(), body(sources=[], annotations=[{"type": "url_citation", "url": URL}])]:
            result = diagnose(value)
            self.assertEqual(result["native_in_scope_url_count"], 1)
            self.assertEqual(result["candidates"][0]["url_match_status"], "matched")
            self.assertEqual(result["candidates"][0]["urls"][0]["match_reason"], "exact_native_url_match")
            self.assertNotIn("DO_NOT_RETAIN_TITLE", json.dumps(result))

    def test_missing_sources_and_annotations_are_distinguishable(self):
        value = body(sources=[])
        result = diagnose(value)
        self.assertEqual(result["action_source_list_count"], 1)
        self.assertEqual(result["native_in_scope_url_count"], 0)
        self.assertEqual(result["candidates"][0]["urls"][0]["match_reason"], "no_native_in_scope_urls_extracted")
        del value["output"][0]["action"]["sources"]
        self.assertEqual(diagnose(value)["action_source_list_count"], 0)

    def test_query_differences_are_reported_without_query_values(self):
        result = diagnose(body(candidate=URL + "?token=PRIVATE_QUERY_VALUE#PRIVATE_FRAGMENT"))
        entry = result["candidates"][0]["urls"][0]
        self.assertEqual(entry["match_reason"], "query_or_port_differs")
        self.assertEqual(entry["url"], URL)
        self.assertTrue(entry["query_present"])
        self.assertNotEqual(entry["canonical_url_sha256"], result["references"][0]["canonical_url_sha256"])
        self.assertNotIn("PRIVATE_QUERY_VALUE", json.dumps(result))
        self.assertNotIn("PRIVATE_FRAGMENT", json.dumps(result))

    def test_path_difference_is_not_accepted(self):
        result = diagnose(body(candidate=URL + "/"))
        self.assertEqual(result["candidates"][0]["urls"][0]["match_reason"], "full_url_not_in_native_set")
        self.assertEqual(result["candidates"][0]["url_match_status"], "no_match")

    def test_unrecognized_reference_types_do_not_contribute(self):
        result = diagnose(body(sources=[{"type": "NEW_PRIVATE_TYPE", "url": URL}], annotations=[{"type": "NEW_PRIVATE_TYPE", "url": URL}]))
        self.assertEqual(result["action_source_type_counts"], {"other": 1})
        self.assertEqual(result["annotation_type_counts"], {"other": 1})
        self.assertEqual(result["native_in_scope_url_count"], 0)
        self.assertNotIn("NEW_PRIVATE_TYPE", json.dumps(result))

    def test_credentials_off_scope_and_http_are_rejected(self):
        for url, reason in [
            ("https://private-user:PRIVATE_PASSWORD@www.hkma.gov.hk/update", "credential_url_rejected"),
            ("https://example.com/PRIVATE_PATH?x=PRIVATE_QUERY", "out_of_scope_url"),
            (URL.replace("https:", "http:"), "invalid_or_non_https_url"),
        ]:
            result = diagnose(body(candidate=url))
            self.assertEqual(result["candidates"][0]["urls"][0]["match_reason"], reason)
            self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertEqual(diagnose(body(candidate=None))["candidates"][0]["urls"][0]["match_reason"], "non_string_url")

    def test_invalid_json_still_records_reference_metadata(self):
        value = body()
        value["output"][1]["content"][0]["text"] = "PRIVATE_INVALID_RESPONSE"
        result = diagnose(value)
        self.assertEqual(result["candidate_parse_status"], "invalid_json")
        self.assertEqual(result["native_in_scope_url_count"], 1)
        self.assertNotIn("PRIVATE_INVALID_RESPONSE", json.dumps(result))

    def test_records_are_bounded(self):
        value = body(sources=[{"type": "url", "url": URL}] * (LIMIT + 1))
        value["output"][1]["content"][0]["text"] = json.dumps({"items": [{"citation_urls": [URL]}] * (LIMIT + 1)})
        result = diagnose(value)
        self.assertEqual(len(result["references"]), LIMIT)
        self.assertEqual(len(result["candidates"]), LIMIT)
        self.assertTrue(result["references_truncated"])
        self.assertTrue(result["candidates_truncated"])

    def test_envelope_checks_disclose_no_untrusted_values(self):
        value = body()
        value["output"][1]["content"][0]["text"] = json.dumps({
            "schema_version": "PRIVATE_VERSION", "coverage_status": "PRIVATE_COVERAGE",
            "PRIVATE_EXTRA_FIELD": "PRIVATE_VALUE", "items": [],
        })
        result = diagnose(value)
        checks = result["envelope_checks"]
        self.assertFalse(checks["schema_version_valid"])
        self.assertFalse(checks["coverage_status_valid"])
        self.assertEqual(checks["unexpected_field_count"], 1)
        self.assertNotIn("PRIVATE_", json.dumps(result))
