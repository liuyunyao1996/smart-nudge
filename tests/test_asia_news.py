from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from scripts.run_poc import main
from smart_nudge.foundry import BingConfig, FoundryConfig
from smart_nudge.pipeline import PocError, PocPipeline, _url_specificity
from smart_nudge.rules import RulePack


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)


def search_body(
    url, published_date, *, title, publisher, market, signal_type, topic,
    subject_type="aia", content_type="corporate", event_scope="firm_specific",
    entities=None,
):
    document = {
        "schema_version": "1.2.0",
        "coverage_status": "checked",
        "items": [{
            "title": title,
            "publisher": publisher,
            "published_date": published_date,
            "grounded_note": "A cited development was reported with potential relevance to Asian insurance markets.",
            "citation_urls": [url],
            "market": market,
            "entities": entities or ["AIA"],
            "topic": topic,
            "signal_type": signal_type,
            "subject_type": subject_type,
            "content_type": content_type,
            "event_scope": event_scope,
        }],
    }
    text = json.dumps(document)
    start = text.index(url)
    return {
        "status": "completed",
        "output": [
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {"type": "search", "sources": [{"type": "url", "url": url}]},
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": text,
                    "annotations": [{
                        "type": "url_citation",
                        "url": url,
                        "title": title,
                        "start_index": start,
                        "end_index": start + len(url),
                    }],
                }],
            },
        ],
    }


class FakeAdapter:
    def __init__(self, searches):
        self.config = SimpleNamespace(model="gpt-5-mini")
        self.searches = list(searches)
        self.search_configs = []
        self.summary_source_notes = []

    def execute_search(self, _payload, config):
        self.search_configs.append(config.instance_name)
        return self.searches.pop(0), {"request_id": "req", "response_id": "resp", "usage": {}}

    def execute_summary(self, payload):
        self.summary_source_notes = json.loads(payload["input"])["source_notes"]
        source_id = self.summary_source_notes[0]["source_item_id"]
        document = {
            "schema_version": "1.4.0",
            "title": "Asia Insurance Executive News",
            "executive_summary": "One material in-window development merits attention.",
            "evaluations": [
                {
                    "source_item_ids": [note["source_item_id"]],
                    "importance_level": "high" if index == 0 else "low",
                    "importance_reason": "Directly relevant to AIA." if index == 0 else "Limited executive impact.",
                }
                for index, note in enumerate(self.summary_source_notes)
            ],
            "items": [{
                "source_item_ids": [source_id],
                "title": "AIA launches a new regional offering",
                "summary": "The cited source describes a material AIA development.",
                "detail_bullets": [
                    "The development directly concerns AIA.",
                    "Its financial materiality is not established by the supplied note.",
                ],
                "timing_or_action": None,
                "potential_impact": "The development may influence AIA's regional positioning.",
                "attention_level": "high",
                "topic": "external_environment",
                "signal_type": "aia_major_news",
                "content_type": "corporate",
            }],
        }
        body = {
            "status": "completed",
            "output": [{
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(document), "annotations": []}],
            }],
        }
        return body, {"request_id": "summary", "response_id": "summary", "usage": {}}


class AsiaNewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule = RulePack.load(ROOT / "config/rules/asia-executive-news.json", ROOT)
        cls.configs = tuple(
            BingConfig(
                "connection",
                item["instance_name"],
                tuple(source["host"] for source in item["sources"]),
                item["configuration_id"],
            )
            for item in cls.rule.bing_configurations
        )

    def test_dry_run_has_four_instances_seven_queries_and_rejects_agent(self):
        self.assertEqual(self.rule.version, "1.5.1")
        output = StringIO()
        with redirect_stdout(output):
            status = main(["--rule", "config/rules/asia-executive-news.json"])
        document = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(document["live_request_limit"], {
            "search": 7, "summarization": 1, "total": 8, "automatic_retries": 0
        })
        self.assertEqual(
            sorted({item["custom_configuration"] for item in document["queries"]}),
            [
                "asia-news-aia-primary",
                "asia-news-authoritative-media",
                "asia-news-corporate-exchange",
                "asia-news-regulatory-official",
            ],
        )
        output = StringIO()
        with redirect_stdout(output):
            status = main([
                "--rule", "config/rules/asia-executive-news.json",
                "--search-approach", "foundry-agent",
            ])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["code"], "configuration")

    def test_aia_queries_use_recall_first_discovery_language(self):
        queries = {
            item["query_id"]: item for item in self.rule.document["search"]["queries"]
        }
        corporate = queries["aia-corporate-markets"]["template"].lower()
        business = queries["aia-business-publications-initiatives"]["template"].lower()
        for template in (corporate, business):
            self.assertIn("recent substantive official", template)
            self.assertIn("later materiality assessment", template)
            for market in ("mainland china", "south korea", "macau", "india"):
                self.assertIn(market, template)

        for phrase in (
            "financial results", "capital or financing", "governance",
            "leadership", "market entry or exit",
        ):
            self.assertIn(phrase, corporate)
        for phrase in (
            "products", "services", "customer propositions", "partnerships",
            "technology", "industry-facing initiatives",
        ):
            self.assertIn(phrase, business)

        combined = " ".join(item["template"].lower() for item in queries.values())
        self.assertNotIn("feedback", combined)
        self.assertNotIn("example", combined)
        self.assertNotIn("do not prioritize", combined)
        self.assertNotIn("with potential strategic or executive significance", combined)

    def test_regulatory_queries_use_generalized_discovery_language(self):
        queries = [
            item for item in self.rule.document["search"]["queries"]
            if item["query_id"].startswith("regulatory-")
        ]
        self.assertEqual(len(queries), 3)
        disallowed = (
            "mas", "bnm", "board independence", "needs assessment",
            "suitability", "affordability", "individual misconduct",
            "feedback", "example",
        )
        for query in queries:
            template = query["template"].lower()
            self.assertIn("material insurance regulatory developments", template)
            self.assertIn("implications for insurers", template)
            self.assertIn("implementation changes", template)
            for phrase in disallowed:
                self.assertNotIn(phrase, template)

        exclusions = " ".join(self.rule.document["search"]["exclusion_rules"]).lower()
        self.assertNotIn("individual financial representatives", exclusions)

    def test_aia_queries_use_the_dedicated_configuration_and_admission_policy(self):
        queries = {
            item["query_id"]: item for item in self.rule.document["search"]["queries"]
        }
        for query_id in ("aia-corporate-markets", "aia-business-publications-initiatives"):
            query = queries[query_id]
            self.assertEqual(query["configuration_id"], "aia-primary")
            self.assertEqual(query["allowed_subject_types"], ["aia"])
            self.assertEqual(query["required_entities_any"], ["AIA"])
        aia_hosts = {
            source["host"]
            for source in self.rule.bing_configuration("aia-primary")["sources"]
        }
        self.assertIn("www.aia.com", aia_hosts)
        self.assertIn("www1.hkexnews.hk", aia_hosts)
        self.assertNotIn("www.manulife.com", aia_hosts)
        competitor = queries["competitor-official-material-moves"]
        self.assertEqual(competitor["configuration_id"], "corporate-exchange")
        self.assertEqual(competitor["allowed_subject_types"], ["competitor"])
        self.assertEqual(
            competitor["required_entities_any"],
            ["AXA", "Manulife", "Ping An", "FWD", "Sun Life", "Prudential"],
        )
        media = queries["competitor-authoritative-media"]
        self.assertEqual(media["allowed_subject_types"], ["aia", "competitor"])
        self.assertEqual(
            media["required_entities_any"],
            ["AIA", "AXA", "Manulife", "Ping An", "FWD", "Sun Life", "Prudential"],
        )

    def test_summary_schema_supports_detailed_items_without_an_item_cap(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        item = {
            "source_item_ids": ["src-0123456789ab"],
            "title": "AIA launches a regional offering",
            "summary": "The cited source describes the launch.",
            "detail_bullets": ["First point."],
            "timing_or_action": None,
            "potential_impact": "The development may affect distribution strategy.",
            "attention_level": "medium",
            "topic": "external_environment",
            "signal_type": "aia_major_news",
            "content_type": "corporate",
        }
        document = {
            "schema_version": "1.4.0",
            "title": "Asia briefing",
            "executive_summary": "One item was selected.",
            "evaluations": [{
                "source_item_ids": ["src-0123456789ab"],
                "importance_level": "medium",
                "importance_reason": "The event has strategic relevance.",
            }],
            "items": [dict(item) for _ in range(11)],
        }
        self.assertEqual(list(pipeline.summary_validator.iter_errors(document)), [])
        document["items"][0]["detail_bullets"] = []
        self.assertTrue(list(pipeline.summary_validator.iter_errors(document)))

    def test_url_specificity_distinguishes_articles_from_listing_pages(self):
        self.assertEqual(_url_specificity("https://www.example.com/"), "homepage")
        self.assertEqual(
            _url_specificity("https://www.tataaia.com/about-us/press-release-and-media-center.html"),
            "listing_page",
        )
        self.assertEqual(
            _url_specificity("https://www.asiainsurancereview.com/News/Category?Cat=Regulations"),
            "listing_page",
        )
        self.assertEqual(
            _url_specificity("https://www.ia.org.hk/en/infocenter/press_releases/20260924.html"),
            "specific_article",
        )
        self.assertEqual(
            _url_specificity(
                "https://www1.hkexnews.hk/search/titlesearch.xhtml?category=0&market=SEHK&stockId=54299"
            ),
            "listing_page",
        )

    def test_aia_query_admission_rejects_wrong_subject_and_entity(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        query = next(
            item for item in self.rule.render_queries(self.rule.default_topic, NOW.date(), 14)
            if item.query_id == "aia-business-publications-initiatives"
        )
        config = self.rule.bing_configuration("aia-primary")
        hosts = tuple(source["host"] for source in config["sources"])
        wrong_subject = search_body(
            "https://www.aia.com/en/media-centre/competitor", "2026-09-10",
            title="Competitor update", publisher="AIA", market="Asia",
            signal_type="competitor_market_move", topic="external_environment",
            subject_type="competitor", entities=["Manulife"],
        )
        items, warnings, _ = pipeline._convert_search(
            query, wrong_subject, allowed_hosts=hosts, configuration_id="aia-primary"
        )
        self.assertEqual(items, [])
        self.assertTrue(any("subject type" in warning for warning in warnings))

        wrong_entity = search_body(
            "https://www.aia.com/en/media-centre/other", "2026-09-10",
            title="Other update", publisher="AIA", market="Asia",
            signal_type="aia_major_news", topic="external_environment",
            subject_type="aia", entities=["Manulife"],
        )
        items, warnings, _ = pipeline._convert_search(
            query, wrong_entity, allowed_hosts=hosts, configuration_id="aia-primary"
        )
        self.assertEqual(items, [])
        self.assertTrue(any("admitted entity" in warning for warning in warnings))

        accepted = search_body(
            "https://www.aia.com/en/media-centre/aia-update", "2026-09-10",
            title="AIA update", publisher="AIA", market="Asia",
            signal_type="aia_major_news", topic="external_environment",
            subject_type="aia", entities=["AIA Hong Kong"],
        )
        items, warnings, _ = pipeline._convert_search(
            query, accepted, allowed_hosts=hosts, configuration_id="aia-primary"
        )
        self.assertEqual(len(items), 1)
        self.assertFalse(any("admission" in warning or "admitted entity" in warning for warning in warnings))

    def test_authoritative_media_query_rejects_unrelated_industry_items(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        query = next(
            item for item in self.rule.render_queries(self.rule.default_topic, NOW.date(), 14)
            if item.query_id == "competitor-authoritative-media"
        )
        config = self.rule.bing_configuration("authoritative-media")
        hosts = tuple(source["host"] for source in config["sources"])
        unrelated = search_body(
            "https://www.reuters.com/world/asia-pacific/pension-proposal", "2026-09-10",
            title="Think tank publishes pension proposal", publisher="Reuters", market="Asia",
            signal_type="informational", topic="external_environment",
            subject_type="industry", content_type="research_thought_leadership",
            entities=["Industry think tank"],
        )
        items, warnings, _ = pipeline._convert_search(
            query, unrelated, allowed_hosts=hosts, configuration_id="authoritative-media"
        )
        self.assertEqual(items, [])
        self.assertTrue(any("subject type" in warning for warning in warnings))

        competitor = search_body(
            "https://www.reuters.com/world/asia-pacific/manulife-strategy", "2026-09-10",
            title="Manulife announces material Asia strategy", publisher="Reuters", market="Asia",
            signal_type="competitor_market_move", topic="external_environment",
            subject_type="competitor", entities=["Manulife"],
        )
        items, warnings, _ = pipeline._convert_search(
            query, competitor, allowed_hosts=hosts, configuration_id="authoritative-media"
        )
        self.assertEqual(len(items), 1)
        self.assertFalse(any("admission" in warning or "admitted entity" in warning for warning in warnings))

    def test_listing_only_source_cannot_keep_high_attention(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        source_id = "src-0123456789ab"
        source_items = [{
            "source_item_id": source_id,
            "publisher": "Tata AIA",
            "published_date": "2026-09-10",
            "content_type": "product_distribution",
            "subject_type": "aia",
            "url_specificity": "listing_page",
            "source_links": [{
                "url": "https://www.tataaia.com/about-us/press-release-and-media-center.html",
                "title": "Press release centre",
            }],
        }]
        document = {
            "schema_version": "1.4.0",
            "title": "Asia briefing",
            "executive_summary": "One item was selected.",
            "evaluations": [{
                "source_item_ids": [source_id],
                "importance_level": "high",
                "importance_reason": "The development directly concerns AIA.",
            }],
            "items": [{
                "source_item_ids": [source_id],
                "title": "AIA launches a new product",
                "summary": "A product launch was reported.",
                "detail_bullets": [
                    "The launch concerns AIA directly.",
                    "Only a listing-page citation was supplied.",
                ],
                "timing_or_action": None,
                "potential_impact": "The launch may affect product competition.",
                "attention_level": "high",
                "topic": "external_environment",
                "signal_type": "aia_major_news",
                "content_type": "product_distribution",
            }],
        }
        body = {
            "output": [{
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(document)}],
            }]
        }
        summary, warnings = pipeline._convert_summary(body, source_items)
        self.assertEqual(summary["items"][0]["attention_level"], "medium")
        self.assertEqual(summary["items"][0]["source_specificity"], "listing_page")
        self.assertTrue(any("article-specific citation" in warning for warning in warnings))

    def test_editorial_policy_has_named_competitors_and_no_item_target_or_cap(self):
        self.assertIsNone(self.rule.max_items)
        self.assertNotIn("minimum_expected_items", self.rule.document["editorial_policy"])
        self.assertEqual(
            self.rule.competitors,
            ("AXA", "Manulife", "Ping An", "FWD", "Sun Life", "Prudential"),
        )
        self.assertEqual(self.rule.included_attention_levels, ("high", "medium"))
        self.assertIn("reinsurance", self.rule.excluded_content_types)

        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        payload = pipeline._summary_payload([], self.rule.default_topic, {
            "start_date": "2026-08-31", "end_date": "2026-09-13",
        })
        instructions = payload["instructions"].lower()
        self.assertNotIn("expected minimum", instructions)
        self.assertIn("same materiality dimensions", instructions)

    def test_all_high_and_medium_events_are_returned_even_above_ten(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        source_items = []
        evaluations = []
        items = []
        for index in range(11):
            source_id = f"src-{index:012x}"
            source_items.append({
                "source_item_id": source_id,
                "publisher": "AIA",
                "published_date": "2026-09-10",
                "content_type": "corporate",
                "subject_type": "aia",
                "source_type": "company",
                "url_specificity": "specific_article",
                "source_links": [{
                    "url": f"https://www.aia.com/en/media-centre/event-{index}",
                    "title": f"Event {index}",
                }],
            })
            evaluations.append({
                "source_item_ids": [source_id],
                "importance_level": "medium",
                "importance_reason": "The event has supported strategic relevance.",
            })
            items.append({
                "source_item_ids": [source_id],
                "title": f"AIA event {index}",
                "summary": "A material event was reported.",
                "detail_bullets": ["A cited source provides the event detail."],
                "timing_or_action": None,
                "potential_impact": "The event may affect AIA or the insurance industry.",
                "attention_level": "medium",
                "topic": "external_environment",
                "signal_type": "aia_major_news",
                "content_type": "corporate",
            })
        document = {
            "schema_version": "1.4.0",
            "title": "Asia briefing",
            "executive_summary": "Eleven events met the importance threshold.",
            "evaluations": evaluations,
            "items": items,
        }
        body = {"output": [{
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": json.dumps(document)}],
        }]}
        summary, warnings = pipeline._convert_summary(body, source_items)
        self.assertEqual(len(summary["items"]), 11)
        self.assertEqual(summary["selection"]["item_cap"], None)
        self.assertIn("not independent media confirmation", summary["items"][0]["source_positioning"])
        self.assertEqual(warnings, [])

    def test_every_candidate_must_be_evaluated_and_reinsurance_cannot_be_selected(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        source_id = "src-0123456789ab"
        source_items = [{
            "source_item_id": source_id,
            "publisher": "Reinsurer",
            "published_date": "2026-09-10",
            "content_type": "reinsurance",
            "subject_type": "reinsurance",
            "url_specificity": "specific_article",
            "source_links": [{"url": "https://www.reuters.com/world/asia/reinsurance", "title": "Report"}],
        }]
        document = {
            "schema_version": "1.4.0",
            "title": "Asia briefing",
            "executive_summary": "One candidate was assessed.",
            "evaluations": [{
                "source_item_ids": [source_id],
                "importance_level": "medium",
                "importance_reason": "The event appears material.",
            }],
            "items": [{
                "source_item_ids": [source_id],
                "title": "Reinsurance event",
                "summary": "A reinsurance event was reported.",
                "detail_bullets": ["The event concerns a reinsurer."],
                "timing_or_action": None,
                "potential_impact": "The event may affect the sector.",
                "attention_level": "medium",
                "topic": "external_environment",
                "signal_type": "informational",
                "content_type": "other",
            }],
        }
        body = {"output": [{
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": json.dumps(document)}],
        }]}
        with self.assertRaisesRegex(PocError, "Reinsurance content"):
            pipeline._convert_summary(body, source_items)

        source_items[0].update({
            "content_type": "corporate",
            "subject_type": "competitor",
            "signal_type": "competitor_market_move",
            "entities": ["Unlisted Insurer"],
        })
        with self.assertRaisesRegex(PocError, "named competitor list"):
            pipeline._convert_summary(body, source_items)

        document["evaluations"] = []
        document["items"] = []
        body["output"][0]["content"][0]["text"] = json.dumps(document)
        with self.assertRaisesRegex(PocError, "Every eligible source item"):
            pipeline._convert_summary(body, source_items)

    def test_live_configuration_loader_binds_all_four_instances(self):
        environ = {
            "BING_CUSTOM_SEARCH_PROJECT_CONNECTION_ID": (
                "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/"
                "Microsoft.CognitiveServices/accounts/resource/projects/project/connections/bing"
            )
        }
        foundry = FoundryConfig(
            "https://resource.services.ai.azure.com/api/projects/project", "gpt-5-mini"
        )
        configs = BingConfig.load_all(
            ROOT / "missing.env", self.rule, foundry, environ
        )
        self.assertEqual(
            [config.instance_name for config in configs],
            [
                "asia-news-regulatory-official",
                "asia-news-aia-primary",
                "asia-news-corporate-exchange",
                "asia-news-authoritative-media",
            ],
        )
        self.assertEqual(
            sum(len(config.allowed_hosts) for config in configs), len(self.rule.allowed_hosts)
        )

    def test_all_news_retains_dates_but_summary_gets_in_window_only(self):
        regulatory = search_body(
            "https://www.hkma.gov.hk/eng/news/2026/update", "2026-09-10",
            title="Regulatory update", publisher="HKMA", market="Hong Kong",
            signal_type="final_rule", topic="government_regulatory",
        )
        corporate = search_body(
            "https://www.aia.com/en/media-centre/2026/partnership", "2026-09-01",
            title="AIA partnership", publisher="AIA", market="Asia",
            signal_type="aia_major_news", topic="external_environment",
        )
        media_old = search_body(
            "https://www.reuters.com/world/asia-pacific/insurance-old-2026-08-01/", "2026-08-01",
            title="Older market report", publisher="Reuters", market="Asia",
            signal_type="macro_market", topic="external_environment",
        )
        corporate_unknown = search_body(
            "https://www.aia.com/en/media-centre/2026/undated-update", None,
            title="Undated AIA update", publisher="AIA", market="Asia",
            signal_type="macro_market", topic="external_environment",
        )
        adapter = FakeAdapter([
            regulatory, regulatory, regulatory, corporate, corporate_unknown, media_old, media_old
        ])
        run = PocPipeline(
            ROOT, self.rule, adapter, self.configs, clock=lambda: NOW
        ).run()

        self.assertTrue(run.ok)
        self.assertEqual(run.brief["schema_version"], "1.5.0")
        self.assertEqual(run.all_news["counts"], {
            "total": 4,
            "in_window": 2,
            "out_of_window": 1,
            "unknown_date": 1,
            "eligible_for_brief": 2,
        })
        self.assertEqual(len(adapter.summary_source_notes), 2)
        self.assertTrue(all(note["published_date"] in {"2026-09-10", "2026-09-01"} for note in adapter.summary_source_notes))
        self.assertTrue(all(note["url_specificity"] == "specific_article" for note in adapter.summary_source_notes))
        self.assertEqual(adapter.search_configs, [
            "asia-news-regulatory-official", "asia-news-regulatory-official",
            "asia-news-regulatory-official", "asia-news-aia-primary",
            "asia-news-aia-primary", "asia-news-corporate-exchange",
            "asia-news-authoritative-media",
        ])
        self.assertTrue(all(
            record["citation_diagnostics"]["envelope_checks"]["schema_version_valid"]
            for record in run.search_results["queries"]
        ))
        item = run.brief["items"][0]
        self.assertEqual(item["title"], "AIA launches a new regional offering")
        self.assertEqual(len(item["detail_bullets"]), 2)
        self.assertNotIn("impact_to_aia", item)
        self.assertNotIn("attention_reason", item)
        self.assertIn("- The development directly concerns AIA.", run.markdown)
        self.assertIn("Potential impact", run.markdown)
        self.assertNotIn("Attention rationale", run.markdown)
        self.assertNotIn("Impact to AIA", run.markdown)
        self.assertFalse(any("editorial target" in warning for warning in run.brief["warnings"]))


if __name__ == "__main__":
    unittest.main()
