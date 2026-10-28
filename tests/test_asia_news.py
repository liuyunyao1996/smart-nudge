from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from scripts.run_poc import main
from smart_nudge.foundry import BingConfig, FoundryConfig
from smart_nudge.pipeline import (
    CUSTOM_BING_APPROACH,
    PocError,
    PocPipeline,
    _url_specificity,
    build_search_tasks,
)
from smart_nudge.rules import RulePack


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)


def search_body(
    url, published_date, *, title, publisher, market, signal_type, topic,
    subject_type="aia", content_type="corporate", event_scope="firm_specific",
    entities=None, coverage_status="checked",
):
    document = {
        "schema_version": "1.2.0",
        "coverage_status": coverage_status,
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
            "schema_version": "1.6.0",
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

    @staticmethod
    def briefing_event(index, attention_level):
        source_id = f"src-{index:012x}"
        source = {
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
        }
        evaluation = {
            "source_item_ids": [source_id],
            "importance_level": attention_level,
            "importance_reason": f"The event has supported {attention_level} relevance.",
        }
        item = {
            "source_item_ids": [source_id],
            "title": f"AIA event {index}",
            "summary": "A cited event was reported.",
            "detail_bullets": [
                "A cited source provides the event detail.",
                "The event occurred in an AIA market during the briefing window.",
            ],
            "potential_impact": "The event may affect AIA or the insurance industry.",
            "attention_level": attention_level,
            "topic": "external_environment",
            "signal_type": "aia_major_news",
            "content_type": "corporate",
        }
        return source, evaluation, item

    @staticmethod
    def summary_body(evaluations, items):
        document = {
            "schema_version": "1.6.0",
            "title": "Asia briefing",
            "executive_summary": "Eligible events were assessed for the briefing.",
            "evaluations": evaluations,
            "items": items,
        }
        return {"output": [{
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": json.dumps(document)}],
        }]}

    def test_dry_run_has_four_instances_twelve_queries_and_rejects_agent(self):
        self.assertEqual(self.rule.version, "1.6.0")
        output = StringIO()
        with redirect_stdout(output):
            status = main(["--rule", "config/rules/asia-executive-news.json"])
        document = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(document["live_request_limit"], {
            "search": 12, "summarization": 1, "total": 13, "automatic_retries": 0
        })
        search_start = datetime.fromisoformat(document["search_window"]["start_date"]).date()
        search_end = datetime.fromisoformat(document["search_window"]["end_date"]).date()
        brief_start = datetime.fromisoformat(document["brief_window"]["start_date"]).date()
        brief_end = datetime.fromisoformat(document["brief_window"]["end_date"]).date()
        self.assertEqual((search_end - search_start).days, 14)
        self.assertEqual((brief_end - brief_start).days, 7)
        self.assertEqual(brief_end, search_end)
        self.assertEqual(
            sorted({item["custom_configuration"] for item in document["queries"]}),
            [
                "asia-news-aia-primary",
                "asia-news-authoritative-media",
                "asia-news-corporate-exchange",
                "asia-news-regulatory-official",
            ],
        )
        dry_queries = {item["query_id"]: item for item in document["queries"]}
        self.assertEqual(
            dry_queries["regulatory-india-regional"]["allowed_source_markets"],
            ["india", "asia"],
        )
        self.assertNotIn(
            "www.fstb.gov.hk",
            dry_queries["regulatory-india-regional"]["target_hosts"],
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

    def test_search_notes_request_generalized_event_detail_without_recommendations(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        query = next(
            item for item in self.rule.render_queries(self.rule.default_topic, NOW.date(), 14)
            if item.query_id == "regulatory-greater-china"
        )
        config = self.rule.bing_configuration(query.configuration_id)
        payload = pipeline._search_payload(
            query,
            self.rule.default_topic,
            {"start_date": "2026-08-30", "end_date": "2026-09-13"},
            allowed_hosts=tuple(source["host"] for source in config["sources"]),
            bing_config=self.configs[0],
        )
        instructions = payload["instructions"].lower()
        self.assertIn("two to four factual sentences", instructions)
        self.assertIn("what the change actually contains", instructions)
        self.assertIn("apply the same concrete-detail standard", instructions)
        self.assertIn("do not put recommendations or suggested aia actions", instructions)
        self.assertIn("configured source markets", instructions)
        self.assertIn("hong_kong, mainland_china, taiwan, asia", instructions)

    def test_regulatory_queries_use_generalized_discovery_language(self):
        queries = [
            item for item in self.rule.document["search"]["queries"]
            if item["query_id"] in (
                "regulatory-greater-china", "regulatory-southeast-asia",
                "regulatory-india-regional",
            )
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

    def test_policy_searches_scope_local_language_discovery_to_each_market(self):
        tasks = {
            task.query.query_id: task
            for task in build_search_tasks(
                self.rule,
                self.rule.render_queries(self.rule.default_topic, NOW.date(), 14),
                CUSTOM_BING_APPROACH,
            )
        }
        expected = {
            "regulatory-china-policy-zh": ("mainland_china", "Simplified Chinese"),
            "regulatory-china-policy-forums": ("mainland_china", "Simplified Chinese"),
            "regulatory-hong-kong-policy-forums": ("hong_kong", "Traditional Chinese"),
            "regulatory-singapore-policy-forums": ("singapore", "English"),
        }
        for query_id, (market, language) in expected.items():
            with self.subTest(query_id=query_id):
                task = tasks[query_id]
                self.assertEqual(task.query.language, language)
                self.assertEqual(task.query.allowed_source_markets, (market,))
                self.assertTrue(all(
                    self.rule.source_metadata(host)["market"] == market
                    for host in task.allowed_hosts
                ))
                self.assertFalse(task.query.required_entities_any)
        china_hosts = tasks["regulatory-china-policy-forums"].allowed_hosts
        self.assertTrue({
            "www.nfra.gov.cn", "www.iachina.cn", "www.nhsa.gov.cn",
            "www.financialstreetforum.com",
        }.issubset(china_hosts))
        self.assertIn("www.ia.org.hk", tasks["regulatory-hong-kong-policy-forums"].allowed_hosts)
        self.assertIn("www.mas.gov.sg", tasks["regulatory-singapore-policy-forums"].allowed_hosts)

    def test_policy_sources_preserve_native_citations_and_publisher_type(self):
        pipeline = PocPipeline(ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW)
        task = next(
            task for task in build_search_tasks(
                self.rule,
                self.rule.render_queries(self.rule.default_topic, NOW.date(), 14),
                CUSTOM_BING_APPROACH,
            ) if task.query.query_id == "regulatory-china-policy-forums"
        )
        for host, source_type in (
            ("www.iachina.cn", "association"),
            ("www.nhsa.gov.cn", "government"),
            ("www.financialstreetforum.com", "forum"),
        ):
            with self.subTest(host=host):
                body = search_body(
                    f"https://{host}/news/policy-statement.html", "2026-09-10",
                    title="Public policy priorities", publisher="Publishing institution",
                    market="Mainland China", signal_type="informational",
                    topic="government_regulatory", subject_type="industry",
                    content_type="regulatory", event_scope="market_sector",
                    entities=["Public speaker"],
                )
                items, _, _ = pipeline._convert_search(
                    task.query, body, allowed_hosts=task.allowed_hosts,
                    configuration_id=task.configuration_id,
                )
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["source_type"], source_type)
                self.assertEqual(items[0]["signal_type"], "informational")
                self.assertEqual(items[0]["source_links"][0]["source_type"], source_type)
                pipeline._classify_source_quality(items)
                pipeline._classify_freshness(items, {"start_date": "2026-09-06", "end_date": "2026-09-13"})
                pipeline._all_news({
                    "run_id": "test", "status": "completed", "generated_at": NOW.isoformat(),
                    "rule": pipeline._rule_record(), "search": pipeline._search_record(),
                    "topic": self.rule.default_topic,
                    "search_window": {"start_date": "2026-08-30", "end_date": "2026-09-13"},
                    "window": {"start_date": "2026-09-06", "end_date": "2026-09-13"},
                    "items": items, "warnings": [],
                })
                body["output"][0]["action"]["sources"] = []
                rejected, warnings, _ = pipeline._convert_search(
                    task.query, body, allowed_hosts=task.allowed_hosts,
                    configuration_id=task.configuration_id,
                )
                self.assertEqual(rejected, [])
                self.assertTrue(any("no native in-scope citation" in warning for warning in warnings))

    def test_regulatory_media_accepts_policy_statements_without_company_mentions(self):
        pipeline = PocPipeline(ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW)
        queries = {
            query.query_id: query
            for query in self.rule.render_queries(self.rule.default_topic, NOW.date(), 14)
        }
        hosts = tuple(
            source["host"] for source in self.rule.bing_configuration("authoritative-media")["sources"]
        )
        for subject, expected_count in (("regulator", 1), ("industry", 1), ("competitor", 0)):
            with self.subTest(subject=subject):
                body = search_body(
                    "https://www.news.cn/finance/policy-forum.html", "2026-09-10",
                    title="Regulator sets insurance policy priorities", publisher="Xinhua",
                    market="Mainland China", signal_type="informational",
                    topic="government_regulatory", subject_type=subject,
                    content_type="regulatory", event_scope="market_sector", entities=["NFRA"],
                )
                items, _, _ = pipeline._convert_search(
                    queries["regulatory-authoritative-media"], body,
                    allowed_hosts=hosts, configuration_id="authoritative-media",
                )
                self.assertEqual(len(items), expected_count)
                if subject == "regulator":
                    old_route, _, _ = pipeline._convert_search(
                        queries["competitor-authoritative-media"], body,
                        allowed_hosts=hosts, configuration_id="authoritative-media",
                    )
                    self.assertEqual(old_route, [])
        summary = pipeline._summary_payload([], self.rule.default_topic, {})["instructions"]
        self.assertIn("non-binding policy intentions", summary)
        self.assertIn("do not downgrade them solely", summary)

    def test_regulatory_queries_admit_only_their_configured_market_groups(self):
        rendered = self.rule.render_queries(self.rule.default_topic, NOW.date(), 14)
        queries = {query.query_id: query for query in rendered}
        self.assertEqual(
            queries["regulatory-greater-china"].allowed_source_markets,
            ("hong_kong", "mainland_china", "taiwan", "asia"),
        )
        self.assertEqual(
            queries["regulatory-india-regional"].allowed_source_markets,
            ("india", "asia"),
        )

        tasks = {
            task.query.query_id: task
            for task in build_search_tasks(self.rule, rendered, CUSTOM_BING_APPROACH)
        }
        india_hosts = tasks["regulatory-india-regional"].allowed_hosts
        self.assertIn("irdai.gov.in", india_hosts)
        self.assertIn("www.iais.org", india_hosts)
        self.assertNotIn("www.fstb.gov.hk", india_hosts)

        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        all_regulatory_hosts = tuple(
            source["host"]
            for source in self.rule.bing_configuration("regulatory-official")["sources"]
        )
        cases = (
            ("https://www.fstb.gov.hk/fsb/en/publication/update.htm", 0, "source-market admission"),
            ("https://irdai.gov.in/document-detail/update", 1, None),
            ("https://www.iais.org/news/update", 1, None),
        )
        for url, expected_count, warning_text in cases:
            with self.subTest(url=url):
                body = search_body(
                    url,
                    "2026-09-10",
                    title="Regulatory update",
                    publisher="Regulator",
                    market="Asia",
                    signal_type="final_rule",
                    topic="government_regulatory",
                    subject_type="regulator",
                    content_type="regulatory",
                    event_scope="market_sector",
                    entities=["Regulator"],
                )
                items, warnings, _ = pipeline._convert_search(
                    queries["regulatory-india-regional"],
                    body,
                    allowed_hosts=all_regulatory_hosts,
                    configuration_id="regulatory-official",
                )
                self.assertEqual(len(items), expected_count)
                if warning_text is not None:
                    self.assertTrue(any(warning_text in warning for warning in warnings))

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
            ["AXA", "Manulife", "Ping An", "FWD", "Sun Life", "Prudential plc"],
        )
        media = queries["competitor-authoritative-media"]
        self.assertEqual(media["allowed_subject_types"], ["aia", "competitor"])
        self.assertEqual(
            media["required_entities_any"],
            ["AIA", "AXA", "Manulife", "Ping An", "FWD", "Sun Life", "Prudential plc"],
        )

    def test_summary_schema_supports_detailed_items_without_an_item_cap(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        item = {
            "source_item_ids": ["src-0123456789ab"],
            "title": "AIA launches a regional offering",
            "summary": "The cited source describes the launch.",
            "detail_bullets": ["First concrete point.", "Second concrete point."],
            "potential_impact": "The development may affect distribution strategy.",
            "attention_level": "medium",
            "topic": "external_environment",
            "signal_type": "aia_major_news",
            "content_type": "corporate",
        }
        document = {
            "schema_version": "1.6.0",
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
        document["items"][0]["detail_bullets"] = ["Only one point."]
        self.assertTrue(list(pipeline.summary_validator.iter_errors(document)))
        document["items"][0]["detail_bullets"] = [
            "One.", "Two.", "Three.", "Four.", "Five.",
        ]
        self.assertTrue(list(pipeline.summary_validator.iter_errors(document)))
        document["items"][0]["detail_bullets"] = ["One.", "Two."]
        document["items"][0]["timing_or_action"] = None
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

    def test_competitor_admission_distinguishes_prudential_corporate_identity(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        query = next(
            item for item in self.rule.render_queries(self.rule.default_topic, NOW.date(), 14)
            if item.query_id == "competitor-authoritative-media"
        )
        config = self.rule.bing_configuration("authoritative-media")
        hosts = tuple(source["host"] for source in config["sources"])

        for index, entity in enumerate((
            "Prudential Financial",
            "Prudential Financial, Inc.",
            "The Prudential Insurance Company of America",
        )):
            with self.subTest(entity=entity):
                body = search_body(
                    f"https://www.reuters.com/world/asia-pacific/prudential-{index}",
                    "2026-09-10",
                    title="Prudential company update",
                    publisher="Reuters",
                    market="Asia",
                    signal_type="competitor_market_move",
                    topic="external_environment",
                    subject_type="competitor",
                    entities=[entity],
                )
                items, warnings, _ = pipeline._convert_search(
                    query,
                    body,
                    allowed_hosts=hosts,
                    configuration_id="authoritative-media",
                )
                self.assertEqual(items, [])
                self.assertTrue(any("admitted entity" in warning for warning in warnings))

        for index, entity in enumerate((
            "Prudential plc",
            "Prudential Insurance",
            "Prudential Corporation Asia",
        )):
            with self.subTest(entity=entity):
                body = search_body(
                    f"https://www.reuters.com/world/asia-pacific/prudential-plc-{index}",
                    "2026-09-10",
                    title="Prudential plc update",
                    publisher="Reuters",
                    market="Asia",
                    signal_type="competitor_market_move",
                    topic="external_environment",
                    subject_type="competitor",
                    entities=[entity],
                )
                items, warnings, _ = pipeline._convert_search(
                    query,
                    body,
                    allowed_hosts=hosts,
                    configuration_id="authoritative-media",
                )
                self.assertEqual(len(items), 1)
                self.assertFalse(any("admitted entity" in warning for warning in warnings))

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
            "schema_version": "1.6.0",
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

    def test_final_classification_metadata_is_replaced_with_source_backed_values(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        source_id = "src-0123456789ab"
        source_items = [{
            "source_item_id": source_id,
            "publisher": "Regulator",
            "published_date": "2026-09-10",
            "topic": "government_regulatory",
            "signal_type": "final_rule",
            "content_type": "regulatory",
            "subject_type": "regulator",
            "source_type": "regulator",
            "url_specificity": "specific_article",
            "source_links": [{
                "url": "https://irdai.gov.in/document-detail/update",
                "title": "Regulatory update",
            }],
        }]
        evaluations = [{
            "source_item_ids": [source_id],
            "importance_level": "medium",
            "importance_reason": "The rule has sector-wide relevance.",
        }]
        items = [{
            "source_item_ids": [source_id],
            "title": "Regulator issues a final rule",
            "summary": "The regulator issued a final rule.",
            "detail_bullets": [
                "The rule affects insurers in the market.",
                "The cited source provides the implementation detail.",
            ],
            "potential_impact": "The rule may change industry operating requirements.",
            "attention_level": "medium",
            "topic": "external_environment",
            "signal_type": "informational",
            "content_type": "other",
        }]
        summary, warnings = pipeline._convert_summary(
            self.summary_body(evaluations, items), source_items
        )
        item = summary["items"][0]
        self.assertEqual(item["topic"], "government_regulatory")
        self.assertEqual(item["signal_type"], "final_rule")
        self.assertEqual(item["content_type"], "regulatory")
        self.assertEqual(
            sum("source-backed metadata" in warning for warning in warnings), 3
        )

    def test_editorial_policy_has_soft_target_and_no_item_cap(self):
        self.assertIsNone(self.rule.max_items)
        self.assertEqual(self.rule.target_items, 10)
        self.assertEqual(self.rule.supplemental_attention_level, "low")
        self.assertEqual(
            self.rule.competitors,
            ("AXA", "Manulife", "Ping An", "FWD", "Sun Life", "Prudential plc"),
        )
        self.assertIn("Prudential Insurance", self.rule.competitor_aliases_for())
        self.assertNotIn("Prudential Financial", self.rule.competitor_aliases_for())
        self.assertEqual(self.rule.included_attention_levels, ("high", "medium"))
        self.assertIn("reinsurance", self.rule.excluded_content_types)

        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        payload = pipeline._summary_payload([], self.rule.default_topic, {
            "start_date": "2026-08-31", "end_date": "2026-09-13",
        })
        instructions = payload["instructions"].lower()
        self.assertEqual(payload["reasoning"], {"effort": "medium"})
        self.assertEqual(payload["max_output_tokens"], 16000)
        self.assertIn("soft target of 10", instructions)
        self.assertIn("highest-value eligible low", instructions)
        self.assertIn("no maximum item count", instructions)
        self.assertIn("never invent or split events", instructions)
        self.assertIn("same materiality dimensions", instructions)
        self.assertIn("substantive two-to-four-sentence event summary", instructions)
        self.assertIn("two to four non-overlapping detail_bullets", instructions)
        self.assertIn("do not return a timing_or_action field", instructions)
        self.assertIn("do not recommend actions", instructions)
        self.assertIn("potential_impact must remain analytical and non-prescriptive", instructions)
        self.assertIn("copy topic, signal_type and content_type from the supplied source notes", instructions)
        self.assertIn("match competitor identities only against", instructions)
        self.assertIn("prudential plc", instructions)
        self.assertNotIn("prudential financial", instructions)

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
                "detail_bullets": [
                    "A cited source provides the event detail.",
                    "The event has supported relevance during the briefing window.",
                ],
                "potential_impact": "The event may affect AIA or the insurance industry.",
                "attention_level": "medium",
                "topic": "external_environment",
                "signal_type": "aia_major_news",
                "content_type": "corporate",
            })
        document = {
            "schema_version": "1.6.0",
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
        self.assertEqual(summary["selection"]["target_items"], 10)
        self.assertEqual(summary["selection"]["supplemental_low_items"], 0)
        self.assertIn("not independent media confirmation", summary["items"][0]["source_positioning"])
        self.assertEqual(warnings, [])

    def test_low_events_supplement_high_and_medium_to_soft_target(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        events = [
            self.briefing_event(index, "medium" if index < 2 else "low")
            for index in range(12)
        ]
        source_items = [event[0] for event in events]
        evaluations = [event[1] for event in events]
        selected_items = [event[2] for event in events[:10]]

        summary, warnings = pipeline._convert_summary(
            self.summary_body(evaluations, selected_items), source_items
        )

        self.assertEqual(len(summary["items"]), 10)
        self.assertEqual(
            [item["attention_level"] for item in summary["items"]],
            ["medium", "medium", *("low" for _ in range(8))],
        )
        self.assertEqual(summary["selection"]["supplemental_low_items"], 8)
        self.assertEqual(summary["selection"]["target_items"], 10)
        self.assertEqual(warnings, [])

    def test_low_supplement_count_must_stop_at_soft_target(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        events = [
            self.briefing_event(index, "medium" if index < 2 else "low")
            for index in range(12)
        ]
        source_items = [event[0] for event in events]
        evaluations = [event[1] for event in events]

        for selected_count in (9, 11):
            with self.subTest(selected_count=selected_count):
                with self.assertRaisesRegex(PocError, "soft target"):
                    pipeline._convert_summary(
                        self.summary_body(
                            evaluations, [event[2] for event in events[:selected_count]]
                        ),
                        source_items,
                    )

    def test_all_eligible_events_are_included_when_total_is_below_ten(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        events = [
            self.briefing_event(0, "medium"),
            self.briefing_event(1, "low"),
            self.briefing_event(2, "low"),
        ]
        source_items = [event[0] for event in events]
        evaluations = [event[1] for event in events]
        items = [event[2] for event in events]

        summary, warnings = pipeline._convert_summary(
            self.summary_body(evaluations, items), source_items
        )

        self.assertEqual(len(summary["items"]), 3)
        self.assertEqual(summary["selection"]["supplemental_low_items"], 2)
        self.assertEqual(summary["selection"]["included_events"], 3)
        self.assertEqual(warnings, [])

    def test_hard_excluded_low_event_does_not_fill_soft_target(self):
        pipeline = PocPipeline(
            ROOT, self.rule, FakeAdapter([]), self.configs, clock=lambda: NOW
        )
        source, evaluation, _ = self.briefing_event(0, "low")
        source.update({
            "publisher": "Reinsurer",
            "content_type": "reinsurance",
            "subject_type": "reinsurance",
            "source_type": "media",
        })

        summary, warnings = pipeline._convert_summary(
            self.summary_body([evaluation], []), [source]
        )

        self.assertEqual(summary["items"], [])
        self.assertEqual(summary["selection"]["supplemental_low_items"], 0)
        self.assertEqual(summary["selection"]["importance_counts"]["low"], 1)
        self.assertEqual(warnings, [])

        competitor_source, competitor_evaluation, _ = self.briefing_event(1, "low")
        competitor_source.update({
            "publisher": "Prudential Financial",
            "content_type": "corporate",
            "subject_type": "competitor",
            "signal_type": "competitor_market_move",
            "entities": ["Prudential Financial, Inc."],
        })
        summary, warnings = pipeline._convert_summary(
            self.summary_body([competitor_evaluation], []), [competitor_source]
        )
        self.assertEqual(summary["items"], [])
        self.assertEqual(summary["selection"]["supplemental_low_items"], 0)
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
            "schema_version": "1.6.0",
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
                "detail_bullets": [
                    "The event concerns a reinsurer.",
                    "Reinsurance content is outside the briefing scope.",
                ],
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

        source_items[0]["entities"] = ["Prudential Financial, Inc."]
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

    def test_search_uses_fourteen_days_but_summary_gets_rolling_seven_days_only(self):
        regulatory = search_body(
            "https://www.hkma.gov.hk/eng/news/2026/update", "2026-09-10",
            title="Regulatory update", publisher="HKMA", market="Hong Kong",
            signal_type="final_rule", topic="government_regulatory",
            subject_type="regulator", content_type="regulatory",
            event_scope="market_sector", entities=["HKMA"], coverage_status="partial",
        )
        regulatory_checked = search_body(
            "https://www.hkma.gov.hk/eng/news/2026/update", "2026-09-10",
            title="Regulatory update", publisher="HKMA", market="Hong Kong",
            signal_type="final_rule", topic="government_regulatory",
            subject_type="regulator", content_type="regulatory",
            event_scope="market_sector", entities=["HKMA"],
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
            regulatory, regulatory_checked, regulatory_checked,
            corporate, corporate_unknown, media_old, media_old
        ] + [{
            "status": "completed",
            "output": [
                {"type": "web_search_call", "status": "completed", "action": {"type": "search", "sources": []}},
                {"type": "message", "role": "assistant", "content": [{
                    "type": "output_text",
                    "text": json.dumps({"schema_version": "1.2.0", "coverage_status": "checked", "items": []}),
                }]},
            ],
        }] * 5)
        run = PocPipeline(
            ROOT, self.rule, adapter, self.configs, clock=lambda: NOW
        ).run()

        self.assertTrue(run.ok)
        self.assertEqual(run.brief["schema_version"], "1.9.0")
        self.assertEqual(run.search_results["status"], "partial")
        self.assertEqual(run.brief["status"], "partial")
        self.assertEqual(run.brief["coverage"], {
            "status": "partial",
            "queries_requested": 12,
            "queries_succeeded": 12,
            "queries_failed": 0,
            "queries_checked": 11,
            "queries_partial": 1,
            "queries_unavailable": 0,
        })
        self.assertEqual(run.search_results["search_window"], {
            "start_date": "2026-08-30",
            "end_date": "2026-09-13",
            "timezone": "Asia/Hong_Kong",
        })
        self.assertEqual(run.brief["window"], {
            "start_date": "2026-09-06",
            "end_date": "2026-09-13",
            "timezone": "Asia/Hong_Kong",
        })
        self.assertEqual(run.all_news["schema_version"], "1.3.0")
        self.assertEqual(run.all_news["search_window"], run.search_results["search_window"])
        self.assertEqual(run.all_news["counts"], {
            "total": 4,
            "in_window": 1,
            "out_of_window": 2,
            "unknown_date": 1,
            "eligible_for_brief": 1,
        })
        self.assertEqual(len(adapter.summary_source_notes), 1)
        self.assertEqual(adapter.summary_source_notes[0]["published_date"], "2026-09-10")
        self.assertTrue(all(note["url_specificity"] == "specific_article" for note in adapter.summary_source_notes))
        self.assertEqual(adapter.search_configs, [
            "asia-news-regulatory-official", "asia-news-regulatory-official",
            "asia-news-regulatory-official", "asia-news-aia-primary",
            "asia-news-aia-primary", "asia-news-corporate-exchange",
            "asia-news-authoritative-media",
            "asia-news-regulatory-official", "asia-news-regulatory-official",
            "asia-news-regulatory-official", "asia-news-regulatory-official",
            "asia-news-authoritative-media",
        ])
        source_coverage = {
            source["host"]: source for source in run.search_results["source_coverage"]["sources"]
        }
        self.assertEqual(source_coverage["www.hkma.gov.hk"]["native_urls_observed"], 1)
        self.assertEqual(source_coverage["www.hkma.gov.hk"]["candidates_accepted"], 1)
        self.assertEqual(source_coverage["www.hkma.gov.hk"]["eligible_for_brief"], 1)
        self.assertEqual(source_coverage["www.hkma.gov.hk"]["sources_in_brief"], 1)
        self.assertEqual(source_coverage["www.hkma.gov.hk"]["limited_coverage_query_ids"], ["regulatory-greater-china"])
        self.assertEqual(source_coverage["www.aia.com"]["outside_brief_window"], 1)
        self.assertEqual(source_coverage["www.aia.com"]["unknown_publication_date"], 1)
        self.assertEqual(source_coverage["www.nhsa.gov.cn"]["candidates_accepted"], 0)
        self.assertTrue(all(
            record["citation_diagnostics"]["envelope_checks"]["schema_version_valid"]
            for record in run.search_results["queries"]
        ))
        item = run.brief["items"][0]
        self.assertEqual(item["title"], "AIA launches a new regional offering")
        self.assertEqual(len(item["detail_bullets"]), 2)
        self.assertNotIn("timing_or_action", item)
        self.assertNotIn("impact_to_aia", item)
        self.assertNotIn("attention_reason", item)
        self.assertIn("- The development directly concerns AIA.", run.markdown)
        self.assertIn("Potential impact", run.markdown)
        self.assertNotIn("Timing / action", run.markdown)
        self.assertIn("**Brief window:** 2026-09-06 to 2026-09-13", run.markdown)
        self.assertIn("**Search window:** 2026-08-30 to 2026-09-13", run.markdown)
        self.assertIn(
            "**Coverage:** PARTIAL (checked 11, partial 1, unavailable 0, failed 0)",
            run.markdown,
        )
        self.assertNotIn("Attention rationale", run.markdown)
        self.assertNotIn("Impact to AIA", run.markdown)
        self.assertFalse(any("editorial target" in warning for warning in run.brief["warnings"]))


if __name__ == "__main__":
    unittest.main()
