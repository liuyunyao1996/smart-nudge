"""Offline preparation of one bounded manual-live PoC run.

This module deliberately does not load credentials, claim an authorization, or
perform network I/O.  It creates request and authorization artifacts only after
the checked-in request, Skill, source, and live-policy validators accept them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from smart_nudge.live_run import ManualLiveRunAuthorization
from smart_nudge.manual_research import ManualLiveResearchRequest
from smart_nudge.research import CoveragePlanner
from smart_nudge.skills import SkillLoader
from smart_nudge.sources import SourceRegistry


HONG_KONG_TIME = timezone(timedelta(hours=8))
DEFAULT_OUTPUT_DIRECTORY = Path(".tmp/manual-live-runs")


class LivePreparationError(RuntimeError):
    """A safe, actionable preparation failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PreparedLiveRun:
    """Paths and safe metadata for prepared, unconsumed live-run artifacts."""

    run_id: str
    request_path: Path
    authorization_path: Path
    result_path: Path
    request_sha256: str
    authorization_id: str
    expires_at: str
    allowed_source_ids: tuple[str, ...]
    max_queries: int
    max_evidence_records: int

    def record(self, repository_root: str | Path) -> dict:
        root = Path(repository_root).resolve()
        request_path = _display_path(root, self.request_path)
        authorization_path = _display_path(root, self.authorization_path)
        result_path = _display_path(root, self.result_path)
        run_command = (
            ".\\.venv\\Scripts\\python.exe scripts\\run_live_poc.py "
            f'--request "{request_path}" --authorization "{authorization_path}" '
            f'--execute-live | Tee-Object -FilePath "{result_path}"'
        )
        return {
            "ok": True,
            "prepared": True,
            "live_executed": False,
            "authorization_consumed": False,
            "run_id": self.run_id,
            "request_path": request_path,
            "authorization_path": authorization_path,
            "result_path": result_path,
            "request_sha256": self.request_sha256,
            "authorization_id": self.authorization_id,
            "authorization_expires_at": self.expires_at,
            "allowed_source_ids": list(self.allowed_source_ids),
            "budget": {
                "max_queries": self.max_queries,
                "max_evidence_records": self.max_evidence_records,
                "automatic_retries": 0,
            },
            "run_command": run_command,
        }


