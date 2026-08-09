#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_timeline — 편집-결정 IR(edit_decisions.json) 검증기: 구조 검증(validate) + 모션그래픽
진입/퇴장 타이밍의 **결정론적 정수-틱 프레임 검증**(check) 게이트.

video-verify-timing의 LLM-비전 타이밍 판정(±0.3초 부동소수 비교)을 결정론 산술로 대체한다.
부동소수 '초'는 프레임 경계를 정확히 표현하지 못하므로(누적 반올림 오차로 NLE 비동기화),
OpenCut(opencut-classic/rust/crates/time/src/media_time.rs:9-16)의 정수-틱 격자를 클린룸
이식한다: 모든 시간은 i64 틱(TICKS_PER_SECOND=120_000 — 24·25·30·48·50·60·23.976·29.97·
59.94fps가 모두 정수 ticks_per_frame로 떨어지는 최소 고합성수). 파이썬 int는 임의정밀이라
무손실. 표현 불가능한 프레임레이트(예: 7/3)는 조용히 반올림하지 않고 **hard-fail(exit 2)**.

producer≠evaluator: 이 게이트는 *타이밍*만 권위 판정한다(intended↔actual 프레임 드리프트가
허용 프레임 내인가). '잘린 진입·갑작스런 컷·퇴장 잔존' 같은 *시각* 결함은 비전(video-verify-
timing 절차 2)이 본다 — 기계 floor는 타이밍, 비전은 시각, 둘은 다른 관문이다. machine PASS는
입력 타임스탬프(forced-alignment·ffprobe) 조건부 결정론이지 ground-truth가 아니다(과신 금지).

입력 계약 — 정전 IR(ezer-pack/schemas/edit_decisions.schema.json · W0-2): 정수 틱이 진실.
  edit_decisions.json = {"schema_version":1, "render_runtime":"...", "fps":<레이트>, "tracks":[
    {"kind":"avatar|broll|graphic|caption|audio|music", "elements":[
      {"id":"g1", "in_ticks":<틱>, "out_ticks":<틱>, "intended_ticks"?:<틱>,
       "mode"?:"fullscreen|left-card|rounded-crop-pip", "transition"?:"cut|dissolve|slide",
       "source"?:"..."}]}]}
    intended_ticks=의도 진입 큐(틱)·in_ticks=실제 진입(틱). 둘 다 있는 element만 타이밍 대상.
  호환(W0-1 flat): 최상위 "elements"|"graphics" + 초 단위 "intended"/"in"/"start"도 읽는다(틱 우선).
  fps 우선순위: --fps > --probe <비디오>(ffprobe) > IR "fps". 셋 다 없으면 exit 2.

사용:
    python3 check_timeline.py validate edit_decisions.json [--json]   # IR 구조 검증(스키마)
    python3 check_timeline.py fps --fps 29.97                         # 레이트 표현성·ticks_per_frame
    python3 check_timeline.py fps --probe final/video.mp4             # ffprobe로 fps 탐지·스냅
    python3 check_timeline.py check edit_decisions.json [--fps N | --probe V] \
            [--tolerance-seconds 0.3 | --tolerance-frames K] [--json]  # 타이밍 드리프트 게이트
    python3 check_timeline.py --self-test                            # 결정론 자기검증 (preflight)
종료 코드: 0 통과(validate 준수 / check GO / fps 표현 가능) · 1 위반(validate 스키마 위반 /
          check NO_GO 드리프트 초과) · 2 인자/입출력/JSON 오류·표현 불가 프레임레이트·ffprobe 실패.
의존성: 파이썬 표준 라이브러리만(ffprobe는 fps 탐지 시에만 외부 호출 — 팩 전제). 네트워크·LLM·
        점수 생성 없음. 결정론(같은 입력→같은 출력·exit).
