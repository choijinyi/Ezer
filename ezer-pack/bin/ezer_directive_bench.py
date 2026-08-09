#!/usr/bin/env python3
"""ezer_directive_bench.py — 디렉티브 회귀 트립와이어 (OMC OPP-18 클린룸 포트) — 개선 채점기가 아니다: ceiling(1.0) 출생 baseline은 회귀 검출 전용이며 개선 측정은 headroom metric 추가 후에만(스킬 Rule 7)

목적: 라이브 절대지침(MASTER·WORKER·CSO·REVIEWER)이 "결함 행동"을 실제로 금지·경계하는지를
결정론으로 채점한다. LLM을 호출하지 않는다 — fixture의 must_flag 키워드가 해당 디렉티브
텍스트에 실재하는지를 소문자·연속공백 정규화 후 부분일치로 확인할 뿐이다.

채점 계약:
- fixture 스키마: {"id","scenario","directive":"MASTER|WORKER|CSO|REVIEWER",
  "must_flag":[...소문자 키워드구...],"must_not":[...있으면 감점...]}
- 정규화: 소문자화 + 연속공백 1개로 축약. 매칭: normalize(키워드) in normalize(디렉티브 텍스트).
- miss_rate  = (전체 must_flag 중 미커버 수) / (전체 must_flag 수)
- hit_rate   = (전체 must_not 중 검출 수) / (전체 must_not 수)   (must_not 0개면 0)
- composite  = 1.0 - 0.20*miss_rate - 0.05*hit_rate   (하한 0.0)
- 동일 입력 → 동일 출력(결정론).

CLI:
- score --directive-dir <dir>              : composite + per_fixture JSON 출력
- score --directive-dir <dir> --save-baseline <file>
      : 현행 점수 + 디렉티브 4종 SHA-256을 <file>에 저장
- score --directive-dir <dir> --compare <file>
      : baseline 대비 composite 하락 >0.01 이면 회귀(exit 1). baseline 부재면 즉시 exit 1.

exit codes: 0 ok/합격 · 1 회귀/baseline부재 · 2 usage
"""
import argparse
import hashlib
import json
import os
import re
import sys

EXIT_OK, EXIT_REGRESS, EXIT_USAGE = 0, 1, 2

# 회귀 판정 임계 — composite 하락이 이 값을 초과하면 회귀로 본다.
REGRESS_EPS = 0.01

# 역할 → 디렉티브 파일명 (--directive-dir 하위에서 이 이름으로 찾는다)
DIRECTIVE_FILES = {
    "MASTER": "MASTER_DIRECTIVE.md",
    "WORKER": "WORKER_DIRECTIVE.md",
    "CSO": "CSO_DIRECTIVE.md",
    "REVIEWER": "REVIEWER_DIRECTIVE.md",
}

# 기본 경로: 라이브 팩 디렉티브 · 동봉 fixtures
_PACK_DIR = os.environ.get("EZER_PACK_DIR", os.path.expanduser("~/.ezer/pack"))
DEFAULT_DIRECTIVE_DIR = os.path.join(_PACK_DIR, "directives")
DEFAULT_FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench", "fixtures")


def normalize(text):
    """소문자화 + 연속공백(개행 포함) 1개로 축약."""
    return re.sub(r"\s+", " ", text.lower())


