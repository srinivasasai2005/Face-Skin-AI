import httpx
import pytest

import recommendations as rec
from image_utils import QualityReport
from model import Analysis, Prediction


@pytest.fixture(autouse=True)
def _clean_cache():
    rec._resolve_cache.clear()
    yield
    rec._resolve_cache.clear()


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _redirect_handler(request):
    return httpx.Response(
        301,
        headers={"location": "https://www.amazon.in/s?k=Acne+treatment+for+face&tag=x"},
    )


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://amzn.to/43uIuJG", True),
        ("https://www.amazon.in/s?k=a", True),
        ("https://www.amazon.co.uk/s?k=a", True),
        ("http://amzn.to/x", False),  # not https
        ("https://amazon.evil.com/x", False),  # lookalike
        ("https://evil.com/amazon.com", False),
        ("https://amazon.com.evil.io/x", False),
        ("javascript:alert(1)", False),
        ("", False),
    ],
)
def test_url_allowlist(url, ok):
    assert rec.is_allowed_url(url) is ok


def test_catalog_has_only_valid_links():
    cat = rec.load_catalog()
    assert len(cat) >= 30
    assert all(rec.is_allowed_url(u) for u in cat.values())


def test_resolve_extracts_search_terms_and_region():
    assert rec.resolve_link("https://amzn.to/x", _client(_redirect_handler)) == (
        "Acne treatment for face",
        "www.amazon.in",
    )


def test_resolve_ignores_redirect_to_foreign_host():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.com/?k=x"})

    assert rec.resolve_link("https://amzn.to/x", _client(handler)) == (None, None)


def test_resolve_survives_network_errors_and_does_not_cache_them():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectTimeout("boom")

    c = _client(handler)
    assert rec.resolve_link("https://amzn.to/x", c) == (None, None)
    assert rec.resolve_link("https://amzn.to/x", c) == (None, None)
    assert len(calls) == 2  # failure was retried, not cached


def test_success_is_cached():
    calls = []

    def handler(request):
        calls.append(1)
        return _redirect_handler(request)

    c = _client(handler)
    rec.resolve_link("https://amzn.to/x", c)
    rec.resolve_link("https://amzn.to/x", c)
    assert len(calls) == 1


def test_products_follow_input_order_and_fallback_for_missing_classes():
    # Order matters: UI passes most-likely first (regression: used spreadsheet order).
    products = rec.build_products(
        ["Whiteheads", "Facial Hair", "Acne"], _client(_redirect_handler)
    )
    assert [p.condition for p in products] == ["Whiteheads", "Facial Hair", "Acne"]
    by = {p.condition: p for p in products}
    assert by["Acne"].curated and by["Acne"].search_terms == "Acne treatment for face"
    assert not by["Facial Hair"].curated
    assert by["Facial Hair"].url.startswith("https://www.amazon.in/s?k=facial+hair")
    assert rec.is_allowed_url(by["Facial Hair"].url)


def test_products_degrade_gracefully_when_offline():
    def handler(request):
        raise httpx.ConnectError("offline")

    products = rec.build_products(["Acne", "Enlarged Pores"], _client(handler))
    assert products[0].curated and products[0].search_terms is None
    assert products[1].url.startswith(f"https://{rec.DEFAULT_DOMAIN}/s?k=")


# --- Analysis rules (regressions for the bugs found while testing) ----------

def _analysis(probs, ok=True):
    preds = [Prediction(n, p) for n, p in probs]
    return Analysis(preds, QualityReport(0.5, 50.0, ok, [] if ok else ["x"]))


def test_unlikely_classes_get_no_recommendation():
    # Regression: Rosacea photo used to also suggest "Chapped Lips" at 0.06%.
    a = _analysis([("Rosacea", 0.854), ("Redness", 0.144), ("Chapped Lips", 0.0006)])
    assert [p.label for p in a.recommend] == ["Rosacea", "Redness"]


def test_top_finding_always_recommended_even_if_diffuse():
    a = _analysis([("Scarring", 0.09), ("Acne", 0.08)])
    assert [p.label for p in a.recommend] == ["Scarring"]


def test_no_recommendations_when_quality_check_fails():
    assert _analysis([("Blackheads", 0.36)], ok=False).recommend == []


@pytest.mark.parametrize("p,tier", [(0.95, "high"), (0.70, "high"), (0.5, "moderate"), (0.31, "low")])
def test_confidence_tiers(p, tier):
    assert _analysis([("Acne", p)]).confidence_tier == tier
