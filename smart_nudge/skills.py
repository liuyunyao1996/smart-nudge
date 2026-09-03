"""Versioned, repository-local domain skills and deterministic output checks.

Only JSON files committed under ``config/skills`` can become instructions. Public
Web content is evidence input and is never loaded through this module.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from string import Formatter
from typing import Mapping

from jsonschema import Draft202012Validator, FormatChecker


ALLOWED_QUERY_FIELDS = {"issuer", "term", "market_name", "date_from", "date_to"}
CASE_TYPES = {"positive", "negative", "insufficient_evidence"}


class SkillDefinitionError(ValueError):
    """A checked-in skill, fixture, or referenced schema is invalid."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SkillSelectionError(LookupError):
    """No eligible skill revision matches an explicit selection request."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Non-JSON numeric constant: {value}")


def _read_json(path: Path):
    try:
        return json.loads(
            path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (OSError, ValueError):
        raise SkillDefinitionError("invalid_json", f"Could not read valid JSON: {path.name}.") from None


def _canonical_sha256(value) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _semver_key(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split("."))


def _schema_errors(schema: dict, instance) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"schema/{'/'.join(str(part) for part in error.absolute_path) or 'root'}: {error.message}"
        for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
    ]


@dataclass(frozen=True)
class SkillRevision:
    path: Path
    _document_json: str
    content_sha256: str
    output_schema_path: Path
    _output_schema_json: str

    @property
    def document(self) -> dict:
        """Return a detached copy so the hashed revision cannot be mutated."""
        return json.loads(self._document_json)

    @property
    def output_schema(self) -> dict:
        return json.loads(self._output_schema_json)

    @property
    def skill_id(self) -> str:
        return self.document["skill_id"]

    @property
    def version(self) -> str:
        return self.document["version"]

    @property
    def status(self) -> str:
        return self.document["status"]

    def snapshot(self) -> dict:
        """Return a detached instruction snapshot for one run."""
        return deepcopy(self.document)

    def execution_record(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "status": self.status,
            "content_sha256": self.content_sha256,
            "output_schema": self.document["output"]["schema_path"],
        }


@dataclass(frozen=True)
class SkillBundle:
    topic_id: str
    event_type: str
    market_id: str
    revisions: tuple[SkillRevision, ...]
    bundle_sha256: str

    def instruction_snapshots(self) -> tuple[dict, ...]:
        return tuple(revision.snapshot() for revision in self.revisions)

    def execution_record(self) -> dict:
        return {
            "selection": {
                "topic_id": self.topic_id,
                "event_type": self.event_type,
                "market_id": self.market_id,
            },
            "skills": [revision.execution_record() for revision in self.revisions],
            "bundle_sha256": self.bundle_sha256,
        }


class SkillLoader:
    """Discover local revisions, select narrowly, and validate skill output."""

    def __init__(self, repository_root: str | Path):
        self.root = Path(repository_root).resolve()
        self.skills_root = (self.root / "config" / "skills").resolve()
        self.schema_path = (self.root / "schemas" / "domain-skill.schema.json").resolve()
        self.topic_path = (self.root / "config" / "topics" / "insurance-intelligence.json").resolve()
        self.profile_path = (self.root / "config" / "watch_profiles" / "aia-group-ceo.json").resolve()
        self.skill_schema = _read_json(self.schema_path)
        try:
            Draft202012Validator.check_schema(self.skill_schema)
        except Exception:
            raise SkillDefinitionError("invalid_schema", "The domain skill schema is invalid.") from None

        taxonomy = _read_json(self.topic_path)
        profile = _read_json(self.profile_path)
        try:
            self.topic_index = {item["topic_id"]: item for item in taxonomy["topics"]}
            self.market_ids = {item["market_id"] for item in profile["pilot_markets"]}
        except (KeyError, TypeError):
            raise SkillDefinitionError("invalid_catalog", "Topic or market configuration is incomplete.") from None

        if not self.skills_root.is_dir():
            raise SkillDefinitionError("missing_skills", "The repository has no config/skills directory.")
        revisions = [self._load_revision(path) for path in sorted(self.skills_root.rglob("*.json"))]
        if not revisions:
            raise SkillDefinitionError("missing_skills", "No versioned domain skills were found.")
        keys = [(revision.skill_id, revision.version) for revision in revisions]
        if len(keys) != len(set(keys)):
            raise SkillDefinitionError("duplicate_revision", "Skill id and version pairs must be unique.")
        self.revisions = tuple(revisions)
        self._by_key = {(revision.skill_id, revision.version): revision for revision in revisions}

    def _repository_file(self, relative_path: str, allowed_root: Path, *, code: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute():
            raise SkillDefinitionError(code, "Skill references must be repository-relative paths.")
        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(allowed_root.resolve()) or not resolved.is_file() or resolved.is_symlink():
            raise SkillDefinitionError(code, "Skill reference is missing or outside its approved directory.")
        return resolved

    def _load_revision(self, path: Path) -> SkillRevision:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.skills_root) or resolved.is_symlink():
            raise SkillDefinitionError("invalid_skill_path", "Skill definitions must be regular files under config/skills.")
        document = _read_json(resolved)
        errors = _schema_errors(self.skill_schema, document)
        if errors:
            raise SkillDefinitionError("invalid_skill", f"{resolved.name}: {errors[0]}")
        self._validate_semantics(document)

        output_path = self._repository_file(
            document["output"]["schema_path"], (self.root / "schemas" / "skills"), code="invalid_output_schema_path"
        )
        output_schema = _read_json(output_path)
        try:
            Draft202012Validator.check_schema(output_schema)
        except Exception:
            raise SkillDefinitionError("invalid_output_schema", f"Output schema is invalid for {document['skill_id']}.") from None

        revision = SkillRevision(
            path=resolved,
            _document_json=_canonical_json(document),
            content_sha256=_canonical_sha256(document),
            output_schema_path=output_path,
            _output_schema_json=_canonical_json(output_schema),
        )
        self._validate_fixture(revision)
        return revision

    def _validate_semantics(self, document: dict) -> None:
        skill_id = document["skill_id"]
        status = document["status"]
        approval = document["review"]["approval_status"]
        expected_approval = {
            "draft_pending_domain_review": "engineering_only",
            "approved": "domain_approved",
            "retired": "retired",
        }[status]
        if approval != expected_approval:
            raise SkillDefinitionError("invalid_approval", f"Status and approval disagree for {skill_id}.")
        if date.fromisoformat(document["review"]["next_review_on"]) < date.fromisoformat(document["review"]["last_reviewed_on"]):
            raise SkillDefinitionError("invalid_review_dates", f"Review dates are reversed for {skill_id}.")

        topics = document["scope"]["topic_ids"]
        events = set(document["scope"]["event_types"])
        markets = set(document["scope"]["market_ids"])
        if set(topics) - self.topic_index.keys():
            raise SkillDefinitionError("unknown_topic", f"Skill {skill_id} references an unknown topic.")
        allowed_events = set().union(*(self.topic_index[topic]["event_types"] for topic in topics))
        if events - allowed_events:
            raise SkillDefinitionError("unknown_event_type", f"Skill {skill_id} references an event outside its topics.")
        if markets - self.market_ids:
            raise SkillDefinitionError("unknown_market", f"Skill {skill_id} references an unknown pilot market.")
        required_fields = set().union(*(self.topic_index[topic]["extract_fields"] for topic in topics))
        if required_fields - set(document["extraction"]["required_fields"]):
            raise SkillDefinitionError("missing_extraction_field", f"Skill {skill_id} omits taxonomy extraction fields.")

        for query in document["research"]["query_templates"]:
            try:
                fields = {field for _, field, format_spec, conversion in Formatter().parse(query["template"]) if field}
            except ValueError:
                raise SkillDefinitionError("invalid_query_template", f"Skill {skill_id} has an invalid query template.") from None
            if not {"term", "market_name", "date_from", "date_to"} <= fields or fields - ALLOWED_QUERY_FIELDS:
                raise SkillDefinitionError("invalid_query_template", f"Skill {skill_id} query placeholders are incomplete or unsafe.")
            if any(("." in field or "[" in field or "]" in field) for field in fields):
                raise SkillDefinitionError("invalid_query_template", f"Skill {skill_id} uses nested query placeholders.")

    def _validate_fixture(self, revision: SkillRevision) -> None:
        fixture_path = self._repository_file(
            revision.document["examples"]["fixture_path"],
            self.root / "evals" / "skills",
            code="invalid_fixture_path",
        )
        fixture = _read_json(fixture_path)
        try:
            cases = fixture["cases"]
            status = fixture["annotation_status"]
            data_kind = fixture["data_kind"]
        except (KeyError, TypeError):
            raise SkillDefinitionError("invalid_fixture", f"Fixture is incomplete for {revision.skill_id}.") from None
        if not isinstance(cases, list) or not cases or status != "draft_pending_domain_review" or data_kind != "synthetic":
            raise SkillDefinitionError("invalid_fixture", f"Fixture status is unsafe for {revision.skill_id}.")
        ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
        case_types = {case.get("case_type") for case in cases if isinstance(case, dict)}
        if (len(ids) != len(cases) or any(not isinstance(item, str) or not item.strip() for item in ids)
                or len(ids) != len(set(ids)) or case_types != CASE_TYPES):
            raise SkillDefinitionError("invalid_fixture", f"Fixture case ids or types are invalid for {revision.skill_id}.")
        for case in cases:
            try:
                selection = case["selection"]
                expected_loaded = case["expected"]["skill_loaded"]
                output = case["output"]
                scenario = case["scenario"]
                topic = self.topic_index[selection["topic_id"]]
                if (type(expected_loaded) is not bool or not isinstance(scenario, str) or not scenario.strip()
                        or selection["event_type"] not in topic["event_types"]
                        or selection["market_id"] not in self.market_ids):
                    raise KeyError
                matches = (
                    selection["topic_id"] in revision.document["scope"]["topic_ids"]
                    and selection["event_type"] in revision.document["scope"]["event_types"]
                    and selection["market_id"] in revision.document["scope"]["market_ids"]
                )
            except (KeyError, TypeError):
                raise SkillDefinitionError("invalid_fixture", f"Fixture case is incomplete for {revision.skill_id}.") from None
            if matches != expected_loaded:
                raise SkillDefinitionError("invalid_fixture", f"Fixture selection expectation is wrong for {case['case_id']}.")
            if expected_loaded:
                if not isinstance(output, dict):
                    raise SkillDefinitionError("invalid_fixture", f"Loaded case lacks output for {case['case_id']}.")
                errors = self._candidate_errors(revision, output, selection)
                if errors:
                    raise SkillDefinitionError("invalid_fixture_output", f"{case['case_id']}: {errors[0]}")
                try:
                    if output["evidence_assessment"]["state"] != case["expected"]["evidence_state"]:
                        raise SkillDefinitionError("invalid_fixture", f"Evidence expectation is wrong for {case['case_id']}.")
                    if output["recommended_disposition"] != case["expected"]["recommended_disposition"]:
                        raise SkillDefinitionError("invalid_fixture", f"Disposition expectation is wrong for {case['case_id']}.")
                except (KeyError, TypeError):
                    raise SkillDefinitionError("invalid_fixture", f"Fixture expectation is incomplete for {case['case_id']}.") from None
            elif output is not None:
                raise SkillDefinitionError("invalid_fixture", f"Non-trigger case must not contain skill output: {case['case_id']}.")

    def select(
        self,
        *,
        topic_id: str,
        event_type: str,
        market_id: str,
        version_pins: Mapping[str, str] | None = None,
        include_drafts: bool = False,
    ) -> SkillBundle:
        topic = self.topic_index.get(topic_id)
        if topic is None:
            raise SkillSelectionError("unknown_topic", "Selection references an unknown topic.")
        if event_type not in topic["event_types"]:
            raise SkillSelectionError("unknown_event_type", "Event type is not valid for the selected topic.")
        if market_id not in self.market_ids:
            raise SkillSelectionError("unknown_market", "Selection references an unknown pilot market.")
        eligible_status = {"approved"}
        if include_drafts:
            eligible_status.add("draft_pending_domain_review")
        candidates = [
            revision for revision in self.revisions
            if revision.status in eligible_status
            and topic_id in revision.document["scope"]["topic_ids"]
            and event_type in revision.document["scope"]["event_types"]
            and market_id in revision.document["scope"]["market_ids"]
        ]
        if not candidates:
            raise SkillSelectionError("no_matching_skill", "No eligible skill matches the explicit scope.")

        selected: list[SkillRevision] = []
        pins = dict(version_pins or {})
        for skill_id in sorted({revision.skill_id for revision in candidates}):
            revisions = [revision for revision in candidates if revision.skill_id == skill_id]
            if skill_id in pins:
                matches = [revision for revision in revisions if revision.version == pins[skill_id]]
                if not matches:
                    raise SkillSelectionError("pinned_version_unavailable", f"Pinned version is unavailable for {skill_id}.")
                selected.append(matches[0])
            else:
                selected.append(max(revisions, key=lambda revision: _semver_key(revision.version)))
        unknown_pins = set(pins) - {revision.skill_id for revision in selected}
        if unknown_pins:
            raise SkillSelectionError("unknown_version_pin", "A version pin does not apply to the selected scope.")

        records = [revision.execution_record() for revision in selected]
        bundle_document = {
            "topic_id": topic_id,
            "event_type": event_type,
            "market_id": market_id,
            "skills": records,
        }
        return SkillBundle(topic_id, event_type, market_id, tuple(selected), _canonical_sha256(bundle_document))

    def validate_candidate(self, bundle: SkillBundle, payload: dict) -> list[str]:
        if not isinstance(payload, dict):
            return ["candidate must be an object"]
        skill_id = payload.get("skill_id")
        version = payload.get("skill_version")
        revision = next(
            (item for item in bundle.revisions if item.skill_id == skill_id and item.version == version),
            None,
        )
        if revision is None:
            return ["candidate skill id and version are not fixed in this bundle"]
        selection = {"topic_id": bundle.topic_id, "event_type": bundle.event_type, "market_id": bundle.market_id}
        return self._candidate_errors(revision, payload, selection)

    @staticmethod
    def _candidate_errors(revision: SkillRevision, payload: dict, selection: Mapping[str, str]) -> list[str]:
        errors = _schema_errors(revision.output_schema, payload)
        if errors:
            return errors
        for field in ("topic_id", "event_type", "market_id"):
            if payload[field] != selection[field]:
                errors.append(f"candidate {field} differs from the selected bundle")
        if payload["skill_id"] != revision.skill_id or payload["skill_version"] != revision.version:
            errors.append("candidate skill revision differs from the loaded revision")

        evidence = payload["evidence_assessment"]
        if evidence["state"] == "primary_supported" and not evidence["primary_document_obtained"]:
            errors.append("primary-supported candidate requires the primary document")
        if evidence["state"] in {"insufficient", "conflicted"} and not payload["unknowns"]:
            errors.append("insufficient or conflicted candidate must state unknowns")
        if payload["document_status"] == "unknown" and not payload["unknowns"]:
            errors.append("unknown document status requires an explicit unknown")
        compatible_statuses = {
            "consultation": {"consultation", "correction", "unknown"},
            "final_rule": {"final_rule", "correction", "unknown"},
            "supervisory_guidance": {"supervisory_guidance", "correction", "unknown"},
            "enforcement": {"enforcement_action", "correction", "unknown"},
            "implementation_update": {"implementation_update", "correction", "unknown"},
        }
        if payload["document_status"] not in compatible_statuses[payload["event_type"]]:
            errors.append("document status is incompatible with the selected event type")
        if evidence["state"] == "primary_supported" and payload["document_status"] == "unknown":
            errors.append("primary-supported candidate cannot have unknown document status")

        support_ids = set(evidence["supporting_claim_ids"])
        referenced_ids = {
            claim_id
            for change in payload["obligation_changes"]
            for claim_id in change["basis_claim_ids"]
        }
        referenced_ids.update(
            claim_id
            for impact in payload["business_impacts"]
            for claim_id in impact["basis_claim_ids"]
        )
        if referenced_ids - support_ids:
            errors.append("analysis references claims outside the evidence assessment")

        transition = payload["transition_period"]
        if transition and transition["start_date"] and transition["end_date"]:
            if date.fromisoformat(transition["start_date"]) > date.fromisoformat(transition["end_date"]):
                errors.append("transition period dates are reversed")
        return errors


def repository_skill_loader() -> SkillLoader:
    """Load skills from the repository containing this package."""
    return SkillLoader(Path(__file__).resolve().parents[1])
