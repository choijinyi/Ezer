#!/usr/bin/env python3
"""ezer_serena_eval.py — Serena crossover eval 하베스터 (S7 · 독립-노드 채점).

설계서: _research/Serena기반_ezer_업그레이드_구현설계서.md §S7.
역할: Serena 토큰절감 주장을 ezer repo **측정 사실**로 전환하고, 작은-편집 crossover rule 을
      산출한다. PURE-PYTHON stdlib(json/subprocess/hashlib/argparse/pathlib만; MCP tool/hook 아님).

producer ≠ evaluator (file-level):
  - PRODUCER = 산출 워커가 task 별 double-run(arm A=Serena 심볼, arm B=빌트인 Read/Grep/Edit)을
    fixture git repo 에서 돌려 RUN-RECORD(기계 JSON)를 방출한다.
  - EVALUATOR = master 가 LOCKED 루브릭(ezer attest pin)으로 이 분석기를 직접 실행해 채점한다.
    Serena 로 혜택보는 노드의 self-score 가 아니다(Serena 자체 eval 약점 'agent evaluates itself' 미재현).

정직 경계(honesty):
  - 토큰 proxy = chars//4 (Serena CharCountEstimator avg_chars_per_token=4, analytics.py:77-82) — tiktoken 아님.
  - code-nav fraction 의 분모는 비코드(한국어 산문/SOT/설교/markdown) task 를 **제외**한다
    (symbol_tools.py:100-103: 비코드는 ValueError, 폴백 없음 → Serena 절감 0).
  - 틀린 편집 arm 은 FAIL(절감 주장 불가) — ground_truth_diff_sha 로 git-diff-verify.
  - 측정불가(worker 미마운트/attest mismatch/arm un-verifiable) = hard-fail(measurement_complete=false).

GATE: net-win 입증 + 구체 crossover_lines/factor 산출 전에는 directive 승격(crossover stanza) 금지.
"""
import argparse
import hashlib
import json
import sys

TOKEN_CHARS_PER_TOKEN = 4   # Serena CharCountEstimator avg_chars_per_token (analytics.py:77-82)
BUCKETS = (("1-3", 1, 3), ("10-30", 10, 30), ("50+", 50, 10 ** 9))


# ── 토큰 proxy ──────────────────────────────────────────────────────────────
def arm_tokens(rec):
    """RUN-RECORD 의 char 축 합 // 4 (input+output+prerequisite_read)."""
    chars = (int(rec.get("input_payload_chars", 0))
             + int(rec.get("output_payload_chars", 0))
             + int(rec.get("prerequisite_read_chars", 0)))
    return chars // TOKEN_CHARS_PER_TOKEN


def _sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _bucket_of(lines):
    for name, lo, hi in BUCKETS:
        if lo <= lines <= hi:
            return name
    return "1-3" if lines < 1 else "50+"


# ── verify-runs (결정론, git-diff-verify) ───────────────────────────────────
def verify_runs(rubric, runs):
    """arm 별 produced_diff sha 를 ground_truth_diff_sha 와 비교. 분류·counted 판정."""
    tasks = {t["id"]: t for t in rubric.get("tasks", [])}
    verdicts = []
    for rec in runs:
        tid = rec.get("task_id")
        t = tasks.get(tid)
        if t is None:
            verdicts.append({"task_id": tid, "arm": rec.get("arm"),
                             "kind": None, "diff_ok": False, "counted": False,
                             "reason": "task_id 루브릭에 없음"})
            continue
        kind = t.get("kind")
        # 비코드(nonapplicable-text)는 절감 분모에서 제외 — Serena 미적용.
        if kind == "nonapplicable-text":
            verdicts.append({"task_id": tid, "arm": rec.get("arm"), "kind": kind,
                             "diff_ok": None, "counted": False, "reason": "비코드 제외"})
            continue
        gt = t.get("ground_truth_diff_sha")
        diff_ok = (_sha(rec.get("produced_diff", "")) == gt) if gt else False
        clean = bool(rec.get("clean_after", False))
        counted = bool(diff_ok and clean)
        verdicts.append({"task_id": tid, "arm": rec.get("arm"), "kind": kind,
                         "diff_ok": diff_ok, "counted": counted,
                         "reason": ("ok" if counted else
                                    ("diff sha mismatch" if not diff_ok else "not clean_after"))})
    return verdicts


