#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EZERagent_learn — RSI 학습 루프(5단계)의 결정론 엔진 (directive RSI_LEARNING §1·§5 · DESIGN §4).

오너 5단계(①검색·탐색 ②패턴·철학 추출 ③객관·근거 평가 ④문서·지침 저장 ⑤skill/harness
제작·발전)를 결정론으로 박제한다. ★할루시네이션 원천 봉쇄(오너 절대명제): 환각 자료가
학습에 침투하면 재귀 증폭으로 전 시스템이 붕괴하므로 입구를 전면 차단한다(부분 통과 = 전체 중단).

이 도구는 **계약 강제·검증·위임자**다 — 점수를 자체 생성하지 않고(③→EZERagent_rsi 위임),
기억을 직접 쓰지 않으며(④→EZERagent_memory 위임), 실제 WebSearch는 에이전트가 수행하고 이 도구는
그 산출(candidates/pattern JSON)의 계약(citation·스키마·정박)을 결정론으로 검증한다(네트워크·LLM
호출 없음). 의미·논리의 독립 모델 검증과 5차원 봉쇄 집행은 rsi-gate.sh가 담당한다.

명령(DESIGN §4 계약):
  propose  --reason <stuck|gate|ceiling> --topic <S> [--json]
      트리거 신호 → 학습 후보·근거 payload 산출(승인 요청용). 승인 전 검색·저장·채택 무실행.
  search   --topic <S> --candidates <path|-> [--json]
      ① 후보 JSON 검증 게이트. source_url·claim·retrieved_at 필수·citation 0이면 hard fail.
  extract  --from <candidates.json|-> --pattern <pattern.json|-> [--json]
      ② pattern 스키마 검증 + evidence_ref가 후보 출처에 정박했는지 대조. 미충족 거부.
  evaluate --round <id> --score F [--baseline] [--note S] [--json]
      ③ EZERagent_rsi에 위임(첫 회=checkpoint·이후=progress). ★score는 주입만(자체생성 금지).
  store    --round <id> --pattern <pattern.json|-> --type <feedback|reference|project>
           [--approved] [--state <provisional|confirmed>] [--fallback] [--name S] [--desc S] [--json]
      ④ verdict=improved AND --approved일 때만 EZERagent_memory add 위임. fallback 모드 confirmed 차단.
  harness  --round <id> --pattern <pattern.json|-> [--evolve <skill>] [--json]
      ⑤ retention. 라운드 verdict=regressed면 EZERagent_rsi rollback(dry-run) 권고.
  status   [--json]
      UI 데이터원 — 라운드·verdict·채택/rollback·발견 누적.

종료 코드: 0 성공 · 2 인자/계약 위반(hard fail) · 3 위임 도구 실패.
의존성: 파이썬 표준 라이브러리 + 같은 bin의 EZERagent_rsi.py·EZERagent_memory.py. 네트워크·LLM 호출 없음.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
RSI = os.path.join(HERE, "EZERagent_rsi.py")
MEM = os.path.join(HERE, "EZERagent_memory.py")
GATE = os.path.join(HERE, "rsi-gate.sh")

PATTERN_FIELDS = ("domain", "condition", "action", "rationale", "evidence_ref")
VALID_REASONS = ("stuck", "gate", "ceiling")
VALID_TYPES = ("feedback", "reference", "project")


def learn_dir():
    root = os.environ.get("EZERAGENT_ROUND_DIR")
    if root:
        return os.path.join(root, "learn")
    return os.path.join(os.getcwd(), "_round", "learn")


def fail(code, msg):
    print(f"error: {msg}", file=sys.stderr)
    return code


def _read_json_arg(val):
    """'-'=stdin · 그 외=파일 경로. 반환: 파싱된 객체 (실패 시 ValueError)."""
    if val == "-":
        return json.loads(sys.stdin.read())
    with open(val, encoding="utf-8") as f:
        return json.load(f)


# ───────────────────────── 순수 로직(테스트 핀) ─────────────────────────