"""

import argparse
import json
import math
import re
import subprocess
import sys

# ── 정수-틱 격자 (OpenCut media_time.rs:9-10 클린룸 이식) ──
TICKS_PER_SECOND = 120_000

# 표준 프레임레이트 (정확 유리수 num/den). 부동소수 fps 입력을 여기에 스냅한다.
# 전부 120_000 틱을 정수 ticks_per_frame로 나눈다(frame_rate.rs:101-113 패리티 표와 동치):
# 24→5000 · 25→4800 · 30→4000 · 48→2500 · 50→2400 · 60→2000 · 23.976→5005 · 29.97→4004 · 59.94→2002.
STANDARD_RATES = (
    (24000, 1001),  # 23.976
    (24, 1),
    (25, 1),
    (30000, 1001),  # 29.97
    (30, 1),
    (48, 1),
    (50, 1),
    (60000, 1001),  # 59.94
    (60, 1),
    (120, 1),
)
# 부동소수 fps를 표준 레이트로 스냅하는 허용 오차(절대 fps 차).
SNAP_TOLERANCE = 0.05
# tolerance 미지정 시 기본(현행 SKILL의 ±0.3초 보존 — W0-2에서 프레임 단위로 강화 예정).
DEFAULT_TOLERANCE_SECONDS = 0.3

# 입력 키 별칭 (W0-1 flat 호환 — 초 단위). canonical IR(W0-2)은 tracks[].elements·정수 _ticks.
ELEMENTS_KEYS = ("elements", "graphics")
ID_KEYS = ("id", "graphic_id")
IN_KEYS = ("in", "start")
OUT_KEYS = ("out", "end")

# ── 정전 IR 스키마(edit_decisions.schema.json) 하드롤 검증 어휘 (jsonschema 미사용·house style) ──
SCHEMA_VERSION = 1
TOP_KEYS = ("schema_version", "render_runtime", "fps", "ticks_per_second", "tracks")
TOP_REQUIRED = ("schema_version", "render_runtime", "fps", "tracks")
TRACK_KEYS = ("kind", "elements")
TRACK_REQUIRED = ("kind", "elements")
TRACK_KINDS = ("avatar", "broll", "graphic", "caption", "audio", "music")
EL_KEYS = ("id", "in_ticks", "out_ticks", "intended_ticks", "mode", "transition", "source")
EL_REQUIRED = ("id", "in_ticks", "out_ticks")
EL_MODES = ("fullscreen", "left-card", "rounded-crop-pip")
EL_TRANSITIONS = ("cut", "dissolve", "slide")


def _is_num(x):
    """진짜 숫자만 — bool 거부(isinstance(True, int) 함정 차단)·NaN/Inf 거부."""
    if isinstance(x, bool):
        return False
    if isinstance(x, int):
        return True
    return isinstance(x, float) and math.isfinite(x)


def gcd(a, b):
    return math.gcd(int(a), int(b))


def ticks_per_frame(num, den):
    """프레임당 틱 = TICKS_PER_SECOND * den / num. 나머지가 있으면 None(표현 불가 — 거부).
    OpenCut frame_rate.rs:82-94 의미론: 7/3 같은 비표준 레이트는 조용히 반올림하지 않는다."""
    if num <= 0 or den <= 0:
        return None
    numerator = TICKS_PER_SECOND * den
    if numerator % num != 0:
        return None
    return numerator // num


def normalize_rate(spec):
    """fps 명세 → (num, den) 정확 유리수, 또는 None(파싱 불가).
    허용: int·float·"num/den" 문자열·[num, den]. 부동소수는 표준 레이트로 스냅 시도."""
    if isinstance(spec, (list, tuple)) and len(spec) == 2 and _is_num(spec[0]) and _is_num(spec[1]):
        n, d = int(spec[0]), int(spec[1])
        if n > 0 and d > 0:
            g = gcd(n, d)
            return (n // g, d // g)
        return None
    if isinstance(spec, str):
        s = spec.strip()
        m = re.match(r"^(\d+)\s*/\s*(\d+)$", s)
        if m:
            n, d = int(m.group(1)), int(m.group(2))
            if n > 0 and d > 0:
                g = gcd(n, d)
                return (n // g, d // g)
            return None
        try:
            spec = float(s)
        except ValueError:
            return None
    if isinstance(spec, bool):
        return None
    if isinstance(spec, int) and spec > 0:
        return (spec, 1)
    if isinstance(spec, float) and math.isfinite(spec) and spec > 0:
        # 표준 레이트로 스냅 (29.97 → 30000/1001 등). 스냅 실패 시 None(추측 반올림 금지).
        best = None
        for (n, d) in STANDARD_RATES:
            diff = abs(spec - n / d)
            if diff <= SNAP_TOLERANCE and (best is None or diff < best[0]):
                best = (diff, (n, d))
        return best[1] if best else None
    return None


def seconds_to_ticks(seconds):
    """초(부동소수) → 틱(i64, 반올림). 유일한 부동소수 진입점 — 여기서 격리한다."""
    return int(round(seconds * TICKS_PER_SECOND))


def round_ticks_to_frame(ticks, tpf):
    """틱을 가장 가까운 프레임 경계로 스냅(half-up). OpenCut to_frame_round(media_time.rs:48-57)
    의미론: 나머지×2 ≥ tpf 면 올림. 음수 안전(Euclidean)."""
    floor = ticks // tpf
    rem = ticks - floor * tpf  # rem_euclid (tpf>0)
    if rem * 2 >= tpf:
        return (floor + 1) * tpf
    return floor * tpf


def fail(code, msg):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    return code


# ── fps 탐지 ──
def probe_fps(video_path):
    """ffprobe로 비디오 스트림의 r_frame_rate를 읽어 (num, den) 반환. (rate, err) 튜플.
    ffprobe 부재·실패·파싱 불가는 err(문자열)로 — fps를 추측하지 않는다."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate", "-of", "default=nk=1:np=1", video_path],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return None, "ffprobe 없음 — 팩 전제(ffmpeg 동봉 ffprobe) 설치 필요"
    except subprocess.TimeoutExpired:
        return None, "ffprobe 30초 타임아웃"
    if out.returncode != 0:
        return None, "ffprobe 실패(%s): %s" % (out.returncode, out.stderr.strip()[:200])
    raw = out.stdout.strip()
    rate = normalize_rate(raw)
    if rate is None:
        return None, "ffprobe r_frame_rate 파싱·스냅 불가: %r" % raw
    return rate, None


def resolve_rate(args, timeline):
    """fps 우선순위 해소: --fps > --probe > timeline 'fps'. → ((num,den), tpf) 또는 (None, 에러)."""
    spec = None
    src = None
    if args.fps is not None:
        spec, src = args.fps, "--fps"
    elif getattr(args, "probe", None):
        rate, err = probe_fps(args.probe)
        if err:
            return None, err
        spec, src = rate, "ffprobe(%s)" % args.probe
    elif isinstance(timeline, dict) and "fps" in timeline:
        spec, src = timeline.get("fps"), "timeline.fps"
    if spec is None:
        return None, "fps 미지정 — --fps 또는 --probe <비디오> 또는 timeline 'fps' 필요"
    rate = normalize_rate(spec)
    if rate is None:
        return None, "fps 표현 불가(%r·%s) — 표준 레이트 아님(추측 반올림 거부)" % (spec, src)
    tpf = ticks_per_frame(rate[0], rate[1])
    if tpf is None:
        return None, "프레임레이트 %d/%d 는 120000 틱 격자에서 표현 불가(hard-fail)" % rate
    return (rate, tpf), None


