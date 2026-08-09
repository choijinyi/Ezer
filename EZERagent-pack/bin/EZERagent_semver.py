#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EZERagent_semver — strictly-newer 버전 비교 결정론 advisory (다운그레이드 유도 방지).

"두 버전 중 어느 쪽이 더 새것이냐"를 LLM 자연어 재추론 없이 결정론으로 판정하는 단일
stdlib 도구. master/CSO/preflight가 PACK·팩 채택검토 시 "이게 더 새것이냐"를 LLM 추론으로
답하면 환각 위험 — 이 자리를 순수 함수+`--self-test` 박제가 메운다(preflight 결정론 본령).

핵심 불변식:
- **strictly-newer**: `remote > local` 일 때만 UPDATE_AVAILABLE. `remote == local`(UP_TO_DATE)·
  `remote < local`(MAIN_AHEAD = 로컬이 앞섬, 다운그레이드 유도 거부)는 비행동이 정답.
- **fail-safe**: 파싱·비교 불가는 INCOMPARABLE — "업데이트 없음" 취급(거짓 권유보다 침묵).
- **score(0-100) 금지** — verdict enum + evidence(사람판 문자열)만(eval-driven 원칙7 동형).
- **순수 advisory**: 재시작·git push·cp 설치 등 비가역/외부발행 행동 0. "더 새것이다" 판정만
  결정론 제공, 실제 재시작·발행은 자율주행 denylist ESCALATE 게이트(오너/CSO 수동 트리거).

references(클린룸·실측):
- Agent Reach `_is_newer_version`(PHIL-07) 계약(strictly-newer + main-ahead 거부 + fail-safe)만
  흡수, 소스 미열람·미복붙. 규칙은 semver.org/PEP440 명세에서 재현(re만 사용; packaging/semver
  pip 미사용=의존성0 원칙). EZERagent 실사용 버전은 0.2.7·0.42.4 류 단순 release뿐(실측) — 프리릴리스/
  build는 최소 규칙만(정식>프리릴리스, build metadata 비교 무시).
- tauri-plugin-updater 2(src-tauri/Cargo.toml:13)는 GUI 자기업데이트 경로에서 이미 내부 semver
  strictly-newer 비교를 수행한다 — 이 도구는 그 경로를 *재발명하지 않고*, Python 측 PACK/팩
  채택검토(tauri가 커버 안 하는 갭)를 결정론으로 판정하는 advisory 용도로 한정한다.

사용:
    python3 EZERagent_semver.py compare --local <V> --remote <V> [--json]
        exit 0=UP_TO_DATE  0=MAIN_AHEAD  10=UPDATE_AVAILABLE  2=INCOMPARABLE/인자오류
        # exit 10 = "행동 가능(업데이트 후보 존재)" advisory 신호 — 호출자가 ESCALATE 티켓
        #   생성 트리거. exit 10 자체는 어떤 행동도 *수행*하지 않는다(advisory only).
    python3 EZERagent_semver.py parse <V> [--json]              # ParsedVersion 상태 방출(디버그)
    python3 EZERagent_semver.py gate --local-file <PATH> --remote <V> [--field version] [--json]
        # Cargo.toml/tauri.conf.json/manifest의 version 필드를 정규식으로 읽어 compare 위임
    python3 EZERagent_semver.py --self-test                    # 결정론 자기검증 (preflight C45)
종료 코드: 0=UP_TO_DATE/MAIN_AHEAD(비행동이 정답) · 10=UPDATE_AVAILABLE · 1=self-test 실패
           · 2=INCOMPARABLE/인자/입출력 오류
