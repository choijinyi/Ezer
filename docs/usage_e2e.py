#!/usr/bin/env python3
"""T5 사용량 관측 수집기 E2E — 샌드박스 데몬에 fixture 트랜스크립트/rollout을 물려
surface.list/org.status 노출·이벤트 발화를 실측 검증한다 (20/20 PASS 기대).

실행법 (재접속 시):
  1) cargo build --bins                          # 신 바이너리 보장 (cargo test는 바이너리 갱신 안 함)
  2) export EZER_E2E_SOCK=/tmp/ezer-e2e-$$.sock
  3) EZER_SOCKET=$EZER_E2E_SOCK EZER_PACK_DIR=/tmp/ezer-e2e-pack EZER_USAGE_POLL_SECS=1 \
       ./target/debug/ezerd > /tmp/ezer-e2e.log 2>&1 &
  4) python3 docs/usage_e2e.py
  5) pgrep -f "$EZER_E2E_SOCK" | xargs kill        # 샌드박스 데몬 정리"""
import json
import os
import socket
import subprocess
import sys
import time

SOCK = os.environ.get("EZER_E2E_SOCK", "/tmp/ezer-e2e-usage-r3.sock")
ROOT = "/Users/user/Desktop/EZERezer/ezer-agent"
CLAUDE_TX = "/tmp/ezer-e2e-claude.jsonl"
CODEX_TX = "/tmp/ezer-e2e-rollout.jsonl"

