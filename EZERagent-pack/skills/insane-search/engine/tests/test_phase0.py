#!/usr/bin/env python3
"""Phase-0 router contract tests (OPP-03 Naver no-auth route; OPP-01 facade seal).

Mostly deterministic & network-free (offline contract block). One optional
online smoke (finance siseJson) runs only if reachable and is SKIPPED, never
failed, when the endpoint is blocked/offline — environment honesty (no invented
results).

Invariants locked:
  * registry invariant (PHIL-07): set(_ROUTERS) == every non-None _detect value;
  * _detect routes naver hosts to "naver" and leaves reddit/x/youtube unchanged;
  * the attempt dict schema is stable and carries the optional "auth" flag only
    when set (reddit/x/youtube attempts never carry it → no regression);
  * naver cafe self-declares auth (the AUTH_REQUIRED signal), is NOT ok;
  * a Naver blog path parses to (blogId, logNo);
  * Chinese platforms / Chzzk are NOT routed (no measured contract → not added);
  * OPP-01 facade: route() is the code-sealed URL→handler entrypoint (no parallel
    router), route()==None is the grid / OPP-22 search-channel handoff contract,
    and WEBFETCH is never a Phase-0 channel (deny-by-default 고삐 불변).

Run:  python3 engine/tests/test_phase0.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from engine import phase0  # noqa: E402
from engine.phase0 import _attempt, _detect, _naver, _parse_blog_path, _ROUTERS, route  # noqa: E402


# --- registry / detect contract ---------------------------------------------
def t_registry_invariant():
    # PHIL-07: every platform _detect can return MUST have a router, and there
    # are no orphan routers. Probe representative URLs per known platform.
    probes = [
        "https://www.reddit.com/r/python/",
        "https://x.com/jack",
        "https://www.youtube.com/watch?v=abc",
        "https://blog.naver.com/foo/123",
    ]
    detected = {_detect(u) for u in probes}
    detected.discard(None)
    assert detected == set(_ROUTERS), (detected, set(_ROUTERS))
    print(f"  ✓ registry invariant: detect set == _ROUTERS keys ({sorted(_ROUTERS)})")


def t_detect_existing_platforms_unchanged():
    assert _detect("https://www.reddit.com/r/x/") == "reddit"
    assert _detect("https://redd.it/abc") == "reddit"
    assert _detect("https://x.com/jack") == "x"
    assert _detect("https://twitter.com/jack") == "x"
    assert _detect("https://www.youtube.com/watch?v=q") == "youtube"
    assert _detect("https://youtu.be/q") == "youtube"
    print("  ✓ reddit/x/youtube detection unchanged (no regression)")


def t_detect_naver_hosts():
    for u in [
        "https://blog.naver.com/foo/123",
        "https://m.blog.naver.com/PostView.naver?blogId=foo&logNo=123",
        "https://finance.naver.com/item/main.naver?code=005930",
        "https://cafe.naver.com/somecafe",
        "https://naver.com/",
    ]:
        assert _detect(u) == "naver", (u, _detect(u))
    print("  ✓ naver hosts (blog/finance/cafe/root) → 'naver'")


def t_no_chinese_or_chzzk_routes():
    # OPP-03 REVISE: these have no measured no-auth contract → must NOT be routed.
    for u in [
        "https://www.bilibili.com/video/BV1",
        "https://b23.tv/abc",
        "https://www.xiaohongshu.com/explore/1",
        "https://chzzk.naver.com/live/1",  # chzzk is under naver.com but has no handler...
    ]:
        d = _detect(u)
        assert d != "bilibili" and d != "xhs" and d != "chzzk", (u, d)
    # chzzk.naver.com falls under the generic naver router (no dedicated handler);
    # _naver simply returns ok=False (no matching subdomain branch) → grid fallback.
    print("  ✓ bilibili/xhs/chzzk have no dedicated route (no hallucinated contracts)")


# --- OPP-01: content-channel single entrypoint (facade) contract ------------
# OPP-01 (ESCALATE redesign): the URL→handler routing must be SEALED IN CODE,
# not left to the SKILL.md doc contract (the report's named anti-pattern: "AR
# 채널을 SKILL.md 문서계약으로만 두기 = 코드가 아닌 문서에 의존 = 검증 불가",
# 보고서 §5494). No new router file is created — phase0.route() is already the
# facade (동형 시그니처, 보고서 §5243); these regression tests박제 that contract.
def t_route_is_code_sealed_facade():
    # route() — not a doc — is the single URL→handler entrypoint. It dispatches
    # recognised URLs to a handler and is reachable as a 1st-class public symbol.
    assert callable(route), "route() must be the public facade entrypoint"
    # The facade's dispatch set is the registry itself (no second, parallel
    # router): _detect → _ROUTERS is the only URL→handler table.
    assert set(_ROUTERS) == {"reddit", "x", "youtube", "naver"}, set(_ROUTERS)
    # Recognised URL → handler runs and returns the channel dict (offline: naver
    # cafe is a pure self-declared auth wall, no network). The point is that the
    # FACADE routed it to a handler at all.
    r = route("https://cafe.naver.com/somecafe/1", timeout=5)
    assert r is not None and r["platform"] == "naver", r
    print("  ✓ route() is the code-sealed URL→handler facade (no parallel router)")


def t_route_none_is_searchchannel_handoff():
    # The facade's None return is the CONTRACT that "this URL is not a Phase-0
    # platform → caller falls through to the generic grid / search-intent channel
    # dispatch (OPP-22 search_fallback)". Lock that an unrecognised URL → None so
    # the handoff point cannot silently regress to a swallow.
    assert route("https://example.com/some/article", timeout=5) is None
    assert route("https://news.ycombinator.com/item?id=1", timeout=5) is None
    assert _detect("https://example.com/x") is None
    print("  ✓ unrecognised URL → route() is None (grid / OPP-22 search handoff)")


def t_webfetch_is_not_a_phase0_channel():
    # WEBFETCH deny-by-default (SKILL.md:42 "WebFetch ... 시도 금지"): OPP-01 must
    # NOT promote WebFetch to a 1st-class channel. Assert no router/detector names
    # webfetch and the engine source carries no "webfetch" channel token, so the
    # redesign cannot erode the deny-by-default 고삐.
    names = {n.lower() for n in _ROUTERS}
    assert not any("webfetch" in n or "web_fetch" in n for n in names), names
    src = os.path.join(ROOT, "engine", "phase0.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read().lower()
    assert "webfetch" not in body and "web_fetch" not in body, \
        "phase0 must not name webfetch as a channel (WEBFETCH deny-by-default)"
    print("  ✓ WEBFETCH is not a Phase-0 channel (deny-by-default 고삐 불변)")


# --- attempt schema contract -------------------------------------------------
def t_attempt_schema():
    a = _attempt("naver", "x", False, 0, "body", "note")
    assert set(a) == {"platform", "route", "ok", "status", "bytes", "note"}, a
    assert "auth" not in a, "auth must be absent unless explicitly set"
    assert a["bytes"] == 4, a["bytes"]
    b = _attempt("naver", "cafe", False, 0, "", "wall", auth=True)
    assert b.get("auth") is True, b
    print("  ✓ attempt schema stable; 'auth' present only when set")


# --- naver handler contract (offline) ----------------------------------------
def t_naver_cafe_declares_auth():
    # Pure offline: cafe is a self-declared auth wall (no network call made).
    r = _naver("https://cafe.naver.com/somecafe/123", timeout=5)
    assert r["ok"] is False, r
    cafe = [a for a in r["attempts"] if a["route"] == "cafe"]
    assert cafe and cafe[0].get("auth") is True, r["attempts"]
    print("  ✓ naver cafe → ok=False with auth=True (AUTH_REQUIRED signal)")


def t_blog_path_parse():
    assert _parse_blog_path("https://blog.naver.com/foo/12345") == ("foo", "12345")
    assert _parse_blog_path(
        "https://m.blog.naver.com/PostView.naver?blogId=bar&logNo=999") == ("bar", "999")
    assert _parse_blog_path("https://blog.naver.com/") == ("", "")
    print("  ✓ blog path parsing (/{ID}/{NO} and ?blogId=&logNo=)")


# --- fetch_chain auth mapping contract ---------------------------------------
def t_fetch_chain_maps_auth_to_auth_required():
    # The 1-line fetch_chain mapping must turn a non-ok auth attempt into
    # AUTH_REQUIRED (not BLOCKED). Verify the source contract literally so the
    # mapping cannot silently regress to BLOCKED.
    fc = os.path.join(ROOT, "engine", "fetch_chain.py")
    with open(fc, encoding="utf-8") as fh:
        src = fh.read()
    assert "AUTH_REQUIRED.value if a.get(\"auth\")" in src, \
        "fetch_chain must map phase0 auth attempts to Verdict.AUTH_REQUIRED"
    print("  ✓ fetch_chain maps phase0 auth attempts → AUTH_REQUIRED")


# --- optional online smoke (skip, never fail, when blocked) ------------------
def t_online_finance_sisejson_smoke():
    # Measured 2026-06-25: api.finance.naver.com/siseJson.naver?symbol=005930 →
    # HTTP 200, body starts "[". Network-gated: SKIP (not fail) if unreachable.
    try:
        r = _naver("https://finance.naver.com/item/main.naver?code=005930", timeout=10)
    except Exception as e:  # transport/import problem → environment honesty: skip
        print(f"  ⚠ SKIP online smoke (exception): {type(e).__name__}")
        return
    fin = [a for a in r["attempts"] if a["route"] == "finance-siseJson"]
    if not fin:
        print("  ⚠ SKIP online smoke (no finance attempt recorded)")
        return
    if fin[0]["ok"]:
        assert r["ok"] is True and r["route"] == "finance-siseJson", r
        print(f"  ✓ online smoke: siseJson ok ({fin[0]['bytes']} bytes)")
    else:
        # endpoint blocked/changed at run time → honest skip, the grid would fall
        # back. Do NOT fabricate a pass.
        print(f"  ⚠ SKIP online smoke (siseJson not ok: {fin[0]['note']})")


ALL = [
    ("registry_invariant", t_registry_invariant),
    ("detect_existing_platforms_unchanged", t_detect_existing_platforms_unchanged),
    ("detect_naver_hosts", t_detect_naver_hosts),
    ("no_chinese_or_chzzk_routes", t_no_chinese_or_chzzk_routes),
    ("route_is_code_sealed_facade", t_route_is_code_sealed_facade),
    ("route_none_is_searchchannel_handoff", t_route_none_is_searchchannel_handoff),
    ("webfetch_is_not_a_phase0_channel", t_webfetch_is_not_a_phase0_channel),
    ("attempt_schema", t_attempt_schema),
    ("naver_cafe_declares_auth", t_naver_cafe_declares_auth),
    ("blog_path_parse", t_blog_path_parse),
    ("fetch_chain_maps_auth_to_auth_required", t_fetch_chain_maps_auth_to_auth_required),
    ("online_finance_sisejson_smoke", t_online_finance_sisejson_smoke),
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
    raise SystemExit(main())
