#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ezer_manifest — 타입드 워크플로우 매니페스트(workflow.json) 기계 검증 + 단계 계약 해소.

산문 워크플로우 선택·단계 성공기준을 타입드 JSON 계약으로 기계검증한다. 단계의
success_criteria가 task-prompt/review-prompt의 --success 문자열이 되고, autopilot
axis-1(gate-status)이 success_criteria **기계통과**(check-criteria exit 0) 시에만 전진한다.
producer≠evaluator 하드절: success_criteria는 **콘텐츠 속성**(citation_present/min_sources 등)
만이며 file_exists kind가 없다 — 산출물 존재가 아니라 산출물 내용을 강제한다.
**check-criteria는 4자수렴의 기계 FLOOR다 — 필요조건이지 충분조건 아님**(agy·codex·master 독립
재유도가 함께 판정). 빈약·게임 산출물(2바이트 등)은 차단하지만 키워드 스푸핑을 완벽 방어하진
않는다 — 단독 machine PASS를 과신 말 것.

핵심 불변식:
- 점수·비용(score/grade/rating/usd/cost/budget_usd/price) 키 금지 — 어느 깊이든 거부.
  (값 기반이 아니라 키 기반 — budget_minutes·max_revisions·min_sources 등 정당한 정수 보존)
- check.kind = closed enum(citation_present/contradiction_flagged/min_sources/section_present/
  no_unsupported_claims/json_valid/field_present/min_items) — **file_exists 없음**(구조적으로 콘텐츠 강제).
  (field_present=필드 존재(비어있지 않음)·min_items=*비어있지 않은* 항목 수 — *구조* floor일 뿐
   내용 품질 보증 아님; json_valid는 파싱만(필드/항목 요구 없음). machine PASS는 필요조건이지 충분조건 아님.)
- phase.id = kebab-case · max_revisions ≤ 10(MAX_ROUNDS) · success_criteria.checks ≥ 1.

사용:
    python3 ezer_manifest.py validate <FILE> [--json]
    python3 ezer_manifest.py phase <FILE> --phase <id> [--json]   # 단계 계약 해소(success·리뷰포커스)
    python3 ezer_manifest.py resolve <FOLDER> [--json]            # 폴더에서 매니페스트 탐색·검증
    python3 ezer_manifest.py check-criteria <FILE> --phase <id> --artifact <PATH> [--json]
    python3 ezer_manifest.py --self-test     # 결정론 자기검증 (preflight C40)
종료 코드: 0 준수/통과(수렴) · 1 validate 스키마 위반 또는 check-criteria 기준 미달 ·
          2 인자/입출력/JSON 오류 또는 phase·check-criteria의 입력 매니페스트 무효 ·
          4 매니페스트 없음(resolve — README 폴백 신호)
