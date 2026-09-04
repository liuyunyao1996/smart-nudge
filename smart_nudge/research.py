"""P4-A offline research-analysis-verification orchestration.

This module is intentionally synthetic-only. It has no network, credential,
source-fetch, model, persistence, or cloud-resource capability.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Mapping, Protocol
import json
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from scripts.validate_p0 import load_assets, validate_result
from smart_nudge.skills import SkillBundle, SkillLoader, SkillSelectionError
from smart_nudge.sources import SourceRegistry


CONTROLLER_VERSION = "p4a-controller@0.1.4"
DOCUMENT_ROLES = {"primary_document", "discovery_signal", "context"}


class ResearchLoopError(RuntimeError):
    """A curated orchestration failure that does not expose evidence content."""

    def __init__(self, code: str, message: str, *, queries_consumed: int = 0):
        super().__init__(message)
        self.code = code
        self.queries_consumed = queries_consumed


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Non-JSON numeric constant: {value}")


def read_json(path: str | Path):
    try:
        return json.loads(
            Path(path).read_text(encoding="utf-8-sig"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (OSError, ValueError):
        raise ResearchLoopError("invalid_json", "Could not read a required offline JSON asset.") from None


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return parsed


def _schema_errors(schema: dict, instance) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"schema/{'/'.join(str(part) for part in error.absolute_path) or 'root'}: {error.message}"
        for error in sorted(validator.iter_errors(instance), key=lambda item: [str(part) for part in item.absolute_path])
    ]


@dataclass(frozen=True)
class ResearchRequest:
    document: dict

    @classmethod
    def validate(cls, document: dict, repository_root: str | Path) -> "ResearchRequest":
        root = Path(repository_root).resolve()
        schema = read_json(root / "schemas" / "research-request.schema.json")
        errors = _schema_errors(schema, document)
        if errors:
            raise ResearchLoopError("invalid_request", errors[0])
        try:
            start = _parse_timestamp(document["window"]["start"])
            end = _parse_timestamp(document["window"]["end"])
            as_of = _parse_timestamp(document["as_of"])
        except (KeyError, TypeError, ValueError):
            raise ResearchLoopError("invalid_request", "Request timestamps must be valid and timezone-aware.") from None
        if not start < end <= as_of:
            raise ResearchLoopError("invalid_request", "Request requires window start < end <= as_of.")

        policy = read_json(root / "config" / "policies" / "p4-offline-research.json")
        try:
            if (policy["status"] != "engineering_only"
                    or policy["allowed_mode"] != document["mode"]
                    or document["scope"]["topic_id"] not in policy["allowed_topic_ids"]
                    or document["scope"]["source_classes"] != policy["allowed_source_classes"]):
                raise KeyError
            for key, value in document["budget"].items():
                if value > policy["limits"][key]:
                    raise ResearchLoopError("budget_exceeds_policy", f"Request exceeds the P4-A limit for {key}.")
        except (KeyError, TypeError):
            raise ResearchLoopError("invalid_policy", "P4-A offline policy is incomplete or inconsistent.") from None
        return cls(deepcopy(document))

    @property
    def run_id(self) -> str:
        return self.document["run_id"]

    @property
    def request_key(self) -> str:
        return self.document["request_key"]

    @property
    def as_of(self) -> str:
        return self.document["as_of"]

    @property
    def market_ids(self) -> tuple[str, ...]:
        return tuple(self.document["scope"]["market_ids"])

    @property
    def topic_id(self) -> str:
        return self.document["scope"]["topic_id"]

    @property
    def event_type(self) -> str:
        return self.document["scope"]["event_type"]

    @property
    def max_followups(self) -> int:
        return self.document["budget"]["max_followup_rounds_per_event"]

    @property
    def max_queries(self) -> int:
        return self.document["budget"]["max_queries"]

    @property
    def max_evidence(self) -> int:
        return self.document["budget"]["max_evidence_records"]

    @property
    def content_sha256(self) -> str:
        encoded = json.dumps(
            self.document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CoveragePlan:
    cells: tuple[dict, ...]
    tasks: tuple[dict, ...]

    def record(self) -> dict:
        return {"cells": deepcopy(list(self.cells)), "tasks": deepcopy(list(self.tasks))}


class CoveragePlanner:
    """Build market/topic/source/language coverage without issuing queries."""

    def __init__(self, repository_root: str | Path, source_registry: SourceRegistry):
        self.root = Path(repository_root).resolve()
        profile = read_json(self.root / "config" / "watch_profiles" / "aia-group-ceo.json")
        self.markets = {item["market_id"]: item for item in profile["pilot_markets"]}
        self.source_registry = source_registry

    def build(self, request: ResearchRequest, bundles: Mapping[str, SkillBundle]) -> CoveragePlan:
        cells: list[dict] = []
        tasks: list[dict] = []
        for market_id in request.market_ids:
            market = self.markets[market_id]
            sources = [
                source for source in self.source_registry.sources_for_search(
                    "trusted_registry", market_id=market_id, topic_id=request.topic_id
                )
                if source["trust"]["tier"] == "primary"
            ]
            if not sources:
                raise ResearchLoopError("missing_source_plan", f"No trusted primary source is registered for {market_id}.")
            languages = tuple(market["languages"])
            cell = {
                "market_id": market_id,
                "topic_id": request.topic_id,
                "source_class": "official",
                "languages_required": list(languages),
                "source_ids": sorted(source["source_id"] for source in sources),
            }
            cells.append(cell)
            skill = bundles[market_id].instruction_snapshots()[0]
            templates = skill["research"]["query_templates"]
            for language in languages:
                matching = [item["template"] for item in templates if item["language"] == language]
                if not matching:
                    raise ResearchLoopError("missing_query_template", f"Skill lacks a {language} query template for {market_id}.")
                tasks.append({
                    "task_id": f"{market_id}:{request.topic_id}:official:{language}",
                    "market_id": market_id,
                    "topic_id": request.topic_id,
                    "source_class": "official",
                    "language": language,
                    "source_ids": cell["source_ids"],
                    "query_templates": matching,
                    "force_company_name": False,
                })
        return CoveragePlan(tuple(cells), tuple(tasks))


@dataclass(frozen=True)
class ResearchContext:
    round_index: int
    followup: bool
    remaining_queries: int
    remaining_evidence_records: int
    coverage_plan: dict
    unresolved_event_ids: tuple[str, ...]
    request_key: str
    request_sha256: str


@dataclass(frozen=True)
class ResearchBatch:
    queries_executed: int
    coverage_updates: tuple[dict, ...]
    discoveries: tuple[dict, ...]


class ResearchRole(Protocol):
    role_version: str

    def research(self, context: ResearchContext) -> ResearchBatch:
        ...


class AnalysisRole(Protocol):
    role_version: str

    def analyze(
        self,
        discoveries: Mapping[str, dict],
        bundles: Mapping[str, SkillBundle],
        request: ResearchRequest,
    ) -> tuple[dict, ...]:
        ...


class VerificationRole(Protocol):
    role_version: str

    def verify(
        self,
        analyzed: tuple[dict, ...],
        evidence: Mapping[str, dict],
        claims: Mapping[str, dict],
    ) -> dict:
        ...


class FixtureResearchRole:
    """Replay explicit synthetic rounds; it cannot perform external I/O."""

    role_version = "fixture-research@0.1.0"

    def __init__(self, rounds: list[dict]):
        if not isinstance(rounds, list) or not rounds:
            raise ResearchLoopError("invalid_fixture", "Offline research requires at least one synthetic round.")
        self.rounds = deepcopy(rounds)

    def research(self, context: ResearchContext) -> ResearchBatch:
        if context.round_index >= len(self.rounds):
            return ResearchBatch(0, (), ())
        record = self.rounds[context.round_index]
        if not isinstance(record, dict):
            raise ResearchLoopError("invalid_fixture", "Synthetic round must be an object.")
        if record.get("error"):
            raise ResearchLoopError("research_failure", "The synthetic research role reported a controlled failure.")
        queries = record.get("queries_executed")
        coverage = record.get("coverage_updates")
        discoveries = record.get("discoveries")
        if (type(queries) is not int or queries < 0
                or not isinstance(coverage, list) or not isinstance(discoveries, list)
                or any(not isinstance(item, dict) for item in coverage + discoveries)):
            raise ResearchLoopError("invalid_fixture", "Synthetic round fields are invalid.")
        return ResearchBatch(queries, tuple(deepcopy(coverage)), tuple(deepcopy(discoveries)))


class RegulatoryAnalysisRole:
    """Validate P3 candidates and separate public facts from impact analysis."""

    role_version = "regulatory-analysis@0.1.0"

    def __init__(self, skill_loader: SkillLoader):
        self.skill_loader = skill_loader

    def analyze(
        self,
        discoveries: Mapping[str, dict],
        bundles: Mapping[str, SkillBundle],
        request: ResearchRequest,
    ) -> tuple[dict, ...]:
        analyzed: list[dict] = []
        for event_id in sorted(discoveries):
            discovery = discoveries[event_id]
            try:
                candidate = discovery["candidate"]
                event = discovery["event"]
                presentation = discovery["presentation"]
                market_id = candidate["market_id"]
                if (event["event_id"] != event_id or candidate["topic_id"] != request.topic_id
                        or candidate["event_type"] != request.event_type or market_id not in bundles):
                    raise KeyError
                required_presentation = {
                    "finding_id", "headline", "what_changed", "why_aia", "importance",
                    "importance_reason", "executive_questions",
                }
                required_event = {"event_id", "entity_ids", "first_seen_at", "change_type", "previous_event_id"}
                if not required_presentation <= presentation.keys() or not required_event <= event.keys():
                    raise KeyError
            except (KeyError, TypeError):
                raise ResearchLoopError("analysis_contract", "A discovery is missing required regulatory fields.") from None
            errors = self.skill_loader.validate_candidate(bundles[market_id], candidate)
            if errors:
                raise ResearchLoopError("analysis_contract", f"Regulatory candidate failed its contract: {errors[0]}")
            analyzed.append(deepcopy(discovery))
        return tuple(analyzed)


class ContractVerificationRole:
    """Recompute claim status from checked links and build P0 event findings."""

    role_version = "contract-verification@0.1.1"

    def __init__(self, *, evidence_policy: str = "synthetic"):
        if evidence_policy not in {"synthetic", "citation_only"}:
            raise ValueError("Unknown verification evidence policy.")
        self.evidence_policy = evidence_policy
        self.checked_by = "fixture_author" if evidence_policy == "synthetic" else "verification_agent"
        if evidence_policy == "citation_only":
            self.role_version = "contract-verification-citation-only@0.1.0"

    def _verified_claims(self, evidence: Mapping[str, dict], claims: Mapping[str, dict]) -> dict[str, dict]:
        verified: dict[str, dict] = {}
        for claim_id, original in claims.items():
            claim = deepcopy(original)
            try:
                if claim["claim_id"] != claim_id or claim["kind"] not in {"fact", "reported_allegation", "observation"}:
                    raise KeyError
                links = claim["supports"]
                if not isinstance(links, list) or not links:
                    raise KeyError
            except (KeyError, TypeError):
                raise ResearchLoopError("verification_contract", "A research claim has an invalid shape.") from None
            checked_support = False
            checked_refute = False
            for link in links:
                try:
                    item = evidence[link["evidence_id"]]
                    if self.evidence_policy == "citation_only" and link["checked_by"] != "not_checked":
                        raise KeyError
                    checked = link["checked_by"] == self.checked_by
                    if link["relation"] == "supports" and checked and item["source_class"] == "official":
                        checked_support = True
                    if link["relation"] == "refutes" and checked:
                        checked_refute = True
                except (KeyError, TypeError):
                    raise ResearchLoopError("verification_contract", "A claim references missing or invalid evidence.") from None
            claim["verification"] = "conflicted" if checked_refute else "supported" if checked_support else "unverified"
            verified[claim_id] = claim
        return verified

    def verify(
        self,
        analyzed: tuple[dict, ...],
        evidence: Mapping[str, dict],
        claims: Mapping[str, dict],
    ) -> dict:
        for item in evidence.values():
            try:
                parsed = urlsplit(item.get("url", ""))
                host = (parsed.hostname or "").lower().rstrip(".")
            except ValueError:
                parsed = None
                host = ""
            if self.evidence_policy == "synthetic":
                if (item.get("origin") != "synthetic" or item.get("retention") != "synthetic"
                        or item.get("source_class") != "official" or item.get("native_citation") is not None
                        or item.get("document_role") not in DOCUMENT_ROLES):
                    raise ResearchLoopError("offline_boundary", "P4-A accepts only synthetic official evidence.")
                if host != "example" and not host.endswith(".example"):
                    raise ResearchLoopError("offline_boundary", "P4-A synthetic evidence must use a reserved .example URL.")
            elif (item.get("origin") != "bing_grounding"
                  or item.get("retention") != "approved_metadata_only"
                  or item.get("source_class") != "official"
                  or not isinstance(item.get("native_citation"), dict)
                  or item.get("excerpt") is not None
                  or item.get("document_role") != "discovery_signal"
                  or parsed is None
                  or parsed.scheme != "https"
                  or parsed.username is not None
                  or parsed.password is not None
                  or not host
                  or host == "example"
                  or host.endswith(".example")
                  or item["native_citation"].get("type") != "url_citation"
                  or item["native_citation"].get("url") != item.get("url")
                  or type(item["native_citation"].get("start_index")) is not int
                  or type(item["native_citation"].get("end_index")) is not int
                  or not (0 <= item["native_citation"]["start_index"]
                          < item["native_citation"]["end_index"])):
                raise ResearchLoopError(
                    "citation_boundary",
                    "Mocked Foundry verification accepts only metadata-only native citation signals.",
                )
        verified_claims = self._verified_claims(evidence, claims)
        events: list[dict] = []
        findings: list[dict] = []
        unresolved: list[str] = []

        claim_owners: dict[str, str] = {}
        evidence_owners: dict[str, str] = {}
        for discovery in analyzed:
            try:
                event_id = discovery["event"]["event_id"]
                local_claim_ids = [item["claim_id"] for item in discovery["claims"]]
                local_evidence_ids = [item["evidence_id"] for item in discovery["evidence"]]
            except (KeyError, TypeError):
                raise ResearchLoopError("verification_contract", "A discovery has invalid evidence ownership.") from None
            if len(local_claim_ids) != len(set(local_claim_ids)) or len(local_evidence_ids) != len(set(local_evidence_ids)):
                raise ResearchLoopError("verification_contract", "A discovery repeats a local claim or evidence id.")
            for claim_id in local_claim_ids:
                owner = claim_owners.setdefault(claim_id, event_id)
                if owner != event_id:
                    raise ResearchLoopError("verification_contract", "A research claim belongs to more than one event.")
            for evidence_id in local_evidence_ids:
                owner = evidence_owners.setdefault(evidence_id, event_id)
                if owner != event_id:
                    raise ResearchLoopError("verification_contract", "An evidence record belongs to more than one event.")

        for discovery in analyzed:
            candidate = discovery["candidate"]
            event_input = discovery["event"]
            presentation = discovery["presentation"]
            event_id = event_input["event_id"]
            claim_ids = candidate["evidence_assessment"]["supporting_claim_ids"]
            local_claim_ids = {item["claim_id"] for item in discovery["claims"]}
            local_evidence_ids = {item["evidence_id"] for item in discovery["evidence"]}
            if any(
                claim_id not in verified_claims
                or claim_id not in local_claim_ids
                or claim_owners.get(claim_id) != event_id
                for claim_id in claim_ids
            ):
                raise ResearchLoopError("verification_contract", "A candidate references a claim outside its event.")
            selected_claims = [verified_claims[claim_id] for claim_id in claim_ids]
            if any(
                link["evidence_id"] not in local_evidence_ids
                or evidence_owners.get(link["evidence_id"]) != event_id
                for claim in selected_claims
                for link in claim["supports"]
            ):
                raise ResearchLoopError("verification_contract", "A candidate claim references evidence outside its event.")
            any_conflict = any(claim["verification"] == "conflicted" for claim in selected_claims)
            all_supported_facts = all(
                claim["verification"] == "supported" and claim["kind"] != "reported_allegation"
                for claim in selected_claims
            )
            all_have_primary_support = all(
                any(
                    link["relation"] == "supports"
                    and link["checked_by"] == self.checked_by
                    and evidence[link["evidence_id"]]["document_role"] == "primary_document"
                    and evidence[link["evidence_id"]]["publisher"] == candidate["issuer"]
                    for link in claim["supports"]
                )
                for claim in selected_claims
            )
            if any_conflict:
                evidence_status = "conflicted"
            elif all_supported_facts and all_have_primary_support:
                evidence_status = "primary_supported"
            elif any(claim["verification"] == "supported" for claim in selected_claims):
                evidence_status = "signal_only"
            else:
                evidence_status = "unverifiable"

            recommendation = candidate["recommended_disposition"]
            if recommendation == "ignore":
                decision, decision_code = "ignored", "ignore_irrelevant"
                decision_reason = "The regulatory skill marked the item outside the actionable scope."
            elif evidence_status == "primary_supported" and recommendation == "proceed_to_verification":
                decision, decision_code = "selected", "select_verified_material"
                decision_reason = "The stated regulatory facts have checked primary support; business impact remains conditional."
            elif evidence_status == "conflicted":
                decision, decision_code = "watch", "watch_conflicting_evidence"
                decision_reason = "Checked evidence conflicts, so the item remains under review."
                unresolved.append(event_input["event_id"])
            else:
                decision, decision_code = "watch", "watch_material_unverified"
                decision_reason = "Material regulatory questions remain unsupported by an applicable checked primary document."
                unresolved.append(event_input["event_id"])

            impact_claim_ids = sorted({
                claim_id
                for impact in candidate["business_impacts"]
                for claim_id in impact["basis_claim_ids"]
            }) or list(claim_ids)
            impact_text = " ".join(impact["assessment"] for impact in candidate["business_impacts"])
            if not impact_text:
                impact_text = "Public evidence is insufficient for a specific AIA business-impact conclusion."
            what_changed = candidate["change_from_prior_rule"] or presentation["what_changed"]
            event = {
                "event_id": event_input["event_id"],
                "topic_id": candidate["topic_id"],
                "market_ids": [candidate["market_id"]],
                "entity_ids": deepcopy(event_input["entity_ids"]),
                "claim_ids": list(claim_ids),
                "event_date": candidate["publication_date"],
                "effective_date": candidate["effective_date"],
                "first_seen_at": event_input["first_seen_at"],
                "change_type": event_input["change_type"],
                "previous_event_id": event_input["previous_event_id"],
            }
            finding = {
                "finding_id": presentation["finding_id"],
                "event_id": event_input["event_id"],
                "headline": presentation["headline"],
                "fact_claim_ids": list(claim_ids),
                "what_changed": what_changed,
                "why_aia": presentation["why_aia"],
                "analysis": {
                    "text": impact_text,
                    "basis_claim_ids": impact_claim_ids,
                    "assumptions": ["AIA applicability and exposure remain conditional until supported by entity and internal data."],
                    "unknowns": deepcopy(candidate["unknowns"]),
                },
                "importance": presentation["importance"],
                "importance_reason": presentation["importance_reason"],
                "evidence_status": evidence_status,
                "decision": decision,
                "decision_code": decision_code,
                "decision_reason": decision_reason,
                "executive_questions": deepcopy(presentation["executive_questions"]),
            }
            events.append(event)
            findings.append(finding)

        sufficient = bool(findings) and not unresolved
        return {
            "claims": [verified_claims[key] for key in sorted(verified_claims)],
            "events": events,
            "findings": findings,
            "unresolved_event_ids": sorted(set(unresolved)),
            "sufficient": sufficient,
        }


@dataclass(frozen=True)
class ResearchOutcome:
    result: dict
    coverage_plan: dict
    budget_usage: dict
    trace: tuple[dict, ...]


class ResearchController:
    """Bounded offline controller for one regulatory event type."""

    def __init__(
        self,
        repository_root: str | Path,
        research_role: ResearchRole,
        *,
        analysis_role: AnalysisRole | None = None,
        verification_role: VerificationRole | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.root = Path(repository_root).resolve()
        self.skill_loader = SkillLoader(self.root)
        self.source_registry = SourceRegistry.load(self.root / "config" / "sources" / "source-registry.json")
        self.coverage_planner = CoveragePlanner(self.root, self.source_registry)
        self.research_role = research_role
        self.analysis_role = analysis_role or RegulatoryAnalysisRole(self.skill_loader)
        self.verification_role = verification_role or ContractVerificationRole()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.assets = load_assets()

    @staticmethod
    def _merge_evidence(target: dict[str, dict], items: list[dict] | tuple[dict, ...]) -> tuple[set[str], int]:
        new_origins: set[str] = set()
        new_count = 0
        existing_origins = {item["origin_group_id"] for item in target.values()}
        for item in items:
            try:
                evidence_id = item["evidence_id"]
                origin_group = item["origin_group_id"]
            except (KeyError, TypeError):
                raise ResearchLoopError("research_contract", "Evidence is missing its id or origin group.") from None
            if evidence_id in target:
                if target[evidence_id] != item:
                    raise ResearchLoopError("research_contract", "The same evidence id changed across rounds.")
                continue
            target[evidence_id] = deepcopy(item)
            new_count += 1
            if origin_group not in existing_origins:
                new_origins.add(origin_group)
        return new_origins, new_count

    @staticmethod
    def _merge_claims(target: dict[str, dict], items: list[dict] | tuple[dict, ...]) -> int:
        new_count = 0
        for item in items:
            try:
                claim_id = item["claim_id"]
                statement = item["statement"]
                kind = item["kind"]
                supports = item["supports"]
            except (KeyError, TypeError):
                raise ResearchLoopError("research_contract", "Claim fields are incomplete.") from None
            if claim_id not in target:
                target[claim_id] = deepcopy(item)
                new_count += 1
                continue
            current = target[claim_id]
            if current.get("statement") != statement or current.get("kind") != kind:
                raise ResearchLoopError("research_contract", "The same claim id changed meaning across rounds.")
            known = {json.dumps(link, sort_keys=True, ensure_ascii=False) for link in current["supports"]}
            for link in supports:
                encoded = json.dumps(link, sort_keys=True, ensure_ascii=False)
                if encoded not in known:
                    current["supports"].append(deepcopy(link))
                    known.add(encoded)
        return new_count

    @staticmethod
    def _merge_repeated_discovery(current: dict, discovery: dict) -> dict:
        try:
            current_candidate = current["candidate"]
            new_candidate = discovery["candidate"]
            current_event = current["event"]
            new_event = discovery["event"]
            immutable_candidate_fields = (
                "skill_id", "skill_version", "topic_id", "event_type", "market_id",
                "issuer", "document_title", "jurisdiction",
            )
            immutable_event_fields = ("change_type", "previous_event_id")
            if any(current_candidate[field] != new_candidate[field] for field in immutable_candidate_fields):
                raise ValueError
            if current["presentation"]["finding_id"] != discovery["presentation"]["finding_id"]:
                raise ValueError
            if sorted(current_event["entity_ids"]) != sorted(new_event["entity_ids"]):
                raise ValueError
            if any(current_event[field] != new_event[field] for field in immutable_event_fields):
                raise ValueError

            for field in ("instrument_id", "publication_date", "effective_date", "consultation_deadline"):
                old_value = current_candidate[field]
                new_value = new_candidate[field]
                if old_value is not None and new_value != old_value:
                    raise ValueError
            old_status = current_candidate["document_status"]
            new_status = new_candidate["document_status"]
            if old_status != "unknown" and new_status != old_status:
                raise ValueError
            old_transition = current_candidate["transition_period"]
            new_transition = new_candidate["transition_period"]
            if old_transition is not None:
                if new_transition is None or old_transition["description"] != new_transition["description"]:
                    raise ValueError
                for field in ("start_date", "end_date"):
                    old_value = old_transition[field]
                    new_value = new_transition[field]
                    if old_value is not None and new_value != old_value:
                        raise ValueError

            current_first_seen = _parse_timestamp(current_event["first_seen_at"])
            new_first_seen = _parse_timestamp(new_event["first_seen_at"])
        except (KeyError, TypeError, ValueError):
            raise ResearchLoopError(
                "research_contract",
                "The same event id changed immutable identity or history across rounds.",
            ) from None

        merged = deepcopy(discovery)
        if current_first_seen <= new_first_seen:
            merged["event"]["first_seen_at"] = current_event["first_seen_at"]

        local_evidence: dict[str, dict] = {}
        ResearchController._merge_evidence(local_evidence, current["evidence"])
        ResearchController._merge_evidence(local_evidence, discovery["evidence"])
        local_claims: dict[str, dict] = {}
        ResearchController._merge_claims(local_claims, current["claims"])
        ResearchController._merge_claims(local_claims, discovery["claims"])
        merged["evidence"] = list(local_evidence.values())
        merged["claims"] = list(local_claims.values())
        return merged

    @staticmethod
    def _merge_discoveries(
        target: dict[str, dict], discoveries: tuple[dict, ...]
    ) -> tuple[list[dict], list[dict], int]:
        evidence: list[dict] = []
        claims: list[dict] = []
        new_events = 0
        for discovery in discoveries:
            try:
                event_id = discovery["event"]["event_id"]
                discovery_evidence = discovery["evidence"]
                discovery_claims = discovery["claims"]
                if not isinstance(discovery_evidence, list) or not isinstance(discovery_claims, list):
                    raise KeyError
            except (KeyError, TypeError):
                raise ResearchLoopError("research_contract", "Discovery fields are incomplete.") from None
            if event_id not in target:
                new_events += 1
                merged_discovery = deepcopy(discovery)
            else:
                current = target[event_id]
                merged_discovery = ResearchController._merge_repeated_discovery(current, discovery)
            target[event_id] = merged_discovery
            evidence.extend(discovery_evidence)
            claims.extend(discovery_claims)
        return evidence, claims, new_events

    @staticmethod
    def _apply_coverage_updates(state: dict[tuple[str, str], dict], updates: tuple[dict, ...]) -> None:
        allowed_statuses = {"checked", "partial", "unavailable", "not_attempted"}
        for update in updates:
            try:
                key = (update["market_id"], update["source_class"])
                current = state[key]
                languages = update["languages_checked"]
                status = update["status"]
                detail = update["detail"]
                if (not isinstance(languages, list) or len(languages) != len(set(languages))
                        or set(languages) - set(current["languages_required"])
                        or status not in allowed_statuses or not isinstance(detail, str) or not detail.strip()):
                    raise KeyError
                if status == "checked" and set(languages) != set(current["languages_required"]):
                    raise KeyError
            except (KeyError, TypeError):
                raise ResearchLoopError("coverage_contract", "Coverage update is invalid or outside the plan.") from None
            current.update(languages_checked=list(languages), status=status, detail=detail)

    def run(self, request_document: dict) -> ResearchOutcome:
        request = ResearchRequest.validate(request_document, self.root)
        try:
            bundles = {
                market_id: self.skill_loader.select(
                    topic_id=request.topic_id,
                    event_type=request.event_type,
                    market_id=market_id,
                    include_drafts=request.document["allow_draft_skills"],
                )
                for market_id in request.market_ids
            }
        except SkillSelectionError as exc:
            raise ResearchLoopError("skill_selection", str(exc)) from None
        plan = self.coverage_planner.build(request, bundles)
        coverage_state = {
            (cell["market_id"], cell["source_class"]): {
                **deepcopy(cell),
                "languages_checked": [],
                "status": "not_attempted",
                "detail": "Offline research has not checked this planned cell.",
            }
            for cell in plan.cells
        }

        evidence: dict[str, dict] = {}
        claims: dict[str, dict] = {}
        discoveries: dict[str, dict] = {}
        trace: list[dict] = []
        queries_used = 0
        rounds_used = 0
        event_followups_used: dict[str, int] = {}
        coverage_followups_used = 0
        verified = {"claims": [], "events": [], "findings": [], "unresolved_event_ids": [], "sufficient": False}
        stop_reason: str | None = None
        technical_error: str | None = None

        round_index = 0
        while True:
            coverage_complete_before_round = all(
                item["status"] == "checked" for item in coverage_state.values()
            )
            followup_event_ids: tuple[str, ...] = ()
            coverage_followup = False
            if round_index > 0:
                followup_event_ids = tuple(
                    event_id
                    for event_id in verified["unresolved_event_ids"]
                    if event_followups_used.get(event_id, 0) < request.max_followups
                )
                coverage_followup = (
                    not coverage_complete_before_round
                    and coverage_followups_used < request.max_followups
                )
                if not followup_event_ids and not coverage_followup:
                    stop_reason = "budget_exhausted"
                    break
            context = ResearchContext(
                round_index=round_index,
                followup=round_index > 0,
                remaining_queries=request.max_queries - queries_used,
                remaining_evidence_records=request.max_evidence - len(evidence),
                coverage_plan=plan.record(),
                unresolved_event_ids=followup_event_ids,
                request_key=request.request_key,
                request_sha256=request.content_sha256,
            )
            try:
                batch = self.research_role.research(context)
                if type(batch.queries_executed) is not int or batch.queries_executed < 0:
                    raise ResearchLoopError(
                        "research_contract",
                        "The research role returned an invalid query count.",
                    )
                if batch.queries_executed > context.remaining_queries:
                    stop_reason = "budget_exhausted"
                    break
                if round_index > 0:
                    try:
                        returned_existing_events = {
                            item["event"]["event_id"]
                            for item in batch.discoveries
                            if item["event"]["event_id"] in discoveries
                        }
                    except (KeyError, TypeError):
                        raise ResearchLoopError("research_contract", "A follow-up discovery has no event id.") from None
                    if returned_existing_events - set(followup_event_ids):
                        raise ResearchLoopError(
                            "followup_budget",
                            "The research role returned an event outside its remaining follow-up budget.",
                        )
                staged_discoveries = deepcopy(discoveries)
                raw_evidence, raw_claims, new_events = self._merge_discoveries(
                    staged_discoveries, batch.discoveries
                )
                new_evidence_ids = {item.get("evidence_id") for item in raw_evidence} - set(evidence)
                if len(new_evidence_ids) > context.remaining_evidence_records:
                    stop_reason = "budget_exhausted"
                    break
                queries_used += batch.queries_executed
                rounds_used += 1
                if round_index > 0:
                    for event_id in followup_event_ids:
                        event_followups_used[event_id] = event_followups_used.get(event_id, 0) + 1
                    if coverage_followup:
                        coverage_followups_used += 1
                discoveries = staged_discoveries
                new_origins, _ = self._merge_evidence(evidence, raw_evidence)
                new_claims = self._merge_claims(claims, raw_claims)
                self._apply_coverage_updates(coverage_state, batch.coverage_updates)
                analyzed = self.analysis_role.analyze(discoveries, bundles, request)
                verified = self.verification_role.verify(analyzed, evidence, claims)
                new_information = bool(new_origins or new_claims or new_events)
                trace.append({
                    "round_index": round_index,
                    "followup": round_index > 0,
                    "queries_executed": batch.queries_executed,
                    "new_origin_groups": len(new_origins),
                    "new_claims": new_claims,
                    "new_events": new_events,
                    "unresolved_events": len(verified["unresolved_event_ids"]),
                })
            except ResearchLoopError as exc:
                if (type(exc.queries_consumed) is int and exc.queries_consumed > 0
                        and exc.queries_consumed <= context.remaining_queries):
                    queries_used += exc.queries_consumed
                stop_reason = "technical_failure"
                technical_error = f"{exc.code}: {exc}"
                break
            except Exception:
                stop_reason = "technical_failure"
                technical_error = "unexpected_failure: Offline research role failed without exposing raw content."
                break

            unavailable = any(item["status"] == "unavailable" for item in coverage_state.values())
            coverage_complete = all(item["status"] == "checked" for item in coverage_state.values())
            if unavailable:
                stop_reason = "required_source_unavailable"
                break
            if verified["sufficient"] and coverage_complete:
                stop_reason = "sufficient_evidence"
                break
            if round_index == 0 and not discoveries and coverage_complete:
                stop_reason = "no_new_independent_information"
                break
            if round_index > 0 and not new_information:
                stop_reason = "no_new_independent_information"
                break
            round_index += 1

        stop_reason = stop_reason or "budget_exhausted"
        generated = self.clock()
        if generated.utcoffset() is None:
            raise ResearchLoopError("invalid_clock", "Controller clock must be timezone-aware.")
        if generated < _parse_timestamp(request.as_of):
            raise ResearchLoopError("invalid_clock", "Controller clock cannot precede the request cutoff.")
        generated_at = generated.isoformat()

        coverage = [
            {
                "market_id": item["market_id"],
                "topic_id": item["topic_id"],
                "source_class": item["source_class"],
                "languages_checked": item["languages_checked"],
                "status": item["status"],
                "detail": item["detail"],
            }
            for _, item in sorted(coverage_state.items())
        ]
        coverage_complete = all(item["status"] == "checked" for item in coverage)
        if stop_reason == "technical_failure":
            status = "failed"
            final_evidence: list[dict] = []
            final_claims: list[dict] = []
            final_events: list[dict] = []
            final_findings: list[dict] = []
            errors = [technical_error or "technical_failure: Offline research failed."]
        else:
            status = "completed" if coverage_complete and stop_reason in {
                "sufficient_evidence", "no_new_independent_information"
            } else "partial"
            final_evidence = []
            for key in sorted(evidence):
                public_item = deepcopy(evidence[key])
                public_item.pop("document_role", None)
                final_evidence.append(public_item)
            final_claims = verified["claims"]
            final_events = verified["events"]
            final_findings = verified["findings"]
            errors = [] if status == "completed" else [
                {
                    "budget_exhausted": "Configured offline research budget ended before all evidence questions and coverage were resolved.",
                    "required_source_unavailable": "A required official-source coverage cell was unavailable.",
                    "no_new_independent_information": "Research stopped without new independent information while coverage remained incomplete.",
                }.get(stop_reason, "Offline research ended with an explicit coverage gap.")
            ]

        skill_versions = sorted({
            f"skill:{record['skill_id']}@{record['version']}#{record['content_sha256']}"
            for bundle in bundles.values()
            for record in bundle.execution_record()["skills"]
        })
        result = {
            "schema_version": "0.1.0",
            "data_kind": "synthetic",
            "profile_id": self.assets["profile"]["profile_id"],
            "profile_version": self.assets["profile"]["version"],
            "taxonomy_version": self.assets["taxonomy"]["version"],
            "entity_catalog_version": self.assets["entities"]["version"],
            "rule_version": self.assets["profile"]["selection_policy"]["rule_version"],
            "run": {
                "run_id": request.run_id,
                "request_key": request.request_key,
                "as_of": request.as_of,
                "generated_at": generated_at,
                "window": deepcopy(request.document["window"]),
                "scope": {
                    "market_ids": list(request.market_ids),
                    "topic_ids": [request.topic_id],
                    "source_classes": deepcopy(request.document["scope"]["source_classes"]),
                },
                "status": status,
                "stop_reason": stop_reason,
                "errors": errors,
                "agent_versions": [
                    CONTROLLER_VERSION,
                    self.research_role.role_version,
                    self.analysis_role.role_version,
                    self.verification_role.role_version,
                    *skill_versions,
                ],
            },
            "evidence": final_evidence,
            "claims": final_claims,
            "events": final_events,
            "findings": final_findings,
            "coverage": coverage,
        }
        contract_errors = validate_result(result, self.assets)
        if contract_errors:
            result["run"].update(
                status="failed",
                stop_reason="technical_failure",
                errors=[f"result_contract: P4-A result failed P0 validation: {contract_errors[0]}"],
            )
            for key in ("evidence", "claims", "events", "findings"):
                result[key] = []
            remaining_errors = validate_result(result, self.assets)
            if remaining_errors:
                raise ResearchLoopError("result_contract", "P4-A could not construct a safe failed result.")
        return ResearchOutcome(
            result=result,
            coverage_plan=plan.record(),
            budget_usage={
                "rounds_executed": rounds_used,
                "followup_rounds_executed": max(0, rounds_used - 1),
                "queries_executed": queries_used,
                "evidence_records": len(evidence),
                "event_followup_rounds": {
                    event_id: event_followups_used[event_id]
                    for event_id in sorted(event_followups_used)
                },
                "query_limit": request.max_queries,
                "evidence_limit": request.max_evidence,
            },
            trace=tuple(trace),
        )


def load_offline_case(path: str | Path, case_id: str) -> dict:
    fixture = read_json(path)
    if (not isinstance(fixture, dict) or fixture.get("data_kind") != "synthetic"
            or fixture.get("annotation_status") != "draft_pending_domain_review"):
        raise ResearchLoopError("invalid_fixture", "Offline case collection is not an approved synthetic fixture.")
    cases = fixture.get("cases")
    if not isinstance(cases, list):
        raise ResearchLoopError("invalid_fixture", "Offline case collection has no cases.")
    matches = [case for case in cases if isinstance(case, dict) and case.get("case_id") == case_id]
    if len(matches) != 1:
        raise ResearchLoopError("unknown_case", "Offline case id must identify exactly one case.")
    return deepcopy(matches[0])
