"""Bounded citation metadata only; never retain response text or query values."""

from collections import Counter
from hashlib import sha256
import json
from urllib.parse import urlsplit, urlunsplit


LIMIT = 100


def build_citation_diagnostics(
    body, allowed_hosts, canonicalize, *, use_annotations, expected_schema_version="1.0.0"
):
    allowed = set(allowed_hosts)
    native = set()
    references = []
    source_types = Counter()
    annotation_types = Counter()
    output_types = Counter()
    action_types = Counter()
    source_fields = Counter()
    annotation_fields = Counter()
    source_lists = 0
    text_parts = []

    def url_record(value):
        if not isinstance(value, str):
            return {"status": "non_string_url"}
        fingerprint = sha256(value.encode("utf-8", errors="replace")).hexdigest()
        canonical = canonicalize(value)
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
        except ValueError:
            return {"status": "invalid_url", "url_sha256": fingerprint}
        if parsed.username is not None or parsed.password is not None:
            return {"status": "credential_url_rejected", "url_sha256": fingerprint}
        # Off-scope URLs retain no path, query, fragment, or userinfo.
        record = {"url_sha256": fingerprint, "status": "valid_in_scope"}
        if canonical is not None:
            record["canonical_url_sha256"] = sha256(canonical.encode("utf-8", errors="replace")).hexdigest()
        if host and host.lower().rstrip(".") in allowed:
            record["url"] = urlunsplit((parsed.scheme, host, parsed.path[:2048] or "/", "", ""))
            record["query_present"] = bool(parsed.query)
            record["fragment_present"] = bool(parsed.fragment)
            record["path_truncated"] = len(parsed.path) > 2048
        else:
            record["status"] = "out_of_scope_url"
        if canonical is None:
            record["status"] = "invalid_or_non_https_url"
        return record

    def kind(value, known):
        return value if isinstance(value, str) and value in known else "other"

    def fields(value, counts):
        # Fixed field names disclose structure, not arbitrary service content.
        for name in ("type", "url", "title", "url_citation", "citation", "source", "start_index", "end_index"):
            if name in value:
                counts[name] += 1

    def reference(value, origin, recognized):
        record = url_record(value)
        canonical = canonicalize(value) if isinstance(value, str) else None
        contributes = bool(
            recognized and canonical and urlsplit(canonical).hostname in allowed
            and (origin == "action_source" or use_annotations)
        )
        if contributes:
            native.add(canonical)
        record.update({"origin": origin, "recognized_type": recognized, "used_for_matching": contributes})
        if len(references) < LIMIT:
            references.append(record)

    output = body.get("output", [])
    for item in output if isinstance(output, list) else []:
        if not isinstance(item, dict):
            output_types["other"] += 1
            continue
        output_types[kind(item.get("type"), {"message", "reasoning", "web_search_call", "bing_custom_search_call", "bing_custom_search_preview_call"})] += 1
        if item.get("type") in {"web_search_call", "bing_custom_search_call", "bing_custom_search_preview_call"}:
            action = item.get("action")
            action_types[kind(action.get("type") if isinstance(action, dict) else None, {"search", "open_page", "find_in_page"})] += 1
            sources = action.get("sources") if isinstance(action, dict) else None
            if isinstance(sources, list):
                source_lists += 1
                for source in sources:
                    if not isinstance(source, dict):
                        source_types["other"] += 1
                        continue
                    source_types[kind(source.get("type"), {"url"})] += 1
                    fields(source, source_fields)
                    reference(source.get("url"), "action_source", source.get("type") == "url")
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        content = item.get("content")
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict) or part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                continue
            text_parts.append(part)
    # The runtime requires exactly one structured text part; do not silently
    # count annotations on other messages as eligible evidence.
    for part in text_parts:
        annotations = part.get("annotations")
        for annotation in annotations if isinstance(annotations, list) else []:
            if not isinstance(annotation, dict):
                annotation_types["other"] += 1
                continue
            annotation_types[kind(annotation.get("type"), {"url_citation", "file_citation", "file_path"})] += 1
            fields(annotation, annotation_fields)
            reference(annotation.get("url"), "annotation", len(text_parts) == 1 and annotation.get("type") == "url_citation")

    diagnostic = {
        "schema_version": "1.0.0",
        "url_policy": "in_scope_path_only_query_values_and_fragments_omitted_off_scope_url_hashed",
        "output_type_counts": dict(output_types),
        "action_source_list_count": source_lists,
        "action_type_counts": dict(action_types),
        "action_source_type_counts": dict(source_types),
        "action_source_field_counts": dict(source_fields),
        "annotation_type_counts": dict(annotation_types),
        "annotation_field_counts": dict(annotation_fields),
        "structured_text_part_count": len(text_parts),
        "native_in_scope_url_count": len(native),
        "references": references,
        "references_truncated": sum(source_types.values()) + sum(annotation_types.values()) > LIMIT,
        "candidates": [],
        "candidate_parse_status": "not_inspected",
    }
    if len(text_parts) != 1:
        return diagnostic
    try:
        document = json.loads(text_parts[0].get("text", ""))
    except (TypeError, ValueError, RecursionError):
        diagnostic["candidate_parse_status"] = "invalid_json"
        return diagnostic
    items = document.get("items") if isinstance(document, dict) else None
    expected_fields = {"schema_version", "coverage_status", "items"}
    diagnostic["envelope_checks"] = {
        "object": isinstance(document, dict),
        "required_fields_present": {name: isinstance(document, dict) and name in document for name in sorted(expected_fields)},
        "unexpected_field_count": len(set(document) - expected_fields) if isinstance(document, dict) else 0,
        "schema_version_valid": (
            isinstance(document, dict)
            and document.get("schema_version") == expected_schema_version
        ),
        "coverage_status_valid": isinstance(document, dict) and document.get("coverage_status") in ("checked", "partial", "unavailable"),
        "items_array": isinstance(items, list),
    }
    if not isinstance(items, list):
        diagnostic["candidate_parse_status"] = "missing_items_array"
        return diagnostic
    diagnostic["candidate_parse_status"] = "parsed_for_url_diagnostics_only"
    diagnostic["candidate_count"] = len(items)
    diagnostic["candidates_truncated"] = len(items) > LIMIT
    for index, item in enumerate(items[:LIMIT], start=1):
        urls = item.get("citation_urls") if isinstance(item, dict) else None
        candidate = {"item_index": index, "urls": [], "url_match_status": "no_match"}
        if not isinstance(urls, list):
            candidate["url_match_status"] = "missing_citation_urls_array"
        else:
            candidate["urls_truncated"] = len(urls) > LIMIT
            for value in urls[:LIMIT]:
                entry = url_record(value)
                canonical = canonicalize(value) if isinstance(value, str) else None
                if canonical in native:
                    reason = "exact_native_url_match"
                    candidate["url_match_status"] = "matched"
                elif entry["status"] != "valid_in_scope":
                    reason = entry["status"]
                elif not native:
                    reason = "no_native_in_scope_urls_extracted"
                else:
                    parsed = urlsplit(canonical)
                    same_path = [url for url in native if urlsplit(url).hostname == parsed.hostname and urlsplit(url).path == parsed.path]
                    reason = "query_or_port_differs" if same_path else "full_url_not_in_native_set"
                entry["match_reason"] = reason
                candidate["urls"].append(entry)
        diagnostic["candidates"].append(candidate)
    return diagnostic
