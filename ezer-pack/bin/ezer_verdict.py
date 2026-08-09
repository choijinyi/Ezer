#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ezer_verdict — 리뷰어 verdict 스키마검증 + CHAI lint (4자수렴 게이트의 기계 검증부).

리뷰어(agy·codex·sub-agent)의 verdict JSON을 REVIEWER_VERDICT_CONTRACT §2 계약으로
**기계 검증**한다. 산문 신뢰·master 전사 대신, 계약 위반(점수 보유·근거 누락·enum 밖·
fix 없는 BLOCK)을 exit-code로 차단한다. `ezer_orchestra round-log --from-cmd`의 machine
평가자로 꽂으면, 한 라운드가 **미검증·점수보유 verdict로는 수렴 불가**가 된다.

핵심 불변식:
- **점수(score/grade/rating·0-100·0-1) 금지** — 어느 깊이든 발견 시 거부(REVIEWER_VERDICT_CONTRACT §1·§2).
- **verdict enum** = ACCEPT|REVISE|BLOCK|ESCALATE(+INVESTIGATE=CHAI R2 강등 타깃).
- **evidence[].ref 필수** — 근거 없는 YES는 검증이 아니다(§2 line33).
- **CHAI R2**: fix 없는 BLOCK/REVISE는 INVESTIGATE로 자동 강등(drive-by 부정 차단).
- 계약 정규 issues 형태 = {severity,where,what,fix}. 라이브 드리프트 {severity,ref,issue}는
  기본 거부 · `--lenient-issues`에서만 수용하되 fix 없으니 R2 발화(여전히 exit 1).

사용:
    python3 ezer_verdict.py validate <FILE> [--json] [--lenient-issues]
    python3 ezer_verdict.py --self-test          # 결정론 자기검증 (preflight C36)
