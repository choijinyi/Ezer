#!/usr/bin/env python3
"""T7 E3 스킬·에이전트 집계 E2E — control.skills RPC를 실측한다.

샌드박스 데몬이 만든 analytics.db의 events 테이블에 PRE/POST 이벤트(툴·스킬·위임·실패)를 직접
적재한 뒤 control.skills를 window별로 호출해 (1) 호출 TOP, (2) 🔥실패율(exit_code≠0),
(3) 스킬×역할, (4) 서브에이전트 위임, (5) 반복실패 TOP, (6) window 라우팅을 검증한다.

실행: cargo build --bins && python3 docs/skills_e2e.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import time

DIR = f"/tmp/EZERagent-e3-{os.getpid()}"
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


def skills(window):
    return rpc("control.skills", {"window": window})["result"]


def main():
    daemon = start_daemon()
    try:
        now = time.time()
        for _ in range(50):
            if os.path.exists(DBP):
                break
            time.sleep(0.1)
        conn = sqlite3.connect(DBP)
        # (session, role, agent, event_type, tool_name, is_skill, skill_name, is_slash, is_agent, agent_type, agent_id, exit_code, duration_ms, ts)
        def ev(etype, role, tool, is_skill, skn, is_agent, at, exit_code, ts):
            return ("/s/a", role, "claude", etype, tool, int(is_skill), skn, 0, int(is_agent), at, None, exit_code, None, ts)
        rows = [
            ev("PRE_TOOL", "worker", "Bash", 0, None, 0, None, None, now - 60),
            ev("POST_TOOL", "worker", "Bash", 0, None, 0, None, 1, now - 59),   # 실패
            ev("PRE_TOOL", "worker", "Bash", 0, None, 0, None, None, now - 50),
            ev("POST_TOOL", "worker", "Bash", 0, None, 0, None, 0, now - 49),   # 성공
            ev("PRE_TOOL", "master", "Skill", 1, "commit", 0, None, None, now - 40),
            ev("POST_TOOL", "master", "Skill", 1, "commit", 0, None, 0, now - 39),
            ev("PRE_TOOL", "master", "Task", 0, None, 1, "Explore", None, now - 30),
            ev("PRE_TOOL", "worker", "Bash", 0, None, 0, None, None, now - 8 * 86400),  # 8일 전 — 7d 제외
        ]
        conn.executemany(
            "INSERT INTO events(session_id, role, agent, event_type, tool_name, is_skill, skill_name, "
            "is_slash, is_agent, agent_type, agent_id, exit_code, duration_ms, ts) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()
        time.sleep(0.2)

        # ── window=7d: 8일 전 PRE 1건 제외 ──
        r = skills("7d")
        check("window 라우팅 7d", r.get("window") == "7d", str(r.get("window")))
        s = r["summary"]
        t = s["totals"]
        check("7d: tool_calls 4(Bash2+Skill1+Task1)", t["tool_calls"] == 4, str(t))
        check("7d: skill_calls 1", t["skill_calls"] == 1, str(t))
        check("7d: agent_calls 1", t["agent_calls"] == 1, str(t))
        check("7d: fail_calls 1", t["fail_calls"] == 1, str(t))
        check("7d: fail_rate 0.25", abs(t["fail_rate"] - 0.25) < 1e-9, str(t["fail_rate"]))

        bt = {x["name"]: x for x in s["by_tool"]}
        check("7d: Bash 1위·calls 2·fail 1", s["by_tool"][0]["name"] == "Bash" and bt["Bash"]["calls"] == 2 and bt["Bash"]["fail"] == 1, str(s["by_tool"]))
        check("7d: Bash fail_rate 0.5", abs(bt["Bash"]["fail_rate"] - 0.5) < 1e-9, str(bt["Bash"]))

        bs = s["by_skill"]
        check("7d: 스킬 commit, fail 0", bs and bs[0]["name"] == "commit" and bs[0]["fail"] == 0, str(bs))
        check("7d: 스킬 commit 역할 master", bs and bs[0]["roles"][0]["role"] == "master", str(bs[0]["roles"] if bs else None))

        ba = s["by_agent"]
        check("7d: 위임 Explore", ba and ba[0]["name"] == "Explore", str(ba))
        check("7d: 위임 호출역할 master", ba and ba[0]["by_role"][0]["role"] == "master", str(ba[0]["by_role"] if ba else None))

        fl = s["failures"]
        check("7d: 🔥반복실패 Bash 1건만", len(fl) == 1 and fl[0]["name"] == "Bash" and fl[0]["fail"] == 1, str(fl))

        # ── window=all: 8일 전 Bash PRE 포함 → Bash calls 3 ──
        sa = skills("all")["summary"]
        bta = {x["name"]: x for x in sa["by_tool"]}
        check("all: Bash calls 3(8일전 포함)", bta["Bash"]["calls"] == 3, str(sa["by_tool"]))
        check("all: tool_calls 5", sa["totals"]["tool_calls"] == 5, str(sa["totals"]))
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
    print("✅ E3 스킬·에이전트 집계 E2E 전부 PASS — 호출TOP·🔥실패율·스킬×역할·위임·반복실패·window 라우팅 검증")


if __name__ == "__main__":
    main()
