#!/usr/bin/env python3
"""T7 E2 비용·효율 집계 E2E — control.analytics RPC를 실측한다.

샌드박스 데몬이 만든 analytics.db에 usage_records를 직접 적재(다중 세션·모델·에이전트·시점)한 뒤
control.analytics를 window별로 호출해 (1) window 라우팅(7d/all), (2) 토큰 4분해 totals,
(3) 캐시절감$ 단가 공식, (4) 모델·에이전트 믹스 정렬, (5) 생산성(턴/세션·세션길이)을 검증한다.

실행: cargo build --bins && python3 docs/analytics_e2e.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import time

DIR = f"/tmp/ezer-e2-{os.getpid()}"
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


def analytics(window):
    return rpc("control.analytics", {"window": window})["result"]


def main():
    daemon = start_daemon()
    try:
        now = time.time()
        # 데몬이 부트에서 analytics.db·스키마를 만든 뒤 직접 적재(WAL — 데몬 연결이 커밋분 관측)
        for _ in range(50):
            if os.path.exists(DBP):
                break
            time.sleep(0.1)
        conn = sqlite3.connect(DBP)
        rows = [
            # (session, role, agent, model, in, out, cc, cr, cost, ts)
            ("/s/a", "worker", "claude", "claude-opus-4-8", 1000, 300, 2000, 50000, 0.05, now - 60),
            ("/s/a", "worker", "claude", "claude-opus-4-8", 500, 200, 0, 0, 0.01, now - 30),
            ("/s/b", "reviewer-codex", "codex", "claude-haiku-4-5", 100, 50, 0, 0, 0.00035, now - 45),
            ("/s/c", "worker", "claude", "claude-opus-4-8", 9, 9, 0, 0, 1.0, now - 8 * 86400),  # 8일 전 — 7d 제외
        ]
        conn.executemany(
            "INSERT INTO usage_records(session_id, role, agent, model, input_tokens, output_tokens, "
            "cache_creation, cache_read, cost_usd, ts) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()
        time.sleep(0.2)

        # ── window=all: 4건 전부 ──
        a = analytics("all")
        check("window 라우팅 all", a.get("window") == "all", str(a.get("window")))
        sa = a["summary"]["totals"]
        check("all: 메시지 4건", sa["msgs"] == 4, str(sa))
        check("all: 세션 3개", sa["sessions"] == 3, str(sa))

        # ── window=7d: 8일 전 1건 제외 → 3건 ──
        s = analytics("7d")["summary"]
        t = s["totals"]
        check("7d: 메시지 3건(8일전 제외)", t["msgs"] == 3, str(t))
        check("7d: 세션 2개", t["sessions"] == 2, str(t))
        check("7d: input 합 1600", t["input"] == 1600, str(t))
        check("7d: cache_read 50000", t["cache_read"] == 50000, str(t))
        check("7d: 토큰 4분해 합 54150", t["tokens"] == 54150, str(t))
        check("7d: 비용 ≈ 0.06035", abs(t["cost_usd"] - 0.06035) < 1e-6, str(t["cost_usd"]))
        # 캐시절감 = 50000/1e6 × (opus input 5 − cache_read 0.5) = 0.225
        check("7d: 캐시절감$ ≈ 0.225", abs(s["cache_savings_usd"] - 0.225) < 1e-6, str(s["cache_savings_usd"]))

        # 모델 믹스 — 비용 우선 정렬, opus 1위
        bm = s["by_model"]
        check("7d: by_model opus 1위(비용)", bm and bm[0]["model"] == "claude-opus-4-8", str(bm))
        check("7d: opus msgs=2", bm and bm[0]["msgs"] == 2, str(bm))
        # 에이전트 믹스 — claude(토큰 多)·codex
        ba = {x["agent"]: x for x in s["by_agent"]}
        check("7d: by_agent claude·codex", "claude" in ba and "codex" in ba, str(ba))
        check("7d: claude 토큰 > codex 토큰(정렬)", s["by_agent"][0]["agent"] == "claude", str(s["by_agent"]))

        # 생산성 — 턴/세션 3/2=1.5, 세션A duration=30s·B=0 → 평균 15
        prod = s["productivity"]
        check("7d: 턴/세션 1.5", abs(prod["turns_per_session"] - 1.5) < 1e-9, str(prod))
        check("7d: 평균 세션길이 15s", abs(prod["avg_session_duration_secs"] - 15.0) < 1e-6, str(prod))

        # ── 빈 윈도우 graceful (미래 cutoff 없음 → today는 최소 구조 유지) ──
        td = analytics("today")
        check("today: 구조 정상(totals 존재)", "totals" in td["summary"], str(td.get("summary")))
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
    print("✅ E2 비용·효율 집계 E2E 전부 PASS — window 라우팅·토큰4분해·캐시절감$·모델/에이전트 믹스·생산성 검증")


if __name__ == "__main__":
    main()
