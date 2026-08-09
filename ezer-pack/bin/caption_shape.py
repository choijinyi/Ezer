#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caption_shape — 단어 타임스탬프를 읽기 좋은 자막 큐로 묶는 **결정론·제로토큰** 셰이퍼.

caption-align의 forced-alignment가 단어별 start/end를 주면, 이 도구가 LLM 없이(제로토큰)
순수 규칙으로 자막 큐(cue)를 만든다 — N-words/cue + 최소 표시시간 + 자연 휴지 분할 + **비중첩**.
OpenCut 자막 셰이핑 발상(결정론 그룹핑) 클린룸 이식. 같은 입력→같은 출력(결정론).

규칙(전부 ParamDefinition로 외부화 — ezer_params와 동형):
- max_words: 큐당 최대 단어 수(가독성)
- max_chars: 큐당 최대 글자 수(한 줄 과밀 방지) — 초과 예상 시 현재 큐 마감
- gap_split_s: 직전 단어 end와 다음 단어 start 간극이 이 값 초과면 자연 휴지로 새 큐 시작
- min_duration_s: 큐가 너무 짧으면 end를 늘려 이 최소 표시시간 보장(단 다음 큐 start 침범 금지=비중첩)

입력: transcript.json/captions.json 형태 — segments[].words[]{w,start,end} 또는 최상위 words[].
출력: captions.json — {cues:[{start,end,text,words:[...]}]} (start≤end·비중첩·소스 경계 안).

사용:
    python3 caption_shape.py shape --input transcript.json [--out captions.json] \
        [--max-words 7] [--max-chars 42] [--gap-split 0.8] [--min-duration 1.0] [--json]
    python3 caption_shape.py --self-test
