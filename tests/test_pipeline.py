from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from smart_nudge.foundry import BingConfig, ProbeError
from smart_nudge.pipeline import PocPipeline
from smart_nudge.rules import RulePack


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)
GOOD_URL = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/example"


def search_body(url=GOOD_URL, *, include_citation=True, title="Capital framework update"):
    document = {
        "schema_version": "1.0.0",
        "coverage_status": "checked",
        "items": [
            {
                "title": title,
                "publisher": "Hong Kong Monetary Authority",
                "published_date": "2026-09-10",
                "grounded_note": "The authority published an implementation update for regulated firms.",
                "citation_urls": [url],
            }
        ],
    }
    text = json.dumps(document, ensure_ascii=False)
    annotations = []
    if include_citation:
        start = text.index(url)
        annotations.append(
            {"type": "url_citation", "url": url, "title": title, "start_index": start, "end_index": start + len(url)}
        )
    return {
        "status": "completed",
        "output": [
            {"type": "bing_custom_search_preview_call", "status": "completed"},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text, "annotations": annotations}]},
        ],
    }


def mixed_quality_search_body():
    body = search_body()
    document = json.loads(body["output"][1]["content"][0]["text"])
    document["items"][0]["published_date"] = "September 10, 2026"
    document["items"].append({"title": "broken"})
    text = json.dumps(document, ensure_ascii=False)
    start = text.index(GOOD_URL)
    body["output"][1]["content"][0] = {
        "type": "output_text",
        "text": text,
        "annotations": [
            {"type": "url_citation", "url": GOOD_URL, "title": "Capital framework update", "start_index": start, "end_index": start + len(GOOD_URL)}
        ],
    }
    return body


def empty_search_body():
    text = json.dumps({"schema_version": "1.0.0", "coverage_status": "checked", "items": []})
    return {
        "status": "completed",
        "output": [
            {"type": "bing_custom_search_preview_call", "status": "completed"},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text, "annotations": []}]},
        ],
    }


def summary_body(source_id):
    document = {
        "schema_version": "1.0.0",
        "title": "Hong Kong Regulatory Pulse",
        "executive_summary": "One potentially relevant official update was identified.",
        "items": [
            {
                "source_item_ids": [source_id],
                "headline": "Implementation update merits review",
                "summary": "The authority published an implementation update.",
                "why_it_matters_to_aia": "AIA may wish to assess whether any regulated operations are in scope.",
            }
        ],
    }
    return {
        "status": "completed",
        "output": [
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps(document), "annotations": []}]}
        ],
    }


class FakeAdapter:
    def __init__(self, searches, summary=None):
        self.config = SimpleNamespace(model="gpt-5-mini")
        self.searches = list(searches)
        self.summary = summary
        self.search_payloads = []
        self.summary_payloads = []

    def execute_search(self, payload, _bing):
        self.search_payloads.append(payload)
        value = self.searches.pop(0)
        if isinstance(value, Exception):
            raise value
        return value, {"request_id": "req-search", "response_id": "resp-search", "usage": {"total_tokens": 10}}

    def execute_summary(self, payload):
        self.summary_payloads.append(payload)
        value = self.summary
        if callable(value):
            value = value(payload)
        if isinstance(value, Exception):
            raise value
        return value, {"request_id": "req-summary", "response_id": "resp-summary", "usage": {"total_tokens": 20}}


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule = RulePack.load(ROOT / "config/rules/hk-regulatory-pulse.json", ROOT)
        cls.bing = BingConfig("connection", "hk-financial-regulators-test", cls.rule.allowed_hosts)

    def pipeline(self, adapter):
        return PocPipeline(ROOT, self.rule, adapter, self.bing, clock=lambda: NOW)

    def test_end_to_end_deduplicates_and_creates_markdown(self):
        def make_summary(payload):
            source_id = json.loads(payload["input"])["source_notes"][0]["source_item_id"]
            return summary_body(source_id)

        adapter = FakeAdapter([search_body(), search_body()], make_summary)
        run = self.pipeline(adapter).run()

        self.assertTrue(run.ok)
        self.assertEqual(run.brief["status"], "completed")
        self.assertEqual(len(run.search_results["items"]), 1)
        self.assertEqual(len(run.brief["items"]), 1)
        self.assertIn("Why it matters to AIA", run.markdown)
        self.assertIn(GOOD_URL, run.markdown)
        self.assertEqual(len(adapter.search_payloads), 2)
        self.assertEqual(len(adapter.summary_payloads), 1)
        self.assertNotIn("tools", adapter.summary_payloads[0])

    def test_one_search_failure_produces_partial_brief(self):
        def make_summary(payload):
            source_id = json.loads(payload["input"])["source_notes"][0]["source_item_id"]
            return summary_body(source_id)

        adapter = FakeAdapter(
            [ProbeError("network", "failed"), search_body()], make_summary
        )
        run = self.pipeline(adapter).run()
        self.assertEqual(run.brief["status"], "partial")
        self.assertEqual(run.brief["coverage"]["queries_failed"], 1)

    def test_missing_native_citation_yields_empty_brief_without_summary_call(self):
        adapter = FakeAdapter([search_body(include_citation=False), empty_search_body()])
        run = self.pipeline(adapter).run()
        self.assertEqual(run.brief["status"], "empty")
        self.assertEqual(run.brief["items"], [])
        self.assertEqual(adapter.summary_payloads, [])

    def test_out_of_scope_citation_is_dropped_not_fatal(self):
        adapter = FakeAdapter(
            [search_body("https://example.com/update"), empty_search_body()]
        )
        run = self.pipeline(adapter).run()
        self.assertEqual(run.brief["status"], "empty")
        self.assertTrue(any("out-of-scope" in value for value in run.brief["warnings"]))

    def test_summary_failure_uses_deterministic_fallback(self):
        adapter = FakeAdapter(
            [search_body(), empty_search_body()], ProbeError("service_error", "failed")
        )
        run = self.pipeline(adapter).run()
        self.assertEqual(run.brief["status"], "partial")
        self.assertEqual(run.brief["summarization"]["status"], "fallback")
        self.assertEqual(run.brief["items"][0]["headline"], "Capital framework update")

    def test_malformed_item_and_date_do_not_discard_valid_item(self):
        def make_summary(payload):
            source_id = json.loads(payload["input"])["source_notes"][0]["source_item_id"]
            return summary_body(source_id)

        adapter = FakeAdapter([mixed_quality_search_body(), empty_search_body()], make_summary)
        run = self.pipeline(adapter).run()
        self.assertTrue(run.ok)
        self.assertEqual(len(run.search_results["items"]), 1)
        self.assertIsNone(run.search_results["items"][0]["published_date"])
        self.assertTrue(any("malformed item" in value for value in run.brief["warnings"]))

    def test_all_search_failures_do_not_create_a_brief(self):
        adapter = FakeAdapter(
            [ProbeError("network", "failed"), ProbeError("timeout", "failed")]
        )
        run = self.pipeline(adapter).run()
        self.assertFalse(run.ok)
        self.assertIsNone(run.brief)
        self.assertEqual(run.search_results["status"], "failed")


if __name__ == "__main__":
    unittest.main()
