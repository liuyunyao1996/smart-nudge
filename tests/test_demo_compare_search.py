from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from demo.build_report import (
    build_document,
    comparison_verdict,
    load_report_config,
    render_html,
    timestamp_suffix,
    write_report,
)
from demo.run_custom_bing_search import DEFAULT_CONFIG as CUSTOM_CONFIG
from demo.run_custom_bing_search import dry_run as custom_dry_run
from demo.run_ordinary_web_search import DEFAULT_CONFIG as ORDINARY_CONFIG
from demo.run_ordinary_web_search import dry_run as ordinary_dry_run
from demo.search_common import extract_search_result


NOW = datetime(2026, 10, 20, 3, 12, 45, tzinfo=timezone.utc)


class DemoComparisonTests(unittest.TestCase):
    def test_method_configs_resolve_complete_and_distinct_requests(self):
        ordinary = ordinary_dry_run(ORDINARY_CONFIG, NOW)
        custom = custom_dry_run(CUSTOM_CONFIG, NOW)
        ordinary_input = ordinary["resolved_request"]["input"][0]["content"]
        custom_input = custom["resolved_request"]["input"]
        self.assertIn("site:www.ia.org.hk", ordinary_input)
        self.assertNotIn("site:www.ia.org.hk", custom_input)
        self.assertEqual(ordinary["resolved_request"]["max_tool_calls"], 1)
        tool = custom["resolved_request"]["tools"][0]
        self.assertEqual(tool["type"], "web_search")
        self.assertEqual(
            tool["custom_search_configuration"]["instance_name"],
            "hk-financial-regulators-test",
        )

    def test_extracts_and_deduplicates_native_sources(self):
        body = {
            "status": "completed",
            "output": [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {
                        "sources": [
                            {"type": "url", "title": "IA item", "url": "https://www.ia.org.hk/a#part"},
                            {"type": "url", "title": "Outside", "url": "https://example.com/b"},
                        ]
                    },
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Answer",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "title": "IA duplicate",
                                    "url": "https://www.ia.org.hk/a",
                                }
                            ],
                        }
                    ],
                },
            ],
        }
        result = extract_search_result(
            body,
            {"request_id": "request-1"},
            ("www.ia.org.hk", "www.hkma.gov.hk"),
        )
        self.assertEqual(result["answer"], "Answer")
        self.assertEqual(result["tool_calls"], {"total": 1, "completed": 1})
        self.assertEqual(result["metrics"]["native_source_count"], 2)
        self.assertEqual(result["metrics"]["in_target_scope_count"], 1)
        self.assertEqual(result["sources"][0]["evidence_types"], ["action_source", "url_citation"])

    def test_timestamp_suffix_is_compact_utc(self):
        self.assertEqual(
            timestamp_suffix("2026-10-20T03:12:45Z"),
            "20261020T031245Z",
        )

    def test_verdict_distinguishes_observed_and_capability_only(self):
        ordinary = {
            "status": "completed",
            "metrics": {"native_source_count": 1, "in_target_scope_count": 0, "out_of_scope_count": 1},
        }
        custom = {
            "status": "completed",
            "metrics": {"native_source_count": 2, "in_target_scope_count": 2, "out_of_scope_count": 0},
        }
        self.assertEqual(comparison_verdict(ordinary, custom)["code"], "difference_observed")
        ordinary["metrics"] = {"native_source_count": 1, "in_target_scope_count": 1, "out_of_scope_count": 0}
        self.assertEqual(comparison_verdict(ordinary, custom)["code"], "boundary_difference_only")

    @staticmethod
    def _artifact(method_id: str, *, outside: bool = False) -> dict:
        host = "example.com" if outside else "www.ia.org.hk"
        return {
            "schema_version": "1.0.0",
            "artifact_type": "search_path_result",
            "method_id": method_id,
            "label": "Path",
            "scope_control": "soft",
            "generated_at": "2026-10-20T03:12:45Z",
            "config_file": f"{method_id}.json",
            "task": {
                "topic": "Topic",
                "result_limit": 5,
                "window": {"start_date": "2026-09-20", "end_date": "2026-10-20", "timezone": "Asia/Hong_Kong"},
                "target_hosts": ["www.ia.org.hk"],
            },
            "request": {
                "instructions": None,
                "input": "<prompt>",
                "parameters": {"store": False},
                "note": "Note",
            },
            "status": "completed",
            "answer": "<script>alert(1)</script>",
            "tool_calls": {"total": 1, "completed": 1},
            "metrics": {
                "native_source_count": 1,
                "in_target_scope_count": 0 if outside else 1,
                "out_of_scope_count": 1 if outside else 0,
                "in_target_scope_percent": 0 if outside else 100,
                "source_hosts": [host],
            },
            "sources": [
                {
                    "title": "Source",
                    "url": f"https://{host}/item",
                    "host": host,
                    "in_target_scope": not outside,
                    "evidence_types": ["action_source"],
                }
            ],
        }

    def test_report_is_built_only_from_comparable_json_artifacts(self):
        ordinary = self._artifact("ordinary_web_search", outside=True)
        custom = self._artifact("custom_bing_search")
        document = build_document(
            ordinary,
            custom,
            load_report_config(),
            "2026-10-20T03:12:45Z",
        )
        html = render_html(document)
        self.assertEqual(document["run_id"], "search-compare-20261020T031245Z")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("Non-compliant: outside target websites", html)
        self.assertIn("What was searched", html)
        self.assertIn("How this path searches", html)
        self.assertIn("Native search results", html)
        self.assertNotIn("This run shows a clear difference", html)
        self.assertNotIn("How to interpret this report", html)
        self.assertNotIn("<h1>", html)
        mismatched = deepcopy(custom)
        mismatched["task"]["topic"] = "Different topic"
        with self.assertRaisesRegex(RuntimeError, "task.topic differs"):
            build_document(ordinary, mismatched, load_report_config(), "2026-10-20T03:12:45Z")

        with TemporaryDirectory() as directory:
            outputs = write_report(
                ordinary,
                custom,
                load_report_config(),
                Path(directory),
                "2026-10-20T03:12:45Z",
            )
            self.assertEqual(outputs["comparison"].name, "comparison-20261020T031245Z.json")
            self.assertEqual(outputs["report"].name, "report-20261020T031245Z.html")
            self.assertTrue(outputs["comparison"].is_file())
            self.assertTrue(outputs["report"].is_file())


if __name__ == "__main__":
    unittest.main()
