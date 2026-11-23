#!/usr/bin/env python3
"""Check a running deployment against the security baseline in SECURITY.md.

    python scripts/check_security.py https://app.example.com
    python scripts/check_security.py http://localhost:8600     # e.g. behind a local proxy

Exit code 0 = no FAIL findings, 1 = at least one FAIL. WARN findings never fail the run.
Only needs httpx (already a dependency of the app). It sends ordinary GET requests.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass(frozen=True)
class Finding:
    level: str
    check: str
    detail: str = ""


def _csp_directives(value: str) -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for part in value.split(";"):
        tokens = part.strip().split()
        if tokens:
            directives[tokens[0].lower()] = tokens[1:]
    return directives


def evaluate_headers(headers: Mapping[str, str], https: bool) -> list[Finding]:
    """Judge response headers. Pure function so it is unit-testable."""
    h = {k.lower(): v for k, v in headers.items()}
    out: list[Finding] = []

    def check(ok: bool, name: str, detail_if_bad: str, level_if_bad: str = FAIL) -> None:
        out.append(Finding(PASS if ok else level_if_bad, name, "" if ok else detail_if_bad))

    # --- Content-Security-Policy: the main defence against injected script ---------
    csp_raw = h.get("content-security-policy")
    check(csp_raw is not None, "Content-Security-Policy present", "header is missing")
    if csp_raw:
        d = _csp_directives(csp_raw)
        script = d.get("script-src", d.get("default-src", []))
        check("'unsafe-eval'" not in script, "CSP forbids eval()", "script-src allows 'unsafe-eval'")
        check("'unsafe-inline'" not in script, "CSP forbids inline scripts",
              "script-src allows 'unsafe-inline' (injected inline <script> would run)")
        check(not any(s in ("*", "http:", "https:", "data:") for s in script),
              "CSP script sources are specific", "script-src allows a wildcard/scheme source")
        check(d.get("frame-ancestors") == ["'none'"], "CSP blocks being framed (frame-ancestors 'none')",
              "frame-ancestors is not 'none': other sites may embed the app (clickjacking)")
        check(d.get("object-src") == ["'none'"], "CSP disables plugins (object-src 'none')", "object-src is not 'none'")
        check(d.get("base-uri") == ["'self'"], "CSP restricts <base> (base-uri 'self')", "base-uri is not 'self'")
        check("default-src" in d and "'self'" in d["default-src"], "CSP default-src is 'self'", "default-src is not restricted to 'self'")
        connect = d.get("connect-src", d.get("default-src", []))
        check(not any(s in ("*", "http:", "https:", "ws:", "wss:") for s in connect),
              "CSP limits where the page can send data (connect-src)",
              "connect-src allows any host: injected code could send photos anywhere")
        img = d.get("img-src", d.get("default-src", []))
        check(not any(s in ("*", "http:", "https:") for s in img), "CSP limits image loads (img-src)",
              "img-src allows any host: a tracking-pixel style data leak is possible")

    # --- Clickjacking (older-browser fallback) ------------------------------------
    check(h.get("x-frame-options", "").upper() in ("DENY", "SAMEORIGIN"), "X-Frame-Options set",
          "missing; older browsers could still frame the app")

    # --- Permissions-Policy: who may use the camera -------------------------------
    pp = h.get("permissions-policy", "")
    check("camera=(self)" in pp.replace(" ", ""), "Permissions-Policy limits camera to this site",
          "camera is not restricted to 'self'")
    check("microphone=()" in pp.replace(" ", ""), "Permissions-Policy disables the microphone",
          "microphone is not disabled (the app never needs it)")
    check("geolocation=()" in pp.replace(" ", ""), "Permissions-Policy disables location",
          "geolocation is not disabled (the app never needs it)")

    check(h.get("x-content-type-options", "").lower() == "nosniff", "X-Content-Type-Options: nosniff", "missing")
    check(bool(h.get("referrer-policy")), "Referrer-Policy set", "missing", WARN)
    check(h.get("cross-origin-opener-policy", "").lower() in ("same-origin", "same-origin-allow-popups"),
          "Cross-Origin-Opener-Policy set", "missing", WARN)

    if https:
        check("max-age" in h.get("strict-transport-security", ""), "HSTS set (HTTPS)",
              "missing: browsers may be downgraded to plain HTTP", FAIL)
    return out


def evaluate_transport(url: str) -> list[Finding]:
    parsed = urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme == "https":
        return [Finding(PASS, "Served over HTTPS")]
    if local:
        return [Finding(WARN, "Plain HTTP on localhost", "fine for development; production must use HTTPS")]
    return [Finding(FAIL, "Served over HTTPS",
                    "plain HTTP: photos travel unencrypted and browsers will not even allow the camera")]


def run(url: str) -> list[Finding]:
    import httpx

    findings = evaluate_transport(url)
    with httpx.Client(timeout=10, follow_redirects=False, verify=True) as client:
        resp = client.get(url)
        findings += evaluate_headers(resp.headers, https=urlparse(url).scheme == "https")
        # The old Amazon screenshots must not be downloadable any more.
        shot = client.get(url.rstrip("/") + "/app/static/Acne.png")
        leaked = shot.headers.get("content-type", "").startswith("image/")
        findings.append(Finding(FAIL if leaked else PASS, "Legacy /app/static screenshots not served",
                                "static file serving is on and exposes images" if leaked else ""))
        server = resp.headers.get("server", "")
        if any(ch.isdigit() for ch in server):
            findings.append(Finding(WARN, "Server header hides its version", f"reveals: {server}"))
    return findings


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    findings = run(argv[1])
    width = max(len(f.check) for f in findings)
    for f in findings:
        print(f"[{f.level}] {f.check:<{width}}  {f.detail}".rstrip())
    fails = sum(f.level == FAIL for f in findings)
    warns = sum(f.level == WARN for f in findings)
    print(f"\n{len(findings) - fails - warns} passed, {warns} warnings, {fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
