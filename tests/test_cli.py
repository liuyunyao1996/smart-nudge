from contextlib import redirect_stdout
from io import StringIO
import json
import unittest

from scripts.run_poc import main


class CliTests(unittest.TestCase):
    def test_default_command_is_offline_dry_run(self):
        output = StringIO()
        with redirect_stdout(output):
            status = main([])
        document = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(document["mode"], "dry_run")
        self.assertEqual(document["search_approach"], "custom-bing")
        self.assertEqual(document["live_request_limit"]["total"], 3)
        self.assertEqual(len(document["queries"]), 2)

    def test_agent_search_dry_run_adds_site_scoped_queries(self):
        output = StringIO()
        with redirect_stdout(output):
            status = main(["--search-approach", "foundry-agent"])
        document = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(document["search_approach"], "foundry-agent")
        self.assertEqual(document["live_request_limit"]["search"], 5)
        self.assertEqual(document["live_request_limit"]["total"], 6)
        self.assertEqual(document["live_request_limit"]["max_tool_calls_per_search"], 3)
        self.assertEqual(document["live_request_limit"]["web_search_tool_calls"], 15)
        self.assertFalse(document["live_request_limit"]["tool_call_limit_guaranteed"])
        self.assertEqual(len(document["queries"]), 5)
        self.assertEqual([query["site_id"] for query in document["queries"]], ["ia", "hkma", "sfc", "fstb", "gov"])
        planned_hosts = []
        for query in document["queries"]:
            planned_hosts.extend(query["target_hosts"])
            self.assertEqual(query["base_query_ids"], ["en", "zh-hant"])
            self.assertEqual(query["max_tool_calls"], 3)
            self.assertEqual(len(query["site_scoped_queries"]), 2)
            for candidate in query["site_scoped_queries"]:
                self.assertIn(f"site:{query['target_hosts'][0]}", candidate)
        self.assertEqual(
            sorted(planned_hosts),
            sorted(document["allowed_hosts"]),
        )

    def test_region_rule_selection_is_an_offline_three_request_plan(self):
        selections = {
            "config/rules/macao-regulatory-pulse.json": (
                "macao-regulatory-pulse",
                ["en", "zh-hant"],
                4,
            ),
            "config/rules/cn-mainland-regulatory-pulse.json": (
                "cn-mainland-regulatory-pulse",
                ["en", "zh-hans"],
                4,
            ),
        }
        for path, expected in selections.items():
            with self.subTest(path=path):
                output = StringIO()
                with redirect_stdout(output):
                    status = main(["--rule", path])
                document = json.loads(output.getvalue())
                self.assertEqual(status, 0)
                self.assertEqual(document["rule"]["rule_id"], expected[0])
                self.assertEqual(
                    [query["query_id"] for query in document["queries"]], expected[1]
                )
                self.assertEqual(len(document["allowed_hosts"]), expected[2])
                self.assertEqual(document["live_request_limit"]["total"], 3)

    def test_regional_agent_rules_use_configured_logical_websites(self):
        for path, site_count in (
            ("config/rules/macao-regulatory-pulse.json", 2),
            ("config/rules/cn-mainland-regulatory-pulse.json", 4),
        ):
            with self.subTest(path=path):
                output = StringIO()
                with redirect_stdout(output):
                    status = main(["--rule", path, "--search-approach", "foundry-agent"])
                document = json.loads(output.getvalue())
                self.assertEqual(status, 0)
                self.assertEqual(document["live_request_limit"]["search"], site_count)
                self.assertEqual(document["live_request_limit"]["total"], site_count + 1)
                self.assertEqual(document["live_request_limit"]["web_search_tool_calls"], site_count * 3)
                self.assertEqual(len(document["queries"]), site_count)

    def test_invalid_days_fails_before_loading_live_configuration(self):
        output = StringIO()
        with redirect_stdout(output):
            status = main(["--days", "91"])
        document = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(document["code"], "invalid_days")



if __name__ == "__main__":
    unittest.main()