의존성: 파이썬 표준 라이브러리만 (jsonschema 미사용·hand-roll·네트워크·LLM 없음·점수 미생성).
"""

import argparse
import contextlib
import io
import json
import os
import re
import sys

TOP_KEYS = ("name", "version", "description", "phases")
REQUIRED_TOP = ("name", "phases")
PHASE_KEYS = ("id", "skill", "requires", "produces", "success_criteria",
              "review_focus", "human_approval_default", "max_revisions", "budget_minutes")
REQUIRED_PHASE = ("id", "skill", "success_criteria")
SC_KEYS = ("statement", "checks")
CHECK_KEYS = ("kind", "value", "statement")
CHECK_KINDS = ("citation_present", "contradiction_flagged", "min_sources",
               "section_present", "no_unsupported_claims", "json_valid",
               "field_present", "min_items")
KINDS_NEED_VALUE = ("min_sources", "section_present", "field_present", "min_items")  # value 필수 kind
# JSON 콘텐츠 kind — artifact를 JSON 파싱 후 필드/항목 검사. thin 가드(MIN_ARTIFACT_CHARS) 면제:
# 작은 valid JSON도 정당하므로 글자수 floor 미적용. 단 이는 *구조* floor일 뿐 내용 품질 보증 아님 —
# json_valid는 파싱만(필드/항목 요구 없음·'{}'·'[]'도 통과), field_present는 필드 존재, min_items는
# 비어있지 않은 항목 수만 본다([null]·[{}] 자리채움은 거르나 [1,1] 스칼라 채움은 못 막음). 의미
# 판정은 agy·codex·master 독립 재유도가 함께 — 단독 machine PASS 과신 말 것.
JSON_KINDS = ("json_valid", "field_present", "min_items")
MAX_REVISIONS_CAP = 10  # MAX_ROUNDS (앵커4 5-8)
MIN_ARTIFACT_CHARS = 40  # check-criteria 게임 방지 — 콘텐츠 checks는 이 미만 산출물에선 미통과(JSON_KINDS 제외)
# 점수·비용 채널 금지(reward-hack·Max전용 — $필드 금지). 값이 아니라 키 이름으로 차단하되,
# snake_case/camelCase 세그먼트 경계로 한정 — total_usd·cost는 잡고 accost·scoreboard·
# budget_minutes·max_revisions 같은 정당한 키는 살린다(닫힌 enum이 1차 게이트·이건 중첩 free-form 방어).
BANNED_KEY_RE = re.compile(r"(?<![a-z])(score|grade|rating|usd|cost|price)(?![a-z])", re.I)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _is_int(x):
    """진짜 정수만 — bool은 거부(isinstance(True, int)가 True인 파이썬 함정 차단)."""
    return isinstance(x, int) and not isinstance(x, bool)

MANIFEST_NAMES = ("workflow.json", "manifest.json")


def assert_no_cost(obj, path="$"):
    """재귀: score/grade/rating/usd/cost/budget_usd/price 키를 모든 깊이에서 거부.
    additionalProperties:false가 닿지 못하는 중첩 free-form까지 막는 무점수·Max전용 핵심."""
    errs = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = "%s.%s" % (path, k)
            if BANNED_KEY_RE.search(str(k)):
                errs.append("금지된 점수·비용 키 %r (%s) — score/$ 채널 금지(reward-hack·Max전용)" % (k, kp))
            errs += assert_no_cost(v, kp)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            errs += assert_no_cost(v, "%s[%d]" % (path, i))
    return errs


def _validate_check(chk, where):
    """단일 check 객체 검증 → 오류 리스트."""
    errs = []
    if not isinstance(chk, dict):
        return ["%s check 객체 아님" % where]
    for k in chk:
        if k not in CHECK_KEYS:
            errs.append("%s 미지 키 %r — check 키는 %s" % (where, k, "|".join(CHECK_KEYS)))
    kind = chk.get("kind")
    if kind not in CHECK_KINDS:
        errs.append("%s kind 무효(%r) — %s (file_exists 부재: 콘텐츠만)"
                    % (where, kind, "|".join(CHECK_KINDS)))
    if kind in KINDS_NEED_VALUE and "value" not in chk:
        errs.append("%s kind=%s 는 value 필수" % (where, kind))
    if kind == "min_sources" and "value" in chk and not _is_int(chk.get("value")):
        errs.append("%s min_sources.value 정수 아님(%r)" % (where, chk.get("value")))
    if kind == "field_present" and "value" in chk:
        fv = chk.get("value")
        if not (isinstance(fv, str) and fv.strip()):
            errs.append("%s field_present.value 비어있지 않은 문자열 필요(JSON 필드 경로, 점 표기)" % where)
    if kind == "min_items" and "value" in chk:
        mv = chk.get("value")
        if not isinstance(mv, dict):
            errs.append("%s min_items.value 객체 필요({field, min})" % where)
        else:
            for k in mv:
                if k not in ("field", "min"):
                    errs.append("%s min_items.value 미지 키 %r — field|min" % (where, k))
            if not (isinstance(mv.get("field"), str) and mv.get("field").strip()):
                errs.append("%s min_items.value.field 비어있지 않은 문자열 필요" % where)
            if not _is_int(mv.get("min")) or mv.get("min") < 1:
                errs.append("%s min_items.value.min 양의 정수 필요(%r)" % (where, mv.get("min")))
    return errs


def validate_manifest(obj):
    """순수 CHECK — schema_errors 리스트 반환(COMMAND와 분리·house style)."""
    errs = []
    if not isinstance(obj, dict):
        return ["최상위가 객체(dict)가 아님"]
    errs += assert_no_cost(obj)
    for k in obj:
        if k not in TOP_KEYS:
            errs.append("미지 최상위 키 %r — 계약 키는 %s" % (k, "|".join(TOP_KEYS)))
    for k in REQUIRED_TOP:
        if k not in obj:
            errs.append("필수 키 누락: %s" % k)
    if "name" in obj and not str(obj.get("name") or "").strip():
        errs.append("name 비어 있음")
    phases = obj.get("phases")
    if "phases" in obj:
        if not isinstance(phases, list) or not phases:
            errs.append("phases는 비어있지 않은 배열이어야 함")
        else:
            seen_ids = set()
            for i, ph in enumerate(phases):
                w = "phases[%d]" % i
                if not isinstance(ph, dict):
                    errs.append("%s 객체 아님" % w)
                    continue
                for k in ph:
                    if k not in PHASE_KEYS:
                        errs.append("%s 미지 키 %r — phase 키는 %s" % (w, k, "|".join(PHASE_KEYS)))
                for k in REQUIRED_PHASE:
                    if k not in ph:
                        errs.append("%s 필수 키 누락: %s" % (w, k))
                pid = ph.get("id")
                if pid is not None:
                    if not isinstance(pid, str) or not ID_RE.match(pid):
                        errs.append("%s id 무효(%r) — kebab-case(a-z0-9-)" % (w, pid))
                    elif pid in seen_ids:
                        errs.append("%s id 중복: %s" % (w, pid))
                    else:
                        seen_ids.add(pid)
                for lk in ("requires", "produces", "review_focus"):
                    if lk in ph and not isinstance(ph.get(lk), list):
                        errs.append("%s.%s 는 배열이어야 함" % (w, lk))
                if "human_approval_default" in ph and not isinstance(ph.get("human_approval_default"), bool):
                    errs.append("%s.human_approval_default 는 bool" % w)
                mr = ph.get("max_revisions")
                if mr is not None:
                    if not _is_int(mr) or mr < 1 or mr > MAX_REVISIONS_CAP:
                        errs.append("%s.max_revisions 무효(%r) — 1..%d(MAX_ROUNDS)" % (w, mr, MAX_REVISIONS_CAP))
                bm = ph.get("budget_minutes")
                if bm is not None and (not _is_int(bm) or bm < 1):
                    errs.append("%s.budget_minutes 무효(%r) — 양의 정수(분)" % (w, bm))
                sc = ph.get("success_criteria")
                if "success_criteria" in ph:
                    if not isinstance(sc, dict):
                        errs.append("%s.success_criteria 객체 아님" % w)
                    else:
                        for k in sc:
                            if k not in SC_KEYS:
                                errs.append("%s.success_criteria 미지 키 %r — %s" % (w, k, "|".join(SC_KEYS)))
                        if not str(sc.get("statement") or "").strip():
                            errs.append("%s.success_criteria.statement 비어 있음" % w)
                        checks = sc.get("checks")
                        if not isinstance(checks, list) or not checks:
                            errs.append("%s.success_criteria.checks ≥1 필요(기계검증 대상)" % w)
                        else:
                            for j, chk in enumerate(checks):
                                errs += _validate_check(chk, "%s.checks[%d]" % (w, j))
    return errs


# ── check-criteria: 콘텐츠 속성 평가(file_exists 없음 — 산출물 *내용*만 검사) ──
_CITATION_RE = re.compile(r"https?://|\[\d+\]|\b[\w./-]+\.[A-Za-z]{1,5}:\d+|출처[:：]|참고문헌|\bsources?[:：]", re.I)
# 대립/모순은 *플래깅 구문*만 인정 — 한글 명사+서술 stem 또는 영어 동사·형용사형.
# 'no conflict found'(bare conflict)·맨 '모순' 토큰은 통과 못 함(키워드 스푸핑 차단).
_CONTRA_RE = re.compile(
    r"(모순|대립|상충|불일치|반증)[^\n]{0,6}"
    r"(한다|한|함|하며|하여|된다|됨|되어|이다|있다|있음|발견|표기|명시|확인|규명|드러)|"
    r"contradict|inconsisten(t|cy|cies)|conflicting\s+\w+|sources?\s+disagree", re.I)
# 미지원 마커 — 영어는 단어 경계로 한정(todoist·mentodo 오탐 차단). 한글 구는 그대로.
_UNSUPPORTED_RE = re.compile(
    r"\bTODO\b|확인\s*필요|출처\s*미상|근거\s*없음|\bunsupported\b|citation needed|\[citation", re.I)
_URL_RE = re.compile(r"https?://[^\s)\]]+")
_FOOTNOTE_RE = re.compile(r"\[\d+\]")  # min_sources 카운트용 — 번호 각주만(가짜 file:line 토큰 제외)


def _resolve_path(obj, dotted):
    """점 표기 경로로 dict 탐색 → (found, value). 어느 세그먼트라도 없으면 (False, None)."""
    cur = obj
    for seg in dotted.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return False, None
    return True, cur


def _nonempty(v):
    """field_present 의미의 '비어있지 않음' — null/빈문자열/빈리스트/빈딕트는 부재로 간주.
    스칼라(숫자 0·bool false 포함)는 존재(콘텐츠 있음·값 타당성은 min_items 등 별도 kind 소관)."""
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def _reject_const(c):
    raise ValueError("비표준 JSON 상수: %s" % c)


def _parse_json(text):
    """artifact 텍스트를 표준 JSON으로 파싱 → (obj, ok). 선두 BOM 허용(BOM emit 도구의 정당
    산출물 오탐 차단)·NaN/Infinity 거부(표준 JSON 강제 — json.loads 기본 확장 차단)."""
    try:
        return json.loads(text.lstrip("\ufeff"), parse_constant=_reject_const), True
    except Exception:
        return None, False


def eval_check(chk, text):
    """단일 check를 artifact 텍스트에 대해 결정론 평가 → (passed, detail)."""
    kind = chk.get("kind")
    if kind == "json_valid":
        _, ok = _parse_json(text)
        return ok, "json_valid: %s" % ("파싱 성공" if ok else "파싱 실패(표준 JSON 아님)")
    if kind == "citation_present":
        n = len(_CITATION_RE.findall(text))
        return n >= 1, "citation_present: 인용 마커 %d개" % n
    if kind == "contradiction_flagged":
        ok = bool(_CONTRA_RE.search(text))
        return ok, "contradiction_flagged: %s" % ("대립/모순 표기 발견" if ok else "표기 없음")
    if kind == "min_sources":
        need = chk.get("value")
        need = need if _is_int(need) else 1
        # 진짜 출처만 — 고유 URL + 고유 번호 각주([n]). 가짜 file:line 토큰은 제외(게임 차단).
        got = len(set(_URL_RE.findall(text))) + len(set(_FOOTNOTE_RE.findall(text)))
        return got >= need, "min_sources: 고유 출처 %d / 요구 %d" % (got, need)
    if kind == "section_present":
        name = str(chk.get("value") or "")
        # CommonMark 헤딩(선행 공백 ≤3·# 뒤 공백 필수)의 제목에 이름이 등장해야 한다.
        ok = bool(re.search(r"(?mi)^ {0,3}#{1,6}\s+.*" + re.escape(name), text)) if name else False
        return ok, "section_present(%s): %s" % (name, "섹션 발견" if ok else "섹션 없음")
    if kind == "no_unsupported_claims":
        m = _UNSUPPORTED_RE.search(text)
        if m is not None:
            return False, "no_unsupported_claims: '%s' 발견" % m.group(0)
        # 마커 부재만으로는 부족 — 실제 지지(인용)가 있어야 '미지원 없음' 인정(공백 통과 차단).
        has_cite = bool(_CITATION_RE.search(text))
        return has_cite, ("no_unsupported_claims: 미지원 마커 없음·출처 동반" if has_cite
                          else "no_unsupported_claims: 지지 출처 없음(미지원 주장으로 간주)")
    if kind == "field_present":
        field = str(chk.get("value") or "")
        data, ok = _parse_json(text)
        if not ok:
            return False, "field_present(%s): artifact가 JSON 아님" % field
        found, val = _resolve_path(data, field)
        if not found:
            return False, "field_present(%s): 필드 없음" % field
        present = _nonempty(val)
        return present, "field_present(%s): %s" % (field, "존재·비어있지 않음" if present else "필드 비어 있음")
    if kind == "min_items":
        spec = chk.get("value") if isinstance(chk.get("value"), dict) else {}
        field = str(spec.get("field") or "")
        need = spec.get("min")
        need = need if _is_int(need) else 1
        data, ok = _parse_json(text)
        if not ok:
            return False, "min_items(%s): artifact가 JSON 아님" % field
        found, val = _resolve_path(data, field)
        if not found:
            return False, "min_items(%s): 필드 없음" % field
        if not isinstance(val, list):
            return False, "min_items(%s): 리스트 아님(%s)" % (field, type(val).__name__)
        # 비어있지 않은 항목만 카운트 — null/빈객체/빈문자열/빈리스트 자리채움 차단(구조 floor·내용 품질 보증 아님).
        got = sum(1 for it in val if _nonempty(it))
        return got >= need, "min_items(%s): 비어있지 않은 항목 %d / 요구 %d" % (field, got, need)
    return False, "알 수 없는 kind: %r" % kind


def find_phase(obj, phase_id):
    for ph in (obj.get("phases") or []):
        if isinstance(ph, dict) and ph.get("id") == phase_id:
            return ph
    return None


def _load_json(path):
    """(obj, err_code, err_msg) — 성공 시 (obj, None, None)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None, None
    except FileNotFoundError:
        return None, 2, "파일 없음: %s" % path
    except (OSError, json.JSONDecodeError) as e:
        return None, 2, "JSON 로드 실패: %s (%s)" % (path, e)


