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
    configuration_id: str | None = None


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
        configurations = document["bing"].get("configurations")
        if configurations is not None:
            if document.get("workflow") != "asia_executive_news":
                raise RulePackError(
                    "invalid_rule", "Multiple Bing configurations require the Asia executive news workflow."
                )
            configuration_ids = [item["configuration_id"] for item in configurations]
            instance_names = [item["instance_name"] for item in configurations]
            source_hosts = [source["host"] for item in configurations for source in item["sources"]]
            query_configuration_ids = [item.get("configuration_id") for item in queries]
            if (
                len(configuration_ids) != len(set(configuration_ids))
                or len(instance_names) != len(set(instance_names))
                or len(source_hosts) != len(set(source_hosts))
                or any(value not in configuration_ids for value in query_configuration_ids)
            ):
                raise RulePackError(
                    "invalid_rule",
                    "Bing configuration IDs, instance names and source hosts must be unique, and every query must reference a configuration.",
                )
        elif any(item.get("configuration_id") is not None for item in queries):
            raise RulePackError("invalid_rule", "Legacy Rule Packs cannot reference a Bing configuration ID.")

        agent = document["search"].get("agent")
        if agent is not None:
            if configurations is not None:
                raise RulePackError("invalid_rule", "The Asia executive news workflow does not support Foundry Agent search.")
            site_ids = [site["site_id"] for site in agent["sites"]]
            site_hosts = [host for site in agent["sites"] for host in site["hosts"]]
            if (
                len(site_ids) != len(set(site_ids))
                or len(site_hosts) != len(set(site_hosts))
                or set(site_hosts) != set(document["bing"]["allowed_hosts"])
            ):
                raise RulePackError(
                    "invalid_rule",
                    "Agent sites must have unique IDs and partition the allowed hosts exactly once.",
                )
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
        configurations = self.document["bing"].get("configurations")
        if configurations is None:
            return tuple(self.document["bing"]["allowed_hosts"])
        return tuple(source["host"] for item in configurations for source in item["sources"])

    @property
    def workflow(self) -> str:
        return self.document.get("workflow", "regulatory_pulse")

    @property
    def is_asia_executive_news(self) -> bool:
        return self.workflow == "asia_executive_news"

    @property
    def bing_configurations(self) -> tuple[dict, ...]:
        configurations = self.document["bing"].get("configurations")
        if configurations is not None:
            return tuple(deepcopy(item) for item in configurations)
        return (
            {
                "configuration_id": "default",
                "instance_name": self.document["bing"]["instance_name"],
                "source_tier": "primary",
                "sources": [
                    {"host": host, "source_type": "regulator", "market": "unspecified"}
                    for host in self.allowed_hosts
                ],
            },
        )

    def bing_configuration(self, configuration_id: str | None) -> dict:
        configurations = self.bing_configurations
        if configuration_id is None and len(configurations) == 1:
            return configurations[0]
        for configuration in configurations:
            if configuration["configuration_id"] == configuration_id:
                return configuration
        raise RulePackError("invalid_rule", "Query references an unknown Bing configuration.")

    def source_metadata(self, host: str) -> dict:
        for configuration in self.bing_configurations:
            for source in configuration["sources"]:
                if source["host"] == host:
                    return {
                        "configuration_id": configuration["configuration_id"],
                        "source_tier": configuration["source_tier"],
                        "source_type": source["source_type"],
                        "market": source["market"],
                    }
        raise RulePackError("invalid_rule", "Source host is not configured by the Rule Pack.")

    @property
    def default_topic(self) -> str:
        return self.document["search"]["default_topic"]

    @property
    def default_days(self) -> int:
        return self.document["search"]["default_days"]

    @property
    def agent_sites(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        agent = self.document["search"].get("agent")
        if agent is None:
            return tuple((f"site-{index}", (host,)) for index, host in enumerate(self.allowed_hosts, start=1))
        return tuple((site["site_id"], tuple(site["hosts"])) for site in agent["sites"])

    @property
    def agent_max_tool_calls_per_site(self) -> int:
        return self.document["search"].get("agent", {}).get("max_tool_calls_per_site", 3)

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
                configuration_id=item.get("configuration_id"),
            )
            for item in self.document["search"]["queries"]
        )