def domain_of(url):
    try:
        return (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""


def slugify(s, prefix="rsi-"):
    """EZERagent_memory의 kebab-case 슬러그([a-z0-9-]·영숫자 시작) 계약에 맞는 이름 생성."""
    base = "".join(ch if (ch.isascii() and ch.isalnum()) else "-" for ch in str(s).lower())
    base = "-".join(filter(None, base.split("-")))
    out = (prefix + base)[:48].strip("-")
    return out or (prefix.strip("-") or "rsi")


def validate_candidates(cands):
    """① 후보 검증(순수). citation 필수·필드 정박. 반환 {ok, errors, normalized, distinct_sources}."""
    if not isinstance(cands, list) or not cands:
        return {"ok": False, "errors": ["후보 0건 — 학습지식 단독 금지(citation 필수·hard fail)"],
                "normalized": [], "distinct_sources": 0}
    errors, norm, domains = [], [], set()
    for i, c in enumerate(cands):
        if not isinstance(c, dict):
            errors.append(f"[{i}] 객체 아님")
            continue
        url = str(c.get("source_url", "")).strip()
        claim = str(c.get("claim", "")).strip()
        ra = str(c.get("retrieved_at", "")).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            errors.append(f"[{i}] source_url 없음/비URL")
        if not claim:
            errors.append(f"[{i}] claim 비어있음")
        if not ra:
            errors.append(f"[{i}] retrieved_at 없음(실호출 로그 정박 필요)")
        if url:
            domains.add(domain_of(url))
        norm.append({"source_url": url, "claim": claim, "retrieved_at": ra,
                     "canonical": bool(c.get("canonical", False))})
    return {"ok": not errors, "errors": errors, "normalized": norm,
            "distinct_sources": len(domains)}


def validate_pattern(pattern, candidate_urls=None):
    """② pattern 스키마 + evidence_ref 정박 검증(순수). 반환 {ok, errors}."""
    if not isinstance(pattern, dict):
        return {"ok": False, "errors": ["pattern 객체 아님"]}
    errors = [f"필드 '{f}' 비어있음" for f in PATTERN_FIELDS if not str(pattern.get(f, "")).strip()]
    ev = str(pattern.get("evidence_ref", "")).strip()
    if ev and candidate_urls is not None and ev not in set(candidate_urls):
        errors.append(f"evidence_ref가 후보 출처에 정박 안 됨: {ev}")
    return {"ok": not errors, "errors": errors}


def confidence_of(distinct_sources):
    """독립 출처 수 → confidence. 2개 미만=low(단일 출처 confirmed 불가)."""
    return "low" if distinct_sources < 2 else "med"


def promotion_allowed(verdict, approved, fallback_mode, state):
    """④ 저장 승격 가부(순수). 반환 (allowed, reason)."""
    if state == "confirmed" and fallback_mode:
        return False, "fallback 모드(단일 모델 변형·공통모드 방어 약화)는 confirmed 승격 불가 — provisional만(codex R3)"
    if verdict != "improved":
        return False, f"verdict={verdict} — improved 아니면 저장 거부(측정 우위 없음)"
    if not approved:
        return False, "사람 승인(--approved) 없음 — ④저장·⑤채택은 사람 승인(directive §4)"
    return True, "ok"


# ───────────────────────── 상태 파일 I/O ─────────────────────────

def _load_state():
    p = os.path.join(learn_dir(), "state.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return {"rounds": {}, "discovery": {"capability": 0, "perspective": 0, "knowledge": 0}}


def _save_state(state):
    d = learn_dir()
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "state.json")
    tmp = p + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(state, ensure_ascii=False, indent=2))
    os.replace(tmp, p)


def _append_ledger(entry):
    d = learn_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "ledger.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _round_rec(state, rid):
    return state.setdefault("rounds", {}).setdefault(
        rid, {"round": rid, "verdict": None, "stored": [], "harness": [], "created_at": time.time()})