def fail(code, msg):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    return code


def cmd_validate(path, as_json):
    obj, ec, em = _load_json(path)
    if ec:
        return fail(ec, em)
    errs = validate_manifest(obj)
    ok = not errs
    if as_json:
        print(json.dumps({"ok": ok, "file": path, "schema_errors": errs},
                         ensure_ascii=False, indent=2))
    else:
        for e in errs:
            print("[SCHEMA] %s" % e)
        print("manifest: %s — %s (phase %d)"
              % ("OK" if ok else "REJECT", path,
                 len(obj.get("phases", [])) if isinstance(obj, dict) else 0))
        if not ok:
            print("이 출력 외의 추론으로 매니페스트 정합을 선언하지 마라.")
    return 0 if ok else 1


def cmd_phase(path, phase_id, as_json):
    """단계 계약 해소 — success_criteria.statement(→--success)·review_focus·human_approval."""
    obj, ec, em = _load_json(path)
    if ec:
        return fail(ec, em)
    errs = validate_manifest(obj)
    if errs:
        return fail(2, "매니페스트 스키마 위반 %d건(입력 오류) — validate로 확인" % len(errs))
    ph = find_phase(obj, phase_id)
    if ph is None:
        return fail(2, "phase 없음: %s (있는 id: %s)"
                    % (phase_id, ", ".join(p.get("id", "?") for p in obj.get("phases", []))))
    sc = ph.get("success_criteria", {})
    out = {"id": ph.get("id"), "skill": ph.get("skill"),
           "success": sc.get("statement", ""),
           "checks": [c.get("kind") for c in sc.get("checks", [])],
           "review_focus": ph.get("review_focus", []),
           "human_approval_default": ph.get("human_approval_default", False),
           "max_revisions": ph.get("max_revisions", MAX_REVISIONS_CAP)}
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("phase: %s (skill: %s)" % (out["id"], out["skill"]))
        print("success(--success 투입): %s" % out["success"])
        print("기계검증 checks: %s" % ", ".join(out["checks"]))
        if out["review_focus"]:
            print("review_focus(리뷰어 초점): %s" % ", ".join(out["review_focus"]))
        print("human_approval_default: %s · max_revisions: %s"
              % (out["human_approval_default"], out["max_revisions"]))
    return 0


