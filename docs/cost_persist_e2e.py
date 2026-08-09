#!/usr/bin/env python3
"""T7 E1 비용·영속 E2E — 샌드박스 데몬에 파싱 가능한 claude 트랜스크립트를 물려
(1) collector→cost→consumption→control.dashboard 비용/모델믹스 노출,
(2) analytics.db usage_records 적재,
(3) 데몬 재시작 시 seed_consumption 리플레이로 오늘 비용 보존 — 을 실측한다.

실행: cargo build --bins && python3 docs/cost_persist_e2e.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import time

DIR = f"/tmp/ezer-e1-{os.getpid()}"
os.makedirs(DIR, exist_ok=True)
SOCK = os.path.join(DIR, "ezer.sock")
TX = os.path.join(DIR, "claude-tx.jsonl")
EZERD = os.path.join(os.path.dirname(__file__), "..", "target", "debug", "ezerd")
ENV = dict(os.environ, EZER_SOCKET=SOCK, EZER_PACK_DIR=os.path.join(DIR, "pack"), EZER_USAGE_POLL_SECS="1")
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


def consumption():
    return rpc("control.dashboard", {})["result"]["consumption"]


def main():
    daemon = start_daemon()
    try:
        sid = rpc("surface.create", {"cmd": "sleep 600", "title": "e1", "cwd": "/tmp"})["result"]["surface_id"]
        rpc("surface.set_meta", {"surface_id": sid, "agent": "claude", "agent_bin": "claude"})
        # 파싱 가능한 claude 어시스턴트 메시지 1건 (opus-4-8, 토큰 4종)
        open(TX, "w").write(json.dumps({
            "type": "assistant", "isSidechain": False, "requestId": "r1",
            "message": {"model": "claude-opus-4-8", "usage": {
                "input_tokens": 1000, "output_tokens": 300,
                "cache_creation_input_tokens": 2000, "cache_read_input_tokens": 50000}}}) + "\n")
        rpc("usage.register", {"surface_id": sid, "transcript": TX})
        time.sleep(3.0)  # 수집기 2틱+ — statusline 없으니 transcript tail → cost 적재

        c = consumption()
        # 비용 = 1000/1e6*5 + 300/1e6*25 + 2000/1e6*6.25 + 50000/1e6*0.50 = 0.05
        check("control.dashboard 비용>0", c.get("today_cost_usd", 0) > 0,
              f"cost={c.get('today_cost_usd')}")
        check("비용 ≈ $0.05", abs(c.get("today_cost_usd", 0) - 0.05) < 1e-6, str(c.get("today_cost_usd")))
        check("모델믹스에 opus-4-8", "claude-opus-4-8" in (c.get("model_mix") or {}), str(c.get("model_mix")))
        check("오늘 소비 토큰 3300", c.get("today_tokens") == 3300, str(c.get("today_tokens")))

        # analytics.db 적재 확인
        dbp = os.path.join(DIR, "analytics.db")
        check("analytics.db 생성", os.path.exists(dbp))
        if os.path.exists(dbp):
            n = sqlite3.connect(dbp).execute("SELECT COUNT(*) FROM usage_records").fetchone()[0]
            check("usage_records ≥ 1건 적재", n >= 1, f"rows={n}")

        cost_before = consumption().get("today_cost_usd", 0)
        # 재시작 → seed_consumption 리플레이
        daemon.terminate()
        try:
            daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            daemon.kill()
        daemon = start_daemon()
        time.sleep(0.5)
        cost_after = consumption().get("today_cost_usd", 0)
        check("재시작 후 오늘 비용 보존(seed 리플레이)", abs(cost_after - cost_before) < 1e-9,
              f"before={cost_before} after={cost_after}")
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
    print("✅ E1 비용·영속 E2E 전부 PASS — collector→cost→대시보드·analytics.db 적재·재시작 보존 검증")


if __name__ == "__main__":
    main()
