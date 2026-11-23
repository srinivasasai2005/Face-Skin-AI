import json
from pathlib import Path

import pytest

from check_security import FAIL, PASS, WARN, evaluate_headers, evaluate_transport

ROOT = Path(__file__).resolve().parent.parent
HEADERS = json.loads((ROOT / "deploy/security_headers.json").read_text())


def levels(findings):
    return {f.check: f.level for f in findings}


def test_the_shipped_header_set_meets_the_baseline():
    findings = evaluate_headers(HEADERS, https=True)
    failed = [f for f in findings if f.level == FAIL]
    assert not failed, failed


def test_shipped_csp_has_no_dangerous_keywords():
    csp = HEADERS["Content-Security-Policy"]
    assert "'unsafe-eval'" not in csp
    script_src = [d for d in csp.split(";") if d.strip().startswith("script-src")][0]
    assert "'unsafe-inline'" not in script_src and "*" not in script_src
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp


def test_a_bare_streamlit_response_fails_the_baseline():
    findings = evaluate_headers({"server": "uvicorn", "content-type": "text/html"}, https=False)
    assert sum(f.level == FAIL for f in findings) >= 6


@pytest.mark.parametrize(
    "mutate, expected_failure",
    [
        (lambda c: c.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'"), "CSP forbids inline scripts"),
        (lambda c: c.replace("script-src 'self'", "script-src 'self' 'unsafe-eval'"), "CSP forbids eval()"),
        (lambda c: c.replace("frame-ancestors 'none'", "frame-ancestors *"), "CSP blocks being framed (frame-ancestors 'none')"),
        (lambda c: c.replace("connect-src 'self' data:", "connect-src *"), "CSP limits where the page can send data (connect-src)"),
        (lambda c: c.replace("img-src 'self' data: blob:", "img-src *"), "CSP limits image loads (img-src)"),
        (lambda c: c.replace("object-src 'none'", "object-src 'self'"), "CSP disables plugins (object-src 'none')"),
    ],
)
def test_each_weakening_of_the_csp_is_caught(mutate, expected_failure):
    weak = dict(HEADERS, **{"Content-Security-Policy": mutate(HEADERS["Content-Security-Policy"])})
    assert levels(evaluate_headers(weak, https=True))[expected_failure] == FAIL


@pytest.mark.parametrize(
    "header, check",
    [
        ("Permissions-Policy", "Permissions-Policy limits camera to this site"),
        ("X-Frame-Options", "X-Frame-Options set"),
        ("X-Content-Type-Options", "X-Content-Type-Options: nosniff"),
        ("Strict-Transport-Security", "HSTS set (HTTPS)"),
    ],
)
def test_each_missing_header_is_caught(header, check):
    missing = {k: v for k, v in HEADERS.items() if k != header}
    assert levels(evaluate_headers(missing, https=True))[check] == FAIL


def test_camera_must_stay_restricted_and_microphone_off():
    loose = dict(HEADERS, **{"Permissions-Policy": "camera=*, microphone=*, geolocation=*"})
    result = levels(evaluate_headers(loose, https=True))
    assert result["Permissions-Policy limits camera to this site"] == FAIL
    assert result["Permissions-Policy disables the microphone"] == FAIL
    assert result["Permissions-Policy disables location"] == FAIL


def test_hsts_is_only_required_over_https():
    no_hsts = {k: v for k, v in HEADERS.items() if k != "Strict-Transport-Security"}
    assert "HSTS set (HTTPS)" not in levels(evaluate_headers(no_hsts, https=False))


def test_plain_http_is_a_failure_in_production_but_only_a_warning_locally():
    assert evaluate_transport("http://app.example.com")[0].level == FAIL
    assert evaluate_transport("http://localhost:8501")[0].level == WARN
    assert evaluate_transport("https://app.example.com")[0].level == PASS


# --- the deployable configs must carry exactly the tested header values ---------

@pytest.mark.parametrize("config", ["deploy/nginx.conf", "deploy/Caddyfile"])
def test_proxy_configs_contain_every_tested_header_verbatim(config):
    text = (ROOT / config).read_text()
    for name, value in HEADERS.items():
        assert name in text, f"{config} is missing header {name}"
        assert value in text, f"{config} has a different value for {name}: re-generate it from deploy/security_headers.json"


def test_nginx_limits_body_size_above_streamlit_upload_limit_and_rate_limits_uploads():
    text = (ROOT / "deploy/nginx.conf").read_text()
    assert "client_max_body_size 16m" in text
    assert "limit_req zone=faceskin_upload" in text and "/_stcore/upload_file/" in text
    assert "server_tokens off" in text


def test_streamlit_config_matches_the_proxy_upload_limit():
    cfg = (ROOT / ".streamlit/config.toml").read_text()
    assert "maxUploadSize = 15" in cfg and 'showErrorDetails = "none"' in cfg
    assert "gatherUsageStats = false" in cfg
    assert "enableXsrfProtection = true" in cfg and "enableCORS = true" in cfg
