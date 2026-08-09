#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T7 E9 RBAC(PII 차단) E2E — control.sessions의 redact 모드를 실측한다.

(1) redact=false → session_id는 원본 경로(PII), (2) redact=true → session_id가 sess-<hash>로
가려지고 경로 미노출·집계(토큰)는 보존, (3) redacted 플래그 반영 — 을 검증한다.

실행: cargo build --bins && python3 docs/redact_e2e.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import time

DIR = f"/tmp/EZERagent-e9-{os.getpid()}"
os.makedirs(DIR, exist_ok=True)
SOCK = os.path.join(DIR, "EZERagent.sock")
EZERAGENTD = os.path.join(os.path.dirname(__file__), "..", "target", "debug", "EZERagentd")
ENV = dict(os.environ, EZERAGENT_SOCKET=SOCK, EZERAGENT_PACK_DIR=os.path.join(DIR, "pack"))
DBP = os.path.join(DIR, "analytics.db")
PII_PATH = "/Users/user/.claude/projects/secret-project/abc-123.jsonl"
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
        for _ in range(50):
            if os.path.exists(DBP):
                break
            time.sleep(0.1)
        conn = sqlite3.connect(DBP)
        conn.execute(
            "INSERT INTO usage_records(session_id, role, agent, model, input_tokens, output_tokens, "
            "cache_creation, cache_read, cost_usd, ts) VALUES(?,'worker','claude','claude-opus-4-8',5000,0,0,0,0.25,?)",
            (PII_PATH, now - 60))
        conn.commit()
        conn.close()
        time.sleep(0.2)

        # redact=false: 원본 경로 노출
        r0 = rpc("control.sessions", {"window": "all", "redact": False})["result"]
        check("redact=false: redacted 플래그 false", r0.get("redacted") is False, str(r0.get("redacted")))
        s0 = r0["sessions"][0]
        check("redact=false: session_id=원본 경로", s0["session_id"] == PII_PATH, s0["session_id"])

        # redact=true: 경로 가림·집계 보존
        r1 = rpc("control.sessions", {"window": "all", "redact": True})["result"]
        check("redact=true: redacted 플래그 true", r1.get("redacted") is True, str(r1.get("redacted")))
        s1 = r1["sessions"][0]
        sid = s1["session_id"]
        check("redact=true: session_id=sess-<hash>", sid.startswith("sess-") and len(sid) == 13, sid)
        check("★PII 미노출(경로·홈·프로젝트명 없음)",
              "/" not in sid and "EZERagent" not in sid and "secret" not in sid, sid)
        check("집계(토큰 5000) 보존", s1["tokens"] == 5000, str(s1.get("tokens")))
        # 안정성: 같은 세션은 같은 해시
        r2 = rpc("control.sessions", {"window": "all", "redact": True})["result"]
        check("해시 안정적(재호출 동일)", r2["sessions"][0]["session_id"] == sid, "불안정")
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
    print("✅ E9 PII 차단 E2E 전부 PASS — redact 모드·경로 미노출·집계 보존·해시 안정성 검증")


if __name__ == "__main__":
    main()
