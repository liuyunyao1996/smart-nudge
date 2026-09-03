#!/usr/bin/env python3
"""Offline schema and semantic validation for the P2 source registry."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smart_nudge.sources import INITIAL_MARKETS, SourcePolicyError, SourceRegistry


REGISTRY_PATH = ROOT / "config" / "sources" / "source-registry.json"
SCHEMA_PATH = ROOT / "schemas" / "source-registry.schema.json"
TOPICS_PATH = ROOT / "config" / "topics" / "insurance-intelligence.json"


def validate_registry() -> list[str]:
    errors: list[str] = []
    try:
        registry_document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8-sig"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ["registry or schema is not readable JSON"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(registry_document), key=lambda item: list(item.path)):
        path = "/".join(str(part) for part in error.path) or "root"
        errors.append(f"schema/{path}: {error.message}")
    if errors:
        return errors
    try:
        registry = SourceRegistry.load(REGISTRY_PATH)
    except SourcePolicyError as exc:
        return [f"policy/{exc.code}: {exc}"]

    try:
        topics = {item["topic_id"] for item in json.loads(TOPICS_PATH.read_text(encoding="utf-8-sig"))["topics"]}
    except (OSError, ValueError, KeyError, TypeError):
        return ["topic taxonomy is not readable"]
    for source in registry.sources:
        unknown = set(source["topic_ids"]) - topics
        if unknown:
            errors.append(f"source/{source['source_id']}: unknown topics {sorted(unknown)}")
        if not set(source["market_ids"]) & INITIAL_MARKETS:
            errors.append(f"source/{source['source_id']}: no initial market")
    return errors


def main() -> int:
    errors = validate_registry()
    if errors:
        print("P2 source registry: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    registry = SourceRegistry.load(REGISTRY_PATH)
    automated = sum(source["access"]["status"] == "approved_automated" for source in registry.sources)
    manual = sum(source["access"]["status"] == "manual_review_only" for source in registry.sources)
    print(f"P2 source registry: PASS ({len(registry.sources)} sources; {automated} automated; {manual} manual-only)")
    print("This is an offline policy check, not a live coverage or permission revalidation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