의존성: 파이썬 표준 라이브러리만(re·json·argparse·sys). 네트워크·LLM·점수·DB 쓰기 0.
"""

import argparse
import json
import re
import sys

# ── verdict enum (score 금지 — enum + evidence만) ──
UP_TO_DATE, UPDATE_AVAILABLE, MAIN_AHEAD, INCOMPARABLE = (
    "UP_TO_DATE", "UPDATE_AVAILABLE", "MAIN_AHEAD", "INCOMPARABLE")

# ParsedVersion.status (파싱단 상태)
OK, EMPTY, UNPARSEABLE = "ok", "empty", "unparseable"

# release: 선행 v/V 1개 strip 후 점-구분 정수. 나머지는 prerelease(-rcN)·build(+meta).
_RELEASE_RE = re.compile(r"^(\d+(?:\.\d+)*)")
_PRERELEASE_RE = re.compile(r"^-([0-9A-Za-z.-]+)")
_BUILD_RE = re.compile(r"^\+([0-9A-Za-z.-]+)")


class ParsedVersion:
    """불변 버전 모델 — release 튜플 + prerelease 식별자 + 원문 보존(negative knowledge)."""

    __slots__ = ("release", "prerelease", "raw", "status")

    def __init__(self, release, prerelease, raw, status):
        self.release = release            # tuple[int,...] — (major, minor, patch[, ...])
        self.prerelease = prerelease      # tuple — 프리릴리스 식별자(빈=정식 release)
        self.raw = raw                    # str — 원문 보존
        self.status = status              # ok|empty|unparseable

    def to_dict(self):
        return {"release": list(self.release), "prerelease": list(self.prerelease),
                "raw": self.raw, "status": self.status}


def parse(s):
    """버전 문자열 → ParsedVersion. 클린룸: semver.org/PEP440 규칙만 재현."""
    raw = s if s is not None else ""
    t = raw.strip()
    if not t:
        return ParsedVersion((), (), raw, EMPTY)
    # 선행 v/V 1개만 strip (v0.2.7 → 0.2.7), 그 외 접두는 거부(UNPARSEABLE).
    if t[:1] in ("v", "V"):
        t = t[1:]
    m = _RELEASE_RE.match(t)
    if not m:
        return ParsedVersion((), (), raw, UNPARSEABLE)
    release = tuple(int(x) for x in m.group(1).split("."))
    rest = t[m.end():]
    prerelease = ()
    # prerelease(-rcN) 추출 — build(+meta)는 비교 무시(semver 규칙)이나 잔여 패턴 검증은 한다.
    pm = _PRERELEASE_RE.match(rest)
    if pm:
        prerelease = _split_prerelease(pm.group(1))
        rest = rest[pm.end():]
    bm = _BUILD_RE.match(rest)
    if bm:
        rest = rest[bm.end():]  # build metadata는 보관/비교 안 함
    if rest:  # 인식 못 한 잔여 토큰 = 비의미 버전 → fail-safe
        return ParsedVersion((), (), raw, UNPARSEABLE)
    return ParsedVersion(release, prerelease, raw, OK)


def _split_prerelease(s):
    """프리릴리스 식별자를 '.'으로 분할 — 숫자 식별자는 int(숫자<문자 semver 규칙)."""
    out = []
    for ident in s.split("."):
        if ident.isdigit():
            out.append((0, int(ident)))   # (0, n): 숫자 식별자, 문자보다 작음
        else:
            out.append((1, ident))        # (1, s): 문자 식별자
    return tuple(out)


def _cmp_release(a, b):
    """release 튜플 짧은 쪽 0패딩 후 사전식 비교 → -1/0/1."""
    n = max(len(a), len(b))
    pa = a + (0,) * (n - len(a))
    pb = b + (0,) * (n - len(b))
    return (pa > pb) - (pa < pb)


def _cmp_prerelease(a, b):
    """prerelease 비교: 정식(빈)>프리릴리스. 둘 다 프리릴리스면 식별자 사전식."""
    if not a and not b:
        return 0
    if not a:                # a=정식, b=프리릴리스 → a가 더 큼
        return 1
    if not b:
        return -1
    return (a > b) - (a < b)


def _cmp(a, b):
    """ParsedVersion 두 개를 비교 → -1(a<b)/0(a==b)/1(a>b). 순수 함수·부작용 0."""
    c = _cmp_release(a.release, b.release)
    if c != 0:
        return c
    return _cmp_prerelease(a.prerelease, b.prerelease)


def compare(local, remote):
    """(verdict, ev) 반환. fail-safe: 어느 쪽이라도 status≠ok → INCOMPARABLE."""
    pl, pr = parse(local), parse(remote)
    if pl.status != OK or pr.status != OK:
        return (INCOMPARABLE,
                "비교 불가(local status=%s · remote status=%s) — fail-safe 비행동"
                % (pl.status, pr.status))
    c = _cmp(pr, pl)  # remote vs local
    if c > 0:
        return (UPDATE_AVAILABLE, "remote %s > local %s (strictly-newer — 업데이트 후보)"
                % (pr.raw.strip(), pl.raw.strip()))
    if c == 0:
        return (UP_TO_DATE, "remote %s == local %s (최신)" % (pr.raw.strip(), pl.raw.strip()))
    return (MAIN_AHEAD, "local %s > remote %s (strictly-newer 거부 — 다운그레이드 유도)"
            % (pl.raw.strip(), pr.raw.strip()))


# ── gate: 로컬 파일 version 필드 추출 후 compare 위임 ──
def extract_version(path, field="version"):
    """Cargo.toml(`version = "x"`)·tauri.conf.json(`"version": "x"`) 단순 케이스만.
    추출 실패=None(호출자가 INCOMPARABLE 처리·fail-safe)."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    # TOML: ^field = "x"   /  JSON: "field": "x"  — 첫 매치만(멀티라인/주석 약함=fail-safe)
    fe = re.escape(field)
    m = re.search(r'(?m)^\s*%s\s*=\s*"([^"]+)"' % fe, text)
    if not m:
        m = re.search(r'"%s"\s*:\s*"([^"]+)"' % fe, text)
    return m.group(1) if m else None


