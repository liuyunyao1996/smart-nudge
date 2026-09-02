"""Offline P0 asset/contract checks. This is NOT an agent or a truth verifier."""

from __future__ import annotations

import argparse
from datetime import datetime
import ipaddress
import itertools
import json
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=(ValueError, TypeError))
def timestamp_with_timezone(value):
    if not isinstance(value, str):
        return True  # JSON Schema's type keyword handles other types.
    return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Non-JSON numeric constant: {value}")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_pairs, parse_constant=reject_constant)


def load_assets():
    return {
        "profile": read_json(ROOT / "config/watch_profiles/aia-group-ceo.json"),
        "taxonomy": read_json(ROOT / "config/topics/insurance-intelligence.json"),
        "entities": read_json(ROOT / "config/entities/aia-pilot.json"),
        "schema": read_json(ROOT / "schemas/intelligence-result.schema.json"),
        "cases": read_json(ROOT / "evals/cases/p0-synthetic.json"),
    }


def index_by(items, key, errors):
    result = {}
    for item in items:
        value = item[key]
        if value in result:
            errors.append(f"duplicate {key}: {value}")
        result[value] = item
    return result


def validate_assets(assets):
    errors = []
    p, taxonomy, catalog, cases = (assets[k] for k in ("profile", "taxonomy", "entities", "cases"))
    topics = index_by(taxonomy["topics"], "topic_id", errors)
    entities = index_by(catalog["entities"], "entity_id", errors)
    refs = index_by(catalog["references"], "reference_id", errors)
    markets = index_by(p["pilot_markets"], "market_id", errors)
    index_by(cases["cases"], "case_id", errors)
    for phase, topic_ids in p["topic_rollout"].items():
        if set(topic_ids) - topics.keys():
            errors.append(f"unknown topic in rollout {phase}")
    for market in markets.values():
        if market["business_view_id"] not in entities:
            errors.append(f"missing business view for {market['market_id']}")
        if market["coverage_status"] != "not_validated":
            errors.append("P0 must not claim validated live coverage")
    for entity in entities.values():
        if not entity["reference_ids"] or set(entity["reference_ids"]) - refs.keys():
            errors.append(f"missing public reference for {entity['entity_id']}")
    for relation in catalog["relationships"]:
        if relation["from"] not in entities or relation["to"] not in entities:
            errors.append("unresolved entity relationship")
        if not relation["reference_ids"] or set(relation["reference_ids"]) - refs.keys():
            errors.append("relationship without public reference")
    for topic in topics.values():
        for field in ("questions", "extract_fields", "query_intents", "materiality_signals", "exclude_examples", "pitfalls"):
            if not topic[field]:
                errors.append(f"empty {field}: {topic['topic_id']}")
    if cases["data_kind"] != "synthetic" or cases["annotation_status"] != "draft_pending_domain_review":
        errors.append("P0 cases must remain synthetic, pending expert review")
    for case in cases["cases"]:
        if case["topic_id"] not in topics or set(case["market_ids"]) - markets.keys():
            errors.append(f"unknown case scope: {case['case_id']}")
        expected = case["expected"]
        if expected["decision"] not in (None, "selected", "watch", "ignored"):
            errors.append(f"unknown expected decision: {case['case_id']}")
        if expected["run_status"] not in (None, "completed", "partial", "failed"):
            errors.append(f"unknown expected status: {case['case_id']}")
        if not expected["must_include"] or not expected["must_not_include"]:
            errors.append(f"missing positive/negative criteria: {case['case_id']}")
    Draft202012Validator.check_schema(assets["schema"])
    return errors


