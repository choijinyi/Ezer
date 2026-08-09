#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T7 E7 RSI 무결성 도구 E2E — EZERagent_rsi.py를 임시 git repo에서 실측한다.

(1) 순수 로직(verdict·parse_markers·rollback_plan), (2) checkpoint(ref·state·ledger),
(3) progress(delta·verdict), (4) markers(iter-id trailer 파싱), (5) rollback dry-run(무실행),
(6) rollback --execute(★백업 브랜치 보존 후 reset·복구가능) — 을 검증한다.

실행: python3 docs/rsi_e2e.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RSI = os.path.join(ROOT, "EZERagent-pack", "bin", "EZERagent_rsi.py")
FAIL = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def load_module():
    spec = importlib.util.spec_from_file_location("rsi", RSI)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def git(args, cwd):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)


def run_rsi(args, cwd):
    env = dict(os.environ, EZERAGENT_ROUND_DIR=os.path.join(cwd, "_round"))
    return subprocess.run([sys.executable, RSI] + args, cwd=cwd, capture_output=True, text=True, env=env)


def main():
    m = load_module()
    # ── 순수 로직 ──
    check("verdict improved/regressed/flat",
          m.verdict(0.2) == "improved" and m.verdict(-0.2) == "regressed" and m.verdict(0.0) == "flat")
    parsed = m.parse_markers("abc123\x1ffeat: x\x1fbody\niter-id: 7\n\x1edef456\x1ffix: y\x1fno trailer\x1e")
    check("parse_markers iter-id 추출", parsed[0]["iter_id"] == 7 and parsed[1]["iter_id"] is None, str(parsed))
    plan = m.rollback_plan("R1", "aaa", "bbb", ["c1", "c2"], dirty=False, is_ancestor=True)
    check("rollback_plan safe 판정", plan["safe"] is True and plan["discarded_count"] == 2, str(plan))
    plan2 = m.rollback_plan("R1", "aaa", "bbb", [], dirty=True, is_ancestor=False)
    check("rollback_plan 더티+비조상 blockers 2", len(plan2["blockers"]) == 2 and plan2["safe"] is False, str(plan2))

    # ── git 흐름 (격리 repo) ──
    with tempfile.TemporaryDirectory(prefix="EZERagent-rsi-") as d:
        git(["init", "-q"], d)
        git(["config", "user.email", "t@t"], d)
        git(["config", "user.name", "t"], d)
        # 실제 프로젝트처럼 _round/ gitignore — rsi 상태파일이 추적되어 dirty 오판하지 않게.
        open(os.path.join(d, ".gitignore"), "w").write("_round/\n")
        open(os.path.join(d, "f.txt"), "w").write("base\n")
        git(["add", "."], d); git(["commit", "-q", "-m", "base"], d)
        base_sha = git(["rev-parse", "HEAD"], d).stdout.strip()

        r = run_rsi(["checkpoint", "--round", "R1", "--score", "0.5"], d)
        check("checkpoint exit 0", r.returncode == 0, r.stderr)
        check("checkpoint ref 생성", git(["rev-parse", "refs/rsi/ckpt/R1"], d).stdout.strip() == base_sha)
        state = json.load(open(os.path.join(d, "_round", "rsi", "state.json")))
        check("state baseline 0.5", state["rounds"]["R1"]["baseline_score"] == 0.5, str(state))

        # 라운드 작업 커밋(iter-id trailer)
        open(os.path.join(d, "f.txt"), "w").write("round work\n")
        git(["add", "."], d); git(["commit", "-q", "-m", "feat: round1 work\n\niter-id: 1"], d)
        work_sha = git(["rev-parse", "HEAD"], d).stdout.strip()

        r = run_rsi(["progress", "--round", "R1", "--score", "0.7"], d)
        prog = json.loads(r.stdout)
        check("progress improved·delta 0.2", prog["verdict"] == "improved" and abs(prog["delta"] - 0.2) < 1e-9, r.stdout)

        r = run_rsi(["markers", "--json"], d)
        mk = json.loads(r.stdout)
        check("markers iter-id 1 검출", any(x["iter_id"] == 1 for x in mk["markers"]), r.stdout)

        # rollback dry-run — HEAD 불변·실행 0
        r = run_rsi(["rollback", "--round", "R1"], d)
        plan = json.loads(r.stdout)
        check("rollback dry-run safe·1커밋 폐기예정", plan["safe"] and plan["discarded_count"] == 1, r.stdout)
        check("dry-run HEAD 불변", git(["rev-parse", "HEAD"], d).stdout.strip() == work_sha, "HEAD 바뀌면 안 됨")
        check("dry-run 백업 브랜치 미생성", "rsi-abandoned" not in git(["branch"], d).stdout)

        # rollback --execute — 백업 보존 후 reset
        r = run_rsi(["rollback", "--round", "R1", "--execute"], d)
        ent = json.loads(r.stdout)
        check("execute exit 0", r.returncode == 0, r.stderr)
        check("HEAD가 checkpoint로 reset", git(["rev-parse", "HEAD"], d).stdout.strip() == base_sha, "reset 실패")
        bak = ent["recovery_branch"]
        check("★백업 브랜치 생성(retention)", bak in git(["branch"], d).stdout, git(["branch"], d).stdout)
        # 백업 브랜치에 버려진 work 커밋이 보존됐나
        check("★버려진 커밋 백업에 보존", git(["rev-parse", bak], d).stdout.strip() == work_sha, "복구 불가면 비가역 삭제")

        # 더티 트리 거부 가드
        run_rsi(["checkpoint", "--round", "R2", "--score", "0.5"], d)
        open(os.path.join(d, "f.txt"), "w").write("dirty uncommitted\n")
        r = run_rsi(["rollback", "--round", "R2", "--execute"], d)
        check("더티 트리 rollback 거부(--force 없이)", r.returncode == 3, f"rc={r.returncode}")

    print()
    if FAIL:
        print(f"❌ {len(FAIL)} FAIL: {FAIL}")
        raise SystemExit(1)
    print("✅ E7 RSI 무결성 도구 E2E 전부 PASS — checkpoint·progress·markers·rollback(dry-run/execute·백업 보존·더티 거부)")


if __name__ == "__main__":
    main()