def _run(tool, args):
    """위임 도구 호출 — (rc, stdout, stderr). 환경(EZERAGENT_ROUND_DIR 등) 승계."""
    r = subprocess.run([sys.executable, tool] + args, capture_output=True, text=True, env=dict(os.environ))
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _enforce_gate(gate_input_arg, step, state, fallback):
    """★rsi-gate.sh 강제 호출(통합 — 봉쇄 우회 차단). 반환 (ok, msg).

    gate-input(검증 증거 번들)을 읽어 step·target_state·fallback_mode를 권위적으로 주입한 뒤
    rsi-gate.sh를 호출한다. gate가 DENY(exit≠0)면 ok=False. gate-input 부재/불량도 fail-closed."""
    if not gate_input_arg:
        return False, "rsi-gate 통합: --gate-input 필수(검증 증거 번들 없이는 봉쇄 통과 증명 불가)"
    try:
        gi = _read_json_arg(gate_input_arg)
    except (OSError, ValueError) as e:
        return False, f"gate-input 읽기/파싱 실패: {e}"
    if not isinstance(gi, dict):
        return False, "gate-input 객체 아님"
    gi["step"] = step
    gi["target_state"] = state
    gi["fallback_mode"] = bool(fallback)
    r = subprocess.run(["bash", GATE], input=json.dumps(gi, ensure_ascii=False),
                       capture_output=True, text=True, env=dict(os.environ))
    if r.returncode != 0:
        return False, "rsi-gate DENY(봉쇄 미통과): " + (r.stderr.strip() or r.stdout.strip())
    return True, "gate allow"


# ───────────────────────── 명령 ─────────────────────────

def cmd_propose(a):
    if a.reason not in VALID_REASONS:
        return fail(2, f"--reason은 {VALID_REASONS} 중 하나")
    payload = {"event": "propose", "topic": a.topic, "reason": a.reason,
               "evidence": [], "status": "awaiting_approval", "ts": time.time(),
               "note": "pending feed approval item 등록 → 사람이 'EZERagent feed reply <id> allow'(또는 feed 패널)로 승인할 때만 ①~⑤ 착수. 거부=무실행."}
    _append_ledger(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2 if not a.json else None))
    return 0


def cmd_search(a):
    try:
        cands = _read_json_arg(a.candidates)
    except (OSError, ValueError) as e:
        return fail(2, f"candidates 읽기/파싱 실패: {e}")
    res = validate_candidates(cands)
    if not res["ok"]:
        return fail(2, "① 검색 게이트 거부(citation/정박) — " + "; ".join(res["errors"]))
    out = {"event": "search", "topic": a.topic, "candidates": res["normalized"],
           "distinct_sources": res["distinct_sources"],
           "confidence": confidence_of(res["distinct_sources"]), "ts": time.time()}
    d = learn_dir()
    os.makedirs(d, exist_ok=True)
    slug = "".join(ch if ch.isalnum() else "-" for ch in a.topic.lower())[:48].strip("-") or "topic"
    path = os.path.join(d, f"candidates_{slug}.json")
    tmp = path + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(out["candidates"], ensure_ascii=False, indent=2))
    os.replace(tmp, path)
    out["candidates_path"] = path
    _append_ledger({k: out[k] for k in ("event", "topic", "distinct_sources", "confidence", "ts")})
    print(json.dumps(out, ensure_ascii=False, indent=2 if not a.json else None))
    return 0


def cmd_extract(a):
    try:
        cands = _read_json_arg(getattr(a, "from"))
        pattern = _read_json_arg(a.pattern)
    except (OSError, ValueError) as e:
        return fail(2, f"from/pattern 읽기/파싱 실패: {e}")
    urls = [c.get("source_url", "") for c in cands] if isinstance(cands, list) else []
    res = validate_pattern(pattern, urls)
    if not res["ok"]:
        return fail(2, "② 추출 게이트 거부(스키마/정박) — " + "; ".join(res["errors"]))
    out = {"event": "extract", "pattern": pattern, "ts": time.time()}
    _append_ledger({"event": "extract", "domain": pattern.get("domain"),
                    "evidence_ref": pattern.get("evidence_ref"), "ts": out["ts"]})
    print(json.dumps(out, ensure_ascii=False, indent=2 if not a.json else None))
    return 0


