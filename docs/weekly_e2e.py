#!/usr/bin/env python3
"""T7 E5 주간 다이제스트 E2E — control.weekly RPC를 실측한다.

이번주(now-7d..now) vs 지난주(now-14d..now-7d)를 seed해 (1) WoW 델타(%),
(2) 일별 오버레이 7칸, (3) 효율 리더(역할별 토큰·세션·스킬다양성), (4) 스킬 자산(신규/휴면/최다)
— 을 검증한다.

실행: cargo build --bins && python3 docs/weekly_e2e.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import time

DIR = f"/tmp/EZERagent-e5-{os.getpid()}"
os.makedirs(DIR, exist_ok=True)
SOCK = os.path.join(DIR, "EZERagent.sock")
EZERAGENTD = os.path.join(os.path.dirname(__file__), "..", "target", "debug", "EZERagentd")
ENV = dict(os.environ, EZERAGENT_SOCKET=SOCK, EZERAGENT_PACK_DIR=os.path.join(DIR, "pack"))
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
    p = subprocess.Popen([EZERAGENTD], env=ENV, stdout=open(os.path.join(DIR, "EZERagentd.log"), "a"), stderr=subprocess.STDOUT)
    for _ in range(50):
        try:
            if rpc("system.ping", {}):
                return p
        except OSError:
            time.sleep(0.1)
    return p


def main():
    daemon = start_daemon()
    try:
        now = time.time()
        day = 86400
        for _ in range(50):
            if os.path.exists(DBP):
                break
            time.sleep(0.1)
        conn = sqlite3.connect(DBP)
        conn.executemany(
            "INSERT INTO usage_records(session_id, role, agent, model, input_tokens, output_tokens, "
            "cache_creation, cache_read, cost_usd, ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                ("/s/a", "worker", "claude", "claude-opus-4-8", 2000, 0, 0, 0, 0.10, now - 1 * day),   # 이번주
                ("/s/x", "worker", "claude", "claude-opus-4-8", 1000, 0, 0, 0, 0.04, now - 8 * day),   # 지난주
            ])

        def ev(sid, role, skill, ts):
            return (sid, role, "claude", "PRE_TOOL", "Skill", 1, skill, 0, 0, None, None, None, None, ts)
        conn.executemany(
            "INSERT INTO events(session_id, role, agent, event_type, tool_name, is_skill, skill_name, "
            "is_slash, is_agent, agent_type, agent_id, exit_code, duration_ms, ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ev("/s/a", "worker", "commit", now - 1 * day),
                ev("/s/a", "worker", "deep-research", now - 1 * day),  # 신규
                ev("/s/x", "worker", "commit", now - 8 * day),
                ev("/s/x", "worker", "old-skill", now - 8 * day),      # 휴면
            ])
        conn.commit()
        conn.close()
        time.sleep(0.2)

        s = rpc("control.weekly", {})["result"]["summary"]
        wow = s["wow"]
        check("WoW 토큰 this 2000·last 1000", wow["tokens"]["this"] == 2000 and wow["tokens"]["last"] == 1000, str(wow["tokens"]))
        check("WoW 토큰 델타 +100%", abs(wow["tokens"]["delta_pct"] - 100.0) < 1e-6, str(wow["tokens"]["delta_pct"]))
        check("WoW 세션 this 1·last 1", wow["sessions"]["this"] == 1 and wow["sessions"]["last"] == 1, str(wow["sessions"]))
        check("일별 오버레이 this 7칸", len(s["daily"]["this"]) == 7, str(len(s["daily"]["this"])))
        check("일별 오버레이 last 7칸", len(s["daily"]["last"]) == 7, str(len(s["daily"]["last"])))
        check("일별 this 합 2000", sum(s["daily"]["this"]) == 2000, str(s["daily"]["this"]))

        leaders = s["leaders"]
        check("리더 worker·토큰 2000", leaders and leaders[0]["role"] == "worker" and leaders[0]["tokens"] == 2000, str(leaders))
        check("리더 스킬다양성 2", leaders and leaders[0]["skill_diversity"] == 2, str(leaders[0] if leaders else None))

        asset = s["skill_asset"]
        check("신규 스킬 deep-research(commit 제외)", "deep-research" in asset["new"] and "commit" not in asset["new"], str(asset["new"]))
        check("휴면 스킬 old-skill", asset["dormant"] == ["old-skill"], str(asset["dormant"]))
        top_names = [t["name"] for t in asset["top"]]
        check("최다 스킬에 commit·deep-research", "commit" in top_names and "deep-research" in top_names, str(top_names))
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
    print("✅ E5 주간 다이제스트 E2E 전부 PASS — WoW 델타·일별 오버레이·효율 리더·스킬 자산 검증")


if __name__ == "__main__":
    main()
