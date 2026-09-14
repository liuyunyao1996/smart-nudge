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
        self.assertEqual(document["live_request_limit"]["total"], 3)
        self.assertEqual(len(document["queries"]), 2)

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

    def test_invalid_days_fails_before_loading_live_configuration(self):
        output = StringIO()
        with redirect_stdout(output):
            status = main(["--days", "91"])
        document = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(document["code"], "invalid_days")


if __name__ == "__main__":
    unittest.main()
