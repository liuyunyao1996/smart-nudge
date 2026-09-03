import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from scripts.validate_sources import REGISTRY_PATH, validate_registry
from smart_nudge.sources import (
    ApprovedSourceClient,
    FetchedSource,
    SourceFetchError,
    SourcePolicyError,
    SourceRegistry,
    extract_document,
)


PUBLIC_DNS = lambda _host, _port: ["93.184.216.34"]


def response_for(content=b"{}", content_type="application/json", status=200, headers=None):
    merged = {"content-type": content_type}
    merged.update(headers or {})

    def handler(request):
        return httpx.Response(status, content=content, headers=merged, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


class SourceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = SourceRegistry.load(REGISTRY_PATH)

    def test_checked_in_registry_passes_schema_and_semantics(self):
        self.assertEqual([], validate_registry())

    def test_initial_markets_have_approved_primary_paths(self):
        for market in ("HK", "CN", "MY"):
            matches = [source for source in self.registry.sources
                       if market in source["market_ids"]
                       and source["trust"]["tier"] == "primary"
                       and source["access"]["status"] == "approved_automated"]
            self.assertTrue(matches, market)

    def test_all_six_hong_kong_pilot_hosts_are_registered(self):
        hosts = {method["host"] for source in self.registry.sources for method in source["methods"]}
        self.assertTrue({"www.ia.org.hk", "www.hkma.gov.hk", "www.sfc.hk", "apps.sfc.hk",
                         "www.fstb.gov.hk", "www.gov.hk"}.issubset(hosts))

    def test_open_discovery_source_cannot_be_fetched(self):
        with self.assertRaises(SourcePolicyError) as error:
            self.registry.approved_target("https://www.aia.com/en/media-centre/press-releases")
        self.assertEqual("automated_access_disabled", error.exception.code)

    def test_trusted_and_open_search_pools_cannot_be_implicitly_mixed(self):
        trusted = {source["source_id"] for source in self.registry.sources_for_search(
            "trusted_registry", market_id="HK", topic_id="capital-and-alm")}
        open_discovery = {source["source_id"] for source in self.registry.sources_for_search(
            "open_discovery_only", market_id="HK", topic_id="capital-and-alm")}
        self.assertIn("hk-hkma-publications", trusted)
        self.assertIn("aia-group-publications", open_discovery)
        self.assertTrue(trusted.isdisjoint(open_discovery))
        with self.assertRaises(SourcePolicyError):
            self.registry.sources_for_search("all")

    def test_manual_method_on_otherwise_approved_source_cannot_be_fetched(self):
        with self.assertRaises(SourcePolicyError) as error:
            self.registry.approved_target("https://www.fstb.gov.hk/en/")
        self.assertEqual("automated_access_disabled", error.exception.code)

    def test_ia_override_remains_manual_and_metadata_only(self):
        source = self.registry.source("hk-ia-publications")
        self.assertFalse(source["access"]["automated_content_access"])
        self.assertEqual("approved_metadata_only", source["rights"]["retention"])

    def test_http_userinfo_port_and_unknown_path_are_rejected(self):
        urls = [
            "http://api.hkma.gov.hk/public/press-releases",
            "https://user:secret@api.hkma.gov.hk/public/press-releases",
            "https://api.hkma.gov.hk:444/public/press-releases",
            "https://api.hkma.gov.hk/private/admin",
            "https://api.hkma.gov.hk/public/press-releases-lookalike",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(SourcePolicyError):
                self.registry.approved_target(url)

    def test_encoded_dot_segment_and_backslash_are_rejected(self):
        urls = [
            "https://api.hkma.gov.hk/public/%2e%2e/private",
            "https://api.hkma.gov.hk/public%5cpress-releases",
            "https://api.hkma.gov.hk/public/press-releases/%252e%252e/private",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(SourcePolicyError):
                self.registry.approved_target(url)

    def test_duplicate_source_ids_fail_semantic_validation(self):
        document = copy.deepcopy(self.registry.document)
        document["sources"].append(copy.deepcopy(document["sources"][0]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(SourcePolicyError) as error:
                SourceRegistry.load(path)
        self.assertEqual("invalid_registry", error.exception.code)

    def test_ia_p1_override_cannot_be_enabled_by_registry_edit(self):
        document = copy.deepcopy(self.registry.document)
        source = next(item for item in document["sources"] if item["source_id"] == "hk-ia-publications")
        source["access"].update(status="approved_automated", automated_content_access=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(SourcePolicyError) as error:
                SourceRegistry.load(path)
        self.assertEqual("invalid_registry", error.exception.code)


class ApprovedSourceClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = SourceRegistry.load(REGISTRY_PATH)
        cls.url = "https://api.hkma.gov.hk/public/press-releases?lang=en"

    def fetch(self, client):
        return ApprovedSourceClient(self.registry, client=client, resolver=PUBLIC_DNS).fetch(self.url)

    def test_fetch_returns_direct_provenance_without_persisting_body_in_reference(self):
        fetched = self.fetch(response_for(b'{"result": []}'))
        reference = fetched.evidence_reference("/result")
        self.assertEqual("direct_api", reference["acquisition_method"])
        self.assertEqual("direct_official_access", reference["origin"])
        self.assertEqual("approved_metadata_only", reference["retention"])
        self.assertNotIn("body", reference)
        datetime.fromisoformat(reference["retrieved_at"])

    def test_private_dns_resolution_is_blocked_before_request(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        guarded = ApprovedSourceClient(self.registry, client=client,
                                       resolver=lambda _host, _port: ["127.0.0.1"])
        with self.assertRaises(SourceFetchError) as error:
            guarded.fetch(self.url)
        self.assertEqual("ssrf_blocked", error.exception.code)
        self.assertEqual([], calls)

    def test_redirect_is_revalidated_and_same_source_redirect_is_allowed(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            if request.url.host == "api.hkma.gov.hk":
                return httpx.Response(302, headers={"location": "https://www.hkma.gov.hk/eng/news-and-media/press-releases/"})
            return httpx.Response(200, text="<p>Official notice</p>", headers={"content-type": "text/html"})

        guarded = ApprovedSourceClient(self.registry,
            client=httpx.Client(transport=httpx.MockTransport(handler)), resolver=PUBLIC_DNS)
        fetched = guarded.fetch(self.url)
        self.assertEqual("direct_html", fetched.acquisition_method)
        self.assertEqual(2, len(calls))

    def test_cross_source_redirect_is_blocked(self):
        client = response_for(status=302, headers={"location": "https://api.bnm.gov.my/public/opr"})
        with self.assertRaises(SourcePolicyError) as error:
            self.fetch(client)
        self.assertEqual("cross_source_redirect", error.exception.code)

    def test_unapproved_redirect_is_blocked(self):
        client = response_for(status=302, headers={"location": "https://example.com/private"})
        with self.assertRaises(SourcePolicyError) as error:
            self.fetch(client)
        self.assertEqual("url_not_approved", error.exception.code)

    def test_redirect_limit_is_enforced(self):
        def handler(request):
            return httpx.Response(302, headers={"location": str(request.url)}, request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(SourceFetchError) as error:
            self.fetch(client)
        self.assertEqual("too_many_redirects", error.exception.code)

    def test_content_type_is_enforced(self):
        with self.assertRaises(SourceFetchError) as error:
            self.fetch(response_for(b"binary", "application/octet-stream"))
        self.assertEqual("content_type_blocked", error.exception.code)

    def test_declared_and_streamed_size_limits_are_enforced(self):
        with self.assertRaises(SourceFetchError) as declared:
            self.fetch(response_for(b"x", headers={"content-length": "10485761"}))
        self.assertEqual("content_too_large", declared.exception.code)
        with self.assertRaises(SourceFetchError) as streamed:
            self.fetch(response_for(b"x" * 10485761))
        self.assertEqual("content_too_large", streamed.exception.code)

    def test_invalid_content_length_is_rejected(self):
        with self.assertRaises(SourceFetchError) as error:
            self.fetch(response_for(b"x", headers={"content-length": "-1"}))
        self.assertEqual("invalid_content_length", error.exception.code)

    def test_http_errors_do_not_expose_response_body(self):
        secret_marker = "publisher-body-must-not-leak"
        with self.assertRaises(SourceFetchError) as error:
            self.fetch(response_for(secret_marker.encode(), status=403))
        self.assertEqual(403, error.exception.status_code)
        self.assertNotIn(secret_marker, str(error.exception))

    def test_network_failures_have_safe_error(self):
        def handler(request):
            raise httpx.ReadTimeout("sensitive transport detail", request=request)

        with self.assertRaises(SourceFetchError) as error:
            self.fetch(httpx.Client(transport=httpx.MockTransport(handler)))
        self.assertEqual("network_failure", error.exception.code)
        self.assertNotIn("sensitive", str(error.exception))


class ExtractionTests(unittest.TestCase):
    def fetched(self, body, content_type):
        return FetchedSource(
            source_id="test-source",
            url="https://example.test/document",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            acquisition_method="direct_html",
            content_type=content_type,
            content_sha256="0" * 64,
            retention="approved_metadata_only",
            body=body,
        )

    def test_html_extracts_title_and_paragraph_locators_without_scripts(self):
        body = b"<html><head><title> Notice </title><script>bad()</script></head><body><h1>Heading</h1><p>First <b>paragraph</b>.</p><p>Second</p></body></html>"
        document = extract_document(self.fetched(body, "text/html"))
        self.assertEqual("Notice", document.title)
        self.assertEqual(["paragraph:1", "paragraph:2", "paragraph:3"],
                         [segment.locator for segment in document.segments])
        self.assertNotIn("bad", " ".join(segment.text for segment in document.segments))

    def test_json_extracts_json_pointer_locators(self):
        document = extract_document(self.fetched(b'{"result":{"title":"Notice"}}', "application/json"))
        self.assertEqual("/result/title", document.segments[0].locator)
        self.assertEqual("Notice", document.segments[0].text)

    def test_xml_extracts_element_locators(self):
        document = extract_document(self.fetched(b"<rss><item><title>Notice</title></item></rss>", "application/rss+xml"))
        self.assertEqual("element:1", document.segments[0].locator)
        self.assertEqual("Notice", document.segments[0].text)

    def test_pdf_extracts_page_locators(self):
        first = Mock()
        first.extract_text.return_value = "Page one"
        second = Mock()
        second.extract_text.return_value = "Page two"
        reader = Mock(is_encrypted=False, pages=[first, second])
        with patch("smart_nudge.sources.PdfReader", return_value=reader):
            document = extract_document(self.fetched(b"synthetic-pdf", "application/pdf"))
        self.assertEqual(["page:1", "page:2"], [segment.locator for segment in document.segments])

    def test_encrypted_pdf_is_rejected(self):
        reader = Mock(is_encrypted=True, pages=[])
        with patch("smart_nudge.sources.PdfReader", return_value=reader):
            with self.assertRaises(SourceFetchError) as error:
                extract_document(self.fetched(b"synthetic-pdf", "application/pdf"))
        self.assertEqual("encrypted_document", error.exception.code)

    def test_unknown_content_type_is_rejected(self):
        with self.assertRaises(SourceFetchError) as error:
            extract_document(self.fetched(b"text", "text/plain"))
        self.assertEqual("content_type_blocked", error.exception.code)


if __name__ == "__main__":
    unittest.main()
