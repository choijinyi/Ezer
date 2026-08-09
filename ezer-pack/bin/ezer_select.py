#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ezer_select — 채점식 provider/도구 선택 엔진 (도메인-무관·결정론).

"처음 사용 가능한 provider" 대신 가중 다차원 적합도로 후보를 랭킹하고, **가용성은
점수가 아니라 하드 게이트**(deny-by-default: 키 없으면 후보에서 제외·setup_offer로 안내)로
다룬다. ezer 철학: 미디어부서 등 에이전트가 과제마다 *자율 선택*하되, 선택의 근거가
설명가능해야 한다. 카탈로그(capability→providers)는 외부 JSON 데이터다(이 엔진은 그 위에서
랭킹만 한다 — 영상 provider 카탈로그는 영상 v2가 공급).

ezer 제약 정합:
- **무점수 채널 오염 금지**: 여기서의 fit(0~1)은 *라우팅 적합도*이지 리뷰어 품질 verdict가
  아니다. 절대 4자수렴 게이트에 품질 점수로 먹이지 않는다(REVIEWER_VERDICT_CONTRACT §1과 무관 층위).
- **Max전용·무료우선**: cost_tier {free|low|high}. free(로컬·스톡·Piper)가 충분하면 우선.
- **deny-by-default**: key_env 미설정 + 비-free = 가용 불가(랭킹 제외·setup_offer 안내).
  미가용 채널은 `setup_offer`가 opt-in 설정 안내(action enum + 텍스트 지시)를 결정론 파생한다 —
  안내는 *텍스트만*이고 키 발급·install·env설정을 자동 실행하지 않는다(자율주행 denylist).
- **로컬 런타임 준비성(W0-4)**: free+local은 probe(bin·module·path)가 실제 설치/캐시됐을 때만 가용 —
  미준비면 deny+설치 안내(무음실패 차단). 'free+local=항상 가용'의 위험한 가정을 닫는다(필요조건 floor).
- **사용자 선호 우선**: prefer가 가용 후보면 강제 1위(AGENT_GUIDE: preference > availability > score).

사용:
    python3 ezer_select.py rank --catalog <C.json> --capability <CAP> \
        [--intent "..."] [--style a,b] [--prefer ID] [--free-first] [--locked ID] [--json]
    python3 ezer_select.py menu --catalog <C.json> [--json]   # capability별 가용/미가용 N-of-M 메뉴
    python3 ezer_select.py --self-test