def validate_result(result, assets):
    """Validate declared structure and cross-field invariants, not source truth."""
    validator = Draft202012Validator(assets["schema"], format_checker=FORMATS)
    errors = [f"schema/{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator.iter_errors(result)]
    if errors:
        return errors
    p = assets["profile"]
    run = result["run"]
    scope = run["scope"]
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    versions = {"profile_id": p["profile_id"], "profile_version": p["version"], "taxonomy_version": assets["taxonomy"]["version"], "entity_catalog_version": assets["entities"]["version"], "rule_version": p["selection_policy"]["rule_version"]}
    for key, expected in versions.items():
        if result[key] != expected:
            errors.append(f"version mismatch: {key}")
    topics = {t["topic_id"] for t in assets["taxonomy"]["topics"]}
    entity_ids = {e["entity_id"] for e in assets["entities"]["entities"]}
    markets = {m["market_id"]: m for m in p["pilot_markets"]}
    classes = set(p["source_policy"]["mandatory_classes"] + p["source_policy"]["discovery_classes"])
    if set(scope["market_ids"]) - markets.keys() or set(scope["topic_ids"]) - topics or set(scope["source_classes"]) - classes:
        errors.append("unknown requested scope")
    if not set(p["source_policy"]["mandatory_classes"]) <= set(scope["source_classes"]):
        errors.append("mandatory source class omitted")
    if not parse(run["window"]["start"]) < parse(run["window"]["end"]) <= parse(run["as_of"]) <= parse(run["generated_at"]):
        errors.append("invalid run time ordering")
    if run["window"]["timezone"] != p["timezone"]:
        errors.append("timezone differs from versioned profile")
    if result["data_kind"] == "live" and not run["agent_versions"]:
        errors.append("live result requires agent versions")

    evidence = index_by(result["evidence"], "evidence_id", errors)
    claims = index_by(result["claims"], "claim_id", errors)
    events = index_by(result["events"], "event_id", errors)
    index_by(result["findings"], "finding_id", errors)
    for item in evidence.values():
        url = urlsplit(item["url"])
        if not url.hostname or url.username or url.password:
            errors.append("citation requires a hostname without credentials")
        host = (url.hostname or "").lower().rstrip(".")
        if host in ("localhost",) or host.endswith((".localhost", ".local")):
            errors.append("citation must not target a local host")
        try:
            if not ipaddress.ip_address(host).is_global:
                errors.append("citation must not target a private IP")
        except ValueError:
            pass  # Full DNS/redirect SSRF enforcement belongs in the P2 connector.
        if result["data_kind"] == "live" and (item["origin"] == "synthetic" or item["retention"] == "synthetic" or host == "example" or host.endswith(".example")):
            errors.append("live output contains synthetic evidence")
        if item["retention"] == "approved_metadata_only" and item["excerpt"] is not None:
            errors.append("metadata-only evidence must not store excerpts")
        if item["origin"] == "bing_grounding" and not item["native_citation"]:
            errors.append("Bing evidence requires native citation provenance")
        if parse(item["available_at"]) > parse(run["as_of"]):
            errors.append("evidence unavailable at historical cutoff")
        if item["published_at"] and parse(item["published_at"]) > parse(item["available_at"]):
            errors.append("evidence available before declared publication")
        if not parse(item["available_at"]) <= parse(item["retrieved_at"]) <= parse(run["generated_at"]):
            errors.append("invalid evidence time ordering")
    for claim in claims.values():
        support = claim["supports"]
        for link in support:
            if link["evidence_id"] not in evidence:
                errors.append(f"unknown evidence: {link['evidence_id']}")
            if result["data_kind"] == "live" and link["checked_by"] == "fixture_author":
                errors.append("live verification cannot be attributed to fixture author")
        checked = [s for s in support if s["checked_by"] != "not_checked"]
        if claim["verification"] == "supported":
            if not any(s["relation"] == "supports" for s in checked):
                errors.append("supported claim lacks checked supporting evidence")
            if any(s["relation"] == "refutes" for s in checked):
                errors.append("supported claim has unresolved counterevidence")
    for event in events.values():
        if event["topic_id"] not in scope["topic_ids"] or not set(event["market_ids"]) <= set(scope["market_ids"]):
            errors.append("event outside requested scope")
        if set(event["entity_ids"]) - entity_ids or set(event["claim_ids"]) - claims.keys():
            errors.append("event has unresolved entity or claim")
        if parse(event["first_seen_at"]) > parse(run["generated_at"]):
            errors.append("event first seen after result generation")
        if (event["change_type"] == "new") != (event["previous_event_id"] is None):
            errors.append("event change type requires consistent history reference")
    for finding in result["findings"]:
        event = events.get(finding["event_id"])
        if event is None:
            errors.append("finding has unknown event")
            continue
        cited = set(finding["fact_claim_ids"] + finding["analysis"]["basis_claim_ids"])
        if not cited <= set(event["claim_ids"]):
            errors.append("finding references claims outside its event")
        prefix = {"selected": "select_", "watch": "watch_", "ignored": "ignore_"}[finding["decision"]]
        if not finding["decision_code"].startswith(prefix):
            errors.append("decision and reason code disagree")
        selected_claims = [claims[c] for c in cited if c in claims]
        if finding["decision"] == "selected":
            if finding["evidence_status"] not in ("primary_supported", "independently_corroborated"):
                errors.append("selected finding lacks sufficient declared evidence")
            if any(c["verification"] != "supported" or c["kind"] == "reported_allegation" for c in selected_claims):
                errors.append("selected finding contains unverified/conflicted claims or allegations")
            if finding["importance"] == "low":
                errors.append("low-importance finding cannot enter CEO selection")
            if event["change_type"] == "unchanged":
                errors.append("unchanged event cannot be selected as new intelligence")
        if finding["evidence_status"] == "independently_corroborated":
            for claim in selected_claims:
                groups = {evidence[s["evidence_id"]]["origin_group_id"] for s in claim["supports"] if s["relation"] == "supports" and s["checked_by"] != "not_checked" and s["evidence_id"] in evidence}
                if len(groups) < 2:
                    errors.append("corroboration requires independent origins for each claim")
        if finding["evidence_status"] == "primary_supported":
            for claim in selected_claims:
                if not any(s["relation"] == "supports" and s["checked_by"] != "not_checked" and evidence.get(s["evidence_id"], {}).get("source_class") in ("official", "company_disclosure", "research") for s in claim["supports"]):
                    errors.append("primary support requires a declared primary source")

    expected_cells = set(itertools.product(scope["market_ids"], scope["topic_ids"], scope["source_classes"]))
    actual_cells = [(c["market_id"], c["topic_id"], c["source_class"]) for c in result["coverage"]]
    if set(actual_cells) != expected_cells or len(actual_cells) != len(set(actual_cells)):
        errors.append("coverage matrix incomplete, duplicated or outside scope")
    for cell in result["coverage"]:
        if cell["status"] == "checked" and not set(markets.get(cell["market_id"], {}).get("languages", [])) <= set(cell["languages_checked"]):
            errors.append("checked coverage omits required languages")
    gaps = any(c["status"] != "checked" for c in result["coverage"])
    if run["status"] == "completed" and (gaps or run["errors"]):
        errors.append("completed run cannot conceal coverage gaps or errors")
    if run["status"] == "partial" and not (gaps or run["errors"]):
        errors.append("partial run must explain its missing coverage or errors")
    if run["status"] == "failed" and (not run["errors"] or result["findings"]):
        errors.append("failed run requires errors and must not publish findings")
    if run["stop_reason"] in ("budget_exhausted", "required_source_unavailable", "technical_failure") and run["status"] == "completed":
        errors.append("incomplete stop reason cannot be marked completed")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, default=ROOT / "examples/intelligence-result.synthetic.json")
    args = parser.parse_args()
    try:
        assets = load_assets()
        errors = validate_assets(assets) + validate_result(read_json(args.result), assets)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"FAIL: {exc}")
        return 1
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print(f"PASS: P0 assets and result contract; {len(assets['cases']['cases'])} synthetic case definitions.")
    print("No live search, factual verification, model evaluation or domain-expert approval was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