종료 코드: 0 성공 · 1 단어 없음·타이밍 무효(start>end 등) · 2 인자/입출력/JSON 오류.
의존성: 파이썬 표준 라이브러리만(네트워크·LLM·점수 없음·결정론).
"""

import argparse
import json
import sys

DEFAULTS = {"max_words": 7, "max_chars": 42, "gap_split_s": 0.8, "min_duration_s": 1.0}


def fail(code, msg):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    return code


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def collect_words(doc):
    """transcript/captions 문서에서 단어 리스트 평탄화 → (words, 에러).
    지원: 최상위 words[], segments[].words[], cues[].words[]. 각 단어 {w,start,end}."""
    if not isinstance(doc, dict):
        return None, "최상위가 객체(dict)가 아님"
    buckets = None
    for container in ("segments", "cues"):
        if isinstance(doc.get(container), list):
            buckets = doc[container]
            break
    words = []
    if buckets is not None:
        for seg in buckets:
            if isinstance(seg, dict) and isinstance(seg.get("words"), list):
                words.extend(seg["words"])
    elif isinstance(doc.get("words"), list):
        words = doc["words"]
    else:
        return None, "단어 출처 없음 — words[] 또는 segments[].words[]/cues[].words[] 필요"
    norm = []
    for i, wd in enumerate(words):
        if not isinstance(wd, dict):
            return None, "words[%d] 객체 아님" % i
        text = wd.get("w", wd.get("word", wd.get("text")))
        s, e = wd.get("start"), wd.get("end")
        if not (isinstance(text, str) and _is_num(s) and _is_num(e)):
            return None, "words[%d] {w,start,end} 필요(%r)" % (i, wd)
        if e < s:
            return None, "words[%d] end<start (%s<%s)" % (i, e, s)
        norm.append({"w": text, "start": float(s), "end": float(e)})
    return norm, None


def shape_cues(words, p):
    """단어 → 자막 큐(결정론). N-words·max-chars·gap-split로 그룹, min-duration 보장(비중첩)."""
    cues = []
    cur = []

    def flush():
        if cur:
            cues.append({
                "start": cur[0]["start"],
                "end": cur[-1]["end"],
                "text": " ".join(w["w"] for w in cur),
                "words": [dict(w) for w in cur],
            })

    for i, wd in enumerate(words):
        if cur:
            prospective_chars = len(" ".join(w["w"] for w in cur)) + 1 + len(wd["w"])
            gap = wd["start"] - cur[-1]["end"]
            if (len(cur) >= p["max_words"]
                    or prospective_chars > p["max_chars"]
                    or gap > p["gap_split_s"]):
                flush()
                cur = []
        cur.append(wd)
    flush()

    # 최소 표시시간 보장 + 비중첩: end를 늘리되 다음 큐 start를 침범하지 않는다.
    for idx, cue in enumerate(cues):
        if cue["end"] - cue["start"] < p["min_duration_s"]:
            desired = cue["start"] + p["min_duration_s"]
            if idx + 1 < len(cues):
                desired = min(desired, cues[idx + 1]["start"])
            cue["end"] = max(cue["end"], desired)
        # 비중첩 강제(부동소수 잔재·역전 방지): 다음 큐 start ≥ 현재 end
        if idx + 1 < len(cues) and cues[idx + 1]["start"] < cue["end"]:
            cue["end"] = cues[idx + 1]["start"]
    return cues


def cmd_shape(args):
    try:
        with open(args.input, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return fail(2, "입력 파일 없음: %s" % args.input)
    except (OSError, json.JSONDecodeError) as e:
        return fail(2, "입력 JSON 로드 실패: %s (%s)" % (args.input, e))
    words, err = collect_words(doc)
    if err:
        return fail(2, err)
    if not words:
        return fail(1, "단어 0개 — 셰이핑 불가(전사를 단어 단위로 재실행)")
    p = {"max_words": args.max_words, "max_chars": args.max_chars,
         "gap_split_s": args.gap_split, "min_duration_s": args.min_duration}
    if p["max_words"] < 1 or p["max_chars"] < 1 or p["gap_split_s"] < 0 or p["min_duration_s"] < 0:
        return fail(2, "파라미터 범위 오류(max_words≥1·max_chars≥1·gap/min≥0)")
    cues = shape_cues(words, p)
    out = {"provider": "caption_shape", "params": p,
           "source": doc.get("source"), "language": doc.get("language"), "cues": cues}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    if args.json or not args.out:
        print(json.dumps(out if args.json else
                         {"ok": True, "cues": len(cues), "out": args.out},
                         ensure_ascii=False, indent=2))
    else:
        print("caption_shape: %d cues → %s" % (len(cues), args.out))
    return 0


def self_test():
    failures = []

    def words_seq(n, dur=0.3, gap=0.05, start=0.0):
        out = []
        t = start
        for i in range(n):
            out.append({"w": "w%d" % i, "start": round(t, 3), "end": round(t + dur, 3)})
            t += dur + gap
        return out

    P = dict(DEFAULTS)

    # 1) N-words 그룹: 16단어, max_words=7 → 3 큐(7+7+2)
    cues = shape_cues(words_seq(16), P)
    if [len(c["words"]) for c in cues] != [7, 7, 2]:
        failures.append("max_words 그룹 실패: %s" % [len(c["words"]) for c in cues])

    # 2) gap_split: 큰 간극에서 분할
    ws = words_seq(3) + [{"w": "after", "start": 10.0, "end": 10.3}]
    cues = shape_cues(ws, P)
    if len(cues) != 2 or cues[1]["words"][0]["w"] != "after":
        failures.append("gap_split 실패: %s" % [[w["w"] for w in c["words"]] for c in cues])

    # 3) max_chars: 긴 단어들로 글자수 초과 시 분할
    longw = [{"w": "x" * 20, "start": i * 0.5, "end": i * 0.5 + 0.3} for i in range(3)]
    cues = shape_cues(longw, dict(P, max_chars=42))
    if all(len(c["words"]) == 3 for c in cues):
        failures.append("max_chars 분할 실패(한 큐에 전부): %s" % [len(c["words"]) for c in cues])

    # 4) min_duration: 짧은 단일 단어 큐의 end가 최소시간으로 연장(다음 큐 없으면)
    cues = shape_cues([{"w": "hi", "start": 0.0, "end": 0.2}], dict(P, min_duration_s=1.0))
    if abs(cues[0]["end"] - 1.0) > 1e-6:
        failures.append("min_duration 연장 실패: %s" % cues[0]["end"])

    # 5) 비중첩: min_duration 연장이 다음 큐 start를 침범하지 않음
    ws = [{"w": "a", "start": 0.0, "end": 0.2}, {"w": "b", "start": 0.5, "end": 5.0}]
    cues = shape_cues(ws, dict(P, min_duration_s=1.0, gap_split_s=0.1))  # gap 0.3>0.1 → 분할
    if len(cues) != 2:
        failures.append("비중첩 셋업 분할 실패: %d" % len(cues))
    elif cues[0]["end"] > cues[1]["start"] + 1e-9:
        failures.append("비중첩 위반: cue0.end=%s > cue1.start=%s" % (cues[0]["end"], cues[1]["start"]))

    # 6) 결정론: 같은 입력 두 번 → 동일
    a = shape_cues(words_seq(16), P)
    b = shape_cues(words_seq(16), P)
    if json.dumps(a) != json.dumps(b):
        failures.append("비결정 셰이핑")

    # 7) collect_words: segments·최상위·cues 출처 + 오류
    w1, e1 = collect_words({"segments": [{"words": words_seq(2)}, {"words": words_seq(2, start=5)}]})
    if e1 or len(w1) != 4:
        failures.append("collect segments 실패: %s %s" % (e1, w1 and len(w1)))
    w2, e2 = collect_words({"words": words_seq(3)})
    if e2 or len(w2) != 3:
        failures.append("collect 최상위 words 실패")
    _, e3 = collect_words({"foo": 1})
    if not e3:
        failures.append("단어 출처 없음이 오류 아님")
    _, e4 = collect_words({"words": [{"w": "x", "start": 1.0, "end": 0.5}]})
    if not e4:
        failures.append("end<start가 오류 아님")

    # 8) cmd 라운드트립
    import contextlib
    import io
    import os
    import tempfile

    class A:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    sink = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="caption-shape-st-") as td:
        tp = os.path.join(td, "transcript.json")
        json.dump({"source": "a.mp4", "language": "ko",
                   "segments": [{"words": words_seq(16)}]}, open(tp, "w", encoding="utf-8"))
        outp = os.path.join(td, "captions.json")
        with contextlib.redirect_stdout(sink):
            rc = cmd_shape(A(input=tp, out=outp, max_words=7, max_chars=42,
                            gap_split=0.8, min_duration=1.0, json=False))
        if rc != 0:
            failures.append("cmd_shape exit 0 아님")
        cap = json.load(open(outp, encoding="utf-8"))
        if len(cap["cues"]) != 3:
            failures.append("cmd 출력 큐 수 예상밖: %d" % len(cap["cues"]))
        empty = os.path.join(td, "empty.json")
        json.dump({"segments": []}, open(empty, "w", encoding="utf-8"))
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            if cmd_shape(A(input=empty, out=None, max_words=7, max_chars=42,
                          gap_split=0.8, min_duration=1.0, json=True)) != 1:
                failures.append("단어 0개가 exit 1 아님")
            if cmd_shape(A(input=os.path.join(td, "nope.json"), out=None, max_words=7,
                          max_chars=42, gap_split=0.8, min_duration=1.0, json=True)) != 2:
                failures.append("없는 파일이 exit 2 아님")

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="결정론·제로토큰 자막 큐 셰이퍼")
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("shape", help="단어 타임스탬프 → 자막 큐 (0=성공 1=단어없음/무효 2=입출력)")
    s.add_argument("--input", required=True)
    s.add_argument("--out", default=None)
    s.add_argument("--max-words", type=int, default=DEFAULTS["max_words"], dest="max_words")
    s.add_argument("--max-chars", type=int, default=DEFAULTS["max_chars"], dest="max_chars")
    s.add_argument("--gap-split", type=float, default=DEFAULTS["gap_split_s"], dest="gap_split")
    s.add_argument("--min-duration", type=float, default=DEFAULTS["min_duration_s"], dest="min_duration")
    s.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.cmd == "shape":
        return cmd_shape(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