# ── element 추출 ──
def _first_key(d, keys):
    for k in keys:
        if k in d:
            return d[k]
    return None


def collect_elements(timeline):
    """check용 element 수집 → (elements, 에러). 정전 IR(tracks[].elements) 또는 호환 flat(elements/graphics)."""
    if not isinstance(timeline, dict):
        return None, "timeline 최상위가 객체(dict)가 아님"
    if isinstance(timeline.get("tracks"), list):
        els = []
        for tr in timeline["tracks"]:
            if isinstance(tr, dict) and isinstance(tr.get("elements"), list):
                els.extend(tr["elements"])
        return els, None
    raw = _first_key(timeline, ELEMENTS_KEYS)
    if raw is None:
        return None, "timeline에 'tracks' 또는 'elements'/'graphics' 없음 — 입력 계약 미준수"
    if not isinstance(raw, list):
        return None, "'elements'가 배열이 아님(%s)" % type(raw).__name__
    return raw, None


def _el_ticks(el, ticks_field, sec_keys):
    """element 시간을 틱으로 해소 — 정전 *_ticks 정수 우선, 없으면 초(부동소수)→틱.
    (ticks, 에러); 부재는 (None, None). ticks_field 가 비정수면 에러(fail-loud)."""
    if ticks_field in el:
        v = el[ticks_field]
        if not (isinstance(v, int) and not isinstance(v, bool)):
            return None, "%s 는 정수 틱이어야 함(%r)" % (ticks_field, v)
        return v, None
    sv = _first_key(el, sec_keys)
    if sv is None:
        return None, None
    if not _is_num(sv):
        return None, "초 값이 유한 숫자가 아님(%r)" % sv
    return seconds_to_ticks(sv), None


