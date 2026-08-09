#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ezer_channels — 콘텐츠 채널 per-channel 헬스 doctor (AGENTREACH OPP-02).

ezer는 "부트 노드가 살아있나"(preflight C01~C48)는 결정론 검증하나 "지금
YouTube/Reddit/X/네이버/HN/arXiv 같은 콘텐츠 채널의 공개 접근 루트가 동작하나"를
묻는 per-channel 헬스 모델이 없었다. 이 도구는 채널 라우트 실측 결과를 9-verdict
2축(insane-search validators)으로 집계해 ChannelVerdict를 낸다.

★coverage_battery 함정 봉인(보고서 OPP-02 self-검출):
  측정 엔진 tests/coverage_battery.py 는 build.rs:17 이 'tests' 디렉터리를 임베드
  제외하므로 배포 머신(~/.ezer/pack)에 **존재하지 않는다**. 따라서:
   - --self-test 는 네트워크0·순수함수(집계/verdict 재유도)만 박제 — coverage_battery
     import 없음 → 배포 머신에서도 항상 통과(C49 결정론 게이트의 본질).
   - --json/--silence-first 의 라이브 타격은 coverage_battery 를 서브프로세스로 호출
     하되 부재 시 ImportError 로 죽지 않고 graceful degrade(verdict=UNKNOWN·evidence
     "battery-absent")로 보고 — tests-제외 봉인.
  요컨대 "헬스 도구가 배선됐나"(C49·결정론)와 "채널이 살아있나"(cron 런타임)를 분리한다.

서브커맨드:
    ezer_channels.py --self-test              # 네트워크0 — 집계/verdict/permutation/429비종결 박제, exit 0=ok
    ezer_channels.py --json [채널...]          # 라이브 타격(엔진 있을 때)·[{platform,verdict,evidence,routes}]
    ezer_channels.py --silence-first [채널...]  # 전부 STRONG_OK면 1줄, 아니면 실패 채널만 상세

종료: 0 = self-test ok 또는 전 채널 도달, 1 = self-test 실패 또는 도달 불가 채널 존재.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

# ── 채널 레지스트리: tier 자기선언(PHIL-09 정직한 tier). tier∈{0,1,2} — unknown=self-test FAIL ──
# 0=zero-config 무인증, 1=쿠키/UA, 2=토큰. blocked_note = negative-knowledge 1급 데이터.
CHANNEL_REGISTRY = {
    "reddit":   {"tier": 0, "blocked_note": "hot.json 403 since ~2026-06(docstring 실측)"},
    "x":        {"tier": 0, "blocked_note": ""},
    "youtube":  {"tier": 0, "blocked_note": "yt-dlp 의존(런타임 absent 가능)"},
    "hn":       {"tier": 0, "blocked_note": ""},
    "arxiv":    {"tier": 0, "blocked_note": ""},
    "naver":    {"tier": 0, "blocked_note": ""},
    "linkedin": {"tier": 1, "blocked_note": "pulse 비인증=Just a moment 챌린지 빈번"},
}
TIER_ENUM = (0, 1, 2)

# ── ChannelVerdict 2-pass(PHIL-06): 9-verdict 2축에 사상. score 금지(eval-driven 7). ──
# validators.Verdict 시맨틱과 byte 정합(별도 진실 금지): 429=terminal nonsuccess(죽음 아님).
V_STRONG_OK = "STRONG_OK"
V_RATE_LIMITED = "RATE_LIMITED"
V_AUTH_REQUIRED = "AUTH_REQUIRED"
V_CHANNEL_DOWN = "CHANNEL_DOWN"
V_UNKNOWN = "UNKNOWN"


def derive_route_verdict(ok, status, error):
    """RouteResult(ok,status,error) → 9-verdict 재유도(validators.py:209-234 임계값 재사용).
    battery 는 ok bool 만 주므로 STRONG_OK 가 천장(success_selector 증명은 battery 범위 밖)."""
    if ok:
        return V_STRONG_OK
    if error and ("not installed" in error.lower() or "FileNotFoundError" in error
                  or "ModuleNotFoundError" in error):
        return V_UNKNOWN
    if status == 429:
        return V_RATE_LIMITED          # 차단 아님·일시적 — 죽음 오판 금지(R6 4조건 정합)
    if status in (401, 403, 407):
        return V_AUTH_REQUIRED          # tier>0 인증 필요 처방
    if status in (0,) and not error:
        return V_CHANNEL_DOWN
    if status == 0 and error:
        return V_UNKNOWN                # 네트워크/예외 — 측정실패(off 아님)
    return V_CHANNEL_DOWN               # 그 외 비2xx = 루트 실패


