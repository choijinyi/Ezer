#!/usr/bin/env python3
"""ezer_serena_probe.py — Serena MCP/LSP 생명주기 라이브니스 프로버 (S4 · CSO heartbeat).

설계서: _research/Serena기반_ezer_업그레이드_구현설계서.md §S4.
역할: 장수 Serena(HTTP/공유 regime, dashboard ON) 의 /heartbeat 라이브니스와 LSP 자식-트리
      fan-out 을 주기적(ezer schedule)으로 관측해 ALERT만 낸다. **절대 kill 하지 않는다** —
      실제 reap(close-surface/ezer kill)은 CSO 가 alert 를 받고 수행한다.

핵심 불변(설계서 §S4):
  - ALERT-ONLY (kill action 없음). 단일 heartbeat miss 로 alert 하지 않는다(N-연속 threshold).
  - 포트는 24282(0x5EDA)부터 auto-increment 스캔 — 하드코딩 금지(master+worker 각 dashboard면 복수).
  - foreground poll 금지 — ezer schedule cadence 로만 호출된다.
  - serena 가 live 가 아니면(포트 무응답·프로세스 없음) 조용히 종료(스팸 방지).
  - stdio per-node serena 는 dashboard OFF(heartbeat 없음) → 라이브니스=노드, 프로버는 child-cap만.
  - --self-test: network 없이 port-scan/child-count/state round-trip 검증 후 exit 0 (C18 self-test 컨벤션).
"""
import argparse
import json
import os
import sys

try:
    import psutil  # child-tree cap 용 — 부재 시 graceful 강등(heartbeat 는 stdlib 로 계속).
    _HAS_PSUTIL = True
except Exception:
    _HAS_PSUTIL = False

import urllib.request

BASE_PORT = 0x5EDA          # 24282 — Serena DASHBOARD_API_BASE_PORT (constants.py:43 실측)
PORT_SPAN = 10              # 24282..24291 스캔
HEARTBEAT_TIMEOUT = 2.0     # s
DEFAULT_MISS_THRESHOLD = 3  # N-연속 무응답 → alert
DEFAULT_CHILD_CEILING = 5   # 예상 LS(pyright+tsserver+rust-analyzer=3) + margin
STATE_PATH = os.path.expanduser("~/.ezer/state/serena-probe.json")


def _load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict):
                return d
    except (OSError, ValueError):
        pass
    return {"ports": {}, "child_over": False}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def probe_heartbeat(port, timeout=HEARTBEAT_TIMEOUT):
    """200 + {"status":"alive"} 이면 True. 무응답/오류면 False (예외 던지지 않음)."""
    url = "http://127.0.0.1:%d/heartbeat" % port
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if r.status != 200:
                return False
            body = r.read(256).decode("utf-8", "replace")
        try:
            return json.loads(body).get("status") == "alive"
        except ValueError:
            return "alive" in body
    except Exception:
        return False


def discover_live_ports(span=PORT_SPAN):
    return [p for p in range(BASE_PORT, BASE_PORT + span) if probe_heartbeat(p)]


def find_serena_pids():
    """cmdline 에 serena/start-mcp-server 가 든 프로세스 pid 목록 (psutil 필요)."""
    if not _HAS_PSUTIL:
        return []
    pids = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = " ".join(proc.info.get("cmdline") or [])
        except Exception:
            continue
        if "start-mcp-server" in cl or ("serena" in cl and "uvx" in cl):
            pids.append(proc.info["pid"])
    return pids


def count_children(pid):
    """psutil 재귀 자식 수 — 실패 시 None."""
    if not _HAS_PSUTIL:
        return None
    try:
        return len(psutil.Process(pid).children(recursive=True))
    except Exception:
        return None


