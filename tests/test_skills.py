import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from smart_nudge.skills import SkillDefinitionError, SkillLoader, SkillSelectionError


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "config" / "skills" / "regulatory-change.json"
FIXTURE_PATH = ROOT / "evals" / "skills" / "regulatory-change.synthetic.json"


def select_engineering(loader, **selection):
    return loader.select(**selection, include_drafts=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_skill_repository(destination):
    files = [
        "config/skills/regulatory-change.json",
        "config/topics/insurance-intelligence.json",
        "config/watch_profiles/aia-group-ceo.json",
        "evals/skills/regulatory-change.synthetic.json",
        "schemas/domain-skill.schema.json",
        "schemas/skills/regulatory-change-output.schema.json",
    ]
    for relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


class SkillLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = SkillLoader(ROOT)
        cls.fixture = read_json(FIXTURE_PATH)

    def test_regulatory_skill_covers_each_declared_event_and_market(self):
        for event_type in ("consultation", "final_rule", "supervisory_guidance", "enforcement", "implementation_update"):
            for market_id in ("HK", "CN", "MY"):
                with self.subTest(event_type=event_type, market_id=market_id):
                    bundle = select_engineering(self.loader,
                        topic_id="regulatory-change", event_type=event_type, market_id=market_id
                    )
                    self.assertEqual(["regulatory-change"], [item.skill_id for item in bundle.revisions])

    def test_nonmatching_topic_and_event_do_not_load_regulatory_skill(self):
        with self.assertRaises(SkillSelectionError) as error:
            self.loader.select(topic_id="competitive-distribution", event_type="product_change", market_id="HK")
        self.assertEqual("no_matching_skill", error.exception.code)

    def test_draft_skill_is_denied_by_default(self):
        with self.assertRaises(SkillSelectionError) as error:
            self.loader.select(
                topic_id="regulatory-change",
                event_type="final_rule",
                market_id="HK",
            )
        self.assertEqual("no_matching_skill", error.exception.code)

    def test_execution_record_fixes_version_and_digest(self):
        first = select_engineering(self.loader, topic_id="regulatory-change", event_type="final_rule", market_id="HK")
        second = select_engineering(self.loader, topic_id="regulatory-change", event_type="final_rule", market_id="HK")
        record = first.execution_record()
        self.assertEqual("0.1.0", record["skills"][0]["version"])
        self.assertRegex(record["skills"][0]["content_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(first.bundle_sha256, second.bundle_sha256)

    def test_version_pin_and_unavailable_pin(self):
        bundle = select_engineering(self.loader,
            topic_id="regulatory-change",
            event_type="final_rule",
            market_id="HK",
            version_pins={"regulatory-change": "0.1.0"},
        )
        self.assertEqual("0.1.0", bundle.revisions[0].version)
        with self.assertRaises(SkillSelectionError) as error:
            select_engineering(self.loader,
                topic_id="regulatory-change",
                event_type="final_rule",
                market_id="HK",
                version_pins={"regulatory-change": "9.9.9"},
            )
        self.assertEqual("pinned_version_unavailable", error.exception.code)

    def test_instruction_snapshots_cannot_mutate_loaded_revision(self):
        bundle = select_engineering(self.loader, topic_id="regulatory-change", event_type="final_rule", market_id="HK")
        snapshot = bundle.instruction_snapshots()[0]
        snapshot["research"]["questions"].append("mutated")
        self.assertNotIn("mutated", bundle.revisions[0].document["research"]["questions"])
        bundle.revisions[0].document["research"]["questions"].append("also-mutated")
        self.assertNotIn("also-mutated", bundle.revisions[0].document["research"]["questions"])

    def test_positive_and_insufficient_fixtures_validate(self):
        for case in self.fixture["cases"]:
            if not case["expected"]["skill_loaded"]:
                continue
            bundle = select_engineering(self.loader, **case["selection"])
            self.assertEqual([], self.loader.validate_candidate(bundle, case["output"]), case["case_id"])

    def test_candidate_must_match_fixed_selection_and_revision(self):
        case = self.fixture["cases"][0]
        bundle = select_engineering(self.loader, **case["selection"])
        candidate = copy.deepcopy(case["output"])
        candidate["market_id"] = "MY"
        errors = self.loader.validate_candidate(bundle, candidate)
        self.assertTrue(any("market_id differs" in item for item in errors))
        candidate = copy.deepcopy(case["output"])
        candidate["skill_version"] = "9.9.9"
        self.assertEqual(["candidate skill id and version are not fixed in this bundle"],
                         self.loader.validate_candidate(bundle, candidate))

    def test_financial_impact_cannot_be_quantified(self):
        case = self.fixture["cases"][0]
        bundle = select_engineering(self.loader, **case["selection"])
        candidate = copy.deepcopy(case["output"])
        candidate["aia_financial_impact_quantification"] = "Synthetic estimate: 10"
        errors = self.loader.validate_candidate(bundle, candidate)
        self.assertTrue(any("aia_financial_impact_quantification" in item for item in errors))

    def test_missing_primary_document_cannot_proceed_as_supported(self):
        case = self.fixture["cases"][0]
        bundle = select_engineering(self.loader, **case["selection"])
        candidate = copy.deepcopy(case["output"])
        candidate["evidence_assessment"]["primary_document_obtained"] = False
        errors = self.loader.validate_candidate(bundle, candidate)
        self.assertTrue(any("evidence_assessment" in item or "recommended_disposition" in item for item in errors))

    def test_analysis_cannot_reference_unassessed_claim(self):
        case = self.fixture["cases"][0]
        bundle = select_engineering(self.loader, **case["selection"])
        candidate = copy.deepcopy(case["output"])
        candidate["business_impacts"][0]["basis_claim_ids"] = ["claim-not-assessed"]
        errors = self.loader.validate_candidate(bundle, candidate)
        self.assertIn("analysis references claims outside the evidence assessment", errors)

    def test_reversed_transition_period_is_rejected(self):
        case = self.fixture["cases"][0]
        bundle = select_engineering(self.loader, **case["selection"])
        candidate = copy.deepcopy(case["output"])
        candidate["transition_period"]["start_date"] = "2027-01-02"
        errors = self.loader.validate_candidate(bundle, candidate)
        self.assertIn("transition period dates are reversed", errors)

    def test_document_status_must_match_event_type(self):
        case = self.fixture["cases"][0]
        bundle = select_engineering(self.loader, **case["selection"])
        candidate = copy.deepcopy(case["output"])
        candidate["document_status"] = "consultation"
        errors = self.loader.validate_candidate(bundle, candidate)
        self.assertIn("document status is incompatible with the selected event type", errors)

    def test_only_repository_skill_directory_becomes_instruction_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_skill_repository(root)
            write_json(root / "downloaded-web-content.json", read_json(SKILL_PATH))
            loader = SkillLoader(root)
        self.assertEqual(1, len(loader.revisions))

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_skill_repository(root)
            path = root / "config" / "skills" / "regulatory-change.json"
            path.write_text('{"skill_id":"one","skill_id":"two"}', encoding="utf-8")
            with self.assertRaises(SkillDefinitionError) as error:
                SkillLoader(root)
        self.assertEqual("invalid_json", error.exception.code)

    def test_taxonomy_required_extraction_fields_cannot_be_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_skill_repository(root)
            skill = read_json(root / "config" / "skills" / "regulatory-change.json")
            skill["extraction"]["required_fields"].remove("effective_date")
            write_json(root / "config" / "skills" / "regulatory-change.json", skill)
            with self.assertRaises(SkillDefinitionError) as error:
                SkillLoader(root)
        self.assertEqual("missing_extraction_field", error.exception.code)

    def test_missing_output_contract_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_skill_repository(root)
            skill = read_json(root / "config" / "skills" / "regulatory-change.json")
            skill["output"]["schema_path"] = "schemas/skills/missing.schema.json"
            write_json(root / "config" / "skills" / "regulatory-change.json", skill)
            with self.assertRaises(SkillDefinitionError) as error:
                SkillLoader(root)
        self.assertEqual("invalid_output_schema_path", error.exception.code)

    def test_malformed_fixture_fails_with_controlled_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_skill_repository(root)
            fixture = read_json(root / "evals" / "skills" / "regulatory-change.synthetic.json")
            del fixture["cases"][0]["selection"]["event_type"]
            write_json(root / "evals" / "skills" / "regulatory-change.synthetic.json", fixture)
            with self.assertRaises(SkillDefinitionError) as error:
                SkillLoader(root)
        self.assertEqual("invalid_fixture", error.exception.code)

    def test_fixture_types_and_review_status_are_explicit(self):
        self.assertEqual(
            {"positive", "negative", "insufficient_evidence"},
            {case["case_type"] for case in self.fixture["cases"]},
        )
        self.assertEqual("draft_pending_domain_review", self.fixture["annotation_status"])
        self.assertEqual("synthetic", self.fixture["data_kind"])


if __name__ == "__main__":
    unittest.main()
