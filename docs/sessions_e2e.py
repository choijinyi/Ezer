#!/usr/bin/env python3
"""T7 E4 세션 타임라인 E2E — control.sessions / session_detail / session_star RPC를 실측한다.

(1) usage_records+events를 세션 단위로 병합(토큰·비용·턴·실패·top_skill·활동리본),
(2) ended_at 내림차순 정렬, (3) ⭐ 토글(star/unstar)·starred 플래그 반영,
(4) session_detail 이벤트 타임라인 + 토큰/비용 요약 — 을 검증한다.

실행: cargo build --bins && python3 docs/sessions_e2e.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import time

DIR = f"/tmp/ezer-e4-{os.getpid()}"
os.makedirs(DIR, exist_ok=True)
SOCK = os.path.join(DIR, "ezer.sock")
EZERD = os.path.join(os.path.dirname(__file__), "..", "target", "debug", "ezerd")
ENV = dict(os.environ, EZER_SOCKET=SOCK, EZER_PACK_DIR=os.path.join(DIR, "pack"))
DBP = os.path.join(DIR, "analytics.db")
FAIL = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def rpc(method, params):
    s = socket.socket(socket.AF_UNIX)
    s.connect(SOCK)
    s.sendall((json.dumps({"id": 1, "method": method, "params": params}) + "\n").encode())
    b = b""
    while not b.endswith(b"\n"):
        c = s.recv(65536)
        if not c:
            break
        b += c
    s.close()
    return json.loads(b)


def start_daemon():
    p = subprocess.Popen([EZERD], env=ENV, stdout=open(os.path.join(DIR, "ezerd.log"), "a"), stderr=subprocess.STDOUT)
    for _ in range(50):
        try:
            if rpc("system.ping", {}):
                return p
        except OSError:
            time.sleep(0.1)
    return p


def sessions(window="all"):
    return rpc("control.sessions", {"window": window})["result"]["sessions"]


def main():
    daemon = start_daemon()
    try:
        now = time.time()
        for _ in range(50):
            if os.path.exists(DBP):
                break
            time.sleep(0.1)
        conn = sqlite3.connect(DBP)
        conn.executemany(
            "INSERT INTO usage_records(session_id, role, agent, model, input_tokens, output_tokens, "
            "cache_creation, cache_read, cost_usd, ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                ("/s/a", "worker", "claude", "claude-opus-4-8", 1000, 300, 0, 0, 0.05, now - 100),
                ("/s/a", "worker", "claude", "claude-opus-4-8", 500, 200, 0, 0, 0.01, now - 40),  # ended later
                ("/s/b", "reviewer-codex", "codex", "claude-haiku-4-5", 200, 50, 0, 0, 0.001, now - 70),
            ])

        def ev(sid, role, tool, isk, skn, isa, exit_code, ts):
            return (sid, role, "claude", "PRE_TOOL" if exit_code is None else "POST_TOOL", tool,
                    int(isk), skn, 0, int(isa), None, None, exit_code, None, ts)
        conn.executemany(
            "INSERT INTO events(session_id, role, agent, event_type, tool_name, is_skill, skill_name, "
            "is_slash, is_agent, agent_type, agent_id, exit_code, duration_ms, ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ev("/s/a", "worker", "Skill", 1, "commit", 0, None, now - 90),
                ev("/s/a", "worker", "Skill", 1, "commit", 0, 0, now - 89),
                ev("/s/a", "worker", "Bash", 0, None, 0, None, now - 60),
                ev("/s/a", "worker", "Bash", 0, None, 0, 1, now - 59),  # 실패
                ev("/s/b", "reviewer-codex", "Task", 0, None, 1, None, now - 68),
            ])
        conn.commit()
        conn.close()
        time.sleep(0.2)

        ss = sessions("all")
        check("세션 2개", len(ss) == 2, str([s["session_id"] for s in ss]))
        check("ended_at 내림차순 — /s/a 먼저", ss and ss[0]["session_id"] == "/s/a", str([s["session_id"] for s in ss]))
        a = next((s for s in ss if s["session_id"] == "/s/a"), {})
        check("/s/a agent=claude·role=worker", a.get("agent") == "claude" and a.get("role") == "worker", str(a))
        check("/s/a 턴 2·토큰 2000", a.get("msgs") == 2 and a.get("tokens") == 2000, str(a))
        check("/s/a 비용 ≈ 0.06", abs(a.get("cost_usd", 0) - 0.06) < 1e-9, str(a.get("cost_usd")))
        check("/s/a skill_calls 1·top_skill commit", a.get("skill_calls") == 1 and a.get("top_skill") == "commit", str(a))
        check("/s/a fail_calls 1", a.get("fail_calls") == 1, str(a))
        check("/s/a 활동리본 24칸", len(a.get("ribbon", [])) == 24, str(len(a.get("ribbon", []))))
        check("/s/a starred 기본 false", a.get("starred") is False, str(a.get("starred")))
        b = next((s for s in ss if s["session_id"] == "/s/b"), {})
        check("/s/b agent_calls 1(위임)", b.get("agent_calls") == 1, str(b))

        # ⭐ 토글
        rpc("control.session_star", {"session_id": "/s/a", "starred": True})
        a2 = next((s for s in sessions("all") if s["session_id"] == "/s/a"), {})
        check("⭐ star 후 starred=true", a2.get("starred") is True, str(a2.get("starred")))
        rpc("control.session_star", {"session_id": "/s/a", "starred": False})
        a3 = next((s for s in sessions("all") if s["session_id"] == "/s/a"), {})
        check("⭐ unstar 후 starred=false", a3.get("starred") is False, str(a3.get("starred")))

        # 상세
        d = rpc("control.session_detail", {"session_id": "/s/a"})["result"]
        check("detail timeline 4 이벤트", len(d.get("timeline", [])) == 4, str(len(d.get("timeline", []))))
        check("detail timeline ts 오름차순", [e["ts"] for e in d["timeline"]] == sorted(e["ts"] for e in d["timeline"]), "정렬")
        check("detail summary 토큰 2000", d.get("summary", {}).get("totals", {}).get("tokens") == 2000, str(d.get("summary", {}).get("totals")))
        post_fail = [e for e in d["timeline"] if e.get("exit_code") == 1]
        check("detail 실패 이벤트 1(Bash POST)", len(post_fail) == 1 and post_fail[0]["tool_name"] == "Bash", str(post_fail))
    finally:
        daemon.terminate()
        try:
            daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            daemon.kill()

    print()
    if FAIL:
        print(f"❌ {len(FAIL)} FAIL: {FAIL}")
        raise SystemExit(1)
    print("✅ E4 세션 타임라인 E2E 전부 PASS — 병합·정렬·top_skill·리본·⭐토글·상세 타임라인 검증")


if __name__ == "__main__":
    main()