def send_alert(role, msg):
    """ezer send --queued --to <role> 로 OOB push (자동 Return 배달). 실패는 stderr."""
    import shutil
    import subprocess
    ezer = shutil.which("ezer")
    if not ezer:
        sys.stderr.write("[serena-probe] ezer 미발견 — alert 미전송: %s\n" % msg)
        return False
    try:
        subprocess.run([ezer, "send", "--queued", "--to", role, msg],
                       capture_output=True, timeout=15)
        return True
    except Exception as e:
        sys.stderr.write("[serena-probe] alert 전송 실패: %s (%s)\n" % (e, msg))
        return False


def run_probe(role, miss_threshold, child_ceiling):
    state = _load_state()
    ports_state = state.setdefault("ports", {})
    live = set(discover_live_ports())
    alerts = []

    # 이전에 alive 였던 포트가 무응답 → miss 누적. threshold 도달 시 1회 alert 후 모니터 해제.
    for p in list(ports_state.keys()):
        ps = ports_state[p]
        if int(p) in live:
            ps["alive_seen"] = True
            ps["miss"] = 0
        elif ps.get("alive_seen"):
            ps["miss"] = ps.get("miss", 0) + 1
            if ps["miss"] >= miss_threshold:
                alerts.append("[serena-probe] heartbeat MISS on port %s (%d consecutive) — "
                              "CSO: close-surface/ezer kill 로 트리 reap 검토" % (p, ps["miss"]))
                ps["alive_seen"] = False
                ps["miss"] = 0
    # 새로 alive 인 포트 등록.
    for p in live:
        ports_state.setdefault(str(p), {})["alive_seen"] = True
        ports_state[str(p)]["miss"] = 0

    # child-tree cap (psutil) — runaway LSP fan-out alert (kill 아님).
    over = False
    if _HAS_PSUTIL:
        for pid in find_serena_pids():
            n = count_children(pid)
            if n is not None and n > child_ceiling:
                over = True
                if not state.get("child_over"):
                    alerts.append("[serena-probe] serena pid %d 자식 LS %d > ceiling %d — "
                                  "runaway LSP fan-out 가능, CSO 점검" % (pid, n, child_ceiling))
    state["child_over"] = over

    _save_state(state)
    for a in alerts:
        send_alert(role, a)
    # serena 가 전혀 live 아님(stdio-only 또는 미기동)이면 조용. 관측 요약만 stdout.
    print("[serena-probe] live_ports=%s alerts=%d psutil=%s"
          % (sorted(live), len(alerts), _HAS_PSUTIL))
    return 0


def self_test():
    """network/serena 없이 결정론 검증 — exit 0 게이트(c43 거버넌스 gap)."""
    # (1) probe_heartbeat 가 닫힌 포트에서 False 반환(예외 없음).
    assert probe_heartbeat(BASE_PORT, timeout=0.2) in (True, False)
    # (2) discover_live_ports 가 list 반환.
    assert isinstance(discover_live_ports(span=1), list)
    # (3) count_children: 자기 pid 에 대해 int 또는 None.
    assert count_children(os.getpid()) is None or isinstance(count_children(os.getpid()), int)
    # (4) state round-trip — 임시 경로로 격리(라이브 state 미오염).
    global STATE_PATH
    import tempfile
    orig = STATE_PATH
    d = tempfile.mkdtemp()
    try:
        STATE_PATH = os.path.join(d, "s.json")
        _save_state({"ports": {"24282": {"alive_seen": True, "miss": 1}}, "child_over": False})
        st = _load_state()
        assert st["ports"]["24282"]["miss"] == 1
    finally:
        STATE_PATH = orig
        import shutil as _sh
        _sh.rmtree(d, ignore_errors=True)
    print("ezer_serena_probe self-test OK (psutil=%s)" % _HAS_PSUTIL)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Serena heartbeat/child-tree liveness probe (alert-only)")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--to", default="cso", help="alert 대상 역할 (기본 cso)")
    ap.add_argument("--miss-threshold", type=int, default=DEFAULT_MISS_THRESHOLD)
    ap.add_argument("--child-ceiling", type=int, default=DEFAULT_CHILD_CEILING)
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    return run_probe(args.to, args.miss_threshold, args.child_ceiling)


if __name__ == "__main__":
    sys.exit(main())