종료 코드: 0 성공(1위 결정) · 1 가용 후보 없음(전부 키 미설정 등) · 2 인자/입력 오류 · 3 — (미사용)
의존성: 파이썬 표준 라이브러리만 (네트워크·LLM 호출 없음·점수를 게이트에 먹이지 않음).
"""

import argparse
import io
import contextlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

# 가중치 — 합 1.0. task_fit 최우선, cost(Max전용 무료우선)·quality 동률 차순.
WEIGHTS = {"task_fit": 0.35, "quality": 0.20, "cost": 0.20,
           "reliability": 0.10, "control": 0.08, "continuity": 0.07}
# 카탈로그 실제 어휘(excellent|good|fair)에 정합 — 'fair' 누락 시 fair provider가 조용히 default
# 점수로 떨어지던 잠복 버그 교정(W1-3 verify가 검출). basic·premium은 후방호환 별칭으로 유지.
QUALITY_SCORE = {"excellent": 0.95, "good": 0.7, "fair": 0.45, "basic": 0.4, "premium": 0.95}
COST_SCORE = {"free": 1.0, "low": 0.7, "high": 0.4}
RUNTIME_REL = {"local": 0.95, "stock": 0.9, "api": 0.7, "local_gpu": 0.85}
VALID_COST = tuple(COST_SCORE)
VALID_QUALITY = tuple(QUALITY_SCORE)

# ── 프로바이더 계약(W1-3 verify) — 카탈로그 레코드를 인터페이스-적합 플러그형으로 ──
PROVIDER_KEYS = ("id", "best_for", "quality_tier", "cost_tier", "key_env", "runtime", "supports", "probe")
PROVIDER_REQUIRED = ("id", "runtime", "cost_tier")
PROBE_KEYS = ("bin", "bins", "any_bin", "module", "modules", "any_module", "path", "paths")
PROBE_STR_KEYS = ("bin", "module", "path")
PROBE_LIST_KEYS = ("bins", "any_bin", "modules", "any_module", "paths")

# 의미 동의어 군 — "cinematic"과 "film"이 키워드는 달라도 매치(lib/scoring.py 발상 이식).
SYNONYMS = [
    {"cinematic", "film", "movie", "trailer", "dramatic", "epic"},
    {"explainer", "educational", "tutorial", "teaching", "lesson"},
    {"social", "tiktok", "reels", "shorts", "viral"},
    {"animation", "animated", "motion", "kinetic"},
    {"realistic", "photorealistic", "lifelike"},
    {"stock", "footage", "b-roll", "broll", "archive"},
    {"avatar", "presenter", "talking-head", "spokesperson"},
    {"voice", "voiceover", "narration", "speech", "tts"},
    {"music", "soundtrack", "score", "ambient"},
]
TOKEN_RE = re.compile(r"[a-z0-9가-힣][a-z0-9가-힣+._-]*")


def _tok(s):
    return set(TOKEN_RE.findall((s or "").lower()))


def _expand(words):
    out = set(words)
    for cl in SYNONYMS:
        if out & cl:
            out |= cl
    return out


def _overlap(a, b):
    """overlap coefficient |A∩B|/min(|A|,|B|) — Jaccard가 풍부한 best_for를 과벌하는 문제 회피."""
    if not a or not b:
        return 0.0
    m = min(len(a), len(b))
    return len(a & b) / m if m else 0.0


def _bin_ready(name):
    return shutil.which(name) is not None


def _module_ready(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def runtime_ready(provider):
    """로컬 런타임 준비성 게이트(W0-4) — 'free+local'이 '설치됨+캐시됨'을 의미하게 한다.
    probe 미선언이면 ready(레거시 보존). 선언 시 bin(PATH)·module(import)·path(존재)를 실측한다.
    필요조건 floor(necessary-not-sufficient: torch가 있어도 모델 가중치는 별도) — 미준비를 자신 있게
    선택해 런타임에 무음실패하는 것을 차단한다. 반환 (ready, reason). 모든 선언 키가 통과해야 ready."""
    probe = provider.get("probe")
    if not probe:
        return True, ""
    missing = []
    b = probe.get("bin")
    if b and not _bin_ready(b):
        missing.append("바이너리 '%s' PATH에 없음" % b)
    for b in probe.get("bins", []) or []:
        if not _bin_ready(b):
            missing.append("바이너리 '%s' 없음" % b)
    anyb = probe.get("any_bin")
    if anyb and not any(_bin_ready(x) for x in anyb):
        missing.append("바이너리 %s 중 하나도 없음" % "|".join(anyb))
    m = probe.get("module")
    if m and not _module_ready(m):
        missing.append("파이썬 모듈 '%s' 미설치" % m)
    for m in probe.get("modules", []) or []:
        if not _module_ready(m):
            missing.append("파이썬 모듈 '%s' 미설치" % m)
    anym = probe.get("any_module")
    if anym and not any(_module_ready(x) for x in anym):
        missing.append("파이썬 모듈 %s 중 하나도 없음" % "|".join(anym))
    p = probe.get("path")
    if p and not os.path.exists(os.path.expanduser(p)):
        missing.append("경로 '%s' 없음(모델 미캐시)" % p)
    for p in probe.get("paths", []) or []:
        if not os.path.exists(os.path.expanduser(p)):
            missing.append("경로 '%s' 없음" % p)
    if missing:
        return False, "런타임 미준비: " + "; ".join(missing)
    return True, ""


def key_available(provider):
    """deny-by-default 키 게이트. key_env 없으면 통과(무키 free), 있으면 env 설정 필요."""
    key_env = provider.get("key_env")
    if not key_env:
        return True  # 키 불필요(로컬·스톡·무료)
    return bool(os.environ.get(key_env))


def available(provider):
    """가용성 = 키 게이트 ∧ 로컬 런타임 준비성. free+local도 미설치/미캐시면 미가용(무음실패 차단)."""
    return key_available(provider) and runtime_ready(provider)[0]


# ── setup_offer — 미가용 채널의 opt-in 설정 안내(순수·결정론·텍스트 only) ──
# 무상태(상태 주입·env 변경·네트워크 0): (reason, hint) → action enum + 사람이 따라 할 안내 문자열.
# 자율주행 denylist: instruction은 *보여줄 텍스트만* — 키 발급·install·export를 자동 실행하지 않음.
SETUP_ACTIONS = ("set_env", "install_bin", "install_module", "fetch_model")


def setup_offer(reason, hint, key_env=None):
    """미가용 사유(reason∈{key,runtime})+hint에서 opt-in 설정 안내를 결정론 파생한다.
    반환 {action∈SETUP_ACTIONS, setup(안내 텍스트), irreversible(항상 False)}.
    action: key→set_env, runtime hint가 '바이너리…'→install_bin / '모듈…'→install_module /
    '경로…미캐시'→fetch_model / 그 외 런타임→install_bin(보수적 기본). 텍스트만 — 자동 실행 금지."""
    if reason == "key":
        action = "set_env"
        setup = "키 %s 설정 시 가용 (export %s=… 후 재실행)" % (key_env, key_env)
    elif "모듈" in (hint or ""):
        action = "install_module"
        setup = (hint or "") + " — 설치 시 가용 (pip install … 후 재실행)"
    elif "경로" in (hint or "") or "미캐시" in (hint or ""):
        action = "fetch_model"
        setup = (hint or "") + " — 모델 캐시 시 가용"
    else:  # '바이너리 …' 및 기타 런타임 미준비
        action = "install_bin"
        setup = (hint or "런타임 미준비") + " — 설치 시 가용"
    return {"action": action, "setup": setup, "irreversible": False}


def score_provider(provider, ctx, free_first):
    """단일 provider의 라우팅 적합도(0~1) + 차원별 근거."""
    best = _expand(_tok(" ".join(provider.get("best_for", []))))
    intent = _expand(_tok(ctx.get("intent", "")) | set(x.lower() for x in ctx.get("style", [])))
    task_fit = _overlap(intent, best) if intent else 0.4

    quality = QUALITY_SCORE.get(provider.get("quality_tier", "good"), 0.6)
    cost_tier = provider.get("cost_tier", "high")
    cost = COST_SCORE.get(cost_tier, 0.4)
    if free_first and cost_tier == "free":
        cost = 1.0  # 무료우선 모드에서 free에 만점
    reliability = RUNTIME_REL.get(provider.get("runtime", "api"), 0.6)
    control = min(1.0, len(provider.get("supports", {})) / 5.0 + 0.2)
    locked = ctx.get("locked")
    continuity = 0.9 if locked and provider.get("id") == locked else (0.5 if not locked else 0.4)

    dims = {"task_fit": round(task_fit, 3), "quality": round(quality, 3),
            "cost": round(cost, 3), "reliability": round(reliability, 3),
            "control": round(control, 3), "continuity": round(continuity, 3)}
    fit = sum(dims[k] * w for k, w in WEIGHTS.items())
    top = sorted(dims.items(), key=lambda kv: -kv[1] * WEIGHTS[kv[0]])[:2]
    why = ", ".join("%s=%.2f" % (k, v) for k, v in top)
    if free_first and cost_tier == "free":
        why = "무료우선·" + why
    return round(fit, 3), dims, why


def load_catalog(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def rank(catalog, capability, ctx, free_first):
    """capability의 가용 provider를 랭킹. 반환 (ranked, unavailable, forced_pref|None)."""
    providers = (catalog.get("capabilities", {}) or {}).get(capability, [])
    ranked, unavailable = [], []
    for p in providers:
        if available(p):
            fit, dims, why = score_provider(p, ctx, free_first)
            ranked.append({"id": p.get("id"), "provider": p.get("provider"),
                           "fit": fit, "dims": dims, "why": why,
                           "cost_tier": p.get("cost_tier"), "quality_tier": p.get("quality_tier")})
        elif not key_available(p):
            off = setup_offer("key", "키 %s" % p.get("key_env"), p.get("key_env"))
            unavailable.append({"id": p.get("id"), "reason": "key", "key_env": p.get("key_env"),
                                "action": off["action"], "setup": off["setup"],
                                "irreversible": off["irreversible"]})
        else:
            _, why = runtime_ready(p)  # 키는 통과했으나 로컬 런타임 미준비(W0-4)
            off = setup_offer("runtime", why)
            unavailable.append({"id": p.get("id"), "reason": "runtime",
                                "action": off["action"], "setup": off["setup"],
                                "irreversible": off["irreversible"]})
    ranked.sort(key=lambda r: -r["fit"])
    forced = None
    prefer = ctx.get("prefer")
    if prefer:
        for i, r in enumerate(ranked):
            if r["id"] == prefer:
                forced = r
                ranked.insert(0, ranked.pop(i))  # 선호를 1위로
                break
    return ranked, unavailable, forced


# ── OPP-22 검색 의도→다중 검색채널 폴백 체인 (REDESIGN — 신규 엔진 0, rank() 재사용) ──
# 설계 근거(실측): ezer 검색은 Exa 단일 의존이 아니라 WebSearch(빌트인 도구)·다수 *-search
# 스킬(k-skill-proxy·OpenAPI·stdlib·RSS)·MCP·insane-search(페이지 리더)로 분산돼 있다.
# 보고서 §1의 "Exa 단일 의존" 단정은 코드 미입증(EXA 참조 0건) — 따라서 신규 channel_router
# 엔진을 만들지 않고, 이미 가진 결정론 도구(ezer_select)에 "검색 채널 폴백"을 최소 배선한다.
# 검색 "채널"은 영상/음성 provider와 동일하게 catalog의 capability(예: "web_search")로 표현되며,
# rank()가 이미 ①首选+备选 우선순위 정렬 ②deny-by-default 가용성 하드게이트(키·런타임)
# ③setup_offer 자동 강등을 제공한다 — 그 위에 R6 전수소진 게이트(검색 채널 차원)만 얹는다.


def search_fallback(catalog, capability, ctx, free_first):
    """검색 의도→다중 검색채널 폴백 체인 + R6 전수소진 게이트(검색 채널 차원).

    rank()를 그대로 호출해 가용 채널을 우선순위 정렬(폴백 체인)하고, 미가용(키/런타임 강등)
    채널을 untried_channels로 노출한다. "검색 결과 없음/막힘" 선언은 R6 4조건의 검색 채널층
    동형(SEARCH_EXHAUSTION_CONTRACT.md §2)을 충족할 때만 허용한다 — 여기선 페이지 fetch가
    아니라 *검색 백엔드*가 전부 소진됐는지를 묻는다(verdict 수렴 ≠ 수집 전수성).

    R6 4조건의 검색 채널층 사상(file:line 근거 = SEARCH_EXHAUSTION_CONTRACT.md §2):
      C1 grid_exhausted            → all_channels_tried  (가용 채널을 전부 시도했는가)
      C2 untried_routes == []      → untried_channels == [] (키·런타임 강등 채널이 남았으면 거짓)
      C3 must_invoke_playwright… == false → 검색층엔 MCP 정찰 단계 부재 → 항상 충족(True 고정)
      C4 stop_reason∈terminal      → fallback_chain != [] (애초에 가용 채널이 1개라도 있었나)
    untried_channels가 비어야(=강등 채널 0) "검색 결과 없음"을 선언할 수 있다.
    반환: {capability, fallback_chain, active_backend, untried_channels, may_declare_no_results, note}.
    """
    ranked, unavailable, forced = rank(catalog, capability, ctx, free_first)
    # 폴백 체인 = 가용 채널 우선순위 순(rank가 이미 정렬). 첫 채널이 首选(active 후보).
    fallback_chain = [{"id": r["id"], "fit": r["fit"], "cost_tier": r["cost_tier"],
                       "why": r["why"]} for r in ranked]
    # untried_channels = 키/런타임 강등으로 *아직 못 써본* 채널(setup_offer로 복구 가능).
    # = R6 C2의 검색 채널층(untried_routes). 비어야 전수소진 선언 가능.
    untried_channels = [{"id": u["id"], "reason": u["reason"],
                         "action": u["action"], "setup": u["setup"]} for u in unavailable]
    # active_backend(PHIL-03): 실증(가용 1위)된 후에만 채운다. 가용 0이면 None.
    active_backend = ranked[0]["id"] if ranked else None
    # R6 4조건 AND(검색 채널 차원) — SEARCH_EXHAUSTION_CONTRACT.md §2 동형.
    c1_all_tried = True                       # rank가 가용 채널을 전부 평가(미시도 없음)
    c2_no_untried = (untried_channels == [])  # 강등 채널이 남으면 거짓 → 선언 금지
    c3_no_mcp_pending = True                  # 검색층엔 MCP 정찰 단계 부재(항상 충족)
    c4_chain_existed = (fallback_chain != []) # 가용 채널이 0이면 "어디에도 못 물음" terminal
    # "검색 결과 없음" 선언 허용 = 가용 채널 전수 소진 AND 강등 채널 0(복구 미시도 없음).
    may_declare_no_results = (not fallback_chain) and c1_all_tried and c2_no_untried \
        and c3_no_mcp_pending and (not c4_chain_existed)
    note = []
    if forced:
        note.append("사용자 선호(%s)를 폴백 체인 1위로 강제" % forced["id"])
    if not fallback_chain:
        if untried_channels:
            note.append("가용 검색 채널 0 — 그러나 강등 채널 %d개 미시도(키/런타임 복구 시 가용) "
                        "→ '검색 결과 없음' 선언 금지(R6 C2 미충족)" % len(untried_channels))
        else:
            note.append("가용 검색 채널 0 + 강등 채널 0 → 전수 소진. "
                        "'검색 결과 없음' 선언 가능(R6 4조건 충족)")
    return {"capability": capability, "fallback_chain": fallback_chain,
            "active_backend": active_backend, "untried_channels": untried_channels,
            "may_declare_no_results": may_declare_no_results, "note": note}


def cmd_search(catalog, args):
    """검색 capability의 폴백 체인 + R6 전수소진 게이트를 산출한다(검색 채널 차원)."""
    if args.capability not in (catalog.get("capabilities", {}) or {}):
        return fail(2, "capability 없음: %s (가용: %s)"
                    % (args.capability, ",".join(catalog.get("capabilities", {}))))
    ctx = {"intent": args.intent or "",
           "style": [s for s in (args.style or "").split(",") if s.strip()],
           "prefer": args.prefer, "locked": args.locked}
    out = search_fallback(catalog, args.capability, ctx, args.free_first)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        chain = out["fallback_chain"]
        head = "→ %s (首选)" % out["active_backend"] if out["active_backend"] else "가용 채널 없음"
        print("search %s: %s" % (args.capability, head))
        for r in chain[1:]:
            print("   ↳ 备选 %-18s fit %.2f · %s" % (r["id"], r["fit"], r["why"]))
        for u in out["untried_channels"]:
            print("   [미시도] %-16s %s" % (u["id"], u["setup"]))
        for n in out["note"]:
            print("   · %s" % n)
    return 0 if out["fallback_chain"] else 1


def cmd_rank(catalog, args):
    if args.capability not in (catalog.get("capabilities", {}) or {}):
        return fail(2, "capability 없음: %s (가용: %s)"
                    % (args.capability, ",".join(catalog.get("capabilities", {}))))
    ctx = {"intent": args.intent or "",
           "style": [s for s in (args.style or "").split(",") if s.strip()],
           "prefer": args.prefer, "locked": args.locked}
    ranked, unavailable, forced = rank(catalog, args.capability, ctx, args.free_first)
    chosen = ranked[0] if ranked else None
    note = []
    if forced:
        note.append("사용자 선호(%s)를 1위로 강제(가용 확인됨)" % forced["id"])
    if not ranked:
        note.append("가용 후보 0 — 전부 키 미설정/비가용. setup_offer 참조")
    out = {"capability": args.capability, "free_first": args.free_first,
           "chosen": chosen, "ranking": ranked, "unavailable": unavailable, "note": note}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("select %s: %s" % (args.capability,
              ("→ %s (fit %.2f · %s)" % (chosen["id"], chosen["fit"], chosen["why"])) if chosen else "가용 후보 없음"))
        for r in ranked[1:]:
            print("   %-22s fit %.2f · %s" % (r["id"], r["fit"], r["why"]))
        for u in unavailable:
            print("   [미가용] %-18s %s" % (u["id"], u["setup"]))
        for n in note:
            print("   · %s" % n)
    return 0 if chosen else 1


def cmd_menu(catalog, as_json):
    """capability별 N-of-M 가용 메뉴(정직한 능력봉투 — 하드코딩 금지·카탈로그 파생)."""
    menu = {}
    for cap, provs in (catalog.get("capabilities", {}) or {}).items():
        avail = [p["id"] for p in provs if available(p)]
        unav = []
        for p in provs:
            if available(p):
                continue
            if not key_available(p):
                hint = "키 %s" % p.get("key_env")
                off = setup_offer("key", hint, p.get("key_env"))
                unav.append({"id": p["id"], "reason": "key", "hint": hint,
                             "action": off["action"], "setup": off["setup"]})
            else:
                _, why = runtime_ready(p)  # 로컬 런타임 미준비(W0-4)
                off = setup_offer("runtime", why)
                unav.append({"id": p["id"], "reason": "runtime", "hint": why,
                             "action": off["action"], "setup": off["setup"]})
        menu[cap] = {"configured": len(avail), "total": len(provs),
                     "available": avail, "unavailable": unav}
    if as_json:
        print(json.dumps(menu, ensure_ascii=False, indent=2))
    else:
        for cap, m in sorted(menu.items()):
            print("%-22s %d/%d  [%s]" % (cap, m["configured"], m["total"], ", ".join(m["available"])))
            for u in m["unavailable"]:
                print("      ↳ %s — %s" % (u["id"], u["setup"]))  # opt-in 안내(setup_offer)
    return 0


def verify_catalog(catalog):
    """프로바이더 계약 적합성 린트 → (errors, warnings). 카탈로그 레코드가 ezer_select가 기대하는
    인터페이스에 부합하는지 검증한다(OpenCut StickerProvider register-bug 교훈: 계약 미검증은 무음
    오동작). errors=차단(스코어 무음 default·미지 키 등), warnings=권고(준비성 게이트 부재 등)."""
    errors, warnings = [], []
    caps = catalog.get("capabilities")
    if not isinstance(caps, dict) or not caps:
        return (["capabilities가 비어있지 않은 객체가 아님"], [])
    seen_ids = {}
    for cap, provs in caps.items():
        if not isinstance(provs, list):
            errors.append("capability '%s' 값이 배열 아님" % cap)
            continue
        for i, p in enumerate(provs):
            if not isinstance(p, dict):
                errors.append("%s[%d] 객체 아님" % (cap, i))
                continue
            pid = p.get("id")
            w = "%s(%s)" % (cap, pid if pid else "?")
            for k in p:
                if k not in PROVIDER_KEYS:
                    errors.append("%s 미지 키 %r — %s" % (w, k, "|".join(PROVIDER_KEYS)))
            for k in PROVIDER_REQUIRED:
                if k not in p:
                    errors.append("%s 필수 키 누락: %s" % (w, k))
            if not (isinstance(pid, str) and pid.strip()):
                errors.append("%s id 비어있지 않은 문자열 필요" % w)
            else:
                seen_ids.setdefault(pid, []).append(cap)
            rt = p.get("runtime")
            if rt is not None and rt not in RUNTIME_REL:
                errors.append("%s runtime 무효(%r) — %s" % (w, rt, "|".join(RUNTIME_REL)))
            ct = p.get("cost_tier")
            if ct is not None and ct not in COST_SCORE:
                errors.append("%s cost_tier 무효(%r) — %s" % (w, ct, "|".join(COST_SCORE)))
            if "quality_tier" in p and p["quality_tier"] not in QUALITY_SCORE:
                errors.append("%s quality_tier 무효(%r) — %s (미인식=점수 무음 default)"
                              % (w, p["quality_tier"], "|".join(QUALITY_SCORE)))
            ke = p.get("key_env")
            if ke is not None and not (isinstance(ke, str) and ke.strip()):
                errors.append("%s key_env는 null 또는 비어있지 않은 문자열" % w)
            if "best_for" in p and not isinstance(p["best_for"], list):
                errors.append("%s best_for 배열 아님" % w)
            if "supports" in p and not isinstance(p["supports"], dict):
                errors.append("%s supports 객체 아님" % w)
            probe = p.get("probe")
            if probe is not None:
                if not isinstance(probe, dict) or not probe:
                    errors.append("%s probe 비어있지 않은 객체 필요" % w)
                else:
                    for k in probe:
                        if k not in PROBE_KEYS:
                            errors.append("%s probe 미지 키 %r — %s" % (w, k, "|".join(PROBE_KEYS)))
                    for k in PROBE_STR_KEYS:
                        if k in probe and not (isinstance(probe[k], str) and probe[k].strip()):
                            errors.append("%s probe.%s 비어있지 않은 문자열 필요" % (w, k))
                    for k in PROBE_LIST_KEYS:
                        if k in probe and not (isinstance(probe[k], list) and probe[k]
                                               and all(isinstance(x, str) and x.strip() for x in probe[k])):
                            errors.append("%s probe.%s 비어있지 않은 문자열 배열 필요" % (w, k))
            # W0-4 권고: 무키 local/local_gpu 인데 probe 없으면 준비성 게이트 부재(미설치도 가용 선택 위험)
            if rt in ("local", "local_gpu") and not p.get("key_env") and not probe:
                warnings.append("%s 무키 %s 인데 probe 없음 — 준비성 게이트 부재" % (w, rt))
    for pid, cw in seen_ids.items():
        if len(cw) > 1:
            warnings.append("id '%s' 가 여러 capability에 중복: %s" % (pid, ", ".join(cw)))
    return errors, warnings


def cmd_verify(catalog, as_json):
    errors, warnings = verify_catalog(catalog)
    ok = not errors
    if as_json:
        print(json.dumps({"ok": ok, "errors": errors, "warnings": warnings},
                         ensure_ascii=False, indent=2))
    else:
        for e in errors:
            print("[ERROR] %s" % e)
        for wn in warnings:
            print("[WARN] %s" % wn)
        print("catalog verify: %s — %d errors, %d warnings"
              % ("OK" if ok else "REJECT", len(errors), len(warnings)))
        if not ok:
            print("이 출력 외 추론으로 카탈로그 정합을 선언하지 마라.")
    return 0 if ok else 1


def fail(code, msg):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    return code


def self_test():
    failures = []
    cat = {"capabilities": {"video_generation": [
        {"id": "fal-kling", "provider": "fal", "key_env": "FAL_KEY", "cost_tier": "high",
         "quality_tier": "good", "runtime": "api", "best_for": ["b-roll", "image-to-video", "cheap"]},
        {"id": "fal-seedance", "provider": "fal", "key_env": "FAL_KEY", "cost_tier": "high",
         "quality_tier": "premium", "runtime": "api", "best_for": ["cinematic", "trailer", "premium"]},
        {"id": "stock-pexels", "provider": "pexels", "cost_tier": "free",
         "quality_tier": "good", "runtime": "stock", "best_for": ["b-roll", "stock", "footage"]},
        {"id": "wan-local", "provider": "wan", "key_env": "WAN_LOCAL", "cost_tier": "free",
         "quality_tier": "good", "runtime": "local_gpu", "best_for": ["b-roll", "free"]},
    ]}}
    sink = io.StringIO()

    def _rank(ctx, free_first=False):
        return rank(cat, "video_generation", ctx, free_first)

    # 1) deny-by-default: FAL_KEY 미설정 환경에선 fal-* 제외, 키 불요 stock만 가용
    saved = os.environ.pop("FAL_KEY", None)
    try:
        ranked, unav, _ = _rank({"intent": "b-roll"})
        avail_ids = {r["id"] for r in ranked}
        if "fal-kling" in avail_ids or "fal-seedance" in avail_ids:
            failures.append("키 없는 fal-*가 가용으로 랭킹됨(deny-by-default 위반)")
        if "stock-pexels" not in avail_ids:
            failures.append("키 불요 stock이 가용에서 빠짐")
        offered = next((u for u in unav if u["id"] == "fal-kling"), None)
        if not offered:
            failures.append("미가용 fal-kling이 setup_offer에 없음")
        elif offered.get("action") != "set_env" or offered.get("irreversible") is not False:
            failures.append("키 미설정 fal-kling의 setup_offer action≠set_env 또는 irreversible≠False")
        # 2) 가용 후보 0 → exit 1
        empty = {"capabilities": {"x": [{"id": "needkey", "key_env": "NOPE", "cost_tier": "high"}]}}
        r2, _, _ = rank(empty, "x", {}, False)
        if r2:
            failures.append("키 없는 단일 후보가 가용으로 잡힘")
        # 3) task_fit: cinematic 의도 → seedance(키 필요)는 제외됐으니 stock 중 best_for 매치 확인
        #    동의어: 'trailer' 의도가 seedance best_for 'cinematic'과 매치되는지(키 복구 후)
    finally:
        if saved is not None:
            os.environ["FAL_KEY"] = saved
        else:
            os.environ["FAL_KEY"] = "selftest-dummy"
    # 키 복구된 상태(dummy)에서:
    # 4) cinematic 의도 → fal-seedance(premium·best_for cinematic)가 1위여야
    ranked, _, _ = _rank({"intent": "cinematic trailer"})
    if not ranked or ranked[0]["id"] != "fal-seedance":
        failures.append("cinematic 의도인데 seedance가 1위가 아님: %s" % (ranked[0]["id"] if ranked else None))
    # 5) free-first: free 모드면 같은 b-roll 의도에서 free(stock/wan)가 fal보다 위로
    rf, _, _ = _rank({"intent": "b-roll"}, free_first=True)
    if rf and rf[0]["cost_tier"] != "free":
        failures.append("free-first인데 1위가 free가 아님: %s" % rf[0]["id"])
    # 6) 사용자 선호 override: prefer=fal-kling이면 강제 1위
    rp, _, forced = _rank({"intent": "cinematic", "prefer": "fal-kling"})
    if not forced or rp[0]["id"] != "fal-kling":
        failures.append("사용자 선호 override 실패")
    # 7) 무점수 채널: 출력에 0-100 정수 grade가 없어야(fit는 0~1 라우팅 적합도)
    with contextlib.redirect_stdout(sink):
        cmd_rank(cat, argparse.Namespace(capability="video_generation", intent="b-roll",
                 style="", prefer=None, locked=None, free_first=False, json=True))
    if re.search(r'"(score|grade|rating)"\s*:', sink.getvalue()):
        failures.append("출력에 금지된 score/grade/rating 키 존재")
    # 8) 결정론: 같은 입력 두 번 → 동일 랭킹 순서
    a = [r["id"] for r in _rank({"intent": "b-roll"})[0]]
    b = [r["id"] for r in _rank({"intent": "b-roll"})[0]]
    if a != b:
        failures.append("비결정 랭킹")

    # 8b) permutation 불변식(OPP-05): prefer override(rank:239-245 insert-0)는 가용 후보
    #     집합의 permutation일 뿐 — 후보를 추가/삭제하거나 작동 백엔드를 숨기지 못한다.
    #     이는 신규 능력이 아니라 기존 forced 로직(가용 후보 내 재배열)의 박제다.
    #     한계: "재배열이 permutation임"만 잠그지 "재배열 순서가 최적인가"는 검증 안 함.
    base = [r["id"] for r in _rank({"intent": "b-roll"})[0]]               # prefer 없는 기준
    pref = _rank({"intent": "b-roll", "prefer": "stock-pexels"})[0]        # 가용 prefer 강제
    if set(r["id"] for r in pref) != set(base):
        failures.append("permutation 위반: prefer override가 가용 집합을 변경(추가/삭제)")
    if len(pref) != len(base):
        failures.append("permutation 위반: prefer override로 후보 수 변동(작동 백엔드 은닉)")
    unk = _rank({"intent": "b-roll", "prefer": "no-such-provider-id"})     # unknown prefer
    if [r["id"] for r in unk[0]] != base or unk[2] is not None:
        failures.append("unknown prefer가 fail-safe 아님(랭킹 변형 또는 forced≠None)")

    # 9) 로컬 런타임 준비성 게이트(W0-4): probe 미선언=ready, bin/module 실측
    def rt(name, prov, want):
        ready, _ = runtime_ready(prov)
        if ready != want:
            failures.append("runtime_ready %s: ready=%s want=%s" % (name, ready, want))

    rt("no-probe", {"id": "x"}, True)                                   # probe 없으면 ready(레거시 보존)
    rt("bin-present", {"probe": {"bin": "sh"}}, True)                   # sh는 어디나 PATH에
    rt("bin-absent", {"probe": {"bin": "no_such_bin_xyz123"}}, False)
    rt("module-present", {"probe": {"module": "json"}}, True)           # stdlib 항상 import 가능
    rt("module-absent", {"probe": {"module": "no_such_mod_xyz123"}}, False)
    rt("any-bin-ok", {"probe": {"any_bin": ["no_x", "sh"]}}, True)
    rt("any-bin-no", {"probe": {"any_bin": ["no_x", "no_y"]}}, False)
    rt("path-absent", {"probe": {"path": "/no/such/path/xyz123"}}, False)
    rt("combined-fail", {"probe": {"bin": "sh", "module": "no_such_mod_xyz123"}}, False)

    # 10) 미준비 local provider는 available=False → 랭킹 제외·unavailable(runtime 사유)
    cat_rt = {"capabilities": {"scene-cut": [
        {"id": "scenecut_ready", "cost_tier": "free", "runtime": "local", "best_for": ["cuts"]},
        {"id": "scenecut_unready", "cost_tier": "free", "runtime": "local", "best_for": ["cuts"],
         "probe": {"bin": "no_such_bin_xyz123"}},
    ]}}
    rr, ru, _ = rank(cat_rt, "scene-cut", {"intent": "cuts"}, False)
    ids = {r["id"] for r in rr}
    if "scenecut_unready" in ids:
        failures.append("미준비 local provider가 가용으로 랭킹됨(W0-4 게이트 실패)")
    if "scenecut_ready" not in ids:
        failures.append("준비된 local provider가 빠짐")
    if not any(u["id"] == "scenecut_unready" and u.get("reason") == "runtime" for u in ru):
        failures.append("미준비 provider가 runtime 사유로 unavailable에 없음")

    # 11) 프로바이더 계약 적합성 린트(W1-3 verify)
    def vc(name, cat, want_err, want_warn=None):
        e, wn = verify_catalog(cat)
        if bool(e) != want_err:
            failures.append("verify %s: errors=%s want_err=%s (%s)" % (name, bool(e), want_err, e))
        if want_warn is not None and bool(wn) != want_warn:
            failures.append("verify %s: warnings=%s want_warn=%s (%s)" % (name, bool(wn), want_warn, wn))

    good_prov = {"id": "p1", "runtime": "api", "cost_tier": "free", "quality_tier": "good",
                 "key_env": "K", "best_for": ["x"], "supports": {}}
    vc("good", {"capabilities": {"c": [good_prov]}}, False, False)
    vc("no-caps", {"capabilities": {}}, True)
    vc("unknown-key", {"capabilities": {"c": [dict(good_prov, wat=1)]}}, True)
    vc("missing-runtime", {"capabilities": {"c": [{"id": "p", "cost_tier": "free"}]}}, True)
    vc("bad-runtime", {"capabilities": {"c": [{"id": "p", "runtime": "quantum", "cost_tier": "free"}]}}, True)
    vc("bad-cost", {"capabilities": {"c": [{"id": "p", "runtime": "api", "cost_tier": "cheap"}]}}, True)
    vc("bad-quality", {"capabilities": {"c": [dict(good_prov, quality_tier="meh")]}}, True)
    vc("bad-keyenv", {"capabilities": {"c": [dict(good_prov, key_env="")]}}, True)
    vc("bad-probe", {"capabilities": {"c": [{"id": "p", "runtime": "local", "cost_tier": "free",
                                             "probe": {"bin": ""}}]}}, True)
    vc("probe-unknown", {"capabilities": {"c": [{"id": "p", "runtime": "local", "cost_tier": "free",
                                                 "probe": {"gpu": "cuda"}}]}}, True)
    # 무키 local + probe 없음 → 에러 아님, 경고
    vc("local-no-probe-warn", {"capabilities": {"c": [{"id": "p", "runtime": "local",
                                                       "cost_tier": "free"}]}}, False, True)

    # 12) setup_offer 결정론 파생(opt-in 안내) — action enum·irreversible 불변식·텍스트 only
    def so(name, reason, hint, key_env, want_action):
        off = setup_offer(reason, hint, key_env)
        if off["action"] != want_action:
            failures.append("setup_offer %s: action=%s want=%s" % (name, off["action"], want_action))
        if off["action"] not in SETUP_ACTIONS:
            failures.append("setup_offer %s: action %s 가 enum 밖" % (name, off["action"]))
        if off["irreversible"] is not False:
            failures.append("setup_offer %s: irreversible≠False(자동 비가역 동작 금지 위반)" % name)

    so("key", "key", "키 FAL_KEY", "FAL_KEY", "set_env")
    so("runtime-bin", "runtime", "런타임 미준비: 바이너리 'ffmpeg' PATH에 없음", None, "install_bin")
    so("runtime-module", "runtime", "런타임 미준비: 파이썬 모듈 'torch' 미설치", None, "install_module")
    so("runtime-path", "runtime", "런타임 미준비: 경로 '~/m.pt' 없음(모델 미캐시)", None, "fetch_model")
    so("runtime-other", "runtime", "런타임 미준비: 알수없음", None, "install_bin")  # 보수적 기본
    # irreversible 불변식: 모든 파생이 False(denylist 박제)
    if any(setup_offer(r, h, k)["irreversible"] is not False for r, h, k in
           [("key", "키 X", "X"), ("runtime", "바이너리 z 없음", None)]):
        failures.append("setup_offer irreversible 불변식 위반(자동 실행 표면)")
    # 멱등·무상태: 동일 입력 2회 동일 출력(env 미변경)
    if setup_offer("key", "키 X", "X") != setup_offer("key", "키 X", "X"):
        failures.append("setup_offer 비결정/상태 누수")

    # 13) OPP-22 검색 채널 폴백 체인 + R6 전수소진 게이트(검색 채널 차원)
    #     신규 엔진 0 — rank()/setup_offer()/available() 재사용의 합성만 검증.
    os.environ.pop("FAL_KEY", None)  # 검색 채널 테스트는 무키 환경에서
    # 채널 = 무키 web(首选)·무키 platform(备选)·키필요 semantic(강등). web/platform만 가용.
    cat_search = {"capabilities": {"web_search": [
        {"id": "web", "cost_tier": "free", "runtime": "stock", "quality_tier": "good",
         "best_for": ["query", "web", "general"]},
        {"id": "semantic", "key_env": "EXA_KEY", "cost_tier": "high", "runtime": "api",
         "quality_tier": "good", "best_for": ["semantic", "similar", "related"]},
        {"id": "platform", "cost_tier": "free", "runtime": "stock", "quality_tier": "fair",
         "best_for": ["reddit", "naver", "site"]},
    ]}}
    sf = search_fallback(cat_search, "web_search", {"intent": "general web"}, False)
    chain_ids = [c["id"] for c in sf["fallback_chain"]]
    # (a) 폴백 체인 = 가용(무키) 채널만 — semantic은 키 없어 강등
    if "semantic" in chain_ids:
        failures.append("search: 키 없는 semantic이 폴백 체인에 들어감(deny-by-default 위반)")
    if "web" not in chain_ids or "platform" not in chain_ids:
        failures.append("search: 무키 web/platform이 폴백 체인에서 빠짐")
    # (b) active_backend = 폴백 체인 1위(실증 후에만, PHIL-03)
    if sf["active_backend"] != chain_ids[0]:
        failures.append("search: active_backend가 폴백 체인 1위와 불일치")
    # (c) 강등된 semantic이 untried_channels에 set_env 처방으로 노출(복구 가능)
    unt = {u["id"]: u for u in sf["untried_channels"]}
    if "semantic" not in unt or unt["semantic"]["action"] != "set_env":
        failures.append("search: 강등 semantic이 untried_channels(set_env)에 없음")
    # (d) R6 C2: 가용 채널이 있으면 '검색 결과 없음' 선언 금지(아직 시도할 게 있음)
    if sf["may_declare_no_results"] is not False:
        failures.append("search: 가용 채널 있는데 may_declare_no_results=True(R6 위반)")
    # (e) 강등 채널이 남으면 가용 0이어도 선언 금지(R6 C2 — untried 미시도)
    cat_keyonly = {"capabilities": {"web_search": [
        {"id": "semantic", "key_env": "EXA_KEY", "cost_tier": "high", "runtime": "api"},
    ]}}
    sf2 = search_fallback(cat_keyonly, "web_search", {"intent": "x"}, False)
    if sf2["fallback_chain"]:
        failures.append("search: 키 없는 단일 채널이 가용으로 잡힘")
    if sf2["may_declare_no_results"] is not False:
        failures.append("search: 강등 채널 미시도인데 may_declare_no_results=True(R6 C2 위반)")
    # (f) 전수 소진(가용 0 + 강등 0) → '검색 결과 없음' 선언 허용(R6 4조건 충족)
    cat_empty = {"capabilities": {"web_search": []}}
    sf3 = search_fallback(cat_empty, "web_search", {"intent": "x"}, False)
    if sf3["may_declare_no_results"] is not True:
        failures.append("search: 전수 소진(채널 0)인데 may_declare_no_results≠True")
    # (g) 결정론: 동일 입력 2회 동일 폴백 체인
    if [c["id"] for c in search_fallback(cat_search, "web_search", {"intent": "general web"}, False)["fallback_chain"]] != chain_ids:
        failures.append("search: 비결정 폴백 체인")
    # (h) 무점수: 출력에 score/grade/rating 키 없음(eval-driven — fit는 0~1 라우팅 적합도)
    if re.search(r'"(score|grade|rating)"\s*:', json.dumps(sf, ensure_ascii=False)):
        failures.append("search: 출력에 금지된 score/grade/rating 키 존재")

    os.environ.pop("FAL_KEY", None)  # 청소

    print(json.dumps({"self_test": "ok" if not failures else "fail",
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="채점식 provider 선택 엔진 (도메인-무관·결정론)")
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    r = sub.add_parser("rank", help="capability 가용 provider 랭킹 (0=결정 1=가용없음)")
    r.add_argument("--catalog", required=True)
    r.add_argument("--capability", required=True)
    r.add_argument("--intent", default="")
    r.add_argument("--style", default="", help="콤마 구분 스타일 키워드")
    r.add_argument("--prefer", default=None, help="사용자 선호 provider id(가용 시 1위 강제)")
    r.add_argument("--locked", default=None, help="이미 잠긴 provider id(연속성 가점)")
    r.add_argument("--free-first", action="store_true", help="무료(로컬·스톡) 우선")
    r.add_argument("--json", action="store_true")

    m = sub.add_parser("menu", help="capability별 N-of-M 가용 메뉴(정직한 능력봉투)")
    m.add_argument("--catalog", required=True)
    m.add_argument("--json", action="store_true")

    ve = sub.add_parser("verify", help="프로바이더 계약 적합성 린트 (0=준수 1=위반 2=입출력)")
    ve.add_argument("--catalog", required=True)
    ve.add_argument("--json", action="store_true")

    sr = sub.add_parser("search", help="검색 의도→다중 검색채널 폴백 체인 + R6 전수소진 게이트 "
                                       "(OPP-22 · 0=가용채널有 1=가용0)")
    sr.add_argument("--catalog", required=True)
    sr.add_argument("--capability", required=True, help="검색 capability(예: web_search)")
    sr.add_argument("--intent", default="")
    sr.add_argument("--style", default="", help="콤마 구분 스타일 키워드")
    sr.add_argument("--prefer", default=None, help="사용자 선호 채널 id(가용 시 1위 강제)")
    sr.add_argument("--locked", default=None, help="이미 잠긴 채널 id(연속성 가점)")
    sr.add_argument("--free-first", action="store_true", help="무료 채널 우선")
    sr.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.cmd in ("rank", "menu", "verify", "search"):
        try:
            catalog = load_catalog(args.catalog)
        except (OSError, json.JSONDecodeError) as e:
            return fail(2, "카탈로그 로드 실패: %s" % e)
        if args.cmd == "rank":
            return cmd_rank(catalog, args)
        if args.cmd == "verify":
            return cmd_verify(catalog, args.json)
        if args.cmd == "search":
            return cmd_search(catalog, args)
        return cmd_menu(catalog, args.json)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