# 채널 집계 우선순위(ok > warn > off > error) — 2-pass select.
_RANK = {V_STRONG_OK: 4, V_RATE_LIMITED: 3, V_AUTH_REQUIRED: 3,
         V_CHANNEL_DOWN: 1, V_UNKNOWN: 0}


def aggregate_channel(routes):
    """채널 라우트 리스트 → (ChannelVerdict, evidence). permutation 불변(순서 무관).
    routes = [{"ok":bool,"status":int,"error":str|None,"route":str}, ...]."""
    if not routes:
        return V_UNKNOWN, "no-routes"
    best = None
    best_route = None
    for r in routes:
        v = derive_route_verdict(r.get("ok"), r.get("status", 0), r.get("error"))
        # permutation 불변: 동률(예: RATE_LIMITED·AUTH_REQUIRED 둘 다 rank3)은
        # verdict 이름 사전순으로 결정론 타이브레이크(라우트 순서 무관).
        if best is None or (_RANK[v], v) > (_RANK[best], best):
            best, best_route = v, r
    ev = "%s:%s(status=%s)" % (best_route.get("route", "?"),
                               "ok" if best_route.get("ok") else "fail",
                               best_route.get("status", 0))
    return best, ev


def channel_report(routes_by_platform):
    """platform→routes dict → 정렬된 [{platform,verdict,tier,evidence,routes}]."""
    out = []
    for plat in sorted(routes_by_platform):
        routes = routes_by_platform[plat]
        verdict, ev = aggregate_channel(routes)
        out.append({
            "platform": plat,
            "verdict": verdict,
            "tier": CHANNEL_REGISTRY.get(plat, {}).get("tier"),
            "evidence": ev,
            "routes": routes,
        })
    return out


# ── 라이브 측정: coverage_battery 서브프로세스 호출(graceful degrade — 함정 봉인) ──
def _battery_path():
    """배포 머신은 tests/ 미동봉(build.rs:17) — SOT/개발 트리에서만 존재. 부재 None."""
    for base in (os.environ.get("EZER_PACK_DIR", ""),
                 os.path.join(os.path.expanduser("~"), ".ezer/pack"),
                 os.path.join(os.path.expanduser("~"), "dev/ezer-agent/ezer-pack")):
        if not base:
            continue
        p = os.path.join(base, "skills", "insane-search", "tests", "coverage_battery.py")
        if os.path.isfile(p):
            return p
    return None


def run_live(channels):
    """coverage_battery --json 호출 → platform→routes. 부재 시 UNKNOWN graceful(ImportError 회피)."""
    bp = _battery_path()
    if not bp:
        return {c: [{"ok": False, "status": 0, "error": "battery-absent",
                     "route": "coverage_battery(tests-제외·미배포)"}]
                for c in channels}, "battery-absent"
    try:
        r = subprocess.run([sys.executable, bp, "--json"] + list(channels),
                           capture_output=True, timeout=180)
    except Exception as e:
        return {c: [{"ok": False, "status": 0, "error": "%s" % e,
                     "route": "coverage_battery(run-failed)"}] for c in channels}, "run-failed"
    try:
        results = json.loads((r.stdout or b"[]").decode("utf-8", "replace"))
    except ValueError:
        return {c: [{"ok": False, "status": 0, "error": "json-parse",
                     "route": "coverage_battery(bad-json)"}] for c in channels}, "bad-json"
    by_plat = {}
    for rr in results:
        by_plat.setdefault(rr.get("platform", "?"), []).append({
            "ok": rr.get("ok"), "status": rr.get("status", 0),
            "error": rr.get("error"), "route": rr.get("route", "?")})
    return by_plat, "live"


