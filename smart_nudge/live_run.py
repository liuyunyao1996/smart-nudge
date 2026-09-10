"""Deny-by-default authorization and accounting for manual live runs.

This module does not load credentials or perform network I/O.  Its checked-in
policy is limited to an explicitly authorized, non-production PoC.  Production
and tests both load the policy from the supplied repository root.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from smart_nudge.sources import (
    ApprovedSourceClient,
    FetchedSource,
    SourcePolicyError,
    SourceRegistry,
)


LIVE_POLICY_PATH = Path("config/policies/p4-manual-live-run.json")
LIVE_AUTHORIZATION_SCHEMA_PATH = Path(
    "schemas/manual-live-run-authorization.schema.json"
)
APPROVED_POLICY_STATUS = "approved_for_manual_live"
_AUTHORIZATION_LOAD_TOKEN = object()
_AUTHORIZATION_RECEIPT_DIRECTORY = Path(".tmp/manual-live-authorizations")


class LiveRunBoundaryError(RuntimeError):
    """A curated live-boundary failure with no credential or content detail."""

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


def _read_json(path: Path, *, code: str) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (OSError, ValueError):
        raise LiveRunBoundaryError(code, "Could not read a required live-run control file.") from None
    if not isinstance(value, dict):
        raise LiveRunBoundaryError(code, "A live-run control file must contain an object.")
    return value


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return parsed


@dataclass(frozen=True, init=False)
class ManualLiveRunAuthorization:
    """Immutable, short-lived permission for exactly one research request."""

    _document_json: str
    policy_version: str

    def __init__(self, document_json: str, policy_version: str, *, _token=None):
        if _token is not _AUTHORIZATION_LOAD_TOKEN:
            raise LiveRunBoundaryError(
                "invalid_authorization",
                "Manual live-run authorization must be created by the checked policy loader.",
            )
        object.__setattr__(self, "_document_json", document_json)
        object.__setattr__(self, "policy_version", policy_version)

    @classmethod
    def load(
        cls,
        repository_root: str | Path,
        authorization_file: str | Path | None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> "ManualLiveRunAuthorization":
        root = Path(repository_root).resolve()
        if authorization_file is None:
            raise LiveRunBoundaryError(
                "live_disabled", "No manual live-run authorization was supplied."
            )
        path = Path(authorization_file).resolve()
        if not path.is_file():
            raise LiveRunBoundaryError(
                "live_disabled", "The manual live-run authorization does not exist."
            )
        document = _read_json(path, code="invalid_authorization")
        schema = _read_json(
            root / LIVE_AUTHORIZATION_SCHEMA_PATH, code="invalid_live_schema"
        )
        try:
            Draft202012Validator.check_schema(schema)
        except Exception:
            raise LiveRunBoundaryError(
                "invalid_live_schema", "The live-run authorization Schema is invalid."
            ) from None
        errors = sorted(
            Draft202012Validator(
                schema, format_checker=FormatChecker()
            ).iter_errors(document),
            key=lambda item: [str(part) for part in item.absolute_path],
        )
        if errors:
            raise LiveRunBoundaryError(
                "invalid_authorization",
                "The manual live-run authorization does not satisfy its Schema.",
            )

        policy = _read_json(root / LIVE_POLICY_PATH, code="invalid_live_policy")
        cls._validate_policy(policy)
        if policy["live_enabled"] is not True or policy["status"] != APPROVED_POLICY_STATUS:
            raise LiveRunBoundaryError(
                "live_disabled",
                "Manual live execution remains disabled pending organizational and domain approval.",
            )

        now = (clock or (lambda: datetime.now(timezone.utc)))()
        if now.utcoffset() is None:
            raise LiveRunBoundaryError(
                "invalid_clock", "The live-run clock must be timezone-aware."
            )
        issued_at = _parse_timestamp(document["issued_at"])
        expires_at = _parse_timestamp(document["expires_at"])
        ttl_seconds = (expires_at - issued_at).total_seconds()
        if ttl_seconds <= 0 or ttl_seconds > policy["limits"]["max_authorization_ttl_minutes"] * 60:
            raise LiveRunBoundaryError(
                "invalid_authorization", "The live-run authorization lifetime is invalid."
            )
        if now < issued_at or now >= expires_at:
            raise LiveRunBoundaryError(
                "authorization_inactive", "The live-run authorization is not currently active."
            )
        for key in ("max_queries", "max_evidence_records"):
            if document["budget"][key] > policy["limits"][key]:
                raise LiveRunBoundaryError(
                    "budget_exceeds_policy", f"The live-run authorization exceeds {key}."
                )
        if document["retry_policy"]["automatic_retries"] != policy["limits"]["automatic_retries"]:
            raise LiveRunBoundaryError(
                "retry_policy", "Automatic retries are not permitted for a manual live run."
            )

        try:
            registry = SourceRegistry.load(
                root / "config" / "sources" / "source-registry.json"
            )
            for source_id in document["allowed_source_ids"]:
                source = registry.source(source_id)
                if source["search_mode"] != "trusted_registry":
                    raise SourcePolicyError(
                        "source_not_searchable", "Source is not enabled for trusted discovery."
                    )
        except SourcePolicyError:
            raise LiveRunBoundaryError(
                "source_not_allowed",
                "The authorization names a source outside the reviewed P2 registry.",
            ) from None
        canonical = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return cls(canonical, policy["policy_version"], _token=_AUTHORIZATION_LOAD_TOKEN)

    @staticmethod
    def _validate_policy(policy: dict) -> None:
        try:
            limits = policy["limits"]
            valid = (
                isinstance(policy["policy_version"], str)
                and policy["status"] in {
                    "disabled_pending_organizational_and_domain_approval",
                    APPROVED_POLICY_STATUS,
                }
                and type(policy["live_enabled"]) is bool
                and policy.get("environment") == "poc_non_production"
                and policy.get("approval_basis") == "user_authorized_assumption"
                and policy.get("allow_draft_skills_for_poc") is True
                and policy["allowed_channels"] == [
                    "foundry_bing_research",
                    "foundry_source_verification",
                    "approved_source_fetch",
                ]
                and type(limits["max_authorization_ttl_minutes"]) is int
                and 1 <= limits["max_authorization_ttl_minutes"] <= 1440
                and type(limits["max_queries"]) is int
                and 1 <= limits["max_queries"] <= 30
                and type(limits["max_evidence_records"]) is int
                and 1 <= limits["max_evidence_records"] <= 100
                and limits["automatic_retries"] == 0
                and isinstance(policy["rules"], list)
                and bool(policy["rules"])
            )
        except (KeyError, TypeError):
            valid = False
        if not valid:
            raise LiveRunBoundaryError(
                "invalid_live_policy", "The manual live-run policy is incomplete or unsafe."
            )
        if policy["live_enabled"] != (policy["status"] == APPROVED_POLICY_STATUS):
            raise LiveRunBoundaryError(
                "invalid_live_policy", "The live-run policy status and enabled flag disagree."
            )

    @property
    def document(self) -> dict:
        return json.loads(self._document_json)

    @property
    def authorization_id(self) -> str:
        return self.document["authorization_id"]

    @property
    def request_key(self) -> str:
        return self.document["request_key"]

    @property
    def request_sha256(self) -> str:
        return self.document["request_sha256"]

    @property
    def expires_at(self) -> str:
        return self.document["expires_at"]

    @property
    def issued_at(self) -> str:
        return self.document["issued_at"]

    @property
    def allowed_source_ids(self) -> tuple[str, ...]:
        return tuple(self.document["allowed_source_ids"])

    @property
    def max_queries(self) -> int:
        return self.document["budget"]["max_queries"]

    @property
    def max_evidence_records(self) -> int:
        return self.document["budget"]["max_evidence_records"]

    @property
    def content_sha256(self) -> str:
        return sha256(self._document_json.encode("utf-8")).hexdigest()

    def audit_record(self) -> dict:
        return {
            "authorization_id": self.authorization_id,
            "authorization_sha256": self.content_sha256,
            "request_key": self.request_key,
            "request_sha256": self.request_sha256,
            "expires_at": self.expires_at,
            "allowed_source_ids": list(self.allowed_source_ids),
            "query_limit": self.max_queries,
            "evidence_limit": self.max_evidence_records,
            "automatic_retries": 0,
            "policy_version": self.policy_version,
        }


def claim_live_authorization(
    repository_root: str | Path,
    authorization: ManualLiveRunAuthorization,
    *,
    clock: Callable[[], datetime] | None = None,
) -> dict:
    """Atomically consume an authorization ID before a CLI can perform live I/O."""

    if type(authorization) is not ManualLiveRunAuthorization:
        raise LiveRunBoundaryError(
            "invalid_authorization",
            "Only a checked manual live-run authorization can be consumed.",
        )
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if now.utcoffset() is None:
        raise LiveRunBoundaryError(
            "invalid_clock", "The live-run clock must be timezone-aware."
        )
    if now < _parse_timestamp(authorization.issued_at) or now >= _parse_timestamp(
        authorization.expires_at
    ):
        raise LiveRunBoundaryError(
            "authorization_inactive",
            "The manual live-run authorization is not currently active.",
        )

    root = Path(repository_root).resolve()
    receipt_directory = root / _AUTHORIZATION_RECEIPT_DIRECTORY
    try:
        receipt_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise LiveRunBoundaryError(
            "authorization_receipt_failed",
            "Could not create the local one-time authorization receipt directory.",
        ) from None
    receipt_name = sha256(authorization.authorization_id.encode("utf-8")).hexdigest()
    receipt_path = receipt_directory / f"{receipt_name}.json"
    record = {
        "schema_version": "0.1.0",
        "authorization_id": authorization.authorization_id,
        "authorization_sha256": authorization.content_sha256,
        "request_key": authorization.request_key,
        "request_sha256": authorization.request_sha256,
        "claimed_at": now.isoformat(),
    }
    encoded = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    descriptor = None
    try:
        descriptor = os.open(
            receipt_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    except FileExistsError:
        raise LiveRunBoundaryError(
            "authorization_already_used",
            "This manual live-run authorization ID has already been consumed.",
        ) from None
    except OSError:
        raise LiveRunBoundaryError(
            "authorization_receipt_failed",
            "Could not persist the local one-time authorization receipt.",
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return deepcopy(record)


class ManualLiveRunSession:
    """Stateful attempt ledger; budget is charged before any external I/O."""

    def __init__(
        self,
        authorization: ManualLiveRunAuthorization,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        if type(authorization) is not ManualLiveRunAuthorization:
            raise LiveRunBoundaryError(
                "invalid_authorization",
                "A live session requires an authorization created by the checked policy loader.",
            )
        self._authorization = authorization
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._queries_attempted = 0
        self._evidence_records_attempted = 0
        self._attempts: list[dict] = []
        self._lock = Lock()

    @property
    def authorization(self) -> ManualLiveRunAuthorization:
        return self._authorization

    @property
    def queries_attempted(self) -> int:
        return self._queries_attempted

    @property
    def evidence_records_attempted(self) -> int:
        return self._evidence_records_attempted

    def authorize(
        self,
        *,
        channel: str,
        request_key: str,
        request_sha256: str,
        source_ids: Iterable[str],
        query_cost: int = 0,
        evidence_cost: int = 0,
        payload_sha256: str,
    ) -> dict:
        now = self._clock()
        if now.utcoffset() is None:
            raise LiveRunBoundaryError(
                "invalid_clock", "The live-run clock must be timezone-aware."
            )
        if now < _parse_timestamp(self.authorization.issued_at):
            raise LiveRunBoundaryError(
                "authorization_inactive", "The manual live-run authorization is not active yet."
            )
        if now >= _parse_timestamp(self.authorization.expires_at):
            raise LiveRunBoundaryError(
                "authorization_expired", "The manual live-run authorization has expired."
            )
        if channel not in {
            "foundry_bing_research",
            "foundry_source_verification",
            "approved_source_fetch",
        }:
            raise LiveRunBoundaryError("channel_not_allowed", "The live channel is not allowed.")
        if (
            request_key != self.authorization.request_key
            or request_sha256 != self.authorization.request_sha256
        ):
            raise LiveRunBoundaryError(
                "request_mismatch", "The live attempt is not bound to the authorized request."
            )
        requested_sources = tuple(dict.fromkeys(source_ids))
        if not requested_sources or not set(requested_sources).issubset(
            self.authorization.allowed_source_ids
        ):
            raise LiveRunBoundaryError(
                "source_not_allowed", "The live attempt names a source outside its authorization."
            )
        if type(query_cost) is not int or query_cost < 0 or type(evidence_cost) is not int or evidence_cost < 0:
            raise LiveRunBoundaryError("invalid_cost", "Live attempt costs must be non-negative integers.")
        if query_cost + evidence_cost == 0:
            raise LiveRunBoundaryError("invalid_cost", "A live attempt must charge a bounded resource.")
        if (
            not isinstance(payload_sha256, str)
            or len(payload_sha256) != 64
            or any(character not in "0123456789abcdef" for character in payload_sha256)
        ):
            raise LiveRunBoundaryError(
                "invalid_payload_hash", "A live attempt requires a canonical payload hash."
            )
        with self._lock:
            if self._queries_attempted + query_cost > self.authorization.max_queries:
                raise LiveRunBoundaryError(
                    "query_budget_exhausted", "The live query budget is exhausted."
                )
            if (
                self._evidence_records_attempted + evidence_cost
                > self.authorization.max_evidence_records
            ):
                raise LiveRunBoundaryError(
                    "evidence_budget_exhausted", "The live evidence budget is exhausted."
                )

            self._queries_attempted += query_cost
            self._evidence_records_attempted += evidence_cost
            record = {
                "attempt_index": len(self._attempts) + 1,
                "channel": channel,
                "authorized_at": now.isoformat(),
                "source_ids": list(requested_sources),
                "query_cost": query_cost,
                "evidence_cost": evidence_cost,
                "payload_sha256": payload_sha256,
            }
            self._attempts.append(record)
        return deepcopy(record)

    @property
    def attempts(self) -> tuple[dict, ...]:
        with self._lock:
            return tuple(deepcopy(self._attempts))

    def audit_record(self) -> dict:
        with self._lock:
            return {
                **self.authorization.audit_record(),
                "queries_attempted": self._queries_attempted,
                "evidence_records_attempted": self._evidence_records_attempted,
                "attempts": deepcopy(self._attempts),
            }


class ManualLiveSourceClient:
    """Authorize and charge one exact-URL fetch before using the P2 client."""

    def __init__(
        self,
        source_client: ApprovedSourceClient,
        session: ManualLiveRunSession,
        *,
        request_key: str,
        request_sha256: str,
    ):
        if type(source_client) is not ApprovedSourceClient:
            raise LiveRunBoundaryError(
                "live_transport_required",
                "Manual live source retrieval requires the P2 approved-source client.",
            )
        if not source_client.uses_default_transport:
            raise LiveRunBoundaryError(
                "live_transport_required",
                "Manual live source retrieval requires the default verified HTTPS transport.",
            )
        if type(session) is not ManualLiveRunSession:
            raise LiveRunBoundaryError(
                "invalid_authorization", "Manual live source retrieval requires a checked session."
            )
        self.source_client = source_client
        self.session = session
        self.request_key = request_key
        self.request_sha256 = request_sha256

    @property
    def registry(self) -> SourceRegistry:
        return self.source_client.registry

    def fetch(self, url: str) -> FetchedSource:
        target = self.source_client.registry.approved_target(url)
        self.session.authorize(
            channel="approved_source_fetch",
            request_key=self.request_key,
            request_sha256=self.request_sha256,
            source_ids=(target.source["source_id"],),
            evidence_cost=1,
            payload_sha256=sha256(url.encode("utf-8")).hexdigest(),
        )
        return self.source_client.fetch(url)
