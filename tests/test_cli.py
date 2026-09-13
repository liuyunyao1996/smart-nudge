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

    def test_invalid_days_fails_before_loading_live_configuration(self):
        output = StringIO()
        with redirect_stdout(output):
            status = main(["--days", "91"])
        document = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(document["code"], "invalid_days")


if __name__ == "__main__":
    unittest.main()