def cmd_evaluate(a):
    # ③ EZERagent_rsi 위임 — 첫 회(또는 --baseline)=checkpoint, 이후=progress. score는 주입만.
    sub = "checkpoint" if a.baseline else "progress"
    args = [sub, "--round", a.round, "--score", repr(a.score)]
    if a.note:
        args += ["--note", a.note]
    rc, out, err = _run(RSI, args)
    if rc != 0:
        # checkpoint 없는데 progress면 baseline부터 — 재시도(checkpoint).
        if sub == "progress" and "checkpoint 없음" in err:
            rc, out, err = _run(RSI, ["checkpoint", "--round", a.round, "--score", repr(a.score)]
                                + (["--note", a.note] if a.note else []))
        if rc != 0:
            return fail(3, f"EZERagent_rsi 위임 실패: {err or out}")
    try:
        rsi_res = json.loads(out)
    except ValueError:
        rsi_res = {"raw": out}
    verdict = rsi_res.get("verdict", "baseline" if a.baseline else None)
    state = _load_state()
    r = _round_rec(state, a.round)
    r["verdict"] = verdict
    r["last_score"] = a.score
    _save_state(state)
    entry = {"event": "evaluate", "round": a.round, "score": a.score, "verdict": verdict, "ts": time.time()}
    _append_ledger(entry)
    print(json.dumps({**entry, "rsi": rsi_res}, ensure_ascii=False, indent=2 if not a.json else None))
    return 0


def cmd_store(a):
    state = _load_state()
    r = state.get("rounds", {}).get(a.round)
    verdict = (r or {}).get("verdict")
    if verdict is None:
        return fail(2, f"라운드 '{a.round}' 평가 기록 없음 — 먼저 evaluate 하라(verdict 필요)")
    allowed, reason = promotion_allowed(verdict, a.approved, a.fallback, a.state)
    if not allowed:
        return fail(2, "④ 저장 거부 — " + reason)
    if a.type not in VALID_TYPES:
        return fail(2, f"--type은 {VALID_TYPES} 중 하나")
    try:
        pattern = _read_json_arg(a.pattern)
    except (OSError, ValueError) as e:
        return fail(2, f"pattern 읽기/파싱 실패: {e}")
    pv = validate_pattern(pattern)
    if not pv["ok"]:
        return fail(2, "④ 저장 거부(pattern 스키마) — " + "; ".join(pv["errors"]))
    # ★rsi-gate 강제 통합(codex BLOCK 보정) — 봉쇄 통과 증명 없이는 저장 불가(존재≠강제 결함 해소).
    ok, gmsg = _enforce_gate(a.gate_input, "store", a.state, a.fallback)
    if not ok:
        return fail(2, "④ 저장 거부 — " + gmsg)
    name = a.name or slugify(pattern.get("domain", "learn"))
    desc = a.desc or f"[{a.state}] {pattern.get('domain')}: {pattern.get('action')}"[:200]
    body = json.dumps({"pattern": pattern, "state": a.state, "round": a.round,
                       "verdict": verdict, "evidence_ref": pattern.get("evidence_ref")},
                      ensure_ascii=False, indent=2)
    rc, out, err = _run(MEM, ["add", "--type", a.type, "--name", name, "--desc", desc, "--body", body])
    if rc != 0:
        return fail(3, f"EZERagent_memory 위임 실패: {err or out}")
    r["stored"].append({"name": name, "state": a.state, "type": a.type, "ts": time.time()})
    _save_state(state)
    entry = {"event": "store", "round": a.round, "name": name, "state": a.state,
             "type": a.type, "verdict": verdict, "ts": time.time()}
    _append_ledger(entry)
    print(json.dumps({**entry, "memory": out}, ensure_ascii=False, indent=2 if not a.json else None))
    return 0


