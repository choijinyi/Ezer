#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EZERagent_report — 5분 주기 진행% 보고의 결정론 산출기 (절대지침: 양방향 소켓 앵커 A6).

master가 "대략 60% 된 것 같다"고 LLM으로 추론하면 환각이다. 진행%는 todo 체크박스의
done/total 산술로만 결정된다 — 이 스크립트 출력이 유일한 사실이다(결정론 환원).

수행:
  ① `EZERagent status --json`으로 노드 현황·feed·idle·데몬 집계 todo를 수집
  ② 전 노드의 `*_TODO.md`(pack/round + 각 surface cwd/_round)를 직접 스캔해
     체크박스(- [x]/- [ ])로 노드별·종합 진행%를 산출
  ③ 주인님께 보고할 텍스트(또는 --json)를 출력

사용: python3 EZERagent_report.py [--json] [--extra-dir <폴더> ...]
의존성: 파이썬 표준 라이브러리 + PATH의 `EZERagent`(없으면 todo 직접 스캔만으로 동작).
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

# governance.rs check_todo와 동일한 체크박스 규칙 (done/total 집계의 단일 진실).
RE_DONE = re.compile(r"- \[[xX]\]")
RE_OPEN = re.compile(r"- \[ \]")
IDLE_ALERT_SECS = 300  # 절대지침 B3: idle 5분+ 즉시 조치 대상


def pack_dir():
    for key in ("EZERAGENT_PACK_DIR",):
        v = os.environ.get(key, "")
        if v:
            return v
    return os.path.join(os.path.expanduser("~"), ".EZERagent/pack")


def EZERagent_status():
    """`EZERagent status --json` 수집. EZERagent 부재·실패 시 None(=todo 직접 스캔만)."""
    EZERagent = shutil.which("EZERagent")
    if not EZERagent:
        return None
    try:
        r = subprocess.run([EZERagent, "status", "--json"], capture_output=True, timeout=10)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        return None


