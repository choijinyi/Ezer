#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EZERagent_params — 능력 스킬 튜너블의 타입드 ParamDefinition + 결정론적 coerce 바닥(가치 게이트).

OpenCut ParamDefinition(opencut-classic/apps/web/src/params/index.ts:175-241·309-342) 클린룸
이식: 모든 창작 서브시스템의 사용자 제어를 6타입(number|boolean|color|select|text|font) 데이터로
선언하고, *순수 함수* 하나가 임의 입력을 검증·스냅한다 — number는 snapToStep→clamp, select는
옵션 멤버십, 나머지는 타입체크, 거부 시 사유. **개별 스킬이 경계검사를 재구현하지 않는다.**

EZERagent 가치: 우리 스킬은 자유텍스트 의도를 받아 각자 산문으로 입력 검증을 재유도한다 — 기계 바닥이
없어 범위-밖 값이 유료/벽-무거운 프로바이더(media-gen-video=fal.ai 초당 종량제)에 그대로 흘러간다.
이 도구는 그 프로바이더가 돌기 *전에* 거부하는 결정론 floor다 — [[cost-preview-confirm]](달러 게이트)
아래의 *가치* 게이트. (품질 점수 아님 — coerce는 입력 정합성만, 무점수 채널.)

ParamDefinition 형식(JSON 배열):
  {"key":"duration","type":"number","default":5,"min":1,"max":60,"step":0.5}
  {"key":"loop","type":"boolean","default":false}
  {"key":"style","type":"select","default":"cinematic","options":["cinematic","flat","retro"]}
  {"key":"title","type":"text","default":"","max_length":120}
  {"key":"bg","type":"color","default":"#000000"}          # #RGB·#RRGGBB·#RRGGBBAA
  {"key":"font","type":"font","default":"Inter"}           # 비어있지 않은 폰트명

사용:
    python3 EZERagent_params.py validate-defs <DEFS.json> [--json]        # ParamDefinition 스키마 검증
    python3 EZERagent_params.py defaults      <DEFS.json> [--json]        # {key: default} 산출
    python3 EZERagent_params.py coerce        <DEFS.json> --values <V.json> [--json]
    python3 EZERagent_params.py --self-test
종료 코드: 0 성공(validate-defs 준수 / coerce 전부 정합) · 1 위반(defs 무효 / coerce 거부 발생) ·
          2 인자/입출력/JSON 오류.
