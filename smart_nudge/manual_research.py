"""Explicit non-production request contract for manual live PoC research."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from scripts.validate_p0 import validate_result
from smart_nudge.research import (
    ContractVerificationRole,
    ResearchController,
    ResearchLoopError,
    ResearchRequest,
    read_json,
)
from smart_nudge.skills import SkillLoader, SkillSelectionError
from smart_nudge.source_verification import LiveVerifiedResearchRole


LIVE_CONTROLLER_VERSION = "manual-live-controller@0.1.0"


@dataclass(frozen=True)
class ManualLiveResearchRequest(ResearchRequest):
    """A live request bound to exact local Skill bundle digests."""

    @classmethod
    def validate(
        cls, document: dict, repository_root: str | Path
    ) -> "ManualLiveResearchRequest":
        root = Path(repository_root).resolve()
        schema = read_json(root / "schemas/manual-live-research-request.schema.json")
        try:
            Draft202012Validator.check_schema(schema)
        except Exception:
            raise ResearchLoopError(
                "invalid_live_request_schema", "The manual-live request Schema is invalid."
            ) from None
        errors = sorted(
            Draft202012Validator(
                schema, format_checker=FormatChecker()
            ).iter_errors(document),
            key=lambda item: [str(part) for part in item.absolute_path],
        )
        if errors:
            raise ResearchLoopError(
                "invalid_live_request",
                "The manual-live request does not satisfy its Schema.",
            )
        try:
            start = datetime.fromisoformat(
                document["window"]["start"].replace("Z", "+00:00")
            )
            end = datetime.fromisoformat(
                document["window"]["end"].replace("Z", "+00:00")
            )
            as_of = datetime.fromisoformat(document["as_of"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            raise ResearchLoopError(
                "invalid_live_request", "Request timestamps must be valid and timezone-aware."
            ) from None
        if (
            start.utcoffset() is None
            or end.utcoffset() is None
            or as_of.utcoffset() is None
            or not start < end <= as_of
        ):
            raise ResearchLoopError(
                "invalid_live_request", "Request requires window start < end <= as_of."
            )

        policy = read_json(root / "config/policies/p4-manual-live-run.json")
        try:
            if (
                policy["status"] != "approved_for_manual_live"
                or policy["live_enabled"] is not True
                or policy["environment"] != "poc_non_production"
                or policy["approval_basis"] != "user_authorized_assumption"
                or policy["allow_draft_skills_for_poc"] is not True
            ):
                raise KeyError
            for key in ("max_queries", "max_evidence_records"):
                if document["budget"][key] > policy["limits"][key]:
                    raise ResearchLoopError(
                        "budget_exceeds_live_policy",
                        f"Request exceeds the manual-live limit for {key}.",
                    )
        except (KeyError, TypeError):
            raise ResearchLoopError(
                "live_policy_disabled", "The PoC manual-live policy is not enabled."
            ) from None

        try:
            loader = SkillLoader(root)
            actual = {
                market_id: loader.select(
                    topic_id=document["scope"]["topic_id"],
                    event_type=document["scope"]["event_type"],
                    market_id=market_id,
                    include_drafts=True,
                ).bundle_sha256
                for market_id in document["scope"]["market_ids"]
            }
        except SkillSelectionError as exc:
            raise ResearchLoopError("skill_selection", str(exc)) from None
        if actual != document["skill_bundle_sha256s"]:
            raise ResearchLoopError(
                "skill_bundle_mismatch",
                "The manual-live request is not bound to the selected Skill bundles.",
            )
        return cls(deepcopy(document))


@dataclass(frozen=True)
class ManualLiveResearchResult:
    """A P0-valid live result bound to one manual-live request."""

    document: dict

    @classmethod
    def validate(
        cls,
        document: dict,
        repository_root: str | Path,
        *,
        request: ManualLiveResearchRequest | None = None,
    ) -> "ManualLiveResearchResult":
        root = Path(repository_root).resolve()
        schema = read_json(root / "schemas/manual-live-research-result.schema.json")
        try:
            Draft202012Validator.check_schema(schema)
        except Exception:
            raise ResearchLoopError(
                "invalid_live_result_schema",
                "The manual-live result Schema is invalid.",
            ) from None
        errors = sorted(
            Draft202012Validator(
                schema, format_checker=FormatChecker()
            ).iter_errors(document),
            key=lambda item: [str(part) for part in item.absolute_path],
        )
        if errors:
            raise ResearchLoopError(
                "invalid_live_result",
                "The manual-live result does not satisfy its Schema.",
            )
        assets = {
            "profile": read_json(root / "config/watch_profiles/aia-group-ceo.json"),
            "taxonomy": read_json(
                root / "config/topics/insurance-intelligence.json"
            ),
            "entities": read_json(root / "config/entities/aia-pilot.json"),
            "schema": read_json(root / "schemas/intelligence-result.schema.json"),
        }
        p0_errors = validate_result(document, assets)
        if p0_errors:
            raise ResearchLoopError(
                "invalid_live_result",
                f"The manual-live result failed P0 validation: {p0_errors[0]}",
            )
        run = document["run"]
        if LIVE_CONTROLLER_VERSION not in run["agent_versions"]:
            raise ResearchLoopError(
                "invalid_live_result",
                "The manual-live result is missing its live controller version.",
            )
        if request is not None:
            expected_scope = {
                "market_ids": list(request.market_ids),
                "topic_ids": [request.topic_id],
                "source_classes": deepcopy(
                    request.document["scope"]["source_classes"]
                ),
            }
            request_as_of = datetime.fromisoformat(
                request.as_of.replace("Z", "+00:00")
            )
            result_as_of = datetime.fromisoformat(
                run["as_of"].replace("Z", "+00:00")
            )
            if (
                run["run_id"] != request.run_id
                or run["request_key"] != request.request_key
                or result_as_of < request_as_of
                or run["as_of"] != run["generated_at"]
                or run["window"] != request.document["window"]
                or run["scope"] != expected_scope
            ):
                raise ResearchLoopError(
                    "live_result_request_mismatch",
                    "The manual-live result is not bound to its validated request.",
                )
        return cls(deepcopy(document))


class ManualLiveResearchController(ResearchController):
    """P0 controller restricted to one authorized live verification composition."""

    controller_version = LIVE_CONTROLLER_VERSION
    data_kind = "live"
    execution_label = "Manual-live research"

    def _result_as_of(
        self, request: ManualLiveResearchRequest, generated: datetime
    ) -> str:
        """A live result is current through completion, not request creation."""

        return generated.isoformat()

    def __init__(
        self,
        repository_root: str | Path,
        research_role: LiveVerifiedResearchRole,
        *,
        clock=None,
    ):
        if type(research_role) is not LiveVerifiedResearchRole:
            raise ValueError(
                "Manual-live control requires the authorized live verification role."
            )
        if type(research_role.request) is not ManualLiveResearchRequest:
            raise ValueError(
                "Manual-live control requires an exact validated manual-live request."
            )
        self.session = research_role.session
        super().__init__(
            repository_root,
            research_role,
            verification_role=ContractVerificationRole(
                evidence_policy="direct_verification"
            ),
            clock=clock,
        )

    def _validate_request_document(
        self, request_document: dict
    ) -> ManualLiveResearchRequest:
        request = ManualLiveResearchRequest.validate(request_document, self.root)
        role_request = self.research_role.request
        authorization = self.session.authorization
        if (
            role_request.request_key != request.request_key
            or role_request.content_sha256 != request.content_sha256
            or authorization.request_key != request.request_key
            or authorization.request_sha256 != request.content_sha256
        ):
            raise ResearchLoopError(
                "live_request_mismatch",
                "The live controller, roles and authorization must share one request.",
            )
        return request

    def _result_contract_errors(
        self, result: dict, request: ResearchRequest
    ) -> list[str]:
        try:
            ManualLiveResearchResult.validate(
                result,
                self.root,
                request=request,
            )
        except ResearchLoopError as exc:
            return [f"{exc.code}: {exc}"]
        return []