def cmd_harness(a):
    state = _load_state()
    r = state.get("rounds", {}).get(a.round)
    verdict = (r or {}).get("verdict")
    try:
        pattern = _read_json_arg(a.pattern)
    except (OSError, ValueError) as e:
        return fail(2, f"pattern 읽기/파싱 실패: {e}")
    harness_ref = a.evolve or slugify(pattern.get("domain", "learn"), prefix="rsi-harness-")
    retention = "keep" if verdict == "improved" else "rollback_recommended"
    # ★rsi-gate 강제 통합 — 채택(keep)은 봉쇄 통과 증명 필수. 폐기(rollback)는 게이트 무관.
    gate_passed = None
    if retention == "keep":
        ok, gmsg = _enforce_gate(a.gate_input, "harness", a.state, a.fallback)
        if not ok:
            return fail(2, "⑤ 채택 거부 — " + gmsg)
        gate_passed = True
    out = {"event": "harness", "round": a.round, "harness_ref": harness_ref,
           "evolve": a.evolve, "verdict": verdict, "retention": retention,
           "state": a.state, "fallback": bool(a.fallback), "gate_passed": gate_passed,
           "ts": time.time()}
    if retention == "rollback_recommended":
        rc, ro, re_ = _run(RSI, ["rollback", "--round", a.round])  # dry-run(기본·무실행)
        out["rollback_dry_run"] = ro or re_
    if r is not None:
        r["harness"].append({"harness_ref": harness_ref, "retention": retention,
                             "state": a.state, "fallback": bool(a.fallback),
                             "gate_passed": gate_passed, "ts": out["ts"]})
        _save_state(state)
    # ledger에 채택 요약(state·fallback·gate 통과) 기록 — codex minor(감사 추적성).
    _append_ledger({k: out[k] for k in
                    ("event", "round", "harness_ref", "retention", "state", "fallback", "gate_passed", "ts")})
    print(json.dumps(out, ensure_ascii=False, indent=2 if not a.json else None))
    return 0


def cmd_status(a):
    state = _load_state()
    if a.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    rounds = state.get("rounds", {})
    if not rounds:
        print("학습 라운드 기록 없음 (propose/search 로 시작)")
        return 0
    for rid, r in rounds.items():
        st = ", ".join(f"{s['name']}({s['state']})" for s in r.get("stored", [])) or "-"
        print(f"라운드 {rid}: verdict={r.get('verdict')} · 저장[{st}] · harness {len(r.get('harness', []))}")
    disc = state.get("discovery", {})
    print(f"발견 누적: 기능 {disc.get('capability', 0)} · 관점 {disc.get('perspective', 0)} · 지식 {disc.get('knowledge', 0)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="RSI 학습 루프(5단계) 결정론 엔진")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("propose"); p.add_argument("--reason", required=True); p.add_argument("--topic", required=True); p.add_argument("--json", action="store_true")
    s = sub.add_parser("search"); s.add_argument("--topic", required=True); s.add_argument("--candidates", required=True); s.add_argument("--json", action="store_true")
    e = sub.add_parser("extract"); e.add_argument("--from", required=True, dest="from"); e.add_argument("--pattern", required=True); e.add_argument("--json", action="store_true")
    ev = sub.add_parser("evaluate"); ev.add_argument("--round", required=True); ev.add_argument("--score", type=float, required=True); ev.add_argument("--baseline", action="store_true"); ev.add_argument("--note"); ev.add_argument("--json", action="store_true")
    st = sub.add_parser("store"); st.add_argument("--round", required=True); st.add_argument("--pattern", required=True); st.add_argument("--type", required=True); st.add_argument("--approved", action="store_true"); st.add_argument("--state", default="provisional", choices=["provisional", "confirmed"]); st.add_argument("--fallback", action="store_true"); st.add_argument("--gate-input", dest="gate_input", help="rsi-gate 검증 증거 번들(path|-) — 강제 봉쇄 통과"); st.add_argument("--name"); st.add_argument("--desc"); st.add_argument("--json", action="store_true")
    h = sub.add_parser("harness"); h.add_argument("--round", required=True); h.add_argument("--pattern", required=True); h.add_argument("--evolve"); h.add_argument("--state", default="provisional", choices=["provisional", "confirmed"]); h.add_argument("--fallback", action="store_true"); h.add_argument("--gate-input", dest="gate_input", help="rsi-gate 검증 증거 번들(path|-) — 채택 시 강제"); h.add_argument("--json", action="store_true")
    stt = sub.add_parser("status"); stt.add_argument("--json", action="store_true")

    a = ap.parse_args()
    return {"propose": cmd_propose, "search": cmd_search, "extract": cmd_extract,
            "evaluate": cmd_evaluate, "store": cmd_store, "harness": cmd_harness,
            "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