def cmd_fps(args):
    """레이트 표현성·ticks_per_frame 출력."""
    if args.probe:
        rate, err = probe_fps(args.probe)
        if err:
            return fail(2, err)
        src = "ffprobe(%s)" % args.probe
    elif args.fps is not None:
        rate = normalize_rate(args.fps)
        src = "--fps %r" % args.fps
    else:
        return fail(2, "fps 명세 필요 — --fps <레이트> 또는 --probe <비디오>")
    if rate is None:
        return fail(2, "fps 표현 불가(%s) — 표준 레이트 아님" % src)
    tpf = ticks_per_frame(rate[0], rate[1])
    if tpf is None:
        return fail(2, "프레임레이트 %d/%d 표현 불가(120000 격자)" % rate)
    out = {"ok": True, "source": src, "fps_rational": "%d/%d" % rate,
           "fps_decimal": round(rate[0] / rate[1], 6),
           "ticks_per_second": TICKS_PER_SECOND, "ticks_per_frame": tpf}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_check(args):
    """timeline.json의 각 element 타이밍 드리프트를 정수-틱 프레임 격자에서 판정.
    출력 계약: {gate:'timing', verdict:GO|NO_GO, issues:[{graphic_id, intended, actual, drift, ...}]}."""
    try:
        with open(args.timeline, encoding="utf-8") as f:
            timeline = json.load(f)
    except FileNotFoundError:
        return fail(2, "timeline 파일 없음: %s" % args.timeline)
    except (OSError, json.JSONDecodeError) as e:
        return fail(2, "timeline JSON 로드 실패: %s (%s)" % (args.timeline, e))

    rate_tpf, err = resolve_rate(args, timeline)
    if err:
        return fail(2, err)
    (num, den), tpf = rate_tpf

    elements, err = collect_elements(timeline)
    if err:
        return fail(2, err)

    # tolerance: --tolerance-frames 우선, 없으면 --tolerance-seconds(기본 0.3초)를 틱으로.
    if args.tolerance_frames is not None:
        if args.tolerance_frames < 0:
            return fail(2, "--tolerance-frames 음수 불가")
        tol_ticks = args.tolerance_frames * tpf
        tol_label = "%d프레임" % args.tolerance_frames
    else:
        tol_sec = args.tolerance_seconds if args.tolerance_seconds is not None else DEFAULT_TOLERANCE_SECONDS
        if tol_sec < 0:
            return fail(2, "--tolerance-seconds 음수 불가")
        tol_ticks = seconds_to_ticks(tol_sec)
        tol_label = "%.3f초(%d틱)" % (tol_sec, tol_ticks)

    issues = []
    checked = 0
    for i, el in enumerate(elements):
        if not isinstance(el, dict):
            return fail(2, "elements[%d] 객체 아님" % i)
        gid = _first_key(el, ID_KEYS)
        gid = gid if isinstance(gid, str) and gid.strip() else "element[%d]" % i
        # 정전 *_ticks 정수 우선, 없으면 초 폴백(W0-1 호환). intended·in 둘 다 있는 element만 타이밍 대상.
        intended_t, e1 = _el_ticks(el, "intended_ticks", ("intended",))
        if e1:
            return fail(2, "%s: %s" % (gid, e1))
        actual_t, e2 = _el_ticks(el, "in_ticks", IN_KEYS)
        if e2:
            return fail(2, "%s: %s" % (gid, e2))
        if intended_t is None or actual_t is None:
            continue
        intended_ticks = round_ticks_to_frame(intended_t, tpf)
        actual_ticks = round_ticks_to_frame(actual_t, tpf)
        drift_ticks = actual_ticks - intended_ticks
        drift_frames = drift_ticks // tpf if tpf else 0
        checked += 1
        if abs(drift_ticks) > tol_ticks:
            issues.append({
                "graphic_id": gid,
                "intended": round(intended_ticks / TICKS_PER_SECOND, 6),
                "actual": round(actual_ticks / TICKS_PER_SECOND, 6),
                "drift": round(drift_ticks / TICKS_PER_SECOND, 6),
                "drift_ticks": drift_ticks,
                "drift_frames": drift_frames,
            })

    verdict = "GO" if not issues else "NO_GO"
    out = {
        "gate": "timing",
        "verdict": verdict,
        "fps_rational": "%d/%d" % (num, den),
        "ticks_per_frame": tpf,
        "tolerance": tol_label,
        "elements_total": len(elements),
        "elements_checked": checked,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("timing 게이트: %s — fps %d/%d · 검증 %d/%d · 허용 %s"
              % (verdict, num, den, checked, len(elements), tol_label))
        for it in issues:
            print("  [DRIFT] %s: intended=%.3fs actual=%.3fs drift=%+dframe(%+d틱)"
                  % (it["graphic_id"], it["intended"], it["actual"],
                     it["drift_frames"], it["drift_ticks"]))
        if verdict == "NO_GO":
            print("이 게이트(결정론 타이밍) 외에 비전(절차2·시각 결함)·agy/codex 독립 판정이 함께 수렴해야 한다.")
    return 0 if verdict == "GO" else 1


# ── boundaries: 렌더 충실도(replay-verify) — 선언 컷 경계 vs 측정(ffprobe) 경계 프레임 비교 ──
def cmd_boundaries(args):
    """선언된 IR 컷 경계(틱)와 실제 렌더에서 측정된 경계(초·ffprobe -show_packets)를 프레임 격자에서
    대조한다(W2-3 replay-verify). 조건부·추가적: 렌더가 IR로부터 프레임-결정적일 때만 유효하며
    keyframe-강제 컷 지점에만 frame-equality를 단언한다(P/B-프레임 오탐 방지·SKILL 참조).
    입력 {fps?, declared_ticks:[..정수..], measured_seconds:[..숫자..]}."""
    try:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return fail(2, "입력 파일 없음: %s" % args.input)
    except (OSError, json.JSONDecodeError) as e:
        return fail(2, "입력 JSON 로드 실패: %s (%s)" % (args.input, e))
    rate_tpf, err = resolve_rate(args, data)
    if err:
        return fail(2, err)
    (num, den), tpf = rate_tpf
    declared = data.get("declared_ticks")
    measured = data.get("measured_seconds")
    if not isinstance(declared, list) or not isinstance(measured, list):
        return fail(2, "declared_ticks·measured_seconds 배열 필요")
    if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in declared):
        return fail(2, "declared_ticks 는 0 이상 정수(틱) 배열")
    if not all(_is_num(x) for x in measured):
        return fail(2, "measured_seconds 는 숫자 배열")
    tol_frames = args.tolerance_frames if args.tolerance_frames is not None else 1
    if tol_frames < 0:
        return fail(2, "--tolerance-frames 음수 불가")
    tol_ticks = tol_frames * tpf
    measured_ticks = [round_ticks_to_frame(seconds_to_ticks(s), tpf) for s in measured]
    mismatches = []
    for d in declared:
        dq = round_ticks_to_frame(d, tpf)
        nearest = min(measured_ticks, key=lambda m: abs(m - dq)) if measured_ticks else None
        if nearest is None:
            mismatches.append({"declared_ticks": dq, "nearest_measured_ticks": None,
                               "delta_ticks": None, "frame_delta": None})
            continue
        delta = abs(dq - nearest)
        if delta > tol_ticks:
            mismatches.append({"declared_ticks": dq, "nearest_measured_ticks": nearest,
                               "delta_ticks": delta, "frame_delta": delta // tpf})
    verdict = "GO" if not mismatches else "NO_GO"
    out = {"gate": "render_fidelity", "verdict": verdict, "fps_rational": "%d/%d" % (num, den),
           "ticks_per_frame": tpf, "tolerance_frames": tol_frames,
           "declared": len(declared), "measured": len(measured), "mismatches": mismatches}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("render_fidelity: %s — fps %d/%d · 선언 %d · 측정 %d · 허용 %d프레임"
              % (verdict, num, den, len(declared), len(measured), tol_frames))
        for m in mismatches:
            print("  [MISMATCH] 선언 %s틱 ↔ 측정 %s틱 (Δ%s프레임)"
                  % (m["declared_ticks"], m["nearest_measured_ticks"], m["frame_delta"]))
    return 0 if verdict == "GO" else 1


# ── validate: 정전 IR(edit_decisions.json) 하드롤 구조 검증 ──
def _validate_element(el, where):
    errs = []
    if not isinstance(el, dict):
        return ["%s 객체 아님" % where]
    for k in el:
        if k not in EL_KEYS:
            errs.append("%s 미지 키 %r — %s" % (where, k, "|".join(EL_KEYS)))
    for k in EL_REQUIRED:
        if k not in el:
            errs.append("%s 필수 키 누락: %s" % (where, k))
    if "id" in el and not (isinstance(el.get("id"), str) and el["id"].strip()):
        errs.append("%s id 비어있지 않은 문자열 필요" % where)
    for tk in ("in_ticks", "out_ticks", "intended_ticks"):
        if tk in el:
            v = el[tk]
            if not (isinstance(v, int) and not isinstance(v, bool)) or v < 0:
                errs.append("%s %s 0 이상 정수 틱 필요(%r)" % (where, tk, v))
    a, b = el.get("in_ticks"), el.get("out_ticks")
    if (isinstance(a, int) and not isinstance(a, bool)
            and isinstance(b, int) and not isinstance(b, bool) and b <= a):
        errs.append("%s out_ticks(%r) 는 in_ticks(%r)보다 커야 함" % (where, b, a))
    if "mode" in el and el.get("mode") not in EL_MODES:
        errs.append("%s mode 무효(%r) — %s" % (where, el.get("mode"), "|".join(EL_MODES)))
    if "transition" in el and el.get("transition") not in EL_TRANSITIONS:
        errs.append("%s transition 무효(%r) — %s" % (where, el.get("transition"), "|".join(EL_TRANSITIONS)))
    if "source" in el and not isinstance(el.get("source"), str):
        errs.append("%s source 는 문자열" % where)
    return errs


def validate_ir(obj):
    """정전 IR 구조 검증 → 오류 리스트(빈 리스트=준수). additionalProperties:false 등가(미지 키 거부)."""
    errs = []
    if not isinstance(obj, dict):
        return ["최상위가 객체(dict)가 아님"]
    for k in obj:
        if k not in TOP_KEYS:
            errs.append("미지 최상위 키 %r — %s" % (k, "|".join(TOP_KEYS)))
    for k in TOP_REQUIRED:
        if k not in obj:
            errs.append("필수 키 누락: %s" % k)
    if "schema_version" in obj and obj.get("schema_version") != SCHEMA_VERSION:
        errs.append("schema_version 은 %d 이어야 함(%r)" % (SCHEMA_VERSION, obj.get("schema_version")))
    if "render_runtime" in obj and not (isinstance(obj.get("render_runtime"), str) and obj["render_runtime"].strip()):
        errs.append("render_runtime 비어있지 않은 문자열 필요(무음 swap 방지·SF-RENDER-RUNTIME-SWAP)")
    if "ticks_per_second" in obj and obj.get("ticks_per_second") != TICKS_PER_SECOND:
        errs.append("ticks_per_second 는 %d 이어야 함(%r)" % (TICKS_PER_SECOND, obj.get("ticks_per_second")))
    if "fps" in obj:
        rate = normalize_rate(obj.get("fps"))
        if rate is None or ticks_per_frame(rate[0], rate[1]) is None:
            errs.append("fps 표현 불가(%r) — 표준 레이트 아님(120000 격자·추측 반올림 거부)" % obj.get("fps"))
    if "tracks" in obj:
        tracks = obj.get("tracks")
        if not isinstance(tracks, list) or not tracks:
            errs.append("tracks 는 비어있지 않은 배열이어야 함")
        else:
            for i, tr in enumerate(tracks):
                w = "tracks[%d]" % i
                if not isinstance(tr, dict):
                    errs.append("%s 객체 아님" % w)
                    continue
                for k in tr:
                    if k not in TRACK_KEYS:
                        errs.append("%s 미지 키 %r — %s" % (w, k, "|".join(TRACK_KEYS)))
                for k in TRACK_REQUIRED:
                    if k not in tr:
                        errs.append("%s 필수 키 누락: %s" % (w, k))
                if "kind" in tr and tr.get("kind") not in TRACK_KINDS:
                    errs.append("%s kind 무효(%r) — %s" % (w, tr.get("kind"), "|".join(TRACK_KINDS)))
                if "elements" in tr:
                    els = tr.get("elements")
                    if not isinstance(els, list):
                        errs.append("%s.elements 배열 아님" % w)
                    else:
                        for j, el in enumerate(els):
                            errs += _validate_element(el, "%s.elements[%d]" % (w, j))
    return errs


def cmd_validate(path, as_json):
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except FileNotFoundError:
        return fail(2, "파일 없음: %s" % path)
    except (OSError, json.JSONDecodeError) as e:
        return fail(2, "JSON 로드 실패: %s (%s)" % (path, e))
    errs = validate_ir(obj)
    ok = not errs
    if as_json:
        print(json.dumps({"ok": ok, "file": path, "schema_errors": errs}, ensure_ascii=False, indent=2))
    else:
        for e in errs:
            print("[SCHEMA] %s" % e)
        n = len(obj.get("tracks", [])) if isinstance(obj, dict) else 0
        print("edit_decisions IR: %s — %s (track %d)" % ("OK" if ok else "REJECT", path, n))
        if not ok:
            print("이 출력 외 추론으로 IR 정합을 선언하지 마라.")
    return 0 if ok else 1


# ── self-test ──
def self_test():
    failures = []

    def eq(name, got, want):
        if got != want:
            failures.append("%s: got %r want %r" % (name, got, want))

    def truthy(name, cond):
        if not cond:
            failures.append("%s: 거짓" % name)

    # 틱 격자 패리티 (frame_rate.rs:101-113 표와 동치)
    eq("tpf-24", ticks_per_frame(24, 1), 5000)
    eq("tpf-25", ticks_per_frame(25, 1), 4800)
    eq("tpf-30", ticks_per_frame(30, 1), 4000)
    eq("tpf-48", ticks_per_frame(48, 1), 2500)
    eq("tpf-50", ticks_per_frame(50, 1), 2400)
    eq("tpf-60", ticks_per_frame(60, 1), 2000)
    eq("tpf-120", ticks_per_frame(120, 1), 1000)
    eq("tpf-23.976", ticks_per_frame(24000, 1001), 5005)
    eq("tpf-29.97", ticks_per_frame(30000, 1001), 4004)
    eq("tpf-59.94", ticks_per_frame(60000, 1001), 2002)
    # 표현 불가 — 조용히 반올림하지 않고 None
    eq("tpf-7/3", ticks_per_frame(7, 3), None)
    eq("tpf-0", ticks_per_frame(0, 1), None)
    eq("tpf-neg", ticks_per_frame(-30, 1), None)

    # 레이트 정규화·스냅
    eq("norm-int", normalize_rate(30), (30, 1))
    eq("norm-float-2997", normalize_rate(29.97), (30000, 1001))
    eq("norm-float-23976", normalize_rate(23.976), (24000, 1001))
    eq("norm-str-rational", normalize_rate("30000/1001"), (30000, 1001))
    eq("norm-str-int", normalize_rate("60"), (60, 1))
    eq("norm-list", normalize_rate([24, 1]), (24, 1))
    eq("norm-reduce", normalize_rate("60/2"), (30, 1))
    eq("norm-bad-str", normalize_rate("abc"), None)
    eq("norm-bool", normalize_rate(True), None)
    eq("norm-far-float", normalize_rate(13.5), None)  # 표준 레이트와 0.05 밖 → 스냅 거부
    eq("norm-zero", normalize_rate(0), None)
    eq("norm-neg", normalize_rate(-30), None)

    # 초→틱·프레임 스냅 (half-up·음수 안전)
    eq("s2t-1.5", seconds_to_ticks(1.5), 180_000)
    eq("rt-frame-floor", round_ticks_to_frame(4000 * 5 + 1, 4000), 4000 * 5)        # 약간 위 → 내림
    eq("rt-frame-half", round_ticks_to_frame(4000 * 5 + 2000, 4000), 4000 * 6)      # 정확히 절반 → 올림
    eq("rt-frame-exact", round_ticks_to_frame(4000 * 5, 4000), 4000 * 5)
    eq("rt-frame-neg", round_ticks_to_frame(-1, 4000), 0)                            # -1틱 → 0프레임(half-up)

    # _is_num 가드
    truthy("isnum-int", _is_num(3))
    truthy("isnum-float", _is_num(3.5))
    truthy("isnum-bool-no", not _is_num(True))
    truthy("isnum-nan-no", not _is_num(float("nan")))
    truthy("isnum-inf-no", not _is_num(float("inf")))

    # check 라운드트립 (임시 파일·exit code·출력 격리)
    import contextlib
    import io
    import os
    import tempfile

    class A:  # argparse.Namespace 대용
        def __init__(self, **kw):
            self.__dict__.update(kw)

    sink = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="check-timeline-st-") as td:
        # GO: 30fps, 드리프트 0.1초(<0.3 허용)
        go = os.path.join(td, "go.json")
        with open(go, "w", encoding="utf-8") as f:
            json.dump({"fps": 30, "elements": [
                {"id": "g1", "intended": 3.5, "in": 3.6, "out": 8.0},
                {"id": "g2", "intended": 10.0, "in": 10.0, "out": 12.0},
            ]}, f)
        with contextlib.redirect_stdout(sink):
            rc = cmd_check(A(timeline=go, fps=None, probe=None,
                            tolerance_frames=None, tolerance_seconds=None, json=True))
        eq("check-go-exit", rc, 0)

        # NO_GO: 드리프트 0.5초(>0.3 허용)
        nogo = os.path.join(td, "nogo.json")
        with open(nogo, "w", encoding="utf-8") as f:
            json.dump({"fps": 30, "elements": [
                {"id": "late", "intended": 3.0, "in": 3.5, "out": 8.0}]}, f)
        with contextlib.redirect_stdout(sink):
            rc = cmd_check(A(timeline=nogo, fps=None, probe=None,
                            tolerance_frames=None, tolerance_seconds=None, json=True))
        eq("check-nogo-exit", rc, 1)

        # 표현 불가 fps → exit 2
        bad = os.path.join(td, "badfps.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"fps": "7/3", "elements": [{"id": "g", "intended": 1.0, "in": 1.0}]}, f)
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            rc = cmd_check(A(timeline=bad, fps=None, probe=None,
                            tolerance_frames=None, tolerance_seconds=None, json=True))
        eq("check-badfps-exit", rc, 2)

        # tracks·elements 모두 부재 → 계약 미준수 exit 2 (구조 위반 탐지는 validate 소관, check는
        # 수집 불가만 거른다). 빈 tracks([])는 구조적으로 유효하나 비어있어 검사 0건→GO(별도 케이스).
        noel = os.path.join(td, "noel.json")
        with open(noel, "w", encoding="utf-8") as f:
            json.dump({"fps": 30, "stuff": 1}, f)
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            rc = cmd_check(A(timeline=noel, fps=None, probe=None,
                            tolerance_frames=None, tolerance_seconds=None, json=True))
        eq("check-noel-exit", rc, 2)
        # 빈 tracks → 검사 0건 → GO(exit 0): check는 타이밍만, 빈 IR 구조 위반은 validate가 잡는다
        empty_tr = os.path.join(td, "empty_tracks.json")
        with open(empty_tr, "w", encoding="utf-8") as f:
            json.dump({"fps": 30, "tracks": []}, f)
        with contextlib.redirect_stdout(sink):
            rc = cmd_check(A(timeline=empty_tr, fps=None, probe=None,
                            tolerance_frames=None, tolerance_seconds=None, json=True))
        eq("check-empty-tracks-go", rc, 0)

        # fps 미지정(timeline에도 없음) → exit 2
        nofps = os.path.join(td, "nofps.json")
        with open(nofps, "w", encoding="utf-8") as f:
            json.dump({"elements": [{"id": "g", "intended": 1.0, "in": 1.0}]}, f)
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            rc = cmd_check(A(timeline=nofps, fps=None, probe=None,
                            tolerance_frames=None, tolerance_seconds=None, json=True))
        eq("check-nofps-exit", rc, 2)

        # 없는 파일 → exit 2
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            rc = cmd_check(A(timeline=os.path.join(td, "nope.json"), fps=None, probe=None,
                            tolerance_frames=None, tolerance_seconds=None, json=True))
        eq("check-nofile-exit", rc, 2)

        # --tolerance-frames 1: 0.1초@30fps=3프레임 드리프트 → NO_GO(1프레임 허용 초과)
        with contextlib.redirect_stdout(sink):
            rc = cmd_check(A(timeline=go, fps=None, probe=None,
                            tolerance_frames=1, tolerance_seconds=None, json=True))
        eq("check-tolframe1-exit", rc, 1)

        # intended/in 부재 element는 건너뜀(검증 대상 아님·에러 아님) → GO
        skip = os.path.join(td, "skip.json")
        with open(skip, "w", encoding="utf-8") as f:
            json.dump({"fps": 30, "elements": [
                {"id": "caption", "in": 5.0},                         # intended 없음 → skip
                {"id": "g1", "intended": 2.0, "in": 2.0}]}, f)        # 검증 대상·드리프트 0
        with contextlib.redirect_stdout(sink):
            rc = cmd_check(A(timeline=skip, fps=None, probe=None,
                            tolerance_frames=None, tolerance_seconds=None, json=True))
        eq("check-skip-exit", rc, 0)

    # ── validate_ir 단위 검증 (정전 IR 스키마) ──
    def ir(**over):
        base = {"schema_version": 1, "render_runtime": "hyperframes", "fps": 30,
                "tracks": [{"kind": "avatar",
                            "elements": [{"id": "a1", "in_ticks": 0, "out_ticks": 4000}]}]}
        base.update(over)
        return base

    def vir(name, obj, want_ok, want_sub=None):
        e = validate_ir(obj)
        ok = not e
        if ok != want_ok:
            failures.append("vir %s: ok=%s want=%s errs=%s" % (name, ok, want_ok, e))
        if want_sub and not any(want_sub in x for x in e):
            failures.append("vir %s: %r 없음 — %s" % (name, want_sub, e))

    vir("ir-happy", ir(), True)
    vir("ir-unknown-top", ir(extra=1), False, "미지 최상위 키")
    vir("ir-no-runtime", {k: v for k, v in ir().items() if k != "render_runtime"}, False, "필수 키 누락: render_runtime")
    vir("ir-bad-ver", ir(schema_version=2), False, "schema_version")
    vir("ir-empty-runtime", ir(render_runtime="  "), False, "render_runtime")
    vir("ir-bad-fps", ir(fps="7/3"), False, "fps 표현 불가")
    vir("ir-bad-tps", ir(ticks_per_second=48000), False, "ticks_per_second")
    vir("ir-empty-tracks", ir(tracks=[]), False, "비어있지 않은 배열")
    vir("ir-bad-kind", ir(tracks=[{"kind": "hologram", "elements": []}]), False, "kind 무효")
    vir("ir-track-unknown", ir(tracks=[{"kind": "avatar", "elements": [], "x": 1}]), False, "미지 키")
    vir("ir-el-missing", ir(tracks=[{"kind": "avatar", "elements": [{"id": "a", "in_ticks": 0}]}]), False, "필수 키 누락: out_ticks")
    vir("ir-el-float", ir(tracks=[{"kind": "avatar", "elements": [{"id": "a", "in_ticks": 0.5, "out_ticks": 4000}]}]), False, "정수 틱")
    vir("ir-el-bool", ir(tracks=[{"kind": "avatar", "elements": [{"id": "a", "in_ticks": True, "out_ticks": 4000}]}]), False, "정수 틱")
    vir("ir-el-neg", ir(tracks=[{"kind": "avatar", "elements": [{"id": "a", "in_ticks": -1, "out_ticks": 4000}]}]), False, "정수 틱")
    vir("ir-el-out-le-in", ir(tracks=[{"kind": "avatar", "elements": [{"id": "a", "in_ticks": 4000, "out_ticks": 4000}]}]), False, "out_ticks")
    vir("ir-el-bad-mode", ir(tracks=[{"kind": "broll", "elements": [{"id": "b", "in_ticks": 0, "out_ticks": 4000, "mode": "ken-burns"}]}]), False, "mode 무효")
    vir("ir-el-bad-trans", ir(tracks=[{"kind": "broll", "elements": [{"id": "b", "in_ticks": 0, "out_ticks": 4000, "transition": "wipe"}]}]), False, "transition 무효")
    vir("ir-el-gpu-field", ir(tracks=[{"kind": "graphic", "elements": [{"id": "g", "in_ticks": 0, "out_ticks": 4000, "blend_mode": "screen"}]}]), False, "미지 키")
    vir("ir-good-full", ir(tracks=[{"kind": "graphic", "elements": [
        {"id": "g1", "in_ticks": 0, "out_ticks": 8008, "intended_ticks": 0,
         "mode": "left-card", "transition": "slide", "source": "gfx/g1.html"}]}]), True)

    # ── 정전 IR(tracks·정수 틱) cmd_check 라운드트립 ──
    with tempfile.TemporaryDirectory(prefix="check-timeline-ir-") as td2:
        irfile = os.path.join(td2, "edit_decisions.json")
        with open(irfile, "w", encoding="utf-8") as f:
            json.dump(ir(tracks=[{"kind": "graphic", "elements": [
                {"id": "g1", "in_ticks": 120000, "out_ticks": 480000, "intended_ticks": 120000}]}]), f)
        with contextlib.redirect_stdout(sink):
            rc = cmd_check(A(timeline=irfile, fps=None, probe=None,
                            tolerance_frames=None, tolerance_seconds=None, json=True))
        eq("check-ir-ticks-go", rc, 0)
        with open(irfile, "w", encoding="utf-8") as f:  # 1초(120000틱) 드리프트 → NO_GO
            json.dump(ir(tracks=[{"kind": "graphic", "elements": [
                {"id": "g1", "in_ticks": 240000, "out_ticks": 480000, "intended_ticks": 120000}]}]), f)
        with contextlib.redirect_stdout(sink):
            rc = cmd_check(A(timeline=irfile, fps=None, probe=None,
                            tolerance_frames=None, tolerance_seconds=None, json=True))
        eq("check-ir-ticks-nogo", rc, 1)
        # validate cmd 라운드트립: 준수=0, 위반=1, 없는 파일=2
        with contextlib.redirect_stdout(sink):
            if cmd_validate(irfile, True) != 0:
                failures.append("cmd_validate(준수 IR) exit 0 아님")
        bad_ir = os.path.join(td2, "bad.json")
        with open(bad_ir, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 1, "tracks": []}, f)  # render_runtime·fps 누락 + 빈 tracks
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_validate(bad_ir, True) != 1:
                failures.append("cmd_validate(위반 IR) exit 1 아님")
            if cmd_validate(os.path.join(td2, "nope.json"), True) != 2:
                failures.append("cmd_validate(없는 파일) exit 2 아님")

        # boundaries(W2-3 replay-verify): 선언 컷 경계 vs 측정 경계 프레임 비교
        bfile = os.path.join(td2, "b.json")
        with open(bfile, "w", encoding="utf-8") as f:
            json.dump({"fps": 30, "declared_ticks": [120000, 480000],
                       "measured_seconds": [1.0, 4.0]}, f)  # 정확 일치 → GO
        with contextlib.redirect_stdout(sink):
            if cmd_boundaries(A(input=bfile, fps=None, probe=None, tolerance_frames=1, json=True)) != 0:
                failures.append("boundaries(일치) exit 0 아님")
        with open(bfile, "w", encoding="utf-8") as f:
            json.dump({"fps": 30, "declared_ticks": [120000],
                       "measured_seconds": [1.5]}, f)  # 0.5초=15프레임 어긋남 → NO_GO
        with contextlib.redirect_stdout(sink):
            if cmd_boundaries(A(input=bfile, fps=None, probe=None, tolerance_frames=1, json=True)) != 1:
                failures.append("boundaries(불일치) exit 1 아님")
        with open(bfile, "w", encoding="utf-8") as f:
            json.dump({"fps": 30, "declared_ticks": "x", "measured_seconds": []}, f)  # 배열 아님
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_boundaries(A(input=bfile, fps=None, probe=None, tolerance_frames=1, json=True)) != 2:
                failures.append("boundaries(잘못된 입력) exit 2 아님")

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="모션그래픽 타이밍의 결정론적 정수-틱 프레임 검증")
    ap.add_argument("--self-test", action="store_true", help="결정론 자기검증")
    sub = ap.add_subparsers(dest="cmd")

    va = sub.add_parser("validate", help="편집-결정 IR(edit_decisions.json) 구조 검증 (0=준수 1=위반 2=입출력)")
    va.add_argument("file")
    va.add_argument("--json", action="store_true")

    fp = sub.add_parser("fps", help="레이트 표현성·ticks_per_frame (0=표현 가능 2=불가)")
    fp.add_argument("--fps", help="프레임레이트(정수·소수·num/den)")
    fp.add_argument("--probe", help="ffprobe로 fps를 읽을 비디오 경로")

    ck = sub.add_parser("check", help="timeline.json 타이밍 드리프트 판정 (0=GO 1=NO_GO 2=입력오류)")
    ck.add_argument("timeline")
    ck.add_argument("--fps", help="프레임레이트 명시(우선순위 최상)")
    ck.add_argument("--probe", help="ffprobe로 fps 탐지할 비디오 경로")
    ck.add_argument("--tolerance-frames", type=int, default=None, dest="tolerance_frames",
                    help="허용 드리프트(프레임). 지정 시 --tolerance-seconds보다 우선")
    ck.add_argument("--tolerance-seconds", type=float, default=None, dest="tolerance_seconds",
                    help="허용 드리프트(초·기본 0.3 — 현행 SKILL 보존)")
    ck.add_argument("--json", action="store_true")

    bd = sub.add_parser("boundaries", help="렌더 충실도: 선언 컷 경계 vs 측정 경계 (0=GO 1=NO_GO 2=입출력)")
    bd.add_argument("--input", required=True, help="{fps?,declared_ticks[],measured_seconds[]}")
    bd.add_argument("--fps", help="프레임레이트 명시(우선)")
    bd.add_argument("--probe", help="ffprobe로 fps 탐지할 비디오 경로")
    bd.add_argument("--tolerance-frames", type=int, default=None, dest="tolerance_frames",
                    help="허용 프레임 오차(기본 1 — keyframe-강제 컷 지점)")
    bd.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.cmd == "validate":
        return cmd_validate(args.file, args.json)
    if args.cmd == "fps":
        return cmd_fps(args)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "boundaries":
        return cmd_boundaries(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