의존성: 파이썬 표준 라이브러리만(네트워크·LLM·점수 생성 없음·결정론).
"""

import argparse
import json
import re
import sys

PARAM_TYPES = ("number", "boolean", "color", "select", "text", "font")
DEF_KEYS = {
    "number": ("key", "type", "default", "min", "max", "step", "label"),
    "boolean": ("key", "type", "default", "label"),
    "color": ("key", "type", "default", "label"),
    "select": ("key", "type", "default", "options", "label"),
    "text": ("key", "type", "default", "max_length", "label"),
    "font": ("key", "type", "default", "label"),
}
_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def fail(code, msg):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    return code


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def validate_defs(defs):
    """ParamDefinition 배열 검증 → 오류 리스트(빈 리스트=준수). 닫힌 키·타입·범위 정합."""
    errs = []
    if not isinstance(defs, list) or not defs:
        return ["defs는 비어있지 않은 배열이어야 함"]
    seen = set()
    for i, d in enumerate(defs):
        w = "defs[%d]" % i
        if not isinstance(d, dict):
            errs.append("%s 객체 아님" % w)
            continue
        key = d.get("key")
        if not (isinstance(key, str) and key.strip()):
            errs.append("%s key 비어있지 않은 문자열 필요" % w)
        elif key in seen:
            errs.append("%s key 중복: %s" % (w, key))
        else:
            seen.add(key)
        t = d.get("type")
        if t not in PARAM_TYPES:
            errs.append("%s type 무효(%r) — %s" % (w, t, "|".join(PARAM_TYPES)))
            continue
        for k in d:
            if k not in DEF_KEYS[t]:
                errs.append("%s(%s) 미지 키 %r — %s" % (w, t, k, "|".join(DEF_KEYS[t])))
        if "default" not in d:
            errs.append("%s default 필수" % w)
        if t == "number":
            for nk in ("min", "max", "step"):
                if nk in d and not _is_num(d[nk]):
                    errs.append("%s number.%s 숫자 아님(%r)" % (w, nk, d[nk]))
            if "min" in d and "max" in d and _is_num(d["min"]) and _is_num(d["max"]) and d["min"] > d["max"]:
                errs.append("%s number min>max" % w)
            if "step" in d and _is_num(d["step"]) and d["step"] <= 0:
                errs.append("%s number step>0 필요" % w)
        if t == "select":
            opts = d.get("options")
            if not (isinstance(opts, list) and opts):
                errs.append("%s select options 비어있지 않은 배열 필요" % w)
            elif "default" in d and d["default"] not in opts:
                errs.append("%s select default가 options에 없음" % w)
        if t == "text" and "max_length" in d and not (_is_int(d["max_length"]) and d["max_length"] >= 0):
            errs.append("%s text.max_length 0 이상 정수 필요" % w)
        # default 자체가 자기 타입에 coerce 가능한지(거부되면 무효 def)
        if "default" in d and t in PARAM_TYPES and not errs_for_key(w, errs):
            _, rej = coerce_value(d, d.get("default"))
            if rej is not None:
                errs.append("%s default가 자기 정의에 부적합: %s" % (w, rej))
    return errs


def errs_for_key(prefix, errs):
    """이미 이 def에 오류가 쌓였으면 True(중복·연쇄 오류 억제용)."""
    return any(e.startswith(prefix) for e in errs)


def _snap_clamp(v, d):
    """number: snapToStep(min 기준 격자) → clamp[min,max]. OpenCut coerceParamValue 의미론."""
    val = float(v)
    step = d.get("step")
    mn = d.get("min")
    if _is_num(step) and step > 0:
        base = mn if _is_num(mn) else 0
        val = base + round((val - base) / step) * step
    if _is_num(mn):
        val = max(val, mn)
    mx = d.get("max")
    if _is_num(mx):
        val = min(val, mx)
    # 정수 격자(min·step·max 모두 정수)면 정수로 환원(부동소수 잔재 제거)
    if all(_is_int(d.get(k)) for k in ("min", "step") if k in d) and float(val).is_integer():
        if not isinstance(v, float) or float(v).is_integer():
            return int(round(val))
    return round(val, 6)


def coerce_value(d, value):
    """단일 값을 def에 맞춰 coerce → (coerced, rejection|None). rejection은 거부 사유 문자열."""
    t = d.get("type")
    if t == "number":
        if not _is_num(value):
            return None, "숫자 아님(%r)" % value
        return _snap_clamp(value, d), None
    if t == "boolean":
        if not isinstance(value, bool):
            return None, "불리언 아님(%r)" % value
        return value, None
    if t == "select":
        opts = d.get("options") or []
        if value not in opts:
            return None, "options(%s)에 없음(%r)" % ("|".join(map(str, opts)), value)
        return value, None
    if t == "text":
        if not isinstance(value, str):
            return None, "문자열 아님(%r)" % value
        ml = d.get("max_length")
        return (value[:ml] if _is_int(ml) else value), None
    if t == "color":
        if not (isinstance(value, str) and _COLOR_RE.match(value)):
            return None, "색상 hex(#RGB·#RRGGBB·#RRGGBBAA) 아님(%r)" % value
        return value, None
    if t == "font":
        if not (isinstance(value, str) and value.strip()):
            return None, "비어있지 않은 폰트명 아님(%r)" % value
        return value, None
    return None, "알 수 없는 타입(%r)" % t


def coerce(defs, values):
    """values를 defs에 맞춰 coerce. 미제공 키는 default. 미지 키·거부는 rejected에.
    반환 (coerced_map, rejected_list)."""
    by_key = {d.get("key"): d for d in defs if isinstance(d, dict)}
    coerced, rejected = {}, []
    for d in defs:
        if not isinstance(d, dict):
            continue
        key = d.get("key")
        if key in values:
            cv, rej = coerce_value(d, values[key])
            if rej is not None:
                rejected.append({"key": key, "value": values[key], "reason": rej})
            else:
                coerced[key] = cv
        else:
            coerced[key] = d.get("default")  # 미제공 → default
    for key in values:
        if key not in by_key:
            rejected.append({"key": key, "value": values[key], "reason": "미지 파라미터(defs에 없음)"})
    return coerced, rejected


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None, None
    except FileNotFoundError:
        return None, 2, "파일 없음: %s" % path
    except (OSError, json.JSONDecodeError) as e:
        return None, 2, "JSON 로드 실패: %s (%s)" % (path, e)


def cmd_validate_defs(path, as_json):
    defs, ec, em = _load(path)
    if ec:
        return fail(ec, em)
    errs = validate_defs(defs)
    ok = not errs
    if as_json:
        print(json.dumps({"ok": ok, "schema_errors": errs}, ensure_ascii=False, indent=2))
    else:
        for e in errs:
            print("[DEF] %s" % e)
        print("param-defs: %s (%d defs)" % ("OK" if ok else "REJECT",
              len(defs) if isinstance(defs, list) else 0))
    return 0 if ok else 1


def cmd_defaults(path, as_json):
    defs, ec, em = _load(path)
    if ec:
        return fail(ec, em)
    errs = validate_defs(defs)
    if errs:
        return fail(1, "defs 무효 %d건 — validate-defs로 확인" % len(errs))
    out = {d["key"]: d.get("default") for d in defs}
    print(json.dumps(out, ensure_ascii=False, indent=2 if as_json else None))
    return 0


def cmd_coerce(defs_path, values_path, as_json):
    defs, ec, em = _load(defs_path)
    if ec:
        return fail(ec, em)
    errs = validate_defs(defs)
    if errs:
        return fail(2, "defs 무효 %d건(입력 오류) — validate-defs로 확인" % len(errs))
    values, ec, em = _load(values_path)
    if ec:
        return fail(ec, em)
    if not isinstance(values, dict):
        return fail(2, "values는 객체(dict)여야 함")
    coerced, rejected = coerce(defs, values)
    ok = not rejected
    out = {"ok": ok, "coerced": coerced, "rejected": rejected}
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("coerce: %s — %d 정합, %d 거부" % ("PASS" if ok else "REJECT",
              len(coerced), len(rejected)))
        for r in rejected:
            print("  [거부] %s=%r — %s" % (r["key"], r["value"], r["reason"]))
        if not ok:
            print("유료/벽-무거운 프로바이더 실행 전 입력을 교정하라(가치 게이트).")
    return 0 if ok else 1


def self_test():
    failures = []

    def eq(name, got, want):
        if got != want:
            failures.append("%s: got %r want %r" % (name, got, want))

    defs = [
        {"key": "duration", "type": "number", "default": 5, "min": 1, "max": 60, "step": 1},
        {"key": "intensity", "type": "number", "default": 0.5, "min": 0, "max": 1, "step": 0.1},
        {"key": "loop", "type": "boolean", "default": False},
        {"key": "style", "type": "select", "default": "cinematic", "options": ["cinematic", "flat"]},
        {"key": "title", "type": "text", "default": "", "max_length": 5},
        {"key": "bg", "type": "color", "default": "#000000"},
        {"key": "font", "type": "font", "default": "Inter"},
    ]
    eq("defs-valid", validate_defs(defs), [])

    # number clamp+snap
    eq("num-clamp-hi", coerce_value(defs[0], 999)[0], 60)
    eq("num-clamp-lo", coerce_value(defs[0], -5)[0], 1)
    eq("num-snap", coerce_value(defs[1], 0.34)[0], 0.3)        # step 0.1 → 0.3
    eq("num-reject", coerce_value(defs[0], "5")[1] is not None, True)  # 문자열 거부
    eq("num-int-grid", coerce_value(defs[0], 7)[0], 7)         # 정수 격자 → 정수
    # boolean
    eq("bool-ok", coerce_value(defs[2], True), (True, None))
    eq("bool-reject", coerce_value(defs[2], 1)[1] is not None, True)   # 1은 bool 아님
    # select
    eq("sel-ok", coerce_value(defs[3], "flat"), ("flat", None))
    eq("sel-reject", coerce_value(defs[3], "neon")[1] is not None, True)
    # text truncate
    eq("text-trunc", coerce_value(defs[4], "abcdefgh")[0], "abcde")
    eq("text-reject", coerce_value(defs[4], 5)[1] is not None, True)
    # color
    eq("color-ok", coerce_value(defs[5], "#ff8800"), ("#ff8800", None))
    eq("color-rgb", coerce_value(defs[5], "#f80"), ("#f80", None))
    eq("color-reject", coerce_value(defs[5], "red")[1] is not None, True)
    # font
    eq("font-ok", coerce_value(defs[6], "Pretendard"), ("Pretendard", None))
    eq("font-reject", coerce_value(defs[6], "  ")[1] is not None, True)

    # coerce(): 미제공→default, 미지 키→rejected
    coerced, rejected = coerce(defs, {"duration": 100, "unknown_x": 1})
    eq("coerce-clamp", coerced["duration"], 60)
    eq("coerce-default", coerced["loop"], False)
    eq("coerce-unknown", any(r["key"] == "unknown_x" for r in rejected), True)
    coerced2, rej2 = coerce(defs, {"style": "cinematic"})
    eq("coerce-clean", rej2, [])

    # validate_defs 위반들
    eq("bad-type", bool(validate_defs([{"key": "x", "type": "vector", "default": 0}])), True)
    eq("dup-key", bool(validate_defs([{"key": "a", "type": "boolean", "default": True},
                                      {"key": "a", "type": "boolean", "default": False}])), True)
    eq("sel-no-opts", bool(validate_defs([{"key": "s", "type": "select", "default": "x"}])), True)
    eq("num-minmax", bool(validate_defs([{"key": "n", "type": "number", "default": 0, "min": 5, "max": 1}])), True)
    eq("bad-default", bool(validate_defs([{"key": "c", "type": "color", "default": "notacolor"}])), True)
    eq("unknown-key", bool(validate_defs([{"key": "n", "type": "number", "default": 0, "wat": 1}])), True)

    # cmd 라운드트립
    import contextlib
    import io
    import os
    import tempfile
    sink = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="EZERagent-params-st-") as td:
        dp = os.path.join(td, "defs.json")
        json.dump(defs, open(dp, "w", encoding="utf-8"))
        vp_ok = os.path.join(td, "v_ok.json")
        json.dump({"duration": 10, "style": "flat"}, open(vp_ok, "w", encoding="utf-8"))
        vp_bad = os.path.join(td, "v_bad.json")
        json.dump({"style": "neon"}, open(vp_bad, "w", encoding="utf-8"))
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_validate_defs(dp, True) != 0:
                failures.append("validate-defs(정상) exit 0 아님")
            if cmd_coerce(dp, vp_ok, True) != 0:
                failures.append("coerce(정합) exit 0 아님")
            if cmd_coerce(dp, vp_bad, True) != 1:
                failures.append("coerce(거부) exit 1 아님")
            if cmd_defaults(dp, True) != 0:
                failures.append("defaults exit 0 아님")
            bad_defs = os.path.join(td, "bad.json")
            json.dump([{"key": "x", "type": "vector", "default": 0}], open(bad_defs, "w", encoding="utf-8"))
            if cmd_validate_defs(bad_defs, True) != 1:
                failures.append("validate-defs(무효) exit 1 아님")
            if cmd_coerce(bad_defs, vp_ok, True) != 2:
                failures.append("coerce(무효 defs) exit 2 아님")

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="타입드 ParamDefinition + 결정론 coerce 바닥")
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    v = sub.add_parser("validate-defs", help="ParamDefinition 스키마 검증")
    v.add_argument("defs")
    v.add_argument("--json", action="store_true")

    d = sub.add_parser("defaults", help="{key: default} 산출")
    d.add_argument("defs")
    d.add_argument("--json", action="store_true")

    c = sub.add_parser("coerce", help="values를 defs에 맞춰 coerce (0=정합 1=거부 2=입력오류)")
    c.add_argument("defs")
    c.add_argument("--values", required=True)
    c.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.cmd == "validate-defs":
        return cmd_validate_defs(args.defs, args.json)
    if args.cmd == "defaults":
        return cmd_defaults(args.defs, args.json)
    if args.cmd == "coerce":
        return cmd_coerce(args.defs, args.values, args.json)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