# ── score (master LOCKED ref launcher 만) ────────────────────────────────────
def score(rubric, runs):
    tasks = {t["id"]: t for t in rubric.get("tasks", [])}
    total_tasks = len(tasks)
    verdicts = verify_runs(rubric, runs)
    vmap = {(v["task_id"], v["arm"]): v for v in verdicts}

    excluded = sorted({t["id"] for t in rubric.get("tasks", [])
                       if t.get("kind") == "nonapplicable-text"})

    # task 별 양 arm 모두 counted 인 경우만 delta 계산.
    by_task_tokens = {}      # tid -> {"symbol": tok, "builtin": tok}
    by_task_calls = {}       # tid -> {"symbol": n, "builtin": n}
    for rec in runs:
        tid, arm = rec.get("task_id"), rec.get("arm")
        v = vmap.get((tid, arm))
        if not v or not v.get("counted"):
            continue
        by_task_tokens.setdefault(tid, {})[arm] = arm_tokens(rec)
        by_task_calls.setdefault(tid, {})[arm] = int(rec.get("tool_call_count", 0))

    code_nav_complete = 0       # symbol arm 이 counted 된 code-nav task 수
    free_lsp_delta = 0          # Σ(armB - armA) over code-nav+edit, 양 arm counted
    per_bucket = {b[0]: 0 for b in BUCKETS}
    per_bucket_n = {b[0]: 0 for b in BUCKETS}
    neg_tasks = []              # delta<0 (심볼이 더 비쌈) — crossover 후보
    measurement_complete = True

    for tid, t in tasks.items():
        kind = t.get("kind")
        if kind == "nonapplicable-text":
            continue
        toks = by_task_tokens.get(tid, {})
        if kind in ("code-nav", "symbolic-edit"):
            if "symbol" in toks and t.get("kind") == "code-nav":
                code_nav_complete += 1
            if "symbol" in toks and "builtin" in toks:
                delta = toks["builtin"] - toks["symbol"]   # >0 = 심볼이 절감
                free_lsp_delta += delta
                b = _bucket_of(int(t.get("edit_size_lines", 0)))
                per_bucket[b] += delta
                per_bucket_n[b] += 1
                if delta < 0:
                    neg_tasks.append((int(t.get("edit_size_lines", 0)),
                                      toks["symbol"], toks["builtin"]))
            else:
                # 양 arm 미완 = 측정 불완전(심볼 arm 은 worker serena 마운트 필요).
                measurement_complete = False

    code_nav_fraction = (code_nav_complete / total_tasks) if total_tasks else 0.0

    # crossover: 심볼이 더 비싼(delta<0) 가장 큰 edit_size — 그 이하는 빌트인 선호.
    crossover_lines = max((n for n, _, _ in neg_tasks), default=0)
    if neg_tasks:
        # 심볼이 더 비싸므로 symbol/builtin 배수로 표현(>1 = 심볼이 N배 비쌈).
        ratios = [a / b for _, a, b in neg_tasks if b > 0]
        crossover_factor = round(sum(ratios) / len(ratios), 3) if ratios else 0.0
    else:
        crossover_factor = 1.0

    net_win = free_lsp_delta > 0

    return {
        "code_nav_fraction": round(code_nav_fraction, 4),
        "free_lsp_delta_tokens": free_lsp_delta,
        "per_bucket_delta": per_bucket,
        "per_bucket_n": per_bucket_n,
        "crossover_lines": crossover_lines,
        "crossover_factor": crossover_factor,
        "net_win": net_win,
        "excluded_nonapplicable": excluded,
        "measurement_complete": measurement_complete,
    }