def _display_path(root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        return str(path.resolve())
    return str(relative)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise LivePreparationError(
            "invalid_timestamp", f"{field} must be an ISO 8601 timestamp."
        ) from None
    if parsed.utcoffset() is None:
        raise LivePreparationError(
            "invalid_timestamp", f"{field} must include a timezone offset."
        )
    return parsed.astimezone(HONG_KONG_TIME)


def _safe_output_directory(root: Path, output_directory: str | Path) -> Path:
    requested = Path(output_directory)
    resolved = (
        (root / requested).resolve()
        if not requested.is_absolute()
        else requested.resolve()
    )
    scratch = (root / ".tmp").resolve()
    if resolved != scratch and scratch not in resolved.parents:
        raise LivePreparationError(
            "unsafe_output_directory",
            "Prepared live-run artifacts must remain under the repository .tmp directory.",
        )
    return resolved


def _write_json_exclusive(path: Path, document: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _cleanup_staging(staging: Path) -> None:
    for name in ("request.json", "authorization.json"):
        try:
            (staging / name).unlink(missing_ok=True)
        except OSError:
            pass
    try:
        staging.rmdir()
    except OSError:
        pass


def prepare_manual_live_run(
    repository_root: str | Path,
    *,
    market_ids: Iterable[str] = ("HK",),
    event_type: str = "final_rule",
    lookback_days: int = 7,
    window_start: str | None = None,
    window_end: str | None = None,
    max_followups: int = 0,
    max_queries: int = 3,
    max_evidence_records: int = 2,
    authorization_ttl_minutes: int = 45,
    organizational_approval_ref: str = "user-poc-assumption",
    domain_approval_ref: str = "user-poc-assumption",
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    run_id: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PreparedLiveRun:
    """Prepare and validate one request/authorization pair without using it."""

    root = Path(repository_root).resolve()
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if now.utcoffset() is None:
        raise LivePreparationError(
            "invalid_clock", "The preparation clock must be timezone-aware."
        )
    now_hk = now.astimezone(HONG_KONG_TIME)
    end = (
        _parse_timestamp(window_end, "window_end")
        if window_end is not None
        else now_hk
    )
    if window_start is not None:
        start = _parse_timestamp(window_start, "window_start")
    else:
        if type(lookback_days) is not int or lookback_days < 1:
            raise LivePreparationError(
                "invalid_lookback", "lookback_days must be a positive integer."
            )
        start = end - timedelta(days=lookback_days)

    selected_markets = tuple(dict.fromkeys(market_ids))
    if not selected_markets:
        raise LivePreparationError(
            "missing_market", "At least one market_id must be supplied."
        )
    if run_id is None:
        run_id = now.astimezone(timezone.utc).strftime(
            "manual-live-poc-%Y%m%dT%H%M%S%fZ"
        )

    loader = SkillLoader(root)
    bundles = {
        market_id: loader.select(
            topic_id="regulatory-change",
            event_type=event_type,
            market_id=market_id,
            include_drafts=True,
        )
        for market_id in selected_markets
    }
    request_document = {
        "schema_version": "0.1.0",
        "mode": "manual_live",
        "run_id": run_id,
        "request_key": run_id,
        "as_of": _timestamp(now_hk),
        "window": {
            "start": _timestamp(start),
            "end": _timestamp(end),
            "timezone": "Asia/Hong_Kong",
        },
        "scope": {
            "market_ids": list(selected_markets),
            "topic_id": "regulatory-change",
            "event_type": event_type,
            "source_classes": ["official"],
        },
        "budget": {
            "max_followup_rounds_per_event": max_followups,
            "max_queries": max_queries,
            "max_evidence_records": max_evidence_records,
        },
        "allow_draft_skills": True,
        "skill_bundle_sha256s": {
            market_id: bundles[market_id].bundle_sha256
            for market_id in selected_markets
        },
        "poc": {
            "non_production": True,
            "approval_basis": "user_authorized_assumption",
        },
    }
    request = ManualLiveResearchRequest.validate(request_document, root)
    registry = SourceRegistry.load(root / "config/sources/source-registry.json")
    plan = CoveragePlanner(root, registry).build(request, bundles)
    allowed_source_ids = tuple(
        sorted(
            {
                source_id
                for task in plan.tasks
                for source_id in task["source_ids"]
            }
        )
    )

    authorization_id = f"auth-{uuid4().hex}"
    authorization_document = {
        "schema_version": "0.1.0",
        "mode": "manual_live",
        "enabled": True,
        "authorization_id": authorization_id,
        "request_key": request.request_key,
        "request_sha256": request.content_sha256,
        "issued_at": _timestamp(now_hk),
        "expires_at": _timestamp(
            now_hk + timedelta(minutes=authorization_ttl_minutes)
        ),
        "organizational_approval_ref": organizational_approval_ref,
        "domain_approval_ref": domain_approval_ref,
        "allowed_source_ids": list(allowed_source_ids),
        "budget": {
            "max_queries": max_queries,
            "max_evidence_records": max_evidence_records,
        },
        "retry_policy": {"automatic_retries": 0},
    }

    output_root = _safe_output_directory(root, output_directory)
    target = (output_root / run_id).resolve()
    if target.parent != output_root:
        raise LivePreparationError(
            "unsafe_run_id",
            "run_id must be a safe single directory name for prepared artifacts.",
        )
    if target.exists():
        raise LivePreparationError(
            "output_exists", "A prepared run with this run_id already exists."
        )
    output_root.mkdir(parents=True, exist_ok=True)
    staging = output_root / f".preparing-{uuid4().hex}"
    try:
        staging.mkdir(exist_ok=False)
        request_path = staging / "request.json"
        authorization_path = staging / "authorization.json"
        _write_json_exclusive(request_path, request_document)
        _write_json_exclusive(authorization_path, authorization_document)
        authorization = ManualLiveRunAuthorization.load(
            root, authorization_path, clock=lambda: now
        )
        staging.rename(target)
    except Exception:
        _cleanup_staging(staging)
        raise

    return PreparedLiveRun(
        run_id=run_id,
        request_path=target / "request.json",
        authorization_path=target / "authorization.json",
        result_path=target / "result.json",
        request_sha256=request.content_sha256,
        authorization_id=authorization.authorization_id,
        expires_at=authorization.expires_at,
        allowed_source_ids=allowed_source_ids,
        max_queries=max_queries,
        max_evidence_records=max_evidence_records,
    )