FAIL = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def rpc(method, params):
    s = socket.socket(socket.AF_UNIX)
    s.connect(SOCK)
    s.sendall((json.dumps({"id": 1, "method": method, "params": params}) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(1 << 16)
        if not chunk:
            break
        buf += chunk
    s.close()
    return json.loads(buf)


def replay_events(names):
    """events.stream after_seq=0 — 재생분만 짧은 타임아웃으로 수집"""
    s = socket.socket(socket.AF_UNIX)
    s.connect(SOCK)
    s.sendall((json.dumps({"id": 1, "method": "events.stream",
                           "params": {"after_seq": 0}}) + "\n").encode())
    s.settimeout(1.0)
    buf = b""
    try:
        while True:
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    s.close()
    evs = []
    for line in buf.decode(errors="replace").splitlines():
        try:
            v = json.loads(line)
        except Exception:
            continue
        if v.get("name") in names:
            evs.append(v)
    return evs


def claude_line(input_t, cache_read, cache_create, sidechain=False):
    return json.dumps({
        "type": "assistant", "isSidechain": sidechain, "requestId": "req",
        "message": {"model": "claude-fable-5",
                    "usage": {"input_tokens": input_t,
                              "cache_read_input_tokens": cache_read,
                              "cache_creation_input_tokens": cache_create,
                              "output_tokens": 999}}}) + "\n"


def append(path, text):
    with open(path, "a") as f:
        f.write(text)


def surfaces():
    return rpc("surface.list", {})["result"]["surfaces"]


def usage_of(sid):
    for s in surfaces():
        if s["surface_id"] == sid:
            return s.get("usage")
    return None


def main():
    for p in (CLAUDE_TX, CODEX_TX):
        if os.path.exists(p):
            os.remove(p)

    # ── claude pane ──
    r = rpc("surface.create", {"cmd": "sleep 600", "title": "e2e-claude", "cwd": "/tmp"})
    sid1 = r["result"]["surface_id"]
    rpc("surface.set_meta", {"surface_id": sid1, "agent": "claude", "agent_bin": "claude"})
    # 파일 생성 전 등록 — SessionStart 시점 시나리오 (수집기는 파일 생길 때까지 무해 대기)
    r = rpc("usage.register", {"surface_id": sid1, "transcript": CLAUDE_TX})
    check("usage.register (파일 생성 전) 통과", r.get("ok") is True, str(r))

    # 사이드체인(서브에이전트) 라인만 → 관측 없음이 정답
    append(CLAUDE_TX, claude_line(2, 150_000, 0, sidechain=True))
    time.sleep(2.5)
    check("사이드체인만 있을 때 usage 미노출", usage_of(sid1) is None, str(usage_of(sid1)))

    # 메인 체인 50% (100k/200k)
    append(CLAUDE_TX, claude_line(2, 99_000, 998))
    time.sleep(2.5)
    u = usage_of(sid1)
    check("claude ctx_pct=50", u and u.get("ctx_pct") == 50, str(u))
    check("claude source=transcript(등록)", u and u.get("source") == "transcript", str(u))
    check("claude ctx_window=200000", u and u.get("ctx_window") == 200_000, str(u))

    # 65%로 상승 → context.threshold(source=observed) 1회
    append(CLAUDE_TX, claude_line(2, 129_000, 998))
    time.sleep(2.5)
    u = usage_of(sid1)
    check("claude ctx_pct=65", u and u.get("ctx_pct") == 65, str(u))
    evs = [e for e in replay_events({"context.threshold"})
           if e.get("surface_id") == sid1]
    check("context.threshold observed 1회", len(evs) == 1, f"{len(evs)}회: {evs}")
    check("threshold payload source=observed",
          bool(evs) and evs[0]["payload"].get("source") == "observed", str(evs))

    # 70% 체류 — 재발화 없음
    append(CLAUDE_TX, claude_line(2, 139_000, 998))
    time.sleep(2.5)
    evs = [e for e in replay_events({"context.threshold"})
           if e.get("surface_id") == sid1]
    check("임계 위 체류 중 재발화 없음", len(evs) == 1, f"{len(evs)}회")

    # 자기보고(status.set 70%)도 공유 게이트에 막혀 이중 발화 없음
    rpc("status.set", {"surface_id": sid1, "state": "working", "context": 70})
    time.sleep(1.0)
    evs = [e for e in replay_events({"context.threshold"})
           if e.get("surface_id") == sid1]
    check("자기보고+관측 공유 게이트 — 이중 발화 차단", len(evs) == 1, f"{len(evs)}회")
    check("발화 이벤트 source=observed 유지",
          bool(evs) and evs[0]["payload"].get("source") == "observed", str(evs))

    # ── codex pane ──
    r = rpc("surface.create", {"cmd": "sleep 600", "title": "e2e-codex", "cwd": "/tmp"})
    sid2 = r["result"]["surface_id"]
    rpc("surface.set_meta", {"surface_id": sid2, "agent": "codex", "agent_bin": "codex"})
    rpc("usage.register", {"surface_id": sid2, "transcript": CODEX_TX})
    append(CODEX_TX, json.dumps({"timestamp": "t", "type": "session_meta",
                                 "payload": {"id": "u", "cwd": "/tmp"}}) + "\n")
    append(CODEX_TX, json.dumps({
        "timestamp": "t", "type": "event_msg",
        "payload": {"type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": 27296,
                                                   "reasoning_output_tokens": 352},
                             "last_token_usage": {"input_tokens": 26788,
                                                  "cached_input_tokens": 2432,
                                                  "output_tokens": 508,
                                                  "reasoning_output_tokens": 352,
                                                  "total_tokens": 27296},
                             "model_context_window": 258400},
                    "rate_limits": {"primary": {"used_percent": 13.0,
                                                "window_minutes": 300,
                                                "resets_at": 1781314865},
                                    "secondary": {"used_percent": 3.0,
                                                  "window_minutes": 10080,
                                                  "resets_at": 1781781650},
                                    "plan_type": "plus"}}}) + "\n")
    time.sleep(2.5)
    u = usage_of(sid2)
    check("codex ctx_pct=10 (26944/258400)", u and u.get("ctx_pct") == 10, str(u))
    check("codex rate 5h=13%", u and u.get("rate") and u["rate"][0]["label"] == "5h"
          and u["rate"][0]["used_pct"] == 13.0, str(u))
    check("codex rate 7d=3%", u and len(u.get("rate", [])) == 2
          and u["rate"][1]["label"] == "7d" and u["rate"][1]["used_pct"] == 3.0, str(u))
    check("codex resets_at 전달", u and u["rate"][0].get("resets_at") == 1781314865, str(u))

    # rate-limit-only 이벤트 → ctx 유지·rate 갱신 (병합)
    append(CODEX_TX, json.dumps({
        "timestamp": "t", "type": "event_msg",
        "payload": {"type": "token_count", "info": None,
                    "rate_limits": {"primary": {"used_percent": 55.0,
                                                "window_minutes": 300,
                                                "resets_at": 1781314865}}}}) + "\n")
    time.sleep(2.5)
    u = usage_of(sid2)
    check("codex rate-only 병합: ctx 유지", u and u.get("ctx_pct") == 10, str(u))
    check("codex rate-only 병합: 5h=55%", u and u["rate"][0]["used_pct"] == 55.0, str(u))

    # org.status에도 동일 노출
    org = rpc("org.status", {})["result"]
    surf = [s for s in org["surfaces"] if s["surface_id"] == sid2]
    check("org.status usage 노출", bool(surf) and surf[0].get("usage", {}).get("ctx_pct") == 10,
          str(surf))

    # usage.updated 이벤트 발화 확인
    ups = [e for e in replay_events({"usage.updated"}) if e.get("surface_id") in (sid1, sid2)]
    check("usage.updated 이벤트 발화", len(ups) >= 3, f"{len(ups)}건")

    # 소유 게이트: pane 밖 발신(이 스크립트)은 익명 통과지만, 등록 검증은 단위테스트가 핀.
    # 여기서는 경로 위생만 재확인.
    r = rpc("usage.register", {"surface_id": sid1, "transcript": "relative/x.jsonl"})
    check("상대경로 등록 거부", r.get("ok") is False, str(r))

    rpc("surface.close", {"surface_id": sid1})
    rpc("surface.close", {"surface_id": sid2})

    print()
    if FAIL:
        print(f"E2E FAIL {len(FAIL)}: {FAIL}")
        sys.exit(1)
    print("E2E ALL PASS")


if __name__ == "__main__":
    main()