# ── self-test (C18 컨벤션 · synthetic, no external) ─────────────────────────
def self_test():
    # 양 arm 은 같은 task 의 ground-truth diff 를 산출해야 한다(같은 변경, 다른 도구 경로의
    # 토큰 비용만 측정). 다른 diff 를 내면 그 arm 은 verify 에서 FAIL(틀린 편집은 절감 불가).
    diff_big = "diff --git a b\n+big edit (cross-file rewrite)\n"
    diff_small = "diff --git c d\n+small one-line edit\n"
    rubric = {"tasks": [
        {"id": "t-nav", "kind": "code-nav", "edit_size_lines": 0,
         "ground_truth_diff_sha": _sha(""), "scoring_weight": 1},
        {"id": "t-big", "kind": "symbolic-edit", "edit_size_lines": 60,
         "ground_truth_diff_sha": _sha(diff_big), "scoring_weight": 1},
        {"id": "t-small", "kind": "symbolic-edit", "edit_size_lines": 2,
         "ground_truth_diff_sha": _sha(diff_small), "scoring_weight": 1},
        {"id": "t-prose", "kind": "nonapplicable-text", "edit_size_lines": 0,
         "ground_truth_diff_sha": _sha(""), "scoring_weight": 1},
    ]}
    runs = [
        # code-nav: symbol arm cheaper (200 vs 800 chars -> 50 vs 200 tok)
        {"task_id": "t-nav", "arm": "symbol", "tool_call_count": 2,
         "input_payload_chars": 100, "output_payload_chars": 100,
         "prerequisite_read_chars": 0, "verification_step_count": 1,
         "produced_diff": "", "clean_after": True},
        {"task_id": "t-nav", "arm": "builtin", "tool_call_count": 3,
         "input_payload_chars": 400, "output_payload_chars": 400,
         "prerequisite_read_chars": 0, "verification_step_count": 1,
         "produced_diff": "", "clean_after": True},
        # big edit: symbol cheaper -> positive delta. 양 arm 모두 diff_big(ground truth) 산출.
        {"task_id": "t-big", "arm": "symbol", "tool_call_count": 2,
         "input_payload_chars": 400, "output_payload_chars": 400,
         "prerequisite_read_chars": 0, "verification_step_count": 1,
         "produced_diff": diff_big, "clean_after": True},
        {"task_id": "t-big", "arm": "builtin", "tool_call_count": 5,
         "input_payload_chars": 2000, "output_payload_chars": 2000,
         "prerequisite_read_chars": 4000, "verification_step_count": 1,
         "produced_diff": diff_big, "clean_after": True},
        # small edit: symbol MORE expensive -> negative delta (crossover). 양 arm 모두 diff_small.
        {"task_id": "t-small", "arm": "symbol", "tool_call_count": 4,
         "input_payload_chars": 800, "output_payload_chars": 800,
         "prerequisite_read_chars": 800, "verification_step_count": 1,
         "produced_diff": diff_small, "clean_after": True},
        {"task_id": "t-small", "arm": "builtin", "tool_call_count": 1,
         "input_payload_chars": 100, "output_payload_chars": 100,
         "prerequisite_read_chars": 0, "verification_step_count": 1,
         "produced_diff": diff_small, "clean_after": True},
        # prose: must be excluded from denominator
        {"task_id": "t-prose", "arm": "symbol", "tool_call_count": 1,
         "input_payload_chars": 50, "output_payload_chars": 50,
         "prerequisite_read_chars": 0, "verification_step_count": 0,
         "produced_diff": "", "clean_after": True},
        # mismatched-diff arm: builtin produced WRONG diff -> not counted
        {"task_id": "t-big", "arm": "builtin-bad", "tool_call_count": 5,
         "input_payload_chars": 9, "output_payload_chars": 9,
         "prerequisite_read_chars": 0, "verification_step_count": 1,
         "produced_diff": "WRONG", "clean_after": True},
    ]
    v = verify_runs(rubric, runs)
    vmap = {(x["task_id"], x["arm"]): x for x in v}
    assert vmap[("t-big", "symbol")]["counted"] is True, "big symbol should count"
    # the bad arm references task t-big but kind=symbolic-edit; wrong diff -> not counted
    assert vmap[("t-big", "builtin-bad")]["counted"] is False, "wrong diff must fail"
    assert vmap[("t-prose", "symbol")]["counted"] is False, "prose excluded"
    s = score(rubric, runs)
    assert s["excluded_nonapplicable"] == ["t-prose"], s["excluded_nonapplicable"]
    assert s["code_nav_fraction"] == round(1 / 4, 4), s["code_nav_fraction"]  # 1 nav / 4 tasks
    # free_lsp_delta = nav(200-50=150) + big(2000-200=1800) + small(50-600=-550) = 1400
    assert s["free_lsp_delta_tokens"] == 1400, s["free_lsp_delta_tokens"]
    assert s["net_win"] is True, "net win expected"
    assert s["crossover_lines"] == 2, s["crossover_lines"]      # small edit (2 lines) negative
    assert s["crossover_factor"] == 12.0, s["crossover_factor"]  # symbol 600 / builtin 50 tok
    assert s["measurement_complete"] is True, s
    # measurement_complete=false when a symbol arm is missing
    runs_missing = [r for r in runs if not (r["task_id"] == "t-big" and r["arm"] == "symbol")]
    s2 = score(rubric, runs_missing)
    assert s2["measurement_complete"] is False, "missing symbol arm -> incomplete"
    print("ezer_serena_eval self-test OK "
          "(code_nav_fraction=%.4f free_lsp_delta=%d crossover_lines=%d net_win=%s)"
          % (s["code_nav_fraction"], s["free_lsp_delta_tokens"],
             s["crossover_lines"], s["net_win"]))
    return 0


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="Serena crossover eval harvester (pure stdlib)")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--verify-runs", metavar="RUNRECORDS_JSON")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--rubric", metavar="RUBRIC_JSON")
    ap.add_argument("--runs", metavar="RUNRECORDS_JSON")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.verify_runs:
        if not args.rubric:
            sys.stderr.write("--verify-runs 는 --rubric 필요\n"); return 2
        out = verify_runs(_load(args.rubric), _load(args.verify_runs))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.score:
        if not (args.rubric and args.runs):
            sys.stderr.write("--score 는 --rubric 와 --runs 필요\n"); return 2
        out = score(_load(args.rubric), _load(args.runs))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        # 측정 불완전 = hard-fail(silent pass 금지).
        return 0 if out["measurement_complete"] else 3

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
