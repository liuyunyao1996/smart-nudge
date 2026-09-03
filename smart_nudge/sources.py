"""Approved-source registry, guarded retrieval, and transient document extraction.

This module deliberately does not persist response bodies.  Callers receive an
in-memory object and must apply the registry retention class when constructing
evidence records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
import ipaddress
import json
from pathlib import Path
import posixpath
import socket
from typing import Callable, Iterable
from urllib.parse import unquote, urljoin, urlsplit
import xml.etree.ElementTree as ET

import httpx
from pypdf import PdfReader


INITIAL_MARKETS = {"HK", "CN", "MY"}
PILOT_HK_HOSTS = {
    "www.ia.org.hk", "www.hkma.gov.hk", "www.sfc.hk", "apps.sfc.hk",
    "www.fstb.gov.hk", "www.gov.hk",
}
REDIRECT_CODES = {301, 302, 303, 307, 308}


class SourcePolicyError(ValueError):
    """A registry or URL violates the approved-source policy."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SourceFetchError(RuntimeError):
    """A fetch failed without exposing a response body in the exception."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ApprovedTarget:
    source: dict
    method: dict
    url: str


@dataclass(frozen=True)
class FetchedSource:
    source_id: str
    url: str
    retrieved_at: str
    acquisition_method: str
    content_type: str
    content_sha256: str
    retention: str
    body: bytes

    def evidence_reference(self, locator: str | None = None) -> dict:
        """Return provenance metadata; response bytes are intentionally omitted."""
        return {
            "source_id": self.source_id,
            "origin": "direct_official_access",
            "acquisition_method": self.acquisition_method,
            "url": self.url,
            "retrieved_at": self.retrieved_at,
            "content_type": self.content_type,
            "content_sha256": self.content_sha256,
            "retention": self.retention,
            "locator": locator,
        }


@dataclass(frozen=True)
class ExtractedSegment:
    locator: str
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    source_id: str
    url: str
    title: str | None
    retrieved_at: str
    content_type: str
    retention: str
    segments: tuple[ExtractedSegment, ...]


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


class SourceRegistry:
    """Load and semantically validate the checked-in source allowlist."""

    def __init__(self, document: dict):
        self.document = document
        self.defaults = document["fetch_defaults"]
        self.sources = tuple(document["sources"])
        self._by_id = {source["source_id"]: source for source in self.sources}

    @classmethod
    def load(cls, path: str | Path) -> "SourceRegistry":
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise SourcePolicyError("invalid_registry", "Could not read the source registry.") from None
        cls._validate(document)
        return cls(document)

    @staticmethod
    def _validate(document: dict) -> None:
        if not isinstance(document, dict) or not _is_text(document.get("registry_version")):
            raise SourcePolicyError("invalid_registry", "Source registry requires a version.")
        defaults = document.get("fetch_defaults")
        sources = document.get("sources")
        if not isinstance(defaults, dict) or not isinstance(sources, list) or not sources:
            raise SourcePolicyError("invalid_registry", "Source registry sections are incomplete.")
        for key in ("connect_timeout_seconds", "read_timeout_seconds", "max_redirects", "max_bytes"):
            if type(defaults.get(key)) is not int or defaults[key] <= 0:
                raise SourcePolicyError("invalid_registry", f"Invalid fetch default: {key}.")
        if defaults.get("https_only") is not True or defaults.get("dns_public_addresses_only") is not True:
            raise SourcePolicyError("invalid_registry", "HTTPS and public-address checks must remain enabled.")

        ids: set[str] = set()
        primary_automated_markets: set[str] = set()
        registered_hosts: set[str] = set()
        for source in sources:
            if not isinstance(source, dict) or not _is_text(source.get("source_id")):
                raise SourcePolicyError("invalid_registry", "Every source requires an id.")
            source_id = source["source_id"]
            if source_id in ids:
                raise SourcePolicyError("invalid_registry", f"Duplicate source id: {source_id}.")
            ids.add(source_id)
            if source.get("search_mode") not in {"trusted_registry", "open_discovery_only"}:
                raise SourcePolicyError("invalid_registry", f"Invalid search mode for {source_id}.")
            access = source.get("access")
            rights = source.get("rights")
            trust = source.get("trust")
            methods = source.get("methods")
            if not all(isinstance(value, dict) for value in (access, rights, trust)) or not isinstance(methods, list):
                raise SourcePolicyError("invalid_registry", f"Source sections are incomplete for {source_id}.")
            if access.get("status") not in {"approved_automated", "manual_review_only", "disabled"}:
                raise SourcePolicyError("invalid_registry", f"Invalid access status for {source_id}.")
            if rights.get("retention") not in {"approved_metadata_only", "approved_excerpt"}:
                raise SourcePolicyError("invalid_registry", f"Invalid retention class for {source_id}.")
            if not isinstance(rights.get("policy_urls"), list) or not rights["policy_urls"]:
                raise SourcePolicyError("invalid_registry", f"Policy evidence is required for {source_id}.")
            automated = access.get("automated_content_access") is True
            if access.get("status") == "approved_automated" and not automated:
                raise SourcePolicyError("invalid_registry", f"Approved source {source_id} must enable access.")
            if access.get("status") != "approved_automated" and automated:
                raise SourcePolicyError("invalid_registry", f"Non-approved source {source_id} cannot enable access.")
            if source.get("search_mode") == "open_discovery_only" and automated:
                raise SourcePolicyError("invalid_registry", "Discovery-only sources cannot enable retrieval.")
            if automated and trust.get("tier") == "primary":
                primary_automated_markets.update(source.get("market_ids", []))

            for method in methods:
                if not isinstance(method, dict):
                    raise SourcePolicyError("invalid_registry", f"Invalid method for {source_id}.")
                host = str(method.get("host", "")).lower()
                prefixes = method.get("path_prefixes")
                content_types = method.get("content_types")
                if (method.get("kind") not in {"api", "rss", "html", "pdf", "manual"}
                        or not host or not isinstance(prefixes, list) or not prefixes
                        or not all(_is_text(prefix) and prefix.startswith("/") for prefix in prefixes)
                        or not isinstance(content_types, list) or not content_types
                        or not all(_is_text(content_type) for content_type in content_types)):
                    raise SourcePolicyError("invalid_registry", f"Invalid method allowlist for {source_id}.")
                registered_hosts.add(host)
                target = SourceRegistry._match_method_url(method.get("entry_url", ""), method)
                if target is None:
                    raise SourcePolicyError("invalid_registry", f"Entry URL is outside its method allowlist: {source_id}.")

            if any(method.get("host") == "www.ia.org.hk" for method in methods):
                if automated or rights.get("retention") != "approved_metadata_only":
                    raise SourcePolicyError("invalid_registry", "The P1 Insurance Authority override must remain deny-by-default.")

        if not INITIAL_MARKETS.issubset(primary_automated_markets):
            missing = ", ".join(sorted(INITIAL_MARKETS - primary_automated_markets))
            raise SourcePolicyError("invalid_registry", f"Initial markets lack approved primary paths: {missing}.")
        if not PILOT_HK_HOSTS.issubset(registered_hosts):
            missing = ", ".join(sorted(PILOT_HK_HOSTS - registered_hosts))
            raise SourcePolicyError("invalid_registry", f"Pilot Hong Kong hosts are missing: {missing}.")

    @staticmethod
    def _match_method_url(url: str, method: dict) -> str | None:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return None
        if parsed.scheme.lower() != "https" or parsed.username is not None or parsed.password is not None:
            return None
        if port not in (None, 443) or not parsed.hostname:
            return None
        host = parsed.hostname.rstrip(".").lower()
        if host != str(method.get("host", "")).lower():
            return None
        if parsed.fragment or "\\" in parsed.path:
            return None
        try:
            decoded_path = unquote(parsed.path)
        except Exception:
            return None
        # Reject nested percent-encoding so an origin cannot decode the path a
        # second time and turn an allowlisted suffix into a traversal segment.
        if unquote(decoded_path) != decoded_path:
            return None
        if "\\" in decoded_path or any(ord(char) < 32 for char in decoded_path):
            return None
        normalized = posixpath.normpath(decoded_path or "/")
        if (not normalized.startswith("/")
                or any(part in {".", ".."} for part in decoded_path.split("/"))):
            return None
        for prefix in method.get("path_prefixes", []):
            if (prefix.endswith("/") and decoded_path.startswith(prefix)) or decoded_path == prefix or decoded_path.startswith(f"{prefix}/"):
                return host
        return None

    def approved_target(self, url: str, *, require_automated: bool = True) -> ApprovedTarget:
        matches: list[ApprovedTarget] = []
        for source in self.sources:
            for method in source["methods"]:
                if self._match_method_url(url, method):
                    matches.append(ApprovedTarget(source, method, url))
        if not matches:
            raise SourcePolicyError("url_not_approved", "URL is outside the approved source registry.")
        target = matches[0]
        access = target.source["access"]
        if require_automated and (access.get("status") != "approved_automated"
                                  or access.get("automated_content_access") is not True
                                  or target.method.get("kind") == "manual"):
            raise SourcePolicyError("automated_access_disabled", "Automated content access is disabled for this source.")
        return target

    def source(self, source_id: str) -> dict:
        try:
            return self._by_id[source_id]
        except KeyError:
            raise SourcePolicyError("unknown_source", "Unknown source id.") from None

    def sources_for_search(self, search_mode: str, *, market_id: str | None = None,
                           topic_id: str | None = None) -> tuple[dict, ...]:
        """Select a search pool without promoting discovery candidates to trusted sources."""
        if search_mode not in {"trusted_registry", "open_discovery_only"}:
            raise SourcePolicyError("invalid_search_mode", "Search mode must be explicit.")
        return tuple(
            source for source in self.sources
            if source["search_mode"] == search_mode
            and (market_id is None or market_id in source["market_ids"])
            and (topic_id is None or topic_id in source["topic_ids"])
        )


def _default_resolver(host: str, port: int) -> Iterable[str]:
    return {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}


def _validate_public_resolution(host: str, resolver: Callable[[str, int], Iterable[str]]) -> None:
    try:
        addresses = tuple(resolver(host, 443))
    except OSError:
        raise SourceFetchError("dns_failure", "Approved source host could not be resolved.") from None
    if not addresses:
        raise SourceFetchError("dns_failure", "Approved source host returned no addresses.")
    try:
        parsed = tuple(ipaddress.ip_address(address) for address in addresses)
    except ValueError:
        raise SourceFetchError("dns_failure", "Approved source host returned an invalid address.") from None
    if any(not address.is_global for address in parsed):
        raise SourceFetchError("ssrf_blocked", "Approved source host resolved to a non-public address.")


class ApprovedSourceClient:
    """Fetch only allowlisted sources, validating DNS and every redirect hop."""

    def __init__(self, registry: SourceRegistry, *, client: httpx.Client | None = None,
                 resolver: Callable[[str, int], Iterable[str]] | None = None):
        self.registry = registry
        self.client = client or httpx.Client(trust_env=False)
        self._owns_client = client is None
        self.resolver = resolver or _default_resolver

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "ApprovedSourceClient":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def fetch(self, url: str) -> FetchedSource:
        target = self.registry.approved_target(url)
        source_id = target.source["source_id"]
        current_url = url
        defaults = self.registry.defaults
        timeout = httpx.Timeout(
            connect=defaults["connect_timeout_seconds"],
            read=defaults["read_timeout_seconds"],
            write=defaults["connect_timeout_seconds"],
            pool=defaults["connect_timeout_seconds"],
        )
        for redirect_count in range(defaults["max_redirects"] + 1):
            target = self.registry.approved_target(current_url)
            if target.source["source_id"] != source_id:
                raise SourcePolicyError("cross_source_redirect", "Redirect crossed the approved source boundary.")
            host = urlsplit(current_url).hostname
            assert host is not None
            _validate_public_resolution(host, self.resolver)
            headers = {
                "User-Agent": defaults["user_agent"],
                "Accept": ", ".join(target.method["content_types"]),
            }
            try:
                with self.client.stream("GET", current_url, headers=headers, timeout=timeout,
                                        follow_redirects=False) as response:
                    if response.status_code in REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise SourceFetchError("invalid_redirect", "Source returned a redirect without a location.")
                        if redirect_count >= defaults["max_redirects"]:
                            raise SourceFetchError("too_many_redirects", "Source exceeded the redirect limit.")
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code < 200 or response.status_code >= 300:
                        raise SourceFetchError("http_error", "Approved source returned an unsuccessful status.",
                                               status_code=response.status_code)

                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    allowed_types = {value.lower() for value in target.method["content_types"]}
                    if content_type not in allowed_types:
                        raise SourceFetchError("content_type_blocked", "Source returned an unapproved content type.")
                    declared_length = response.headers.get("content-length")
                    if declared_length:
                        try:
                            parsed_length = int(declared_length)
                            if parsed_length < 0:
                                raise ValueError
                            if parsed_length > defaults["max_bytes"]:
                                raise SourceFetchError("content_too_large", "Source content exceeds the size limit.")
                        except ValueError:
                            raise SourceFetchError("invalid_content_length", "Source returned an invalid content length.") from None
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > defaults["max_bytes"]:
                            raise SourceFetchError("content_too_large", "Source content exceeds the size limit.")
                        chunks.append(chunk)
            except SourceFetchError:
                raise
            except httpx.HTTPError:
                raise SourceFetchError("network_failure", "Approved source request failed or timed out.") from None

            body = b"".join(chunks)
            return FetchedSource(
                source_id=source_id,
                url=current_url,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                acquisition_method=f"direct_{target.method['kind']}",
                content_type=content_type,
                content_sha256=sha256(body).hexdigest(),
                retention=target.source["rights"]["retention"],
                body=body,
            )
        raise SourceFetchError("too_many_redirects", "Source exceeded the redirect limit.")


class _ParagraphHTMLParser(HTMLParser):
    BLOCKS = {"article", "blockquote", "dd", "div", "dt", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "pre", "section", "td", "th"}
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.paragraphs: list[str] = []
        self._parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, _attrs) -> None:
        tag = tag.lower()
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCKS or tag == "br":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self._parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = " ".join("".join(self._parts).split())
        self._parts.clear()
        if text and (not self.paragraphs or text != self.paragraphs[-1]):
            self.paragraphs.append(text)


def _json_segments(body: bytes, limit: int) -> tuple[ExtractedSegment, ...]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        raise SourceFetchError("parse_error", "JSON source could not be parsed.") from None
    segments: list[ExtractedSegment] = []

    def walk(item, pointer: str) -> None:
        if len(segments) >= limit:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                walk(child, f"{pointer}/{escaped}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{pointer}/{index}")
        elif item is not None:
            text = str(item).strip()
            if text:
                segments.append(ExtractedSegment(pointer or "/", text))

    walk(value, "")
    return tuple(segments)


def extract_document(fetched: FetchedSource, *, max_segments: int = 2000,
                     max_pdf_pages: int = 200) -> ExtractedDocument:
    """Extract locator-addressable text in memory; this does not grant retention."""
    if max_segments <= 0 or max_pdf_pages <= 0:
        raise ValueError("Extraction limits must be positive.")
    content_type = fetched.content_type
    title: str | None = None
    segments: tuple[ExtractedSegment, ...]
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _ParagraphHTMLParser()
        try:
            parser.feed(fetched.body.decode("utf-8-sig", errors="replace"))
            parser.close()
        except Exception:
            raise SourceFetchError("parse_error", "HTML source could not be parsed.") from None
        title_value = " ".join("".join(parser.title_parts).split())
        title = title_value or None
        segments = tuple(ExtractedSegment(f"paragraph:{index}", text)
                         for index, text in enumerate(parser.paragraphs[:max_segments], 1))
    elif content_type == "application/pdf":
        try:
            reader = PdfReader(BytesIO(fetched.body))
            if reader.is_encrypted:
                raise SourceFetchError("encrypted_document", "Encrypted PDF documents are not supported.")
            page_count = len(reader.pages)
            if page_count > max_pdf_pages:
                raise SourceFetchError("document_too_long", "PDF exceeds the page limit.")
            extracted = []
            for index, page in enumerate(reader.pages, 1):
                text = "\n".join(line.strip() for line in (page.extract_text() or "").splitlines() if line.strip())
                if text:
                    extracted.append(ExtractedSegment(f"page:{index}", text))
                    if len(extracted) >= max_segments:
                        break
            segments = tuple(extracted)
        except SourceFetchError:
            raise
        except Exception:
            raise SourceFetchError("parse_error", "PDF source could not be parsed.") from None
    elif content_type in {"application/json", "application/problem+json"}:
        segments = _json_segments(fetched.body, max_segments)
    elif content_type in {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}:
        try:
            root = ET.fromstring(fetched.body)
        except ET.ParseError:
            raise SourceFetchError("parse_error", "XML source could not be parsed.") from None
        values = []
        for element in root.iter():
            text = " ".join((element.text or "").split())
            if text:
                values.append(ExtractedSegment(f"element:{len(values) + 1}", text))
                if len(values) >= max_segments:
                    break
        segments = tuple(values)
    else:
        raise SourceFetchError("content_type_blocked", "No extractor is available for this content type.")
    return ExtractedDocument(
        source_id=fetched.source_id,
        url=fetched.url,
        title=title,
        retrieved_at=fetched.retrieved_at,
        content_type=fetched.content_type,
        retention=fetched.retention,
        segments=segments,
    )