def cmd_resolve(folder, as_json):
    """폴더에서 매니페스트 탐색·검증. 없으면 exit 4(README 폴백 신호)."""
    found = None
    for nm in MANIFEST_NAMES:
        p = os.path.join(folder, nm)
        if os.path.isfile(p):
            found = p
            break
    if found is None:
        if as_json:
            print(json.dumps({"ok": False, "manifest": None, "folder": folder,
                              "fallback": "README"}, ensure_ascii=False, indent=2))
        else:
            print("[resolve] 매니페스트 없음: %s — README 디스패치로 폴백(exit 4)" % folder,
                  file=sys.stderr)
        return 4
    obj, ec, em = _load_json(found)
    if ec:
        return fail(ec, em)
    errs = validate_manifest(obj)
    ok = not errs
    if as_json:
        print(json.dumps({"ok": ok, "manifest": found,
                          "name": obj.get("name") if isinstance(obj, dict) else None,
                          "phases": [p.get("id") for p in obj.get("phases", [])] if ok else [],
                          "schema_errors": errs}, ensure_ascii=False, indent=2))
    else:
        if ok:
            print("[resolve] %s — %s · phases: %s"
                  % (found, obj.get("name"), ", ".join(p.get("id", "?") for p in obj.get("phases", []))))
        else:
            for e in errs:
                print("[SCHEMA] %s" % e)
            print("[resolve] %s 스키마 위반 %d건" % (found, len(errs)))
    return 0 if ok else 1