def load_fixtures(fixtures_dir):
    """fixtures_dir 의 *.json 을 id 오름차순으로 로드(결정론 순서)."""
    fixtures = []
    for name in sorted(os.listdir(fixtures_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(fixtures_dir, name), encoding="utf-8") as fh:
            fixtures.append(json.load(fh))
    fixtures.sort(key=lambda fx: fx["id"])
    return fixtures


def resolve_directive_path(directive_dir, fname, stage_pre_ceo):
    """채점 대상 경로 해석. --stage-pre-ceo 시 MASTER는 승격 보존본(.pre-ceo)이 정본이다 —
    CEO 승격 상태(ezer-dept가 라이브를 CEO 규약으로 교체)에서 라이브를 채점하면 승격 자체가
    영구 회귀로 잡힌다. save-baseline과 compare(preflight C64)가 같은 플래그를 쓰면 재핀
    의례와 비교가 구조적으로 비대칭일 수 없다. 마커 부재면 no-op(비승격에서 같은 명령 유효)."""
    if stage_pre_ceo and fname == "MASTER_DIRECTIVE.md":
        marker = os.path.join(directive_dir, fname + ".pre-ceo")
        if os.path.isfile(marker):
            return marker
    return os.path.join(directive_dir, fname)


def load_directive_texts(directive_dir, stage_pre_ceo=False):
    """역할 → 정규화된 디렉티브 텍스트. 파일 부재 시 빈 문자열(해당 fixture 전건 미커버)."""
    texts = {}
    missing = []
    for role, fname in DIRECTIVE_FILES.items():
        path = resolve_directive_path(directive_dir, fname, stage_pre_ceo)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                texts[role] = normalize(fh.read())
        else:
            texts[role] = ""
            missing.append(fname)
    return texts, missing


def sha256_map(directive_dir, stage_pre_ceo=False):
    """디렉티브 4종의 SHA-256(원본 바이트). 파일 부재 시 값은 null."""
    result = {}
    for role, fname in DIRECTIVE_FILES.items():
        path = resolve_directive_path(directive_dir, fname, stage_pre_ceo)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                result[fname] = hashlib.sha256(fh.read()).hexdigest()
        else:
            result[fname] = None
    return result


def score(fixtures, directive_texts):
    """composite + per_fixture 산출(결정론)."""
    per_fixture = []
    flag_total = flag_missed = 0
    mustnot_total = mustnot_hit_cnt = 0

    for fx in fixtures:
        text = directive_texts.get(fx["directive"], "")
        flags = fx.get("must_flag", [])
        mustnot = fx.get("must_not", [])

        covered = [k for k in flags if normalize(k) in text]
        missed = [k for k in flags if normalize(k) not in text]
        mn_hit = [k for k in mustnot if normalize(k) in text]

        flag_total += len(flags)
        flag_missed += len(missed)
        mustnot_total += len(mustnot)
        mustnot_hit_cnt += len(mn_hit)

        per_fixture.append({
            "id": fx["id"],
            "directive": fx["directive"],
            "flag_total": len(flags),
            "flag_covered": len(covered),
            "flag_missed": missed,
            "mustnot_total": len(mustnot),
            "mustnot_hit": mn_hit,
            "coverage": round(len(covered) / len(flags), 4) if flags else 1.0,
        })

    miss_rate = (flag_missed / flag_total) if flag_total else 0.0
    hit_rate = (mustnot_hit_cnt / mustnot_total) if mustnot_total else 0.0
    composite = max(0.0, 1.0 - 0.20 * miss_rate - 0.05 * hit_rate)

    return {
        "composite": round(composite, 4),
        "miss_rate": round(miss_rate, 4),
        "hit_rate": round(hit_rate, 4),
        "per_fixture": per_fixture,
    }


def _dump(obj):
    """결정론 JSON 문자열(키 정렬·비ASCII 보존)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)


def cmd_score(args):
    """score 서브커맨드 — 채점하고 필요 시 baseline 저장/비교."""
    fixtures = load_fixtures(args.fixtures_dir)
    texts, missing = load_directive_texts(args.directive_dir, args.stage_pre_ceo)
    result = score(fixtures, texts)
    if missing:
        result["missing_directives"] = missing

    # --compare: baseline 대비 회귀 판정 (composite 기준)
    if args.compare is not None:
        if not os.path.isfile(args.compare):
            print("baseline 없음 — placeholder 금지", file=sys.stderr)
            return EXIT_REGRESS
        with open(args.compare, encoding="utf-8") as fh:
            baseline = json.load(fh)
        base_composite = baseline["composite"]
        cur = result["composite"]
        drop = base_composite - cur
        # flag-소실 규칙(critic-gov R1): 24개 flag 중 1개 소실은 composite drop 0.0083으로
        # 임계(0.01) 미달 — 트립와이어가 구조적으로 무디다. baseline에서 covered였던 flag가
        # 지금 missed면 drop 크기와 무관하게 즉시 회귀로 판정한다.
        base_missed = {f["id"]: set(f.get("flag_missed", []))
                       for f in baseline.get("per_fixture", [])}
        lost_flags = []
        for f in result["per_fixture"]:
            newly = [k for k in f["flag_missed"] if k not in base_missed.get(f["id"], set())]
            if newly:
                lost_flags.append({"id": f["id"], "lost": newly})
        regression = drop > REGRESS_EPS or bool(lost_flags)
        report = {
            "baseline_composite": base_composite,
            "current_composite": cur,
            "drop": round(drop, 4),
            "threshold": REGRESS_EPS,
            "lost_flags": lost_flags,
            "regression": regression,
        }
        print(_dump(report))
        return EXIT_REGRESS if regression else EXIT_OK

    # --save-baseline: 현행 점수 + 디렉티브 SHA-256 저장
    if args.save_baseline is not None:
        baseline = {
            "composite": result["composite"],
            "miss_rate": result["miss_rate"],
            "hit_rate": result["hit_rate"],
            "per_fixture": result["per_fixture"],
            "directive_sha256": sha256_map(args.directive_dir, args.stage_pre_ceo),
        }
        with open(args.save_baseline, "w", encoding="utf-8") as fh:
            fh.write(_dump(baseline))
        print(_dump({"composite": result["composite"], "saved": args.save_baseline}))
        return EXIT_OK

    # 기본: 채점 결과 출력
    print(_dump(result))
    return EXIT_OK


def build_parser():
    p = argparse.ArgumentParser(description="디렉티브 회귀 벤치 (LLM 무호출·결정론 채점)")
    sub = p.add_subparsers(dest="cmd")

    sc = sub.add_parser("score", help="디렉티브를 fixture로 채점")
    sc.add_argument("--directive-dir", default=DEFAULT_DIRECTIVE_DIR,
                    help="채점 대상 디렉티브 폴더(기본: 라이브 팩)")
    sc.add_argument("--fixtures-dir", default=DEFAULT_FIXTURES_DIR,
                    help="fixture 폴더(기본: 동봉 bench/fixtures)")
    sc.add_argument("--save-baseline", metavar="FILE", default=None,
                    help="현행 점수+디렉티브 SHA-256 저장")
    sc.add_argument("--compare", metavar="FILE", default=None,
                    help="baseline 대비 회귀 판정(하락>0.01=exit 1·부재=exit 1)")
    sc.add_argument("--stage-pre-ceo", action="store_true",
                    help="CEO 승격 상태면 MASTER를 보존본(.pre-ceo)으로 채점(마커 부재 시 no-op) — "
                         "save-baseline·compare 양쪽에 같이 써서 재핀/비교 대칭을 보장")
    sc.set_defaults(func=cmd_score)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