종료 코드: 0 계약 준수+비차단 · 1 스키마 위반 또는 차단 CHAI lint · 2 인자/입출력/JSON 파싱 오류
의존성: 파이썬 표준 라이브러리만 (jsonschema 미사용·hand-roll·네트워크·LLM 없음·점수 미생성).
"""

import argparse
import contextlib
import io
import json
import os
import re
import sys

# ── 단일 머신 SOT (T6-P5) ──
# 리터럴(VERDICT_ENUM·SEVERITY·ISSUE_CONTRACT 등)을 schemas/verdict_schema.json 에서 런타임
# 로드한다 — 한 소스에서 파생해 doc↔CI 드리프트 0. 스키마 부재·손상 시 아래 인라인 폴백으로
# graceful degrade(네트워크·외부의존 0, 항상 동작). C51 이 "스키마 로드됨 + 스키마↔코드 정합"을
# 결정론 검증한다. INVESTIGATE 는 검증기 emit 전용(reviewer enum 4 + R2 강등 타깃 1)이다.
_INLINE = {
    "VERDICT_ENUM": ["ACCEPT", "REVISE", "BLOCK", "ESCALATE", "INVESTIGATE"],
    "SEVERITY_ENUM": ["blocking", "major", "minor"],
    "TOP_KEYS": ["verdict", "justification", "evidence", "issues", "missing"],
    "REQUIRED_TOP": ["verdict", "justification", "evidence", "issues"],
    "EVIDENCE_KEYS": ["claim", "ref", "verified"],
    "ISSUE_CONTRACT": ["severity", "where", "what", "fix"],
    "ISSUE_DRIFT": ["severity", "ref", "issue"],
}


def _schema_path():
    """schemas/verdict_schema.json 위치 — bin/ 의 형제 schemas/, 폴백으로 EZER_PACK_DIR."""
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(os.path.dirname(here), "schemas", "verdict_schema.json")
    if os.path.isfile(cand):
        return cand
    pd = os.environ.get("EZER_PACK_DIR") or os.environ.get("EZER_PACK_DIR")
    if pd:
        p = os.path.join(pd, "schemas", "verdict_schema.json")
        if os.path.isfile(p):
            return p
    return cand  # 부재여도 경로 반환(로더가 폴백)


SCHEMA_LOADED = False  # C51 이 검사: 스키마가 실제 로드됐는지(폴백이 아닌지)


def _load_consts():
    """스키마 로드(성공 시 SCHEMA_LOADED=True), 실패 시 인라인 폴백. 필수 키 누락도 폴백."""
    global SCHEMA_LOADED
    try:
        with open(_schema_path(), encoding="utf-8") as f:
            s = json.load(f)
        vals = {k: tuple(s[k]) for k in _INLINE}  # 모든 키 존재 필수 — 누락 시 KeyError→폴백
        SCHEMA_LOADED = True
        return vals
    except (OSError, ValueError, KeyError, TypeError):
        SCHEMA_LOADED = False
        return {k: tuple(v) for k, v in _INLINE.items()}


_C = _load_consts()
VERDICT_ENUM = _C["VERDICT_ENUM"]
SEVERITY_ENUM = _C["SEVERITY_ENUM"]
TOP_KEYS = _C["TOP_KEYS"]
REQUIRED_TOP = _C["REQUIRED_TOP"]
EVIDENCE_KEYS = _C["EVIDENCE_KEYS"]
ISSUE_CONTRACT = _C["ISSUE_CONTRACT"]
ISSUE_DRIFT = _C["ISSUE_DRIFT"]
SCORE_KEY_RE = re.compile(r"score|grade|rating", re.I)


def assert_no_score(obj, path="$"):
    """재귀: score/grade/rating 키 또는 그 아래 숫자(0-100·0-1)를 모두 거부.
    additionalProperties:false가 닿지 못하는 중첩 free-form까지 막는 §1 핵심."""
    errs = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = "%s.%s" % (path, k)
            if SCORE_KEY_RE.search(str(k)):
                errs.append("금지된 점수류 키 %r (%s) — score 채널은 reward-hack(§1)" % (k, kp))
            errs += assert_no_score(v, kp)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            errs += assert_no_score(v, "%s[%d]" % (path, i))
    return errs


def validate_verdict(obj, lenient=False):
    """순수 CHECK — (schema_errors, lint, verdict_out) 반환. COMMAND와 분리(house style)."""
    schema_errors = []
    lint = []
    if not isinstance(obj, dict):
        return (["최상위가 객체(dict)가 아님"], [], None)

    # §1 점수 금지 (재귀)
    schema_errors += assert_no_score(obj)

    # additionalProperties:false (최상위) — 미지 키 거부(score 키도 여기서 1차 차단)
    for k in obj:
        if k not in TOP_KEYS:
            schema_errors.append("미지 최상위 키 %r — 계약 키는 %s" % (k, "|".join(TOP_KEYS)))

    # 필수 키
    for k in REQUIRED_TOP:
        if k not in obj:
            schema_errors.append("필수 키 누락: %s" % k)

    # verdict enum
    verdict = obj.get("verdict")
    if verdict not in VERDICT_ENUM:
        schema_errors.append("verdict 무효(%r) — %s 중 하나" % (verdict, "|".join(VERDICT_ENUM)))

    # justification
    if "justification" in obj and not str(obj.get("justification") or "").strip():
        schema_errors.append("justification 비어 있음")

    # evidence[] — 각 항목 claim/ref/verified, ref 필수(R1)
    ev = obj.get("evidence")
    if "evidence" in obj:
        if not isinstance(ev, list):
            schema_errors.append("evidence는 배열이어야 함")
        else:
            for i, e in enumerate(ev):
                if not isinstance(e, dict):
                    schema_errors.append("evidence[%d] 객체 아님" % i)
                    continue
                for ek in e:
                    if ek not in EVIDENCE_KEYS:
                        schema_errors.append("evidence[%d] 미지 키 %r" % (i, ek))
                if not str(e.get("ref") or "").strip():
                    schema_errors.append("evidence[%d].ref 누락 — 근거 없는 주장(§2 line33)" % i)

    # issues[] — 계약 형태 {severity,where,what,fix} 강제. 드리프트는 lenient에서만.
    issues = obj.get("issues")
    issue_shapes = []  # (has_fix) per issue
    if "issues" in obj:
        if not isinstance(issues, list):
            schema_errors.append("issues는 배열이어야 함")
        else:
            for i, it in enumerate(issues):
                if not isinstance(it, dict):
                    schema_errors.append("issues[%d] 객체 아님" % i)
                    issue_shapes.append(False)
                    continue
                keys = set(it)
                sev = it.get("severity")
                if sev not in SEVERITY_ENUM:
                    schema_errors.append("issues[%d].severity 무효(%r) — %s"
                                         % (i, sev, "|".join(SEVERITY_ENUM)))
                is_contract = keys <= set(ISSUE_CONTRACT) and {"where", "what"} <= keys
                is_drift = keys <= set(ISSUE_DRIFT) and {"ref", "issue"} <= keys
                if is_contract:
                    issue_shapes.append(bool(str(it.get("fix") or "").strip()))
                elif is_drift:
                    if not lenient:
                        schema_errors.append(
                            "issues[%d] 드리프트 형태{severity,ref,issue} — 계약은 "
                            "{severity,where,what,fix}. --lenient-issues 필요(fix 없어 R2 발화)" % i)
                    issue_shapes.append(False)  # 드리프트엔 fix 없음
                else:
                    schema_errors.append("issues[%d] 형태 불명 %s — 계약 {severity,where,what,fix}"
                                         % (i, sorted(keys)))
                    issue_shapes.append(False)

    # CHAI R2: fix 없는 BLOCK/REVISE → INVESTIGATE 강등(drive-by 부정 차단)
    verdict_out = verdict
    if verdict in ("BLOCK", "REVISE"):
        actionable = any(issue_shapes) if issue_shapes else False
        if not actionable:
            lint.append("R2: 실행가능 fix 없는 %s — INVESTIGATE로 강등(맥킨지급 비평은 교정안 동반)"
                        % verdict)
            verdict_out = "INVESTIGATE"

    return schema_errors, lint, verdict_out


def cmd_validate(path, lenient, as_json):
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except FileNotFoundError:
        return fail(2, "파일 없음: %s" % path)
    except (OSError, json.JSONDecodeError) as e:
        return fail(2, "JSON 로드 실패: %s (%s)" % (path, e))

    schema_errors, lint, verdict_out = validate_verdict(obj, lenient)
    ok = not schema_errors and not lint
    report = {"ok": ok, "file": path,
              "schema_errors": schema_errors, "lint": lint,
              "verdict_in": obj.get("verdict"), "verdict_out": verdict_out}
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for e in schema_errors:
            print("[SCHEMA] %s" % e)
        for l in lint:
            print("[CHAI]   %s" % l)
        print("verdict: %s — %s%s"
              % ("OK" if ok else "REJECT",
                 obj.get("verdict"),
                 ("" if verdict_out == obj.get("verdict") else " → %s(강등)" % verdict_out)))
        if not ok:
            print("이 출력 외의 추론으로 verdict 정합·수렴을 선언하지 마라.")
    return 0 if ok else 1


def fail(code, msg):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    return code


def _v(verdict="ACCEPT", justification="근거 충분", evidence=None, issues=None, missing=None, **extra):
    d = {"verdict": verdict, "justification": justification,
         "evidence": evidence if evidence is not None else [{"claim": "c", "ref": "f.py:1", "verified": True}],
         "issues": issues if issues is not None else [],
         "missing": missing if missing is not None else []}
    d.update(extra)
    return d


def self_test():
    """in-memory 가공 verdict 배터리 — 각 위반이 잡히는지·정상이 통과하는지."""
    failures = []

    def check(name, obj, want_ok=None, want_schema_substr=None, want_verdict_out=None, lenient=False):
        se, lint, vo = validate_verdict(obj, lenient)
        ok = not se and not lint
        if want_ok is not None and ok != want_ok:
            failures.append("%s: ok=%s 기대=%s (errors=%s lint=%s)" % (name, ok, want_ok, se, lint))
        if want_schema_substr and not any(want_schema_substr in e for e in se):
            failures.append("%s: 스키마오류에 %r 없음 — %s" % (name, want_schema_substr, se))
        if want_verdict_out and vo != want_verdict_out:
            failures.append("%s: verdict_out=%s 기대=%s" % (name, vo, want_verdict_out))

    # 정상(계약 형태) → 통과
    check("happy", _v(), want_ok=True, want_verdict_out="ACCEPT")
    # 점수 금지: 최상위 score
    check("score-top", _v(score=87), want_ok=False, want_schema_substr="점수류 키")
    # 점수 금지: 중첩 score(재귀)
    check("score-nested", _v(evidence=[{"claim": "c", "ref": "r", "verified": True, "score": 9}]),
          want_ok=False, want_schema_substr="점수류 키")
    # verdict enum 밖
    check("bad-verdict", _v(verdict="PASS"), want_ok=False, want_schema_substr="verdict 무효")
    # evidence.ref 누락
    check("no-ref", _v(evidence=[{"claim": "c", "verified": True}]),
          want_ok=False, want_schema_substr="ref 누락")
    # 드리프트 issues 기본 거부
    drift = _v(verdict="BLOCK", issues=[{"severity": "blocking", "ref": "f:1", "issue": "x"}])
    check("drift-strict", drift, want_ok=False, want_schema_substr="드리프트 형태")
    # 드리프트 lenient 수용하되 fix 없어 R2 → INVESTIGATE
    check("drift-lenient-r2", drift, want_ok=False, want_verdict_out="INVESTIGATE", lenient=True)
    # CHAI R2: fix 없는 BLOCK → INVESTIGATE 강등
    check("r2-blocknofix", _v(verdict="BLOCK", issues=[{"severity": "blocking", "where": "f:1",
          "what": "결함", "fix": ""}]), want_ok=False, want_verdict_out="INVESTIGATE")
    # R2 미발화: fix 있는 BLOCK은 강등 안 됨(스키마는 통과·lint 없음)
    check("block-withfix", _v(verdict="BLOCK", issues=[{"severity": "blocking", "where": "f:1",
          "what": "결함", "fix": "이렇게 고쳐라"}]), want_ok=True, want_verdict_out="BLOCK")
    # 필수 키 누락
    check("missing-key", {"verdict": "ACCEPT"}, want_ok=False, want_schema_substr="필수 키 누락")
    # severity enum
    check("bad-sev", _v(verdict="REVISE", issues=[{"severity": "huge", "where": "w", "what": "x", "fix": "y"}]),
          want_ok=False, want_schema_substr="severity 무효")

    # cmd_validate 라운드트립(파일 경유)·exit code — 내부 출력 격리
    import tempfile
    import os as _os
    sink = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="ezer-verdict-st-") as td:
        good = _os.path.join(td, "good.json")
        open(good, "w", encoding="utf-8").write(json.dumps(_v()))
        with contextlib.redirect_stdout(sink):
            if cmd_validate(good, False, True) != 0:
                failures.append("정상 verdict 파일이 exit 0 아님")
        bad = _os.path.join(td, "bad.json")
        open(bad, "w", encoding="utf-8").write(json.dumps(_v(score=99)))
        with contextlib.redirect_stdout(sink):
            if cmd_validate(bad, False, True) != 1:
                failures.append("점수보유 verdict 파일이 exit 1 아님")
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_validate(_os.path.join(td, "nope.json"), False, True) != 2:
                failures.append("없는 파일이 exit 2 아님")
        notjson = _os.path.join(td, "x.json")
        open(notjson, "w").write("not json")
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_validate(notjson, False, True) != 2:
                failures.append("비-JSON이 exit 2 아님")

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="리뷰어 verdict 스키마검증 + CHAI lint")
    ap.add_argument("--self-test", action="store_true", help="결정론 자기검증")
    sub = ap.add_subparsers(dest="cmd")
    v = sub.add_parser("validate", help="verdict JSON 1건 계약 검증 (0=준수 1=위반 2=입출력오류)")
    v.add_argument("file")
    v.add_argument("--lenient-issues", action="store_true",
                   help="드리프트 issues{severity,ref,issue} 수용(단 fix 없어 R2 발화)")
    v.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.cmd == "validate":
        return cmd_validate(args.file, args.lenient_issues, args.json)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
