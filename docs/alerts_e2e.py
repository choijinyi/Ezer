#!/usr/bin/env python3
"""T7 E6 경보 E2E — control.alerts RPC를 실측한다.

(1) 기본 설정(주간 예산 0=비활성)에선 데이터가 있어도 예산 경보 없음(오경보 0),
(2) alerts-config.json 핫로드(파일만 고치면 다음 평가부터 반영),
(3) 7d usage_records 비용 ≥ 한도 → weekly_budget:cost,
(4) 7d events 반복실패(fail수·실패율·최소표본 동시충족) → repeated_failure:<tool>,
(5) 해소(임계 복원) 시 경보 사라짐(재무장) — 을 검증한다.

실행: cargo build --bins && python3 docs/alerts_e2e.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import time

DIR = f"/tmp/ezer-e6-{os.getpid()}"
os.makedirs(DIR, exist_ok=True)
SOCK = os.path.join(DIR, "ezer.sock")
PACK = os.path.join(DIR, "pack")
CFG = os.path.join(PACK, "alerts-config.json")
EZERD = os.path.join(os.path.dirname(__file__), "..", "target", "debug", "ezerd")
ENV = dict(os.environ, EZER_SOCKET=SOCK, EZER_PACK_DIR=PACK)
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


def alerts():
    r = rpc("control.alerts", {})["result"]
    return r, {a["key"] for a in r["alerts"]}


def write_cfg(d):
    tmp = CFG + ".tmp"
    open(tmp, "w").write(json.dumps(d))
    os.replace(tmp, CFG)


def main():
    daemon = start_daemon()
    try:
        now = time.time()
        for _ in range(50):
            if os.path.exists(DBP):
                break
            time.sleep(0.1)
        conn = sqlite3.connect(DBP)
        # 7d 비용 0.05 적재
        conn.execute(
            "INSERT INTO usage_records(session_id, role, agent, model, input_tokens, output_tokens, "
            "cache_creation, cache_read, cost_usd, ts) VALUES('/s/a','worker','claude','claude-opus-4-8',1000,300,0,0,0.05,?)",
            (now - 60,))
        # Bash 반복실패: PRE×3, POST exit1×2, POST exit0×1 → calls3 fail2 rate0.67
        def ev(etype, tool, exit_code, ts):
            return ("/s/a", "worker", "claude", etype, tool, 0, None, 0, 0, None, None, exit_code, None, ts)
        evs = [
            ev("PRE_TOOL", "Bash", None, now - 60), ev("POST_TOOL", "Bash", 1, now - 59),
            ev("PRE_TOOL", "Bash", None, now - 58), ev("POST_TOOL", "Bash", 1, now - 57),
            ev("PRE_TOOL", "Bash", None, now - 56), ev("POST_TOOL", "Bash", 0, now - 55),
        ]
        conn.executemany(
            "INSERT INTO events(session_id, role, agent, event_type, tool_name, is_skill, skill_name, "
            "is_slash, is_agent, agent_type, agent_id, exit_code, duration_ms, ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", evs)
        conn.commit()
        conn.close()
        time.sleep(0.2)

        # (1) 기본 설정(주간 예산 0) — 예산 경보 없음, 반복실패는 기본 fail_count=5라 아직 미발화(fail=2)
        _, keys0 = alerts()
        check("기본 설정: 예산 경보 없음(0=비활성)", not any("weekly_budget" in k for k in keys0), str(keys0))
        check("기본 설정: 반복실패 미발화(fail2<기본5)", "repeated_failure:Bash" not in keys0, str(keys0))

        # (2)(3)(4) 핫로드 — 낮은 한도로 교체
        write_cfg({"rate_limit_pct": 90, "weekly_cost_usd": 0.001, "weekly_tokens": 0,
                   "fail_count": 2, "fail_rate": 0.3, "fail_min_calls": 2})
        r, keys = alerts()
        check("핫로드: weekly_budget:cost 발화(0.05≥0.001)", "weekly_budget:cost" in keys, str(keys))
        check("핫로드: repeated_failure:Bash 발화(fail2≥2·rate0.67≥0.3)", "repeated_failure:Bash" in keys, str(keys))
        bash = next((a for a in r["alerts"] if a["key"] == "repeated_failure:Bash"), None)
        check("repeated_failure crit(rate≥0.5)", bash and bash["severity"] == "crit", str(bash))
        check("count = alerts 길이", r["count"] == len(r["alerts"]), str(r["count"]))

        # (5) 해소 — 한도 다시 비활성/상향 → 경보 사라짐(재무장)
        write_cfg({"weekly_cost_usd": 0, "fail_count": 99})
        _, keys2 = alerts()
        check("해소: 경보 사라짐(재무장)", not any(k in keys2 for k in ("weekly_budget:cost", "repeated_failure:Bash")), str(keys2))
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
    print("✅ E6 경보 E2E 전부 PASS — config 핫로드·주간예산·반복실패·심각도·재무장(해소) 검증")


if __name__ == "__main__":
    main()