def _verdict_exit(verdict):
    """verdict → 종료코드. UPDATE_AVAILABLE만 10(행동가능 advisory 신호)."""
    if verdict == UPDATE_AVAILABLE:
        return 10
    if verdict == INCOMPARABLE:
        return 2
    return 0  # UP_TO_DATE / MAIN_AHEAD = 비행동이 정답


def _emit(report, as_json):
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("verdict: %s — %s" % (report["verdict"], report["evidence"]))


def cmd_compare(local, remote, as_json):
    verdict, ev = compare(local, remote)
    report = {"verdict": verdict, "local": parse(local).to_dict(),
              "remote": parse(remote).to_dict(), "evidence": ev}
    _emit(report, as_json)
    return _verdict_exit(verdict)


def cmd_parse(s, as_json):
    pv = parse(s)
    if as_json:
        print(json.dumps(pv.to_dict(), ensure_ascii=False, indent=2))
    else:
        print("status: %s · release=%s · prerelease=%s"
              % (pv.status, pv.release, pv.prerelease))
    return 0 if pv.status == OK else 2


def cmd_gate(local_file, remote, field, as_json):
    local = extract_version(local_file, field)
    if local is None:
        report = {"verdict": INCOMPARABLE, "evidence":
                  "version 필드 추출 실패: %s (field=%s) — fail-safe 비행동" % (local_file, field)}
        _emit(report, as_json)
        return 2
    verdict, ev = compare(local, remote)
    report = {"verdict": verdict, "local": parse(local).to_dict(),
              "remote": parse(remote).to_dict(),
              "source": {"file": local_file, "field": field}, "evidence": ev}
    _emit(report, as_json)
    return _verdict_exit(verdict)


