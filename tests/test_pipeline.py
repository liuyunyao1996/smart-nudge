from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from smart_nudge.foundry import AgentSearchConfig, BingConfig, ProbeError
from smart_nudge.pipeline import PocPipeline
from smart_nudge.rules import RulePack


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)
GOOD_URL = "https://www.hkma.gov.hk/eng/news-and-media/press-releases/2026/example"


def search_body(
    url=GOOD_URL,
    *,
    include_annotation=True,
    include_action_source=True,
    title="Capital framework update",
):
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
    if include_annotation:
        start = text.index(url)
        annotations.append(
            {"type": "url_citation", "url": url, "title": title, "start_index": start, "end_index": start + len(url)}
        )
    return {
        "status": "completed",
        "output": [
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {
                    "type": "search",
                    "sources": ([{"type": "url", "url": url}] if include_action_source else []),
                },
            },
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
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {"type": "search", "sources": []},
            },
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text, "annotations": []}]},
        ],
    }


def summary_body(
    source_id,
    *,
    attention_level="high",
    signal_type="final_rule",
    attention_reason="A final regulatory requirement has direct relevance and merits prompt review.",
):
    document = {
        "schema_version": "1.1.0",
        "title": "Hong Kong Regulatory Pulse",
        "executive_summary": "One potentially relevant official update was identified.",
        "items": [
            {
                "source_item_ids": [source_id],
                "headline": "Implementation update merits review",
                "summary": "The authority published an implementation update.",
                "why_it_matters_to_aia": "AIA may wish to assess whether any regulated operations are in scope.",
                "attention_level": attention_level,
                "signal_type": signal_type,
                "attention_reason": attention_reason,
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
        self.agent_search_payloads = []
        self.summary_payloads = []

    def execute_search(self, payload, _bing):
        self.search_payloads.append(payload)
        value = self.searches.pop(0)
        if isinstance(value, Exception):
            raise value
        return value, {"request_id": "req-search", "response_id": "resp-search", "usage": {"total_tokens": 10}}

    def execute_agent_search(self, payload, _agent):
        self.agent_search_payloads.append(payload)
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
        self.assertEqual(run.brief["schema_version"], "1.1.0")
        self.assertEqual(len(run.search_results["items"]), 1)
        self.assertEqual(len(run.brief["items"]), 1)
        self.assertEqual(run.brief["items"][0]["attention_level"], "high")
        self.assertEqual(run.brief["items"][0]["signal_type"], "final_rule")
        self.assertIn("**Attention:** HIGH | FINAL RULE", run.markdown)
        self.assertIn("Attention rationale", run.markdown)
        self.assertIn("Why it matters to AIA", run.markdown)
        self.assertIn(GOOD_URL, run.markdown)
        self.assertEqual(len(adapter.search_payloads), 2)
        self.assertEqual(len(adapter.summary_payloads), 1)
        self.assertNotIn("tools", adapter.summary_payloads[0])
        self.assertEqual(
            adapter.search_payloads[0]["tools"],
            [
                {
                    "type": "web_search",
                    "custom_search_configuration": {
                        "project_connection_id": "connection",
                        "instance_name": "hk-financial-regulators-test",
                    },
                }
            ],
        )
        self.assertEqual(
            adapter.search_payloads[0]["include"],
            ["web_search_call.action.sources"],
        )
        search_schema = adapter.search_payloads[0]["text"]["format"]["schema"]
        summary_schema = adapter.summary_payloads[0]["text"]["format"]["schema"]
        self.assertEqual(
            search_schema["properties"]["schema_version"], {"enum": ["1.0.0"]}
        )
        self.assertEqual(
            summary_schema["properties"]["schema_version"], {"enum": ["1.1.0"]}
        )
        summary_item = summary_schema["$defs"]["item"]["properties"]
        self.assertEqual(summary_item["attention_level"]["enum"], ["high", "medium", "low"])
        self.assertEqual(
            summary_item["signal_type"]["enum"],
            ["final_rule", "enforcement", "consultation", "guidance", "informational"],
        )
        self.assertNotIn('"const"', json.dumps(search_schema))
        self.assertNotIn('"const"', json.dumps(summary_schema))

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

    def test_agent_search_is_site_scoped_and_accepts_native_annotations(self):
        def make_summary(payload):
            source_id = json.loads(payload["input"])["source_notes"][0]["source_item_id"]
            return summary_body(source_id)

        agent = AgentSearchConfig("regulatory-web-search", "3", self.rule.allowed_hosts)
        adapter = FakeAdapter(
            [search_body(include_action_source=False)]
            + [empty_search_body() for _ in range(5)],
            make_summary,
        )
        run = PocPipeline(
            ROOT, self.rule, adapter, agent, clock=lambda: NOW
        ).run()

        self.assertTrue(run.ok)
        self.assertEqual(run.search_results["search"]["approach"], "foundry-agent")
        self.assertEqual(
            run.search_results["search"]["agent"],
            {"name": "regulatory-web-search", "version": "3"},
        )
        self.assertEqual(len(adapter.agent_search_payloads), 6)
        payload = adapter.agent_search_payloads[0]
        self.assertNotIn("model", payload)
        self.assertNotIn("tools", payload)
        self.assertNotIn("agent_reference", payload)
        self.assertNotIn("text", payload)
        self.assertEqual(payload["max_tool_calls"], 1)
        agent_input = payload["input"][0]["content"]
        self.assertIn("Return exactly one JSON object", agent_input)
        self.assertIn('"schema_version":{"const":"1.0.0"}', agent_input)
        self.assertIn("site:www.ia.org.hk", agent_input)
        self.assertIn("site:www.hkma.gov.hk", agent_input)
        self.assertNotIn("site:www.sfc.hk", agent_input)
        records = run.search_results["queries"]
        self.assertEqual([record["query_id"] for record in records[:3]], [
            "en-sites-1",
            "en-sites-2",
            "en-sites-3",
        ])
        self.assertEqual(records[0]["base_query_id"], "en")
        self.assertEqual(records[0]["target_hosts"], ["www.ia.org.hk", "www.hkma.gov.hk"])
        self.assertEqual(run.brief["coverage"]["queries_requested"], 6)
        self.assertEqual(len(run.search_results["items"]), 1)
        self.assertIn("prompt-based", run.brief["disclaimer"])

    def test_agent_search_rejects_multiple_web_search_calls(self):
        body = search_body()
        body["output"].insert(1, json.loads(json.dumps(body["output"][0])))
        agent = AgentSearchConfig("regulatory-web-search", "3", self.rule.allowed_hosts)
        adapter = FakeAdapter([body] + [empty_search_body() for _ in range(5)])

        run = PocPipeline(
            ROOT, self.rule, adapter, agent, clock=lambda: NOW
        ).run()

        self.assertEqual(run.brief["status"], "empty")
        self.assertTrue(
            any("search_call_limit_exceeded" in value for value in run.brief["warnings"])
        )

    def test_agent_search_drops_citations_outside_the_current_host_group(self):
        agent = AgentSearchConfig("regulatory-web-search", "3", self.rule.allowed_hosts)
        adapter = FakeAdapter(
            [search_body("https://www.sfc.hk/Regulatory-functions/update")]
            + [empty_search_body() for _ in range(5)]
        )
        run = PocPipeline(
            ROOT, self.rule, adapter, agent, clock=lambda: NOW
        ).run()

        self.assertEqual(run.brief["status"], "empty")
        self.assertEqual(run.search_results["items"], [])
        self.assertTrue(
            any("out-of-scope citation host" in value for value in run.brief["warnings"])
        )

    def test_missing_native_action_source_yields_empty_brief_without_summary_call(self):
        adapter = FakeAdapter(
            [search_body(include_action_source=False), empty_search_body()]
        )
        run = self.pipeline(adapter).run()
        self.assertEqual(run.brief["status"], "empty")
        self.assertEqual(run.brief["items"], [])
        self.assertEqual(adapter.summary_payloads, [])

    def test_action_source_accepts_item_without_message_annotation(self):
        def make_summary(payload):
            source_id = json.loads(payload["input"])["source_notes"][0]["source_item_id"]
            return summary_body(source_id)

        adapter = FakeAdapter(
            [search_body(include_annotation=False), empty_search_body()], make_summary
        )
        run = self.pipeline(adapter).run()

        self.assertTrue(run.ok)
        self.assertEqual(run.search_results["items"][0]["source_links"][0]["url"], GOOD_URL)

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
        self.assertEqual(run.brief["items"][0]["attention_level"], "medium")
        self.assertEqual(run.brief["items"][0]["signal_type"], "unclassified")

    def test_high_attention_is_downgraded_for_non_binding_signal(self):
        def make_summary(payload):
            source_id = json.loads(payload["input"])["source_notes"][0]["source_item_id"]
            return summary_body(
                source_id,
                attention_level="high",
                signal_type="consultation",
                attention_reason="A consultation may affect future requirements.",
            )

        adapter = FakeAdapter([search_body(), empty_search_body()], make_summary)
        run = self.pipeline(adapter).run()

        self.assertEqual(run.brief["status"], "partial")
        self.assertEqual(run.brief["items"][0]["attention_level"], "medium")
        self.assertIn("not a final rule", run.brief["items"][0]["attention_reason"])
        self.assertTrue(any("downgraded item" in value for value in run.brief["warnings"]))

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
