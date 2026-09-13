"""Versioned, user-editable rules for the demonstration pipeline."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
from string import Formatter

from jsonschema import Draft202012Validator, FormatChecker


class RulePackError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def read_json(path: str | Path) -> dict:
    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8-sig"),
            object_pairs_hook=_unique_pairs,
        )
    except (OSError, ValueError):
        raise RulePackError("invalid_json", f"Could not read valid JSON from {Path(path).name}.") from None
    if not isinstance(value, dict):
        raise RulePackError("invalid_json", f"{Path(path).name} must contain a JSON object.")
    return value


@dataclass(frozen=True)
class RenderedQuery:
    query_id: str
    language: str
    market: str
    set_lang: str
    text: str


@dataclass(frozen=True)
class RulePack:
    document: dict
    sha256: str

    @classmethod
    def load(cls, path: str | Path, repository_root: str | Path) -> "RulePack":
        document = read_json(path)
        root = Path(repository_root).resolve()
        schema = read_json(root / "schemas" / "poc-rule.schema.json")
        try:
            Draft202012Validator.check_schema(schema)
            errors = sorted(
                Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
                key=lambda item: [str(part) for part in item.absolute_path],
            )
        except Exception:
            raise RulePackError("invalid_rule_schema", "The checked-in PoC rule Schema is invalid.") from None
        if errors:
            location = "/".join(str(part) for part in errors[0].absolute_path) or "root"
            raise RulePackError("invalid_rule", f"Rule Pack validation failed at {location}.")

        queries = document["search"]["queries"]
        query_ids = [item["query_id"] for item in queries]
        if len(query_ids) != len(set(query_ids)):
            raise RulePackError("invalid_rule", "Rule Pack query IDs must be unique.")
        expected_fields = {"topic", "date_from", "date_to"}
        for query in queries:
            try:
                fields = {
                    field_name
                    for _, field_name, _, _ in Formatter().parse(query["template"])
                    if field_name is not None
                }
            except ValueError:
                raise RulePackError("invalid_rule", "A query template is malformed.") from None
            if fields != expected_fields:
                raise RulePackError(
                    "invalid_rule",
                    "Every query template must use topic, date_from and date_to exactly.",
                )

        encoded = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return cls(deepcopy(document), sha256(encoded).hexdigest())

    @property
    def rule_id(self) -> str:
        return self.document["rule_id"]

    @property
    def version(self) -> str:
        return self.document["version"]

    @property
    def name(self) -> str:
        return self.document["name"]

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        return tuple(self.document["bing"]["allowed_hosts"])

    @property
    def default_topic(self) -> str:
        return self.document["search"]["default_topic"]

    @property
    def default_days(self) -> int:
        return self.document["search"]["default_days"]

    @property
    def max_items(self) -> int:
        return self.document["summarization"]["max_items"]

    def render_queries(self, topic: str, end_date: date, days: int) -> tuple[RenderedQuery, ...]:
        if not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > 300:
            raise RulePackError("invalid_topic", "Topic must contain 1 to 300 characters.")
        if any(ord(character) < 32 or ord(character) == 127 for character in topic):
            raise RulePackError("invalid_topic", "Topic cannot contain control characters.")
        if type(days) is not int or not 1 <= days <= 90:
            raise RulePackError("invalid_days", "Search window must be between 1 and 90 days.")
        start_date = end_date - timedelta(days=days)
        return tuple(
            RenderedQuery(
                query_id=item["query_id"],
                language=item["language"],
                market=item["market"],
                set_lang=item["set_lang"],
                text=item["template"].format(
                    topic=topic.strip(),
                    date_from=start_date.isoformat(),
                    date_to=end_date.isoformat(),
                ),
            )
            for item in self.document["search"]["queries"]
        )
