#!/usr/bin/env python3
"""U8 tests — OPP-12 broken-sibling recovery hints on success.

Offline & deterministic: no network, no file I/O. Fixtures are synthetic
Attempt records — _broken_siblings/_sibling_hint are pure functions of the
trace, so no monkeypatch is needed.

Run:  python3 engine/tests/test_u8.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from engine.fetch_chain import (                    # noqa: E402
    Attempt, FetchResult, _broken_siblings, _sibling_hint, _BROKEN_VERDICTS,
)
from engine.validators import Verdict               # noqa: E402


def _att(transform="original", impersonate="safari", referer="self_root",
         verdict=Verdict.CHALLENGE.value, reasons=None, phase="grid",
         executor="curl_cffi"):
    return Attempt(
        phase=phase, executor=executor, url="https://example.com/x",
        url_transform=transform, impersonate=impersonate, referer=referer,
        verdict=verdict, reasons=reasons or [],
    )


def t_winner_excluded():
    """Invariant 1: the winning route is never in broken_siblings."""
    winner = _att(impersonate="chrome", verdict=Verdict.STRONG_OK.value)
    trace = [
        _att(impersonate="safari", verdict=Verdict.CHALLENGE.value),
        winner,
    ]
    out = _broken_siblings(trace, winner)
    keys = {(s["transform"], s["impersonate"], s["referer"]) for s in out}
    assert ("original", "chrome", "self_root") not in keys, out
    assert ("original", "safari", "self_root") in keys, out
    print("  ✓ winner route excluded; broken sibling retained")


def t_dedup():
    """Invariant 2: same (transform,impersonate,referer) appears once."""
    trace = [
        _att(impersonate="safari", verdict=Verdict.CHALLENGE.value, reasons=["a"]),
        _att(impersonate="safari", verdict=Verdict.BLOCKED.value, reasons=["b"]),
        _att(impersonate="safari", verdict=Verdict.CHALLENGE.value, reasons=["c"]),
    ]
    out = _broken_siblings(trace, None)
    assert len(out) == 1, out
    # first occurrence wins
    assert out[0]["verdict"] == Verdict.CHALLENGE.value and out[0]["reasons"] == ["a"], out
    print("  ✓ dedup keeps first occurrence only")


def t_url_level_excluded():
    """Invariant 3: AUTH/NOT_FOUND/RATE_LIMITED are excluded (route innocent)."""
    trace = [
        _att(impersonate="safari", verdict=Verdict.AUTH_REQUIRED.value),
        _att(impersonate="chrome", verdict=Verdict.NOT_FOUND.value),
        _att(impersonate="edge", verdict=Verdict.RATE_LIMITED.value),
        _att(impersonate="firefox", verdict=Verdict.SUSPECT_OK.value),
        _att(impersonate="safari_ios", verdict=Verdict.UNKNOWN.value, reasons=[]),
    ]
    out = _broken_siblings(trace, None)
    assert out == [], out
    print("  ✓ url-level / suspect / unknown verdicts all excluded")


def t_playwright_fallback_ar_bilibili():
    """Regression: Playwright fallback success + whole grid CHALLENGE →
    broken_siblings is non-empty (the AR bilibili scenario this OPP exists for)."""
    pw_winner = _att(phase="fallback", executor="playwright_real_chrome",
                     impersonate=None, referer="", transform="original",
                     verdict=Verdict.STRONG_OK.value)
    trace = [
        _att(transform="original", impersonate="safari", verdict=Verdict.CHALLENGE.value),
        _att(transform="original", impersonate="chrome", verdict=Verdict.CHALLENGE.value),
        _att(transform="mobile_subdomain", impersonate="edge", verdict=Verdict.BLOCKED.value),
        pw_winner,
    ]
    out = _broken_siblings(trace, pw_winner)
    assert len(out) == 3, out
    assert all(s["hint"] for s in out), "every broken sibling carries a hint"
    print(f"  ✓ Playwright fallback success surfaces {len(out)} broken siblings (AR bilibili)")


def t_phase0_only_trace_empty():
    """Risk 3 guard: Phase0-only trace (impersonate=None, transform='-') yields
    no false siblings — non-broken verdicts are filtered out naturally."""
    trace = [
        _att(phase="phase0", executor="reddit_json", impersonate=None,
             transform="-", referer="", verdict=Verdict.STRONG_OK.value),
    ]
    out = _broken_siblings(trace, None)
    assert out == [], out
    print("  ✓ Phase0-only success trace produces no broken siblings")


def t_empty_and_none_failsafe():
    """Fail-safe: empty trace / None winner return []."""
    assert _broken_siblings([], None) == []
    assert _broken_siblings([], _att()) == []
    print("  ✓ empty trace / None inputs fail-safe to []")


def t_hint_actionable_no_hardcode():
    """Hints are agent-actionable (user_hint retry / Playwright MCP) and contain
    no date/site hard-coding; BLOCKED hint does NOT suggest engine auto-deprioritize."""
    ch = _sibling_hint(_att(impersonate="safari_ios", verdict=Verdict.CHALLENGE.value))
    bl = _sibling_hint(_att(impersonate="chrome", transform="mobile_subdomain",
                            verdict=Verdict.BLOCKED.value))
    assert "user_hint" in ch and "Playwright MCP" in ch, ch
    assert "safari_ios" in ch, ch  # derived from _family, not hard-coded site
    assert "user_hint" in bl and "Playwright MCP" in bl, bl
    assert "deprioritize" not in bl and "강등" not in bl, ("revision 4: no auto-deprioritize", bl)
    print("  ✓ hints are agent-actionable; BLOCKED omits engine-internal deprioritize")


def t_broken_verdicts_set():
    """Sanity: _BROKEN_VERDICTS is exactly CHALLENGE/BLOCKED."""
    assert _BROKEN_VERDICTS == frozenset({Verdict.CHALLENGE.value, Verdict.BLOCKED.value})
    print("  ✓ _BROKEN_VERDICTS = {challenge, blocked}")


def t_to_dict_carries_key():
    """Regression: FetchResult.to_dict() carries broken_siblings (JSON exposure)."""
    r = FetchResult(ok=True, broken_siblings=[{"transform": "original"}])
    d = r.to_dict()
    assert "broken_siblings" in d and d["broken_siblings"] == [{"transform": "original"}], d
    # backward-compat: default is empty list, existing keys untouched.
    assert FetchResult(ok=True).to_dict()["broken_siblings"] == []
    print("  ✓ to_dict() exposes broken_siblings (default [])")


ALL = [
    ("winner_excluded", t_winner_excluded),
    ("dedup", t_dedup),
    ("url_level_excluded", t_url_level_excluded),
    ("playwright_fallback_ar_bilibili", t_playwright_fallback_ar_bilibili),
    ("phase0_only_trace_empty", t_phase0_only_trace_empty),
    ("empty_and_none_failsafe", t_empty_and_none_failsafe),
    ("hint_actionable_no_hardcode", t_hint_actionable_no_hardcode),
    ("broken_verdicts_set", t_broken_verdicts_set),
    ("to_dict_carries_key", t_to_dict_carries_key),
]


def main() -> int:
    p = f = 0
    for name, fn in ALL:
        try:
            print(f"[{name}]")
            fn()
            p += 1
        except AssertionError as e:
            f += 1
            print(f"  ✗ FAIL: {e}")
        except Exception as e:
            f += 1
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
    print(f"\n{p} passed, {f} failed")
    return 0 if f == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
