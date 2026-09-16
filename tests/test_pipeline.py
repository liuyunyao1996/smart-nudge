from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from smart_nudge.foundry import AgentSearchConfig, BingConfig, ProbeError
from smart_nudge.pipeline import PocPipeline
from smart_nudge.rules import RulePack
from scripts.run_poc import _write_atomic


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
        cited_body = search_body(include_action_source=False)
        cited_body["output"][1:1] = [
            json.loads(json.dumps(cited_body["output"][0])) for _ in range(2)
        ]
        adapter = FakeAdapter(
            [empty_search_body(), cited_body]
            + [empty_search_body() for _ in range(3)],
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
        self.assertEqual(len(adapter.agent_search_payloads), 5)
        payload = adapter.agent_search_payloads[0]
        self.assertNotIn("model", payload)
        self.assertNotIn("tools", payload)
        self.assertNotIn("agent_reference", payload)
        self.assertNotIn("text", payload)
        self.assertEqual(payload["max_tool_calls"], 3)
        self.assertEqual(payload["include"], ["web_search_call.action.sources"])
        agent_input = payload["input"][0]["content"]
        self.assertIn("Return exactly one JSON object", agent_input)
        self.assertIn('"schema_version":{"const":"1.0.0"}', agent_input)
        self.assertIn("site:www.ia.org.hk", agent_input)
        self.assertNotIn("site:www.hkma.gov.hk", agent_input)
        self.assertNotIn("site:www.sfc.hk", agent_input)
        self.assertIn("3 Web Search tool calls TOTAL", agent_input)
        self.assertIn("do not combine them", agent_input)
        self.assertIn("Copy each citation_urls value exactly", agent_input)
        self.assertIn("valid empty envelope", agent_input)
        records = run.search_results["queries"]
        self.assertEqual([record["query_id"] for record in records], [
            "site-ia", "site-hkma", "site-sfc", "site-fstb", "site-gov",
        ])
        self.assertEqual(records[0]["base_query_ids"], ["en", "zh-hant"])
        self.assertEqual(records[0]["target_hosts"], ["www.ia.org.hk"])
        self.assertEqual(records[2]["target_hosts"], ["www.sfc.hk", "apps.sfc.hk"])
        self.assertEqual(records[1]["web_search_calls"], 3)
        diagnostic = records[1]["citation_diagnostics"]
        self.assertEqual(diagnostic["annotation_type_counts"], {"url_citation": 1})
        self.assertEqual(diagnostic["candidates"][0]["url_match_status"], "matched")
        self.assertEqual(diagnostic["local_validation"]["items_accepted"], 1)
        self.assertEqual(diagnostic["requested_include"], ["web_search_call.action.sources"])
        self.assertEqual(run.brief["coverage"]["queries_requested"], 5)
        self.assertEqual(len(run.search_results["items"]), 1)
        self.assertEqual(run.search_results["items"][0]["query_ids"], ["site-hkma"])
        self.assertIn("prompt-based", run.brief["disclaimer"])

    def test_agent_accepts_included_sources_without_annotations(self):
        agent = AgentSearchConfig("regulatory-web-search", "3", self.rule.allowed_hosts)
        value = search_body(include_annotation=False)
        def make_summary(payload):
            source_id = json.loads(payload["input"])["source_notes"][0]["source_item_id"]
            return summary_body(source_id)
        adapter = FakeAdapter([empty_search_body(), value] + [empty_search_body() for _ in range(3)], make_summary)
        run = PocPipeline(ROOT, self.rule, adapter, agent, clock=lambda: NOW).run()
        self.assertEqual(len(run.search_results["items"]), 1)
        self.assertEqual(len(adapter.summary_payloads), 1)
        diagnostic = run.search_results["queries"][1]["citation_diagnostics"]
        self.assertEqual(diagnostic["annotation_type_counts"], {})
        self.assertEqual(diagnostic["native_in_scope_url_count"], 1)

    def test_macao_and_mainland_share_hk_site_search_contract(self):
        for filename, site_ids, base_ids, language in (
            ("macao-regulatory-pulse.json", ["amcm", "bo"], ["en", "zh-hant"], "Traditional Chinese"),
            ("cn-mainland-regulatory-pulse.json", ["nfra", "pbc", "gov", "safe"], ["en", "zh-hans"], "Simplified Chinese"),
        ):
            with self.subTest(region=filename):
                rule = RulePack.load(ROOT / "config/rules" / filename, ROOT)
                agent = AgentSearchConfig("regulatory-web-search", "3", rule.allowed_hosts)
                adapter = FakeAdapter([empty_search_body() for _ in site_ids])
                run = PocPipeline(ROOT, rule, adapter, agent, clock=lambda: NOW).run()
                self.assertEqual(len(adapter.agent_search_payloads), len(site_ids))
                records = run.search_results["queries"]
                self.assertEqual([record["site_id"] for record in records], site_ids)
                self.assertEqual(run.brief["coverage"]["queries_succeeded"], len(site_ids))
                covered_hosts = []
                for record, payload in zip(records, adapter.agent_search_payloads):
                    covered_hosts.extend(record["target_hosts"])
                    self.assertEqual(record["base_query_ids"], base_ids)
                    self.assertEqual(payload["max_tool_calls"], 3)
                    self.assertEqual(payload["include"], ["web_search_call.action.sources"])
                    prompt = payload["input"][0]["content"]
                    self.assertIn(f"English / {language}", prompt)
                    self.assertIn("3 Web Search tool calls TOTAL", prompt)
                    self.assertIn(f"site:{record['target_hosts'][0]}", prompt)
                    self.assertIn("within the remaining call budget", prompt)
                    for host in record["target_hosts"]:
                        self.assertIn(host, prompt)
                    for other_host in set(rule.allowed_hosts) - set(record["target_hosts"]):
                        self.assertNotIn(f"site:{other_host}", prompt)
                    diagnostic = record["citation_diagnostics"]
                    self.assertEqual(diagnostic["requested_include"], payload["include"])
                    self.assertEqual(diagnostic["local_validation"]["status"], "succeeded")
                self.assertEqual(sorted(covered_hosts), sorted(rule.allowed_hosts))
                self.assertEqual(adapter.search_payloads, [])
                self.assertEqual(adapter.summary_payloads, [])

    def test_agent_plain_urls_without_native_metadata_still_rejected(self):
        agent = AgentSearchConfig("regulatory-web-search", "3", self.rule.allowed_hosts)
        value = search_body(include_annotation=False, include_action_source=False)
        adapter = FakeAdapter([empty_search_body(), value] + [empty_search_body() for _ in range(3)])
        run = PocPipeline(ROOT, self.rule, adapter, agent, clock=lambda: NOW).run()
        self.assertEqual(run.search_results["items"], [])
        self.assertEqual(adapter.summary_payloads, [])
        diagnostic = run.search_results["queries"][1]["citation_diagnostics"]
        self.assertEqual(diagnostic["candidates"][0]["urls"][0]["match_reason"], "no_native_in_scope_urls_extracted")

    def test_agent_search_rejects_more_than_three_web_search_calls(self):
        body = search_body()
        body["output"][1:1] = [json.loads(json.dumps(body["output"][0])) for _ in range(3)]
        agent = AgentSearchConfig("regulatory-web-search", "3", self.rule.allowed_hosts)
        adapter = FakeAdapter([body] + [empty_search_body() for _ in range(4)])

        run = PocPipeline(
            ROOT, self.rule, adapter, agent, clock=lambda: NOW
        ).run()

        self.assertEqual(run.brief["status"], "empty")
        record = run.search_results["queries"][0]
        self.assertEqual(record["web_search_calls"], 4)
        self.assertEqual(record["request_id"], "req-search")
        self.assertEqual(record["usage"]["total_tokens"], 10)
        self.assertEqual(record["citation_diagnostics"]["local_validation"]["code"], "search_call_limit_exceeded")
        self.assertTrue(
            any("search_call_limit_exceeded" in value for value in run.brief["warnings"])
        )

    def test_agent_search_drops_citations_outside_the_current_host_group(self):
        agent = AgentSearchConfig("regulatory-web-search", "3", self.rule.allowed_hosts)
        adapter = FakeAdapter(
            [search_body("https://www.sfc.hk/Regulatory-functions/update")]
            + [empty_search_body() for _ in range(4)]
        )
        run = PocPipeline(
            ROOT, self.rule, adapter, agent, clock=lambda: NOW
        ).run()

        self.assertEqual(run.brief["status"], "empty")
        self.assertEqual(run.search_results["items"], [])
        self.assertTrue(
            any("out-of-scope citation host" in value for value in run.brief["warnings"])
        )

    def test_agent_call_budget_can_be_lowered_in_the_rule_pack(self):
        document = json.loads(json.dumps(self.rule.document))
        document["search"]["agent"]["max_tool_calls_per_site"] = 2
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rule.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            rule = RulePack.load(path, ROOT)
        body = empty_search_body()
        body["output"][1:1] = [json.loads(json.dumps(body["output"][0])) for _ in range(2)]
        adapter = FakeAdapter([body] + [empty_search_body() for _ in range(4)])
        agent = AgentSearchConfig("regulatory-web-search", "3", rule.allowed_hosts)
        run = PocPipeline(ROOT, rule, adapter, agent, clock=lambda: NOW).run()
        self.assertTrue(all(payload["max_tool_calls"] == 2 for payload in adapter.agent_search_payloads))
        self.assertEqual(run.search_results["queries"][0]["code"], "search_call_limit_exceeded")
        self.assertEqual(run.search_results["queries"][0]["web_search_calls"], 3)
        self.assertEqual(run.brief["coverage"]["queries_failed"], 1)

    def test_agent_invalid_json_keeps_persisted_citation_diagnostics(self):
        value = search_body()
        value["output"][1]["content"][0]["text"] = "PRIVATE_INVALID_RESPONSE"
        agent = AgentSearchConfig("regulatory-web-search", "3", self.rule.allowed_hosts)
        adapter = FakeAdapter([empty_search_body(), value] + [empty_search_body() for _ in range(3)])
        run = PocPipeline(ROOT, self.rule, adapter, agent, clock=lambda: NOW).run()
        with tempfile.TemporaryDirectory() as directory:
            _write_atomic(Path(directory) / "search-results.json", json.dumps(run.search_results))
            saved = json.loads((Path(directory) / "search-results.json").read_text(encoding="utf-8"))
        diagnostic = saved["queries"][1]["citation_diagnostics"]
        self.assertEqual(diagnostic["candidate_parse_status"], "invalid_json")
        self.assertEqual(diagnostic["native_in_scope_url_count"], 1)
        self.assertEqual(diagnostic["local_validation"]["code"], "invalid_search_json")
        self.assertNotIn("PRIVATE_INVALID_RESPONSE", json.dumps(saved))

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

    def test_rollback_accepts_optional_dates_and_index_sources_on_both_approaches(self):
        cases = [
            (GOOD_URL, "2026-08-01", "date_out_of_window"),
            (GOOD_URL, "2026-09-14", "date_out_of_window"),
            (GOOD_URL, None, "date_unknown"),
            ("https://www.hkma.gov.hk/eng/news-and-media/press-releases/", "2026-09-10", "index_only_source"),
            ("https://www.hkma.gov.hk/random.pdf", "2026-09-10", "source_type_unknown"),
        ]
        for agent_path in (False, True):
            for url, value, reason in cases:
                with self.subTest(agent_path=agent_path, reason=reason):
                    body = search_body(url)
                    part = body["output"][1]["content"][0]
                    document = json.loads(part["text"])
                    document["items"][0]["published_date"] = value
                    part["text"] = json.dumps(document)
                    if agent_path:
                        searches = [empty_search_body(), body] + [empty_search_body() for _ in range(3)]
                        config = AgentSearchConfig("regulatory-web-search", "3", self.rule.allowed_hosts)
                        record_index = 1
                    else:
                        searches, config, record_index = [body, empty_search_body()], self.bing, 0
                    def make_summary(payload):
                        notes = json.loads(payload["input"])["source_notes"]
                        return summary_body(notes[0]["source_item_id"])
                    adapter = FakeAdapter(searches, make_summary)
                    run = PocPipeline(ROOT, self.rule, adapter, config, clock=lambda: NOW).run()
                    self.assertEqual(len(run.search_results["items"]), 1)
                    self.assertEqual(len(adapter.summary_payloads), 1)
                    self.assertEqual(run.search_results["items"][0]["published_date"], value)
                    record = run.search_results["queries"][record_index]
                    self.assertNotIn("admission_diagnostics", record)
                    self.assertEqual(record["citation_diagnostics"]["local_validation"]["items_accepted"], 1)
                    for payload in adapter.search_payloads + adapter.agent_search_payloads:
                        prompt = payload.get("instructions", "") + str(payload.get("input", ""))
                        self.assertNotIn("Source admission rules", prompt)
                        self.assertNotIn("Omit items with unknown publication dates", prompt)



if __name__ == "__main__":
    unittest.main()