def self_test():
    """불변식 박제(PHIL-07 메타기법) — 반사·반대칭·전이·main-ahead 회귀를 결정론 검증."""
    failures = []

    def want(local, remote, expect):
        v, _ = compare(local, remote)
        if v != expect:
            failures.append("compare(%r,%r)=%s 기대=%s" % (local, remote, v, expect))

    # strictly
    want("0.2.7", "0.2.7", UP_TO_DATE)
    want("0.2.7", "0.2.8", UPDATE_AVAILABLE)
    want("0.2.7", "0.2.6", MAIN_AHEAD)
    # main-ahead 회귀 박제(AR 핵심 케이스 고정)
    want("1.0.0", "0.9.9", MAIN_AHEAD)
    # 0패딩
    want("1.0", "1.0.0", UP_TO_DATE)
    want("1.2", "1.2.1", UPDATE_AVAILABLE)
    # 프리릴리스(정식>프리릴리스)
    want("1.0.0", "1.0.0-rc1", MAIN_AHEAD)
    want("1.0.0-rc1", "1.0.0", UPDATE_AVAILABLE)
    want("1.0.0-rc1", "1.0.0-rc2", UPDATE_AVAILABLE)
    want("1.0.0-rc.2", "1.0.0-rc.1", MAIN_AHEAD)
    # build metadata 비교 무시(semver 규칙)
    want("1.0.0+build5", "1.0.0+build9", UP_TO_DATE)
    # 선행 v strip
    want("v0.2.7", "v0.2.8", UPDATE_AVAILABLE)
    # fail-safe
    want("", "1.0", INCOMPARABLE)
    want("main", "1.0", INCOMPARABLE)
    want("1.0", "garbage", INCOMPARABLE)
    want("1.0.x", "1.0.0", INCOMPARABLE)

    # 반사성: v !> v (어떤 v도 자기 자신엔 UP_TO_DATE)
    versions = ["0.0.1", "0.2.6", "0.2.7", "1.0.0", "1.0.0-rc1", "1.2.0", "0.42.4", "10.0.0"]
    for v in versions:
        if compare(v, v)[0] != UP_TO_DATE:
            failures.append("반사성 위반: compare(%r,%r)≠UP_TO_DATE" % (v, v))

    # 반대칭: a>b(MAIN_AHEAD) ⇒ b vs a 는 UPDATE_AVAILABLE (¬(b>a) 대칭)
    for i in range(len(versions)):
        for j in range(len(versions)):
            if i == j:
                continue
            vij = compare(versions[i], versions[j])[0]   # remote=j vs local=i
            vji = compare(versions[j], versions[i])[0]
            if vij == UPDATE_AVAILABLE and vji != MAIN_AHEAD:
                failures.append("반대칭 위반: %s↑%s 인데 역=%s" % (versions[j], versions[i], vji))
            if vij == MAIN_AHEAD and vji != UPDATE_AVAILABLE:
                failures.append("반대칭 위반: %s 거부인데 역=%s" % (versions[i], vji))

    # 전이성: a<b<c(release 정렬 순서) ⇒ a<c. 고정 오름차순 리스트로 결정론 검증(랜덤 0).
    asc = ["0.0.1", "0.2.6", "0.2.7", "1.0.0-rc1", "1.0.0", "1.2.0", "10.0.0"]
    for i in range(len(asc)):
        for k in range(i + 1, len(asc)):
            # remote(asc[k]) > local(asc[i]) 이어야 함
            if compare(asc[i], asc[k])[0] != UPDATE_AVAILABLE:
                failures.append("전이/정렬 위반: %s→%s 이 UPDATE_AVAILABLE 아님" % (asc[i], asc[k]))

    # exit-code 매핑 결정론
    if _verdict_exit(UPDATE_AVAILABLE) != 10:
        failures.append("exit 매핑: UPDATE_AVAILABLE≠10")
    if _verdict_exit(MAIN_AHEAD) != 0 or _verdict_exit(UP_TO_DATE) != 0:
        failures.append("exit 매핑: MAIN_AHEAD/UP_TO_DATE≠0")
    if _verdict_exit(INCOMPARABLE) != 2:
        failures.append("exit 매핑: INCOMPARABLE≠2")

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(
        description="strictly-newer 버전 비교 결정론 advisory (다운그레이드 유도 방지)")
    ap.add_argument("--self-test", action="store_true", help="결정론 자기검증")
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("compare", help="두 버전 비교 (0=UP_TO_DATE/MAIN_AHEAD 10=UPDATE 2=INCOMPARABLE)")
    c.add_argument("--local", required=True)
    c.add_argument("--remote", required=True)
    c.add_argument("--json", action="store_true")

    p = sub.add_parser("parse", help="버전 1건 파싱 상태 방출(디버그)")
    p.add_argument("version")
    p.add_argument("--json", action="store_true")

    g = sub.add_parser("gate", help="로컬 파일 version 필드 추출 후 compare 위임")
    g.add_argument("--local-file", required=True)
    g.add_argument("--remote", required=True)
    g.add_argument("--field", default="version")
    g.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.cmd == "compare":
        return cmd_compare(args.local, args.remote, args.json)
    if args.cmd == "parse":
        return cmd_parse(args.version, args.json)
    if args.cmd == "gate":
        return cmd_gate(args.local_file, args.remote, args.field, args.json)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
