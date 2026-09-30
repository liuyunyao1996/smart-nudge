from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from scripts.run_poc import main
from smart_nudge.foundry import BingConfig, FoundryConfig
from smart_nudge.pipeline import PocPipeline, _url_specificity
from smart_nudge.rules import RulePack


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)


def search_body(url, published_date, *, title, publisher, market, signal_type, topic):
    document = {
        "schema_version": "1.1.0",
        "coverage_status": "checked",
        "items": [{
            "title": title,
            "publisher": publisher,
            "published_date": published_date,
            "grounded_note": "A cited development was reported with potential relevance to Asian insurance markets.",
            "citation_urls": [url],
            "market": market,
            "entities": ["AIA"],
            "topic": topic,
            "signal_type": signal_type,
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
            "schema_version": "1.2.0",
            "title": "Asia Insurance Executive News",
            "executive_summary": "One material in-window development merits attention.",
            "items": [{
                "source_item_ids": [source_id],
                "headline": "AIA-relevant development",
                "news_summary": "The cited source describes a material development.",
                "attention_level": "high",
                "attention_reason": "The supplied note identifies a major AIA event.",
                "topic": "external_environment",
                "signal_type": "aia_major_news",
                "impact_to_aia": {
                    "business_competitive": {"status": "direct", "description": "The development concerns AIA directly."},
                    "capital_rbc_solvency": {"status": "not_established", "description": "No capital effect is established."},
                    "investor": {"status": "potential", "description": "Investors may assess strategic implications."},
                },
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

    def test_dry_run_has_three_instances_six_queries_and_rejects_agent(self):
        output = StringIO()
        with redirect_stdout(output):
            status = main(["--rule", "config/rules/asia-executive-news.json"])
        document = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(document["live_request_limit"], {
            "search": 6, "summarization": 1, "total": 7, "automatic_retries": 0
        })
        self.assertEqual(
            sorted({item["custom_configuration"] for item in document["queries"]}),
            [
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

    def test_listing_only_source_cannot_keep_high_attention(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        source_id = "src-0123456789ab"
        source_items = [{
            "source_item_id": source_id,
            "publisher": "Tata AIA",
            "published_date": "2026-09-10",
            "url_specificity": "listing_page",
            "source_links": [{
                "url": "https://www.tataaia.com/about-us/press-release-and-media-center.html",
                "title": "Press release centre",
            }],
        }]
        document = {
            "schema_version": "1.2.0",
            "title": "Asia briefing",
            "executive_summary": "One item was selected.",
            "items": [{
                "source_item_ids": [source_id],
                "headline": "AIA product launch",
                "news_summary": "A product launch was reported.",
                "attention_level": "high",
                "attention_reason": "This is a major AIA event.",
                "topic": "external_environment",
                "signal_type": "aia_major_news",
                "impact_to_aia": {
                    "business_competitive": {"status": "direct", "description": "Direct product impact."},
                    "capital_rbc_solvency": {"status": "not_established", "description": "No capital impact established."},
                    "investor": {"status": "not_established", "description": "No investor impact established."},
                },
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

    def test_live_configuration_loader_binds_all_three_instances(self):
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
        media_unknown = search_body(
            "https://www.bloomberg.com/news/articles/insurance-market", None,
            title="Undated market report", publisher="Bloomberg", market="Asia",
            signal_type="macro_market", topic="external_environment",
        )
        adapter = FakeAdapter([
            regulatory, regulatory, corporate, corporate, media_old, media_unknown
        ])
        run = PocPipeline(
            ROOT, self.rule, adapter, self.configs, clock=lambda: NOW
        ).run()

        self.assertTrue(run.ok)
        self.assertEqual(run.brief["schema_version"], "1.2.0")
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
            "asia-news-corporate-exchange", "asia-news-corporate-exchange",
            "asia-news-authoritative-media", "asia-news-authoritative-media",
        ])
        self.assertTrue(all(
            record["citation_diagnostics"]["envelope_checks"]["schema_version_valid"]
            for record in run.search_results["queries"]
        ))
        self.assertEqual(run.brief["items"][0]["impact_to_aia"]["business_competitive"]["status"], "direct")
        self.assertIn("Capital / RBC / solvency", run.markdown)


if __name__ == "__main__":
    unittest.main()
