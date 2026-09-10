from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from smart_nudge.live_preparation import (
    LivePreparationError,
    prepare_manual_live_run,
)
from smart_nudge.live_run import ManualLiveRunAuthorization
from smart_nudge.manual_research import ManualLiveResearchRequest
from scripts.prepare_live_poc import main as prepare_live_poc_main


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-09-10T10:00:00+08:00")


class LivePreparationTests(unittest.TestCase):
    def test_prepares_fully_validated_unconsumed_pair_without_live_io(self):
        scratch = ROOT / ".tmp"
        scratch.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=scratch) as directory:
            prepared = prepare_manual_live_run(
                ROOT,
                output_directory=directory,
                run_id="manual-live-preparation-test",
                clock=lambda: NOW,
            )
            request_document = json.loads(
                prepared.request_path.read_text(encoding="utf-8")
            )
            request = ManualLiveResearchRequest.validate(request_document, ROOT)
            authorization = ManualLiveRunAuthorization.load(
                ROOT, prepared.authorization_path, clock=lambda: NOW
            )

            self.assertEqual(request.content_sha256, authorization.request_sha256)
            self.assertEqual(request.request_key, authorization.request_key)
            self.assertEqual(3, authorization.max_queries)
            self.assertEqual(2, authorization.max_evidence_records)
            self.assertTrue(authorization.allowed_source_ids)
            self.assertFalse(prepared.result_path.exists())

            record = prepared.record(ROOT)
            self.assertTrue(record["prepared"])
            self.assertFalse(record["live_executed"])
            self.assertFalse(record["authorization_consumed"])
            self.assertIn("--execute-live", record["run_command"])
            self.assertIn("Tee-Object", record["run_command"])

    def test_refuses_to_overwrite_an_existing_prepared_run(self):
        scratch = ROOT / ".tmp"
        scratch.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=scratch) as directory:
            first = prepare_manual_live_run(
                ROOT,
                output_directory=directory,
                run_id="manual-live-preparation-collision",
                clock=lambda: NOW,
            )
            original = first.request_path.read_bytes()
            with self.assertRaises(LivePreparationError) as error:
                prepare_manual_live_run(
                    ROOT,
                    output_directory=directory,
                    run_id="manual-live-preparation-collision",
                    clock=lambda: NOW,
                )
            self.assertEqual("output_exists", error.exception.code)
            self.assertEqual(original, first.request_path.read_bytes())

    def test_refuses_a_run_id_that_could_escape_the_output_directory(self):
        scratch = ROOT / ".tmp"
        scratch.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=scratch) as directory:
            with self.assertRaises(LivePreparationError) as error:
                prepare_manual_live_run(
                    ROOT,
                    output_directory=directory,
                    run_id="C:unsafe",
                    clock=lambda: NOW,
                )
            self.assertEqual("unsafe_run_id", error.exception.code)

    def test_cli_reports_policy_failure_without_executing_live(self):
        output = StringIO()
        with redirect_stdout(output):
            status = prepare_live_poc_main(
                [
                    "--max-queries",
                    "31",
                    "--run-id",
                    "manual-live-preparation-invalid",
                ],
                clock=lambda: NOW,
            )
        result = json.loads(output.getvalue())
        self.assertEqual(1, status)
        self.assertFalse(result["ok"])
        self.assertFalse(result["live_executed"])
        self.assertFalse(result["authorization_consumed"])

    def test_cli_prepares_artifacts_and_prints_the_exact_next_command(self):
        scratch = ROOT / ".tmp"
        scratch.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=scratch) as directory:
            output = StringIO()
            with redirect_stdout(output):
                status = prepare_live_poc_main(
                    [
                        "--output-dir",
                        directory,
                        "--run-id",
                        "manual-live-preparation-cli",
                    ],
                    clock=lambda: NOW,
                )
            result = json.loads(output.getvalue())
            self.assertEqual(0, status)
            self.assertTrue(result["ok"])
            self.assertTrue((ROOT / result["request_path"]).is_file())
            self.assertTrue((ROOT / result["authorization_path"]).is_file())
            self.assertIn(result["request_path"], result["run_command"])
            self.assertIn(result["result_path"], result["run_command"])


if __name__ == "__main__":
    unittest.main()