def count_checkboxes(path):
    """(done, total) — 64KB 상한(거대 파일 방어, governance.rs와 동일 정신)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read(65536)
    except OSError:
        return None
    done = len(RE_DONE.findall(content))
    total = done + len(RE_OPEN.findall(content))
    return done, total


def node_label(filename):
    """MASTER_TODO.md → master, WORKER_TODO.md → worker ..."""
    base = os.path.basename(filename)
    if base.endswith("_TODO.md"):
        return base[: -len("_TODO.md")].lower()
    return base


def discover_todo_files(status, extra_dirs):
    """스캔 대상 *_TODO.md 절대경로 집합 — 결정론(존재 파일만, 정렬).
    ① pack/round  ② status의 각 surface cwd/_round  ③ --extra-dir/_round ④ EZERAGENT_TODO_DIRS."""
    roots = [os.path.join(pack_dir(), "round")]
    if status:
        for s in status.get("surfaces", []):
            # live_cwd(현재 cd 위치) 우선, 없으면 spawn-time cwd — 워커 cd 이동 시 누락 방지.
            for cwd in (s.get("live_cwd"), s.get("cwd")):
                if cwd:
                    roots.append(os.path.join(cwd, "_round"))
    for d in extra_dirs or []:
        roots.append(os.path.join(d, "_round"))
        roots.append(d)
    for d in os.environ.get("EZERAGENT_TODO_DIRS", "").split(os.pathsep):
        if d:
            roots.append(d)
    found = set()
    for root in roots:
        for p in glob.glob(os.path.join(root, "*_TODO.md")):
            if os.path.isfile(p):
                found.add(os.path.realpath(p))
    return sorted(found)


def pct(done, total):
    """결정론 진행률(%) — total 0은 0%(미착수)로 정의. 정수 내림."""
    return 0 if total == 0 else (done * 100) // total


def build_report(status, extra_dirs):
    files = discover_todo_files(status, extra_dirs)
    nodes = []
    agg_done = agg_total = 0
    for path in files:
        c = count_checkboxes(path)
        if c is None:
            continue
        done, total = c
        agg_done += done
        agg_total += total
        nodes.append({
            "node": node_label(path),
            "path": path,
            "done": done,
            "total": total,
            "pct": pct(done, total),
        })

    # 노드 현황·idle·feed (status 있을 때만)
    live_nodes = []
    idle_nodes = []
    feed_pending = None
    paused = None
    if status:
        feed_pending = status.get("feed", {}).get("pending")
        paused = status.get("paused")
        for s in status.get("surfaces", []):
            role = s.get("role")
            if not role:
                continue
            ag = s.get("status") or {}  # org.status는 자기보고를 "status" 필드로 노출
            # idle = PTY 무출력 경과(surface 상위 "idle_secs"). 자기보고 갱신 경과(status.age_secs)는
            # 활동 중에도 갱신되므로 idle 판정에 쓰면 안 된다(절대지침 B3: 출력 멎은 지 5분+).
            idle_secs = s.get("idle_secs")
            entry = {
                "role": role,
                "state": ag.get("state"),
                "context_pct": ag.get("context_pct"),
                "idle_secs": idle_secs,
                "agent_alive": s.get("agent_alive"),
            }
            live_nodes.append(entry)
            if isinstance(idle_secs, int) and idle_secs >= IDLE_ALERT_SECS and s.get("agent_alive"):
                idle_nodes.append(entry)

    return {
        "overall_pct": pct(agg_done, agg_total),
        "overall_done": agg_done,
        "overall_total": agg_total,
        "nodes": nodes,
        "live_nodes": live_nodes,
        "idle_nodes": idle_nodes,
        "feed_pending": feed_pending,
        "paused": paused,
        "status_available": status is not None,
    }


def render_text(rep):
    lines = []
    lines.append("주인님께 보고 (5분 주기 진행 현황 · 결정론 산출):")
    if rep["overall_total"] == 0:
        lines.append("  • 전체 진행: todo 미등록(착수 전) — *_TODO.md에 체크박스가 없습니다")
    else:
        lines.append("  • 전체 진행: %d%% (%d/%d 완료, todo 기준)"
                     % (rep["overall_pct"], rep["overall_done"], rep["overall_total"]))
    if rep["nodes"]:
        lines.append("  • 노드별 진행:")
        for n in rep["nodes"]:
            lines.append("      - %s: %d%% (%d/%d)"
                         % (n["node"], n["pct"], n["done"], n["total"]))
    else:
        lines.append("  • 노드별 진행: *_TODO.md 미발견")

    if not rep["status_available"]:
        lines.append("  • 노드 현황: EZERagent status 수집 실패(데몬 미가동?) — todo 스캔만 반영")
    else:
        if rep["paused"]:
            lines.append("  • ⚠ 큐/스케줄 일시정지(kill-switch) 상태")
        alive = sum(1 for n in rep["live_nodes"] if n.get("agent_alive"))
        lines.append("  • 활성 노드: %d개" % alive)
        if rep["feed_pending"]:
            lines.append("  • ⚠ 미처리 승인(feed): %d건 — 즉결 필요" % rep["feed_pending"])
        if rep["idle_nodes"]:
            roles = ", ".join(n["role"] for n in rep["idle_nodes"])
            lines.append("  • ⚠ idle 5분+ 노드: %s — read-screen 확인·재지시 필요" % roles)
        high_ctx = [n for n in rep["live_nodes"]
                    if isinstance(n.get("context_pct"), int) and n["context_pct"] >= 60]
        if high_ctx:
            roles = ", ".join("%s(%d%%)" % (n["role"], n["context_pct"]) for n in high_ctx)
            lines.append("  • ⚠ 컨텍스트 60%%+ 노드: %s — cycle-agent 집행 검토" % roles)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="5분 주기 진행% 결정론 보고 산출기")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("--extra-dir", action="append", default=[], metavar="DIR",
                    help="추가 스캔 폴더(그 안의 _round/*_TODO.md 및 직접 *_TODO.md)")
    args = ap.parse_args()

    rep = build_report(EZERagent_status(), args.extra_dir)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(render_text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