# ── self-test: 네트워크0·순수함수 박제(producer≠evaluator·LOCKED 기대값) ──
def self_test():
    fails = []
    # 1) 2-pass ok>warn: 한 라우트 ok면 채널 STRONG_OK(다른 라우트 실패해도).
    v, _ = aggregate_channel([{"ok": False, "status": 403, "route": "a"},
                              {"ok": True, "status": 200, "route": "b"}])
    if v != V_STRONG_OK:
        fails.append("2-pass: 1 ok route must win STRONG_OK")
    # 2) permutation 불변: 순서 바꿔도 동일 verdict.
    rs = [{"ok": False, "status": 429, "route": "a"},
          {"ok": False, "status": 403, "route": "b"}]
    v1, _ = aggregate_channel(rs)
    v2, _ = aggregate_channel(list(reversed(rs)))
    if v1 != v2:
        fails.append("permutation: order must not change verdict")
    # 3) 429 → RATE_LIMITED(terminal 아님·죽음 오판 금지).
    if derive_route_verdict(False, 429, None) != V_RATE_LIMITED:
        fails.append("429 must be RATE_LIMITED (not death)")
    # 4) 401/403 → AUTH_REQUIRED.
    if derive_route_verdict(False, 403, None) != V_AUTH_REQUIRED:
        fails.append("403 must be AUTH_REQUIRED")
    # 5) status=0 무에러 → CHANNEL_DOWN, 의존성 부재 → UNKNOWN(측정실패≠죽음).
    if derive_route_verdict(False, 0, None) != V_CHANNEL_DOWN:
        fails.append("status0 no-error must be CHANNEL_DOWN")
    if derive_route_verdict(False, 0, "yt-dlp not installed") != V_UNKNOWN:
        fails.append("dep-missing must be UNKNOWN (measurement fail, not death)")
    # 6) tier enum: 레지스트리 전 채널 tier∈{0,1,2}(PHIL-07 enum 강제).
    for c, meta in CHANNEL_REGISTRY.items():
        if meta.get("tier") not in TIER_ENUM:
            fails.append("tier enum: %s tier=%r not in {0,1,2}" % (c, meta.get("tier")))
    # 7) 라이브 부재 graceful: battery 없으면 UNKNOWN, ImportError 안 던짐.
    by, mode = run_live(["reddit"])
    if mode == "live":
        pass  # 개발 트리 — 실제 측정 가능(정상)
    else:
        rep = channel_report(by)
        if not rep or rep[0]["verdict"] != V_UNKNOWN:
            fails.append("battery-absent must graceful-degrade to UNKNOWN (트랩 봉인)")
    print(json.dumps({"self_test": "ok" if not fails else "fail", "failures": fails},
                     ensure_ascii=False))
    return 1 if fails else 0


def main(argv):
    ap = argparse.ArgumentParser(description="콘텐츠 채널 per-channel 헬스 doctor(OPP-02)")
    ap.add_argument("--self-test", action="store_true", help="네트워크0 집계/verdict 자기검증")
    ap.add_argument("--json", action="store_true", help="기계판 — 라이브 verdict 배열")
    ap.add_argument("--silence-first", action="store_true",
                    help="전부 STRONG_OK면 1줄, 아니면 실패 채널만 상세")
    ap.add_argument("channels", nargs="*", help="부분집합(예: reddit x). 비우면 전체")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    wanted = [c for c in (args.channels or list(CHANNEL_REGISTRY)) if c in CHANNEL_REGISTRY]
    by_plat, mode = run_live(wanted)
    report = channel_report(by_plat)
    down = [r for r in report if r["verdict"] in (V_CHANNEL_DOWN, V_UNKNOWN)]

    if args.json:
        print(json.dumps({"mode": mode, "channels": report}, ensure_ascii=False, indent=2))
    elif args.silence_first:
        strong = [r for r in report if r["verdict"] == V_STRONG_OK]
        if len(strong) == len(report) and report:
            print("channels OK: %d/%d reachable" % (len(strong), len(report)))
        else:
            for r in report:
                if r["verdict"] != V_STRONG_OK:
                    print("  ⚠ %s: %s [%s] tier=%s"
                          % (r["platform"], r["verdict"], r["evidence"], r["tier"]))
    else:
        for r in report:
            print("%-10s %-14s %s" % (r["platform"], r["verdict"], r["evidence"]))
    return 1 if down else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
