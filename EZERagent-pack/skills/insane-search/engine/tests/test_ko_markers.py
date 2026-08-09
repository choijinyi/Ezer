#!/usr/bin/env python3
"""Korean WAF marker regression tests (OPP-04).

Deterministic, network-free. Locks in the measured Korean block markers.

The markers (`사용자 활동 검토 요청 및 안내`,
`고객님의 사이트 내 활동이 봇의 동작과 유사해 보입니다`) are SOFT, not HARD: a
tech / security / scraping article can quote them verbatim, so they are not
"impossible in legitimate content" (adversarial review 2026-06-25). As SOFT they
keep OPP-04 value (a real block page with no positive proof is still CHALLENGE)
while deferring to caller positive proof (success_selectors) on a legitimate page
that merely quotes the phrase — removing the false-CHALLENGE risk.

Invariants locked:
  * a Korean block body with NO positive proof → CHALLENGE (block still caught);
  * the same phrase + a MATCHING success_selector → STRONG_OK/WEAK_OK, NOT
    CHALLENGE (SOFT override — the core correction);
  * every Korean SOFT marker traces to a measured row in blocked-ko.md
    (no invented markers — environment honesty gate);
  * English HARD markers do not regress.

Run:  python3 engine/tests/test_ko_markers.py
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from engine.validators import (  # noqa: E402
    validate, Verdict, HARD_CHALLENGE_MARKERS, SOFT_CHALLENGE_MARKERS,
)

BLOCKED_KO = os.path.join(ROOT, "references", "blocked-ko.md")
KO = re.compile(r"[가-힣]")


class _Resp:
    def __init__(self, status=200, text="", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {"Content-Type": "text/html"}

        class _Jar:
            jar: list = []
        self.cookies = _Jar()


# Verbatim excerpt of the measured gmarket/auction bot-challenge container
# (references/blocked-ko.md, measured 2026-06-25). Padded so the body is a
# complete, sizeable HTML document — the exact shape that used to be박제 WEAK_OK.
_KO_BLOCK_BODY = (
    "<html><head><title>G마켓 - 쇼핑을 바꾸는 쇼핑</title></head><body>"
    + "<p>안내</p>" * 600
    + "<H2><p>사용자 활동 검토 요청 및 안내</p></H2>"
    + "<p>고객님의 사이트 내 활동이 봇의 동작과 유사해 보입니다.</p>"
    + "<p>봇이 아님을 아래 확인해 주시고 도움이 필요하면 고객센터로 연락 부탁드립니다.</p>"
    + "</body></html>"
)


def t_ko_block_no_proof_is_challenge_200():
    # Real block page, no caller positive proof: SOFT marker decides CHALLENGE.
    # (The dangerous case that used to be박제 WEAK_OK at 200.)
    v = validate(_Resp(200, _KO_BLOCK_BODY))
    assert v.verdict == Verdict.CHALLENGE, (v.verdict, v.reasons)
    assert v.body_size >= 3000, v.body_size  # sizeable → proves not tiny-body path
    print(f"  ✓ 200 Korean block, no proof → {v.verdict.value} ({v.reasons[:2]})")


def t_ko_block_no_proof_is_challenge_403():
    # gmarket/auction actually return 403, which falls through to marker analysis.
    v = validate(_Resp(403, _KO_BLOCK_BODY))
    assert v.verdict == Verdict.CHALLENGE, (v.verdict, v.reasons)
    print(f"  ✓ 403 Korean block, no proof → {v.verdict.value}")


def t_ko_marker_overridden_by_matching_selector():
    # CORE CORRECTION: the very block-marker phrase appears verbatim in a page,
    # but a caller success_selector matches → positive proof wins, NOT CHALLENGE.
    # This is the false-positive a security/scraping article would have triggered
    # under the old HARD classification.
    body = ("<html><body><h1>봇 차단 페이지 분석</h1><main id='c'>"
            "본 글은 차단 페이지를 인용한다: "
            "사용자 활동 검토 요청 및 안내 — "
            "고객님의 사이트 내 활동이 봇의 동작과 유사해 보입니다. "
            + "이 문구에 대한 기술적 분석 본문. " * 200
            + "</main></body></html>")
    v = validate(_Resp(200, body), success_selectors=["#c"])
    assert v.verdict == Verdict.STRONG_OK, (v.verdict, v.reasons)
    print(f"  ✓ block phrase + matching selector → {v.verdict.value} (SOFT overridden)")


def t_ko_marker_with_selector_but_no_match_still_challenge():
    # If selectors are requested but none match, that is itself negative proof:
    # validate() returns CHALLENGE at the selector layer (no_success_selector).
    v = validate(_Resp(200, _KO_BLOCK_BODY), success_selectors=["#definitely-absent"])
    assert v.verdict == Verdict.CHALLENGE, (v.verdict, v.reasons)
    print(f"  ✓ block + selector-requested-but-unmatched → {v.verdict.value}")


def t_legit_korean_article_no_false_positive():
    # A real article that mentions captcha/bot as a TOPIC (different wording),
    # with positive proof, must NOT be flagged.
    body = ("<html><body><h1>카카오 캡차 도입 논란</h1><main id='c'>"
            + "기사 본문입니다. 로봇이 아닙니다 위젯과 봇 차단에 대한 분석. " * 200
            + "</main></body></html>")
    v = validate(_Resp(200, body), success_selectors=["#c"])
    assert v.verdict == Verdict.STRONG_OK, (v.verdict, v.reasons)
    print(f"  ✓ legit Korean captcha-topic article + selector → {v.verdict.value}")


def t_english_hard_markers_no_regression():
    v = validate(_Resp(200, "<html>" + "x" * 5000 + " sec-if-cpt-container </html>"))
    assert v.verdict == Verdict.CHALLENGE, v.verdict
    v2 = validate(_Resp(200, "Just a moment..."))
    assert v2.verdict == Verdict.CHALLENGE, v2.verdict
    print("  ✓ English HARD markers still → challenge (no regression)")


def _measured_rows() -> set[str]:
    """Korean marker phrases listed in the '실측' (measured) table of
    blocked-ko.md (any tier). Used to prove every code marker is sourced."""
    rows: set[str] = set()
    in_measured = False
    with open(BLOCKED_KO, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("## 실측"):
                in_measured = True
                continue
            if in_measured and line.startswith("## "):
                break
            if in_measured and line.lstrip().startswith("|"):
                cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
                # columns: 플랫폼 | 차단유형 | 응답특징 | 마커문구 | tier | 확인일
                if len(cells) >= 4:
                    rows.add(cells[3])
    return rows


def t_every_ko_soft_marker_traces_to_measured_catalog():
    # Environment-honesty invariant: every Korean SOFT marker in validators.py
    # MUST appear as a measured row in blocked-ko.md (no invented markers).
    measured = _measured_rows()
    ko_soft = [m for m in SOFT_CHALLENGE_MARKERS if KO.search(m)]
    assert ko_soft, "expected at least one measured Korean SOFT marker"
    for m in ko_soft:
        assert any(m in row for row in measured), (
            f"Korean SOFT marker not traceable to a measured blocked-ko.md row: {m!r}"
        )
    print(f"  ✓ all {len(ko_soft)} Korean SOFT markers traced to measured catalog rows")


def t_no_korean_hard_markers():
    # Korean markers are SOFT only (HARD = impossible-in-legit-content; Korean
    # block phrases can be quoted by articles, so they must not be HARD).
    ko_hard = [m for m in HARD_CHALLENGE_MARKERS if KO.search(m)]
    assert not ko_hard, f"Korean markers must be SOFT, found in HARD list: {ko_hard}"
    print("  ✓ no Korean markers in HARD list (Korean block phrases are SOFT only)")


ALL = [
    ("ko_block_no_proof_is_challenge_200", t_ko_block_no_proof_is_challenge_200),
    ("ko_block_no_proof_is_challenge_403", t_ko_block_no_proof_is_challenge_403),
    ("ko_marker_overridden_by_matching_selector", t_ko_marker_overridden_by_matching_selector),
    ("ko_marker_with_selector_but_no_match_still_challenge", t_ko_marker_with_selector_but_no_match_still_challenge),
    ("legit_korean_article_no_false_positive", t_legit_korean_article_no_false_positive),
    ("english_hard_markers_no_regression", t_english_hard_markers_no_regression),
    ("every_ko_soft_marker_traces_to_measured_catalog", t_every_ko_soft_marker_traces_to_measured_catalog),
    ("no_korean_hard_markers", t_no_korean_hard_markers),
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
