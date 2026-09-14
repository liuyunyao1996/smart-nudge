import json
from datetime import date
from pathlib import Path
import tempfile
import unittest

from smart_nudge.rules import RulePack, RulePackError


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULE = ROOT / "config/rules/hk-regulatory-pulse.json"
REGION_RULES = {
    "hk-regulatory-pulse.json": {
        "instance": "hk-financial-regulators-test",
        "queries": ["en", "zh-hant"],
        "hosts": 6,
    },
    "macao-regulatory-pulse.json": {
        "instance": "macao-financial-regulators-test",
        "queries": ["en", "zh-hant"],
        "hosts": 4,
    },
    "cn-mainland-regulatory-pulse.json": {
        "instance": "cn-mainland-financial-regulators-test",
        "queries": ["en", "zh-hans"],
        "hosts": 4,
    },
}


class RulePackTests(unittest.TestCase):
    def test_all_region_rules_bind_expected_instances_hosts_and_languages(self):
        for filename, expected in REGION_RULES.items():
            with self.subTest(filename=filename):
                rule = RulePack.load(ROOT / "config" / "rules" / filename, ROOT)
                queries = rule.render_queries(rule.default_topic, date(2026, 9, 13), 30)
                self.assertEqual(rule.version, "1.1.0")
                self.assertEqual(rule.document["bing"]["instance_name"], expected["instance"])
                self.assertGreaterEqual(len(rule.document["summarization"]["attention_rules"]), 3)
                self.assertEqual(len(rule.allowed_hosts), expected["hosts"])
                self.assertEqual([query.query_id for query in queries], expected["queries"])

    def test_default_rule_renders_two_bilingual_queries(self):
        rule = RulePack.load(DEFAULT_RULE, ROOT)
        queries = rule.render_queries(rule.default_topic, date(2026, 9, 13), 30)

        self.assertEqual([query.query_id for query in queries], ["en", "zh-hant"])
        self.assertEqual([query.market for query in queries], ["en-HK", "zh-HK"])
        self.assertTrue(all("2026-08-14" in query.text for query in queries))
        self.assertTrue(all("2026-09-13" in query.text for query in queries))
        self.assertEqual(rule.max_items, 5)

    def test_topic_and_window_are_bounded(self):
        rule = RulePack.load(DEFAULT_RULE, ROOT)
        with self.assertRaises(RulePackError) as days:
            rule.render_queries("regulation", date(2026, 9, 13), 91)
        self.assertEqual(days.exception.code, "invalid_days")
        with self.assertRaises(RulePackError) as topic:
            rule.render_queries("bad\nquery", date(2026, 9, 13), 30)
        self.assertEqual(topic.exception.code, "invalid_topic")

    def test_template_placeholders_are_fixed(self):
        document = json.loads(DEFAULT_RULE.read_text(encoding="utf-8"))
        document["search"]["queries"][0]["template"] = "{topic} {unknown}"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rule.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(RulePackError) as error:
                RulePack.load(path, ROOT)
        self.assertEqual(error.exception.code, "invalid_rule")


if __name__ == "__main__":
    unittest.main()
