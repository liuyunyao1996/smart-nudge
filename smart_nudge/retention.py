"""Conservative P1 data-use guardrails for public-Web probe results."""

from copy import deepcopy
import json
from pathlib import Path


class DataUsePolicyError(ValueError):
    """The checked-in policy is missing a required deny-by-default guardrail."""


def load_data_use_policy(path):
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise DataUsePolicyError("Could not read the data-use policy.") from None
    if not isinstance(policy, dict) or not isinstance(policy.get("policy_version"), str):
        raise DataUsePolicyError("Data-use policy requires a version.")

    query = policy.get("query_policy")
    bing = policy.get("bing_grounding")
    source = policy.get("official_source")
    audit = policy.get("local_probe_audit")
    if not all(isinstance(item, dict) for item in (query, bing, source, audit)):
        raise DataUsePolicyError("Data-use policy sections are incomplete.")
    if query.get("public_topics_only") is not True:
        raise DataUsePolicyError("Bing queries must be limited to public topics.")
    required_prohibited_inputs = {
        "credentials", "confidential_or_internal_information",
        "personal_data_not_already_intentionally_public", "customer_or_employee_identifiers",
    }
    prohibited_inputs = query.get("prohibited_inputs")
    if (not isinstance(prohibited_inputs, list)
            or not all(isinstance(item, str) for item in prohibited_inputs)
            or not required_prohibited_inputs.issubset(set(prohibited_inputs))):
        raise DataUsePolicyError("Public-query policy is missing required input exclusions.")
    if (bing.get("raw_tool_output_available_to_developer") is not False
            or bing.get("persist_raw_response") is not False):
        raise DataUsePolicyError("Raw Bing responses must not be accessed or persisted.")
    if bing.get("persist_generated_answer") != "copyright_permitted_approved_integrated_work_product_only":
        raise DataUsePolicyError("Generated Bing answers require approved work-product treatment.")
    if bing.get("persist_references") != "exact_unmodified_and_adjacent_to_the_output":
        raise DataUsePolicyError("Bing references must remain exact and adjacent to their output.")
    if bing.get("use_for_model_training") is not False or bing.get("use_for_model_evaluation") is not False:
        raise DataUsePolicyError("Bing output must not be used for model training or evaluation.")
    if (bing.get("use_as_crawl_seed_or_link_index") is not False
            or bing.get("build_search_output_database") is not False):
        raise DataUsePolicyError("Bing output must not become a crawl seed, link index, or search database.")
    if source.get("search_snippet_counts_as_original") is not False:
        raise DataUsePolicyError("Search snippets cannot count as original-source access.")
    if source.get("on_robots_or_access_denial") != "stop_without_bypass":
        raise DataUsePolicyError("Access denial must stop without bypass.")
    if (source.get("default_retention") != "approved_metadata_only"
            or source.get("excerpt_requires") != "documented_permission_or_license"
            or source.get("fulltext_requires") != "documented_permission_or_license"):
        raise DataUsePolicyError("Official-source content must default to metadata-only retention.")
    allowed = audit.get("allowed_fields")
    forbidden = audit.get("forbidden_fields")
    if (not isinstance(allowed, list) or not isinstance(forbidden, list)
            or not all(isinstance(item, str) for item in allowed + forbidden)):
        raise DataUsePolicyError("Probe audit field lists are required.")
    if set(allowed) & set(forbidden) or "output_text" in allowed:
        raise DataUsePolicyError("Probe audit fields must exclude generated answer text.")
    if audit.get("persistence") != "explicit_only":
        raise DataUsePolicyError("Probe audit persistence must be explicit only.")
    publisher_overrides = policy.get("publisher_overrides")
    ia = (publisher_overrides.get("www.ia.org.hk", {})
          if isinstance(publisher_overrides, dict) else {})
    if (not isinstance(ia, dict)
            or ia.get("automated_content_access")
            != "disabled_pending_explicit_permission_or_verified_publisher_path"
            or ia.get("retention") != "approved_metadata_only"):
        raise DataUsePolicyError("The IA publisher override must disable content access and retention by default.")
    return policy


def make_search_probe_audit(result, policy):
    """Return metadata and exact references, excluding answer and tool content.

    The returned object is an integration-test work product, not a source registry,
    a factual verification result, or permission to persist publisher content.
    """
    if not isinstance(result, dict):
        raise DataUsePolicyError("Search result must be an object.")
    allowed = policy["local_probe_audit"]["allowed_fields"]
    record = {key: deepcopy(result[key]) for key in allowed if key in result}
    record["policy_version"] = policy["policy_version"]
    record["output_text_retained"] = False
    record["raw_response_retained"] = False
    record["raw_tool_output_retained"] = False
    record["record_kind"] = "bing_search_integration_audit"
    return record
