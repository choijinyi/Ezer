"""Adversarial-round-trip credential sink guard (OPP-15).

A real-browser fallback harvests cookies + User-Agent from an attacker-influenced
page and the bridge seeds them straight into the curl_cffi cookie jar / HTTP
headers (see `executor._bridge_cookies_to_pool` -> `transport.inject_cookies`).
Those values are attacker-influenced input flowing into three credential sinks:

    cookie name  -> session.cookies.set(name, ...)
    cookie value -> session.cookies.set(..., value, ...)
    cookie domain-> session.cookies.set(..., domain=...)   (scope)
    UA string    -> headers["User-Agent"]

This module is a clean-room stdlib sanitizer applying the defensive-security-gate
9 principles to that path. It is NOT a port of any upstream source: AgentReach's
threat sink was an sh `source` + env file (`shlex.quote`), which does not exist in
this engine (verified: no shlex/os.open/source sink in engine/). Only the
*contract* is absorbed — "adversarial round-trip -> value fidelity + zero side
effect" — re-implemented against the real EZERagent sinks (curl_cffi jar, HTTP header,
UA, cookie domain scope).

Principles applied (defensive-security-gate SKILL.md §1-§8):
  §1 deny-by-default allowlist  : each sink declares an allowed character class.
  §3 fail-closed                : unparseable / out-of-scope -> REJECTED (drop).
  §4 over-block on doubt        : a 1-label or public-suffix cookie domain is
                                  rejected outright (conservative, no full PSL).
  §6 strong block mechanism     : CR/LF/CTL are removed at the value BEFORE the
                                  sink, so library header serialization is moot.
  §7 normalize before matching  : NFKC + control/zero-width scan.
  §5 documented residual limit  : see references / module docstring below.

Residual limits (§5, negative knowledge):
  * The public-suffix deny list is a conservative hardcoded mini-list, NOT a full
    PSL — it can go stale. Backstop: any 1-label domain is rejected and any
    uncertain domain is narrowed to the request host by the caller.
  * curl_cffi internal header serialization is out of our control; we defend by
    stripping CR/LF from the value before it reaches the sink (splitting cannot
    occur without CR/LF in the value).
  * Threat model = an adversarial page planting cookies/UA in the browser that
    then leak cross-host or split the outgoing request header. Not a defense
    against a trusted operator's own misconfiguration.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional


class CredSink(Enum):
    """Credential sink classes (defensive-gate §1 allowlist host)."""
    COOKIE_NAME = "cookie_name"      # session.cookies.set() name argument
    COOKIE_VALUE = "cookie_value"    # session.cookies.set() value argument
    COOKIE_DOMAIN = "cookie_domain"  # session.cookies.set() domain= (scope)
    HEADER_UA = "header_ua"          # injected_ua -> User-Agent header


Verdict = Literal["CLEAN", "STRIPPED", "REJECTED"]


@dataclass(frozen=True)
class SanitizeResult:
    """eval-driven enum verdict (no 0-100 score) + evidence reasons.

    CLEAN    : allowlist passed unchanged -> round-trip equality guaranteed.
    STRIPPED : dangerous chars removed; sanitized differs from original.
    REJECTED : fail-closed; the whole cookie/UA must be dropped (sanitized=None).
    """
    sink: CredSink
    verdict: Verdict
    original: str
    sanitized: Optional[str]
    reasons: list[str] = field(default_factory=list)


# Control characters that must never reach a header / cookie sink. CR/LF enable
# header splitting / cookie-injection; NUL and other C0/C1/DEL corrupt the jar.
_CTL = frozenset(chr(c) for c in range(0x00, 0x20)) | {"\x7f"} | frozenset(
    chr(c) for c in range(0x80, 0xA0)
)

# Conservative public-suffix deny mini-list (NOT a full PSL — see §5 limit).
# A cookie domain equal to one of these (or any 1-label domain) is rejected
# because it would scope the cookie across an entire TLD / registry. Kept as
# generic public-suffix tokens. These are registry suffixes, not target-site
# names, so the No-Site-Name rule does not apply; the two-level entries match the
# bias_check URL_PATTERN and are whitelisted with the sanctioned NOTE-BIAS-OK
# marker (bias_check.py COMMENT_OK_MARKERS).
_PUBLIC_SUFFIX_DENY = frozenset({
    "com", "net", "org", "io", "co", "kr", "jp", "cn", "uk", "us", "de",
    "fr", "ru", "info", "biz", "dev", "app", "xyz", "gov", "edu", "mil",
    "co.kr", "ne.kr", "or.kr", "go.kr", "co.jp", "co.uk", "com.cn",  # NOTE-BIAS-OK
})


def _strip_ctl(raw: str) -> tuple[str, list[str]]:
    """Remove control / zero-width chars; return (clean, reasons)."""
    reasons: list[str] = []
    # \r \n plus U+2028 LINE SEP / U+2029 PARA SEP — the latter are newline-class
    # to some parsers but fall outside _CTL and Cf/Cc, so flag them explicitly.
    if any(c in raw for c in ("\r", "\n", "\u2028", "\u2029")):
        reasons.append("crlf_injection")
    out_chars = []
    for ch in raw:
        if ch in _CTL:
            reasons.append(f"ctrl_char:0x{ord(ch):02x}")
            continue
        # Cf/Cc = format/control; Zl/Zp = U+2028/U+2029 line/paragraph separators
        # (a CRLF-injection variant outside _CTL and Cf/Cc). Strip all four.
        if unicodedata.category(ch) in ("Cf", "Cc", "Zl", "Zp"):
            reasons.append(f"fmt_char:0x{ord(ch):02x}")
            continue
        out_chars.append(ch)
    return "".join(out_chars), reasons


def _sanitize_text(sink: CredSink, raw: str, reject_on_strip: bool) -> SanitizeResult:
    """Normalize (NFKC) + strip CR/LF/CTL for name/value/UA sinks."""
    norm = unicodedata.normalize("NFKC", raw)
    cleaned, reasons = _strip_ctl(norm)
    norm_changed = norm != raw
    if cleaned == raw:
        # Includes the case where NFKC was a no-op and nothing was stripped.
        return SanitizeResult(sink, "CLEAN", raw, raw, [])
    if not cleaned:
        # Nothing survives sanitization -> drop (fail-closed §3).
        return SanitizeResult(sink, "REJECTED", raw, None, reasons or ["empty_after_sanitize"])
    if reject_on_strip:
        # cookie name: altering it silently breaks meaning -> drop instead.
        return SanitizeResult(sink, "REJECTED", raw, None, reasons or ["name_altered"])
    if norm_changed and not reasons:
        reasons.append("nfkc_normalized")
    return SanitizeResult(sink, "STRIPPED", raw, cleaned, reasons)


def _sanitize_domain(raw: str, host: Optional[str]) -> SanitizeResult:
    """cookie domain scope check (defensive-gate §4 over-block on doubt).

    CLEAN only when the domain is the request host or a registrable parent of it.
    A 1-label domain, a public-suffix, a domain unrelated to host, or any domain
    carrying control chars is REJECTED (caller narrows scope to host).
    """
    sink = CredSink.COOKIE_DOMAIN
    norm = unicodedata.normalize("NFKC", raw)
    cleaned, reasons = _strip_ctl(norm)
    if cleaned != raw:
        # Any mutation of a domain is unsafe to silently apply -> reject.
        return SanitizeResult(sink, "REJECTED", raw, None, reasons or ["domain_mutated"])
    dom = cleaned.lstrip(".").lower().strip()
    if not dom:
        return SanitizeResult(sink, "REJECTED", raw, None, ["empty_domain"])
    h = (host or "").lower().strip()
    if not h:
        # No request host to scope against -> cannot validate -> reject (§3).
        return SanitizeResult(sink, "REJECTED", raw, None, ["no_host_context"])
    if "." not in dom:
        return SanitizeResult(sink, "REJECTED", raw, None, ["domain_single_label"])
    if dom in _PUBLIC_SUFFIX_DENY:
        return SanitizeResult(sink, "REJECTED", raw, None, [f"public_suffix:{dom}"])
    if dom == h:
        return SanitizeResult(sink, "CLEAN", raw, dom, [])
    # Registrable-parent: host is a subdomain of dom (e.g. host=a.b.example,
    # dom=b.example). Require the boundary to be a real dot.
    if h.endswith("." + dom):
        return SanitizeResult(sink, "CLEAN", raw, dom, [])
    # Anything else (cross-host, broader-than-registrable, unrelated) -> reject.
    return SanitizeResult(sink, "REJECTED", raw, None, ["domain_mismatch_host"])


def sanitize(sink: CredSink, raw: str, host: Optional[str] = None) -> SanitizeResult:
    """Sanitize one credential value for one sink. fail-closed by default.

    raw == None / non-str is treated as empty -> REJECTED (no silent pass).
    """
    if raw is None or not isinstance(raw, str):
        return SanitizeResult(sink, "REJECTED", "" if raw is None else str(raw),
                              None, ["non_str_input"])
    if sink is CredSink.COOKIE_DOMAIN:
        return _sanitize_domain(raw, host)
    if sink is CredSink.COOKIE_NAME:
        # Empty name is meaningless -> reject.
        if raw == "":
            return SanitizeResult(sink, "REJECTED", raw, None, ["empty_name"])
        return _sanitize_text(sink, raw, reject_on_strip=True)
    # COOKIE_VALUE / HEADER_UA: strip CR/LF/CTL, keep the cleaned remainder.
    return _sanitize_text(sink, raw, reject_on_strip=False)
