"""Unit tests for the category placeholder mapping and the SSRF-guarded image
reachability probe (frontend fallback images).

The pure category mapping is exercised directly. The reachability probe's SSRF
guard (https-only, host allowlist, private/loopback/link-local rejection,
no redirects) is tested with the HTTP boundary (``requests``) mocked — no real
network call is made. The in-memory Pillow generation is left to runtime.
"""

import pytest
import requests
from components.placeholders import (
    _PROBE_TIMEOUT_SECONDS,
    ALLOWED_IMAGE_HOSTS,
    CATEGORY_PLACEHOLDERS,
    _probe_reachable,
    image_source_for,
    is_allowed_image_url,
    placeholder_asset_path,
    placeholder_filename,
)


def test_shoes_maps_to_shoe_placeholder() -> None:
    assert placeholder_filename("Shoes") == "shoe-placeholder.jpg"


def test_clothing_and_sportswear_map_to_shirt() -> None:
    assert placeholder_filename("Clothing") == "shirt-placeholder.jpg"
    assert placeholder_filename("Sportswear") == "shirt-placeholder.jpg"


def test_accessories_and_watches_map_to_watch() -> None:
    assert placeholder_filename("Accessories") == "watch-placeholder.jpg"
    assert placeholder_filename("Watches") == "watch-placeholder.jpg"


def test_dresses_and_bags() -> None:
    assert placeholder_filename("Dresses") == "dress-placeholder.jpg"
    assert placeholder_filename("Bags") == "bag-placeholder.jpg"


def test_lookup_is_case_and_whitespace_insensitive() -> None:
    assert placeholder_filename("  SHOES ") == "shoe-placeholder.jpg"


def test_unknown_category_uses_default() -> None:
    assert placeholder_filename("Spaceship") == "product-placeholder.jpg"


def test_none_category_uses_default() -> None:
    assert placeholder_filename(None) == "product-placeholder.jpg"


def test_asset_path_points_into_frontend_assets() -> None:
    path = placeholder_asset_path("Shoes")
    assert path.name == "shoe-placeholder.jpg"
    assert path.parent.name == "assets"


def test_every_mapping_value_is_a_jpg_filename() -> None:
    assert all(name.endswith("-placeholder.jpg") for name in CATEGORY_PLACEHOLDERS.values())


# --- SSRF guard (VULN-003) -------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def close(self) -> None:
        pass


class TestImageUrlAllowlist:
    def test_allowed_https_host_passes(self) -> None:
        assert is_allowed_image_url("https://loremflickr.com/600/600/shoes?lock=1001") is True

    def test_all_catalog_hosts_are_https_allowlisted(self) -> None:
        for host in ALLOWED_IMAGE_HOSTS:
            assert is_allowed_image_url(f"https://{host}/x.jpg") is True

    def test_non_https_scheme_blocked(self) -> None:
        assert is_allowed_image_url("http://loremflickr.com/x.jpg") is False
        assert is_allowed_image_url("ftp://loremflickr.com/x.jpg") is False
        assert is_allowed_image_url("file:///etc/passwd") is False

    def test_unlisted_host_blocked(self) -> None:
        assert is_allowed_image_url("https://evil.example.com/x.jpg") is False
        # Look-alike / subdomain of an allowed host is NOT allow-listed (exact match).
        assert is_allowed_image_url("https://loremflickr.com.evil.com/x.jpg") is False
        assert is_allowed_image_url("https://evilloremflickr.com/x.jpg") is False

    @pytest.mark.parametrize("url", [
        "https://localhost/x.jpg",
        "https://sub.localhost/x.jpg",
        "https://127.0.0.1/x.jpg",
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "https://10.0.0.5/x.jpg",                       # private
        "https://192.168.1.10/x.jpg",                   # private
        "https://172.16.0.1/x.jpg",                     # private
        "https://[::1]/x.jpg",                          # IPv6 loopback
        "https://0.0.0.0/x.jpg",                        # unspecified
    ])
    def test_internal_and_private_targets_blocked(self, url: str) -> None:
        assert is_allowed_image_url(url) is False

    def test_malformed_or_empty_url_blocked(self) -> None:
        assert is_allowed_image_url("") is False
        assert is_allowed_image_url("not a url") is False
        assert is_allowed_image_url("https:///x.jpg") is False  # no host


class TestProbeReachable:
    def test_blocked_url_makes_no_network_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def must_not_call(*args: object, **kwargs: object) -> object:
            raise AssertionError("network request issued for a disallowed URL")

        monkeypatch.setattr(requests, "get", must_not_call)
        assert _probe_reachable("https://169.254.169.254/latest/meta-data/") is False
        assert _probe_reachable("http://loremflickr.com/x.jpg") is False  # not https
        assert _probe_reachable("https://evil.example.com/x.jpg") is False

    def test_allowed_url_uses_no_redirects_and_timeout_constant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def fake_get(url: str, **kwargs: object) -> _FakeResponse:
            captured["url"] = url
            captured.update(kwargs)
            return _FakeResponse(200)

        monkeypatch.setattr(requests, "get", fake_get)
        assert _probe_reachable("https://loremflickr.com/600/600/shoes?lock=1001") is True
        assert captured["allow_redirects"] is False
        assert captured["timeout"] == _PROBE_TIMEOUT_SECONDS

    def test_redirect_status_counts_as_reachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # loremflickr 302-redirects to its CDN; a 3xx means the image exists.
        monkeypatch.setattr(requests, "get", lambda url, **kw: _FakeResponse(302))
        assert _probe_reachable("https://loremflickr.com/x.jpg") is True

    def test_404_is_not_reachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(requests, "get", lambda url, **kw: _FakeResponse(404))
        assert _probe_reachable("https://loremflickr.com/x.jpg") is False

    def test_request_exception_is_not_reachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raiser(url: str, **kw: object) -> object:
            raise requests.RequestException("connection failed")

        monkeypatch.setattr(requests, "get", raiser)
        assert _probe_reachable("https://loremflickr.com/x.jpg") is False


class TestImageSourceForUnchangedForValidImages:
    def test_valid_reachable_image_is_returned_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("components.placeholders._url_reachable", lambda url: True)
        url = "https://loremflickr.com/600/600/shoes?lock=1001"
        assert image_source_for(url, "Shoes") == url

    def test_unreachable_or_blocked_image_falls_back_to_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("components.placeholders._url_reachable", lambda url: False)
        result = image_source_for("https://evil.example.com/x.jpg", "Shoes")
        assert result != "https://evil.example.com/x.jpg"  # a placeholder, not the URL
