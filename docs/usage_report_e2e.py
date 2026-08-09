#!/usr/bin/env python3
"""T5 Phase 2-A 사용량 보고(statusline) E2E — 샌드박스 데몬에 usage.report를 RPC 직접 +
`ezer usage-report-stdin` 바이너리 경로로 흘려 org.status 배지(ctx·5h·7d)·우선순위 병합·
소유 게이트를 실측 검증한다.

실행법:
  cargo build --bins
  EZER_E2E_SOCK=/tmp/ezer-rep-e2e-$$.sock python3 docs/usage_report_e2e.py
  (스크립트가 데몬을 직접 기동·정리한다)
"""
import json
import os
import socket
import subprocess
import sys
import time

SOCK = os.environ.get("EZER_E2E_SOCK", "/tmp/ezer-rep-e2e.sock")
PACK = "/tmp/ezer-rep-e2e-pack"
EZER = os.path.join(os.path.dirname(__file__), "..", "target", "debug", "ezer")
EZERD = os.path.join(os.path.dirname(__file__), "..", "target", "debug", "ezerd")
FAIL = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
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


def usage_of(sid):
    for s in rpc("org.status", {})["result"]["surfaces"]:
        if s["surface_id"] == sid:
            return s.get("usage")
    return None


def main():
    env = dict(os.environ, EZER_SOCKET=SOCK, EZER_PACK_DIR=PACK, EZER_USAGE_POLL_SECS="1")
    daemon = subprocess.Popen([EZERD], env=env,
                              stdout=open("/tmp/ezer-rep-e2e.log", "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                if rpc("system.ping", {}):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            check("데몬 기동", False, "ping 실패")
            return

        # ── surface 생성(가짜 claude pane) ──
        sid = rpc("surface.create", {"cmd": "sleep 600", "title": "e2e-rep", "cwd": "/tmp"})["result"]["surface_id"]
        rpc("surface.set_meta", {"surface_id": sid, "agent": "claude", "agent_bin": "claude"})

        # 1) usage.report RPC 직접 — ctx + rate 5h/7d 저장 ----------------
        r = rpc("usage.report", {"surface_id": sid, "ctx_pct": 41.6, "ctx_tokens": 83000,
                                 "ctx_window": 200000,
                                 "rate": [{"label": "5h", "used_pct": 41.0, "resets_at": 1781314865.0},
                                          {"label": "7d", "used_pct": 12.0, "resets_at": 1781781650.0}]})
        check("usage.report 통과", r.get("ok") is True, str(r))
        u = usage_of(sid)
        check("org.status source=statusline", u and u.get("source") == "statusline", str(u))
        check("org.status ctx_pct 반올림 42", u and u.get("ctx_pct") == 42, str(u))
        rate = {w["label"]: w for w in (u or {}).get("rate", [])}
        check("배지에 5h rate 노출", rate.get("5h", {}).get("used_pct") == 41.0, str(u))
        check("배지에 7d rate 노출", rate.get("7d", {}).get("used_pct") == 12.0, str(u))
        check("5h resets_at 보존", rate.get("5h", {}).get("resets_at") == 1781314865.0, str(u))

        # 2) 우선순위 병합 — transcript가 파싱 가능해도(미게이트면 덮어쓸) 신선 statusline이 이긴다.
        #    fixture는 parse_claude_line 통과 형식(type=assistant·usage·ctx>0) — 게이트 진짜 검증.
        open("/tmp/ezer-rep-e2e-tx.jsonl", "w").write(json.dumps({
            "type": "assistant", "isSidechain": False, "requestId": "req",
            "message": {"model": "claude-fable-5",
                        "usage": {"input_tokens": 5000, "cache_read_input_tokens": 5000,
                                  "cache_creation_input_tokens": 0, "output_tokens": 999}}}) + "\n")
        rpc("usage.register", {"surface_id": sid, "transcript": "/tmp/ezer-rep-e2e-tx.jsonl"})
        time.sleep(2.5)  # 수집기 2틱+ — statusline 신선(<60s)이라 트랜스크립트 수집 스킵돼야 함
        u2 = usage_of(sid)
        check("우선순위 병합: statusline 유지(파싱가능 transcript 미덮어씀)",
              u2 and u2.get("source") == "statusline" and u2.get("ctx_pct") == 42, str(u2))

        # 3) `ezer usage-report-stdin` 바이너리 경로 — 실제 statusline JSON push -------------
        fake = json.dumps({"model": {"display_name": "Opus 4.8"},
                           "context_window": {"context_window_size": 1000000, "used_percentage": 73.0,
                                              "current_usage": {"input_tokens": 1000,
                                                                "cache_read_input_tokens": 700000,
                                                                "cache_creation_input_tokens": 0}},
                           "rate_limits": {"five_hour": {"used_percentage": 55.0, "resets_at": 1781314999},
                                           "seven_day": {"used_percentage": 22.0, "resets_at": 1781781999}}})
        benv = dict(env, EZER_SURFACE_ID=f"surface:{sid}")
        out = subprocess.run([EZER, "usage-report-stdin"], input=fake.encode(), env=benv,
                             capture_output=True)
        check("ezer usage-report-stdin exit 0", out.returncode == 0, out.stderr.decode())
        check("사람용 줄 출력", b"CTX 73%" in out.stdout and b"5h 55%" in out.stdout, out.stdout.decode())
        u3 = usage_of(sid)
        check("바이너리 push → 배지 갱신(ctx 73)", u3 and u3.get("ctx_pct") == 73, str(u3))
        rate3 = {w["label"]: w for w in (u3 or {}).get("rate", [])}
        check("바이너리 push → 5h 55% 갱신", rate3.get("5h", {}).get("used_pct") == 55.0, str(u3))
        # (context.threshold 교차 발화는 handlers 단위 테스트 usage_report_fires_context_threshold가 핀)
    finally:
        daemon.terminate()
        try:
            daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            daemon.kill()
        for f in (SOCK, "/tmp/ezer-rep-e2e-tx.jsonl"):
            try:
                os.unlink(f)
            except OSError:
                pass

    print()
    if FAIL:
        print(f"❌ {len(FAIL)} FAIL: {FAIL}")
        sys.exit(1)
    print("✅ usage.report E2E 전부 PASS — 배지 5h/7d·우선순위 병합·바이너리 push 라운드트립 검증")


if __name__ == "__main__":
    main()