def cmd_check_criteria(path, phase_id, artifact, as_json):
    """단계 success_criteria의 checks를 artifact 콘텐츠에 대해 기계평가.
    autopilot machine 슬롯: 전부 통과 시 exit 0(=수렴), 하나라도 미달 시 exit 1."""
    obj, ec, em = _load_json(path)
    if ec:
        return fail(ec, em)
    errs = validate_manifest(obj)
    if errs:
        return fail(2, "매니페스트 스키마 위반 %d건(입력 오류) — validate로 확인" % len(errs))
    ph = find_phase(obj, phase_id)
    if ph is None:
        return fail(2, "phase 없음: %s" % phase_id)
    try:
        with open(artifact, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return fail(2, "artifact 읽기 실패: %s (%s)" % (artifact, e))
    checks = ph.get("success_criteria", {}).get("checks", [])
    thin = len(re.sub(r"\s+", "", text)) < MIN_ARTIFACT_CHARS  # 빈약 산출물의 게임 PASS 차단
    results = []
    for chk in checks:
        kind = chk.get("kind")
        if thin and kind not in JSON_KINDS:
            results.append((kind, False, "%s: artifact 내용 부족(<%d자) — 게임 방지" % (kind, MIN_ARTIFACT_CHARS)))
        else:
            results.append((kind, *eval_check(chk, text)))
    all_pass = all(passed for _, passed, _ in results)
    if as_json:
        print(json.dumps({"ok": all_pass, "phase": phase_id, "artifact": artifact,
                          "results": [{"kind": k, "passed": p, "detail": d} for k, p, d in results]},
                         ensure_ascii=False, indent=2))
    else:
        for k, p, d in results:
            print("  [%s] %s" % ("PASS" if p else "FAIL", d))
        print("check-criteria: %s — phase %s (%d/%d 통과)"
              % ("PASS(수렴)" if all_pass else "FAIL(미달)", phase_id,
                 sum(1 for _, p, _ in results if p), len(results)))
    return 0 if all_pass else 1


# ── self-test ──
def _phase(pid="gather", skill="deep-research", checks=None, **extra):
    p = {"id": pid, "skill": skill,
         "success_criteria": {"statement": "충분한 출처 확보",
                              "checks": checks if checks is not None else [{"kind": "min_sources", "value": 3}]}}
    p.update(extra)
    return p


def _manifest(phases=None, **extra):
    m = {"name": "test-wf", "phases": phases if phases is not None else [_phase()]}
    m.update(extra)
    return m


def self_test():
    failures = []

    def chk(name, obj, want_ok=None, want_substr=None):
        errs = validate_manifest(obj)
        ok = not errs
        if want_ok is not None and ok != want_ok:
            failures.append("%s: ok=%s 기대=%s (errs=%s)" % (name, ok, want_ok, errs))
        if want_substr and not any(want_substr in e for e in errs):
            failures.append("%s: 오류에 %r 없음 — %s" % (name, want_substr, errs))

    # 정상
    chk("happy", _manifest(), want_ok=True)
    # 비용·점수 키 금지(재귀)
    chk("score-top", _manifest(score=9), want_ok=False, want_substr="점수·비용 키")
    chk("usd-nested", _manifest(phases=[_phase(budget_usd=5)]), want_ok=False, want_substr="점수·비용 키")
    chk("cost-deep", _manifest(phases=[_phase(checks=[{"kind": "min_sources", "value": 3, "cost": 1}])]),
        want_ok=False, want_substr="점수·비용 키")
    # 정당한 정수는 보존(budget_minutes·max_revisions·min_sources)
    chk("legit-ints", _manifest(phases=[_phase(budget_minutes=30, max_revisions=5)]), want_ok=True)
    # 미지 최상위 키
    chk("bad-top", _manifest(extra_key=1), want_ok=False, want_substr="미지 최상위 키")
    # 필수 키 누락
    chk("no-phases", {"name": "x"}, want_ok=False, want_substr="필수 키 누락: phases")
    chk("empty-phases", _manifest(phases=[]), want_ok=False, want_substr="비어있지 않은 배열")
    # phase id kebab
    chk("bad-id", _manifest(phases=[_phase(pid="Gather Phase")]), want_ok=False, want_substr="kebab-case")
    chk("dup-id", _manifest(phases=[_phase(pid="g"), _phase(pid="g")]), want_ok=False, want_substr="id 중복")
    # check.kind enum — file_exists 거부(콘텐츠 강제)
    chk("file-exists-banned", _manifest(phases=[_phase(checks=[{"kind": "file_exists"}])]),
        want_ok=False, want_substr="kind 무효")
    chk("good-kind", _manifest(phases=[_phase(checks=[{"kind": "citation_present"}])]), want_ok=True)
    # min_sources value 필수·정수
    chk("minsrc-noval", _manifest(phases=[_phase(checks=[{"kind": "min_sources"}])]),
        want_ok=False, want_substr="value 필수")
    chk("minsrc-strval", _manifest(phases=[_phase(checks=[{"kind": "min_sources", "value": "3"}])]),
        want_ok=False, want_substr="정수 아님")
    # checks ≥1
    chk("no-checks", _manifest(phases=[_phase(checks=[])]), want_ok=False, want_substr="checks ≥1")
    # max_revisions ≤ 10
    chk("revs-overflow", _manifest(phases=[_phase(max_revisions=11)]), want_ok=False, want_substr="max_revisions 무효")
    # success_criteria.statement 필수
    bad_sc = _phase()
    bad_sc["success_criteria"] = {"statement": "", "checks": [{"kind": "json_valid"}]}
    chk("empty-statement", _manifest(phases=[bad_sc]), want_ok=False, want_substr="statement 비어 있음")

    # D4 확장 — field_present·min_items (영상 JSON 콘텐츠 강제) 스키마 검증
    chk("fp-noval", _manifest(phases=[_phase(checks=[{"kind": "field_present"}])]),
        want_ok=False, want_substr="value 필수")
    chk("fp-emptyval", _manifest(phases=[_phase(checks=[{"kind": "field_present", "value": ""}])]),
        want_ok=False, want_substr="field_present.value")
    chk("fp-intval", _manifest(phases=[_phase(checks=[{"kind": "field_present", "value": 3}])]),
        want_ok=False, want_substr="field_present.value")
    chk("fp-good", _manifest(phases=[_phase(checks=[{"kind": "field_present", "value": "scenes"}])]),
        want_ok=True)
    chk("fp-good-nested", _manifest(phases=[_phase(checks=[{"kind": "field_present", "value": "plan.scenes"}])]),
        want_ok=True)
    chk("mi-noval", _manifest(phases=[_phase(checks=[{"kind": "min_items"}])]),
        want_ok=False, want_substr="value 필수")
    chk("mi-notobj", _manifest(phases=[_phase(checks=[{"kind": "min_items", "value": 3}])]),
        want_ok=False, want_substr="객체 필요")
    chk("mi-badmin", _manifest(phases=[_phase(checks=[{"kind": "min_items", "value": {"field": "scenes", "min": 0}}])]),
        want_ok=False, want_substr="min 양의 정수")
    chk("mi-boolmin", _manifest(phases=[_phase(checks=[{"kind": "min_items", "value": {"field": "scenes", "min": True}}])]),
        want_ok=False, want_substr="min 양의 정수")
    chk("mi-nofield", _manifest(phases=[_phase(checks=[{"kind": "min_items", "value": {"min": 3}}])]),
        want_ok=False, want_substr="field 비어있지 않은 문자열")
    chk("mi-unknownkey", _manifest(phases=[_phase(checks=[{"kind": "min_items", "value": {"field": "s", "min": 1, "extra": 2}}])]),
        want_ok=False, want_substr="미지 키")
    chk("mi-good", _manifest(phases=[_phase(checks=[{"kind": "min_items", "value": {"field": "scenes", "min": 3}}])]),
        want_ok=True)

    # eval_check — 콘텐츠 속성 평가
    def ec(name, kind, text, want, value=None):
        c = {"kind": kind}
        if value is not None:
            c["value"] = value
        passed, _ = eval_check(c, text)
        if passed != want:
            failures.append("eval %s: %s 기대=%s" % (name, passed, want))

    ec("cite-yes", "citation_present", "근거 https://a.com 참조", True)
    ec("cite-no", "citation_present", "출처 없는 단정", False)
    ec("contra-yes", "contradiction_flagged", "두 출처가 상충한다", True)
    ec("contra-no", "contradiction_flagged", "합의된 사실", False)
    ec("minsrc-yes", "min_sources", "https://a.com https://b.com https://c.com", True, value=3)
    ec("minsrc-no", "min_sources", "https://a.com", False, value=3)
    ec("section-yes", "section_present", "## 결론\n내용", True, value="결론")
    ec("section-no", "section_present", "본문만", False, value="결론")
    ec("unsup-clean", "no_unsupported_claims", "출처 https://a.com 동반", True)
    ec("unsup-dirty", "no_unsupported_claims", "이건 TODO 확인 필요", False)
    ec("json-yes", "json_valid", '{"a": 1}', True)
    ec("json-no", "json_valid", "not json", False)

    # 강건성 회귀(적대검증 D4 R3): bool int 함정·출처 게임·키워드 스푸핑·오탐
    chk("bool-revs", _manifest(phases=[_phase(max_revisions=True)]), want_ok=False, want_substr="max_revisions 무효")
    chk("bool-budget", _manifest(phases=[_phase(budget_minutes=True)]), want_ok=False, want_substr="budget_minutes 무효")
    chk("bool-minsrc", _manifest(phases=[_phase(checks=[{"kind": "min_sources", "value": True}])]),
        want_ok=False, want_substr="정수 아님")
    ec("minsrc-fake", "min_sources", "a.b:1 c.d:2 e.f:3", False, value=3)    # 가짜 file:line은 출처 아님
    ec("minsrc-foot", "min_sources", "주장[1] 주장[2] 주장[3]", True, value=3)  # 번호 각주는 출처
    ec("contra-spoof", "contradiction_flagged", "no conflict found", False)  # bare conflict 통과 못 함
    ec("contra-bareword", "contradiction_flagged", "모순", False)            # 맨 토큰 통과 못 함
    ec("contra-en", "contradiction_flagged", "the sources contradict each other", True)
    ec("unsup-nocite", "no_unsupported_claims", "출처 없는 평범한 문장이다", False)   # 인용 없으면 미통과
    ec("unsup-todoist", "no_unsupported_claims", "a todoist app, 근거 https://a.com", True)  # todo 오탐 아님
    ec("section-lead-space", "section_present", "  ## 결론\n내용", True, value="결론")  # 선행 공백 허용

    # field_present — JSON 필드 존재·비어있지않음(점 표기·스칼라0 존재)
    ec("fp-yes", "field_present", '{"scenes": [1,2,3]}', True, value="scenes")
    ec("fp-missing", "field_present", '{"title": "x"}', False, value="scenes")
    ec("fp-empty-list", "field_present", '{"scenes": []}', False, value="scenes")
    ec("fp-empty-str", "field_present", '{"scenes": "   "}', False, value="scenes")
    ec("fp-null", "field_present", '{"scenes": null}', False, value="scenes")
    ec("fp-zero", "field_present", '{"count": 0}', True, value="count")        # 스칼라 0=존재
    ec("fp-false", "field_present", '{"flag": false}', True, value="flag")     # 스칼라 false=존재
    ec("fp-nested", "field_present", '{"plan": {"scenes": [1]}}', True, value="plan.scenes")
    ec("fp-notjson", "field_present", 'not json at all', False, value="scenes")
    # min_items — 명명 필드가 리스트이고 len≥min
    ec("mi-enough", "min_items", '{"scenes": [1,2,3]}', True, value={"field": "scenes", "min": 3})
    ec("mi-exact", "min_items", '{"scenes": [1,2]}', True, value={"field": "scenes", "min": 2})
    ec("mi-short", "min_items", '{"scenes": [1,2]}', False, value={"field": "scenes", "min": 3})
    ec("mi-notlist", "min_items", '{"scenes": "abc"}', False, value={"field": "scenes", "min": 1})
    ec("mi-missing", "min_items", '{"x": 1}', False, value={"field": "scenes", "min": 1})
    ec("mi-nested", "min_items", '{"plan": {"scenes": [1,2,3,4]}}', True, value={"field": "plan.scenes", "min": 3})
    ec("mi-notjson", "min_items", 'nope', False, value={"field": "scenes", "min": 1})
    # 적대검증 R1(gaming MAJOR): min_items는 비어있지 않은 항목만 카운트 — 자리채움 차단
    ec("mi-null-fill", "min_items", '{"scenes": [null, null, null]}', False, value={"field": "scenes", "min": 3})
    ec("mi-emptyobj-fill", "min_items", '{"scenes": [{}, {}, {}]}', False, value={"field": "scenes", "min": 3})
    ec("mi-emptystr-fill", "min_items", '{"scenes": ["", "  ", ""]}', False, value={"field": "scenes", "min": 3})
    ec("mi-emptylist-fill", "min_items", '{"scenes": [[], [], []]}', False, value={"field": "scenes", "min": 3})
    ec("mi-mixed-filter", "min_items", '{"scenes": [1, null, 2, {}, 3]}', True, value={"field": "scenes", "min": 3})  # 비어있지않은 3개
    ec("mi-scalar-floor", "min_items", '{"scenes": [1, 1, 1]}', True, value={"field": "scenes", "min": 3})  # 스칼라 채움은 구조상 통과(floor 한계·문서화)
    # 적대검증 R1(MINOR): BOM 선두 valid JSON 오탐 차단(정당 산출물) · NaN/Infinity 표준 거부
    ec("json-bom", "json_valid", '\ufeff{"a": 1}', True)
    ec("fp-bom", "field_present", '\ufeff{"scenes": [1]}', True, value="scenes")
    ec("mi-bom", "min_items", '\ufeff{"scenes": [1, 2, 3]}', True, value={"field": "scenes", "min": 3})
    ec("json-nan", "json_valid", '{"x": NaN}', False)
    ec("json-inf", "json_valid", '{"x": Infinity}', False)
    ec("fp-nan", "field_present", '{"scenes": NaN}', False, value="scenes")  # 비표준 JSON → 파싱실패

    # cmd 라운드트립(파일 경유)·exit code — 출력 격리
    import tempfile
    sink = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="ezer-manifest-st-") as td:
        good = os.path.join(td, "workflow.json")
        with open(good, "w", encoding="utf-8") as f:
            json.dump(_manifest(), f)
        with contextlib.redirect_stdout(sink):
            if cmd_validate(good, True) != 0:
                failures.append("정상 매니페스트가 exit 0 아님")
            if cmd_resolve(td, True) != 0:
                failures.append("resolve(정상 폴더)가 exit 0 아님")
            if cmd_phase(good, "gather", True) != 0:
                failures.append("phase(존재) exit 0 아님")
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_resolve(os.path.join(td, "empty"), True) != 4:
                failures.append("resolve(매니페스트 없음)가 exit 4 아님")
            if cmd_validate(os.path.join(td, "nope.json"), True) != 2:
                failures.append("없는 파일이 exit 2 아님")
            if cmd_phase(good, "no-such", True) != 2:
                failures.append("phase(부재) exit 2 아님")
        # check-criteria 라운드트립: 통과/미달
        art_ok = os.path.join(td, "ok.md")
        with open(art_ok, "w", encoding="utf-8") as f:
            f.write("출처 https://a.com https://b.com https://c.com 충분")
        art_bad = os.path.join(td, "bad.md")
        with open(art_bad, "w", encoding="utf-8") as f:
            f.write("출처 없음")
        with contextlib.redirect_stdout(sink):
            if cmd_check_criteria(good, "gather", art_ok, True) != 0:
                failures.append("check-criteria(충족) exit 0 아님")
            if cmd_check_criteria(good, "gather", art_bad, True) != 1:
                failures.append("check-criteria(미달) exit 1 아님")
        # 빈약 산출물(2바이트) → 콘텐츠 checks 미통과(게임 차단·exit 1)
        art_thin = os.path.join(td, "thin.md")
        with open(art_thin, "w", encoding="utf-8") as f:
            f.write("모순")
        with contextlib.redirect_stdout(sink):
            if cmd_check_criteria(good, "gather", art_thin, True) != 1:
                failures.append("빈약 artifact가 exit 1 아님(게임 차단 실패)")
        # 스키마 무효 매니페스트 → phase·check-criteria 입력오류 exit 2(기준 미달 1과 구분)
        badm = os.path.join(td, "badm.json")
        with open(badm, "w", encoding="utf-8") as f:
            json.dump({"name": "x", "phases": [{"id": "BadId", "skill": "s",
                       "success_criteria": {"statement": "s", "checks": [{"kind": "json_valid"}]}}]}, f)
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_check_criteria(badm, "x", art_ok, True) != 2:
                failures.append("스키마 무효 매니페스트가 check-criteria exit 2 아님")
            if cmd_phase(badm, "x", True) != 2:
                failures.append("스키마 무효 매니페스트가 phase exit 2 아님")
        # field_present/min_items: 작은 valid JSON(<40자·thin)도 통과해야(JSON kind 면제)
        mani_fp = _manifest(phases=[_phase(checks=[
            {"kind": "field_present", "value": "scenes"},
            {"kind": "min_items", "value": {"field": "scenes", "min": 2}}])])
        fpfile = os.path.join(td, "fp.json")
        with open(fpfile, "w", encoding="utf-8") as f:
            json.dump(mani_fp, f)
        art_small = os.path.join(td, "small.json")
        with open(art_small, "w", encoding="utf-8") as f:
            f.write('{"scenes":[1,2,3]}')  # 18자<40(thin)이나 통과해야(구조 충족)
        art_short = os.path.join(td, "short.json")
        with open(art_short, "w", encoding="utf-8") as f:
            f.write('{"scenes":[1]}')      # min 2 미달 → exit 1
        with contextlib.redirect_stdout(sink):
            if cmd_check_criteria(fpfile, "gather", art_small, True) != 0:
                failures.append("작은 valid JSON이 field_present/min_items 통과 못함(thin 면제 실패)")
            if cmd_check_criteria(fpfile, "gather", art_short, True) != 1:
                failures.append("min_items 미달이 exit 1 아님")

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="타입드 워크플로우 매니페스트 검증·해소")
    ap.add_argument("--self-test", action="store_true", help="결정론 자기검증")
    sub = ap.add_subparsers(dest="cmd")

    v = sub.add_parser("validate", help="워크플로우 매니페스트 스키마 검증 (0=준수 1=위반 2=입출력)")
    v.add_argument("file")
    v.add_argument("--json", action="store_true")

    ph = sub.add_parser("phase", help="단계 계약 해소(success_criteria→--success·review_focus)")
    ph.add_argument("file")
    ph.add_argument("--phase", required=True)
    ph.add_argument("--json", action="store_true")

    rs = sub.add_parser("resolve", help="폴더에서 매니페스트 탐색·검증 (4=없음→README 폴백)")
    rs.add_argument("folder")
    rs.add_argument("--json", action="store_true")

    cc = sub.add_parser("check-criteria",
                        help="단계 checks를 artifact 콘텐츠에 기계평가 (0=수렴 1=미달)")
    cc.add_argument("file")
    cc.add_argument("--phase", required=True)
    cc.add_argument("--artifact", required=True)
    cc.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.cmd == "validate":
        return cmd_validate(args.file, args.json)
    if args.cmd == "phase":
        return cmd_phase(args.file, args.phase, args.json)
    if args.cmd == "resolve":
        return cmd_resolve(args.folder, args.json)
    if args.cmd == "check-criteria":
        return cmd_check_criteria(args.file, args.phase, args.artifact, args.json)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
