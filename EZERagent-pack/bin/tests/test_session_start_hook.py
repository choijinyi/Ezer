#!/usr/bin/env python3
"""test_session_start_hook.py — session-start.sh 3상태 재대조·안내문 계약 핀 (WP-1·핀ⓒ).

가짜 팩 디렉터리(디렉티브 파일)+PATH 스텁 EZERagent로 hook을 sh 실행:
  ⓐ claim 성공 → 디렉티브 주입(현행)
  ⓑ 명시적 거부(claim_denied) → 디렉티브 대신 self-demote 지시·exit 0
  ⓒ 데몬-불가(스텁이 비0+무패턴/응답없음) → fail-open: 디렉티브 주입+고지 1줄
+ 안내문(role-less)이 EZERagent_bootstrap.py 단일 진입점·exit 7 인계·인용 의무를 담는지
+ worker role은 재대조 미적용(무왕복) 핀.
"""
import os
import shutil
import subprocess
import sys
import tempfile

SELF = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(SELF, "..", "..", "hooks", "session-start.sh")
fails = []


def check(name, cond, detail=""):
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, (" — " + detail) if detail else ""))
    if not cond:
        fails.append(name)


def setup(tmp, claim_mode):
    """claim_mode: ok | denied | dead(비0 무패턴) | silent(무한대기→timeout)"""
    pack = os.path.join(tmp, "pack")
    bindir = os.path.join(tmp, "stubbin")
    os.makedirs(os.path.join(pack, "directives"), exist_ok=True)
    os.makedirs(bindir, exist_ok=True)
    for d in ("MASTER", "WORKER", "CSO", "REVIEWER"):
        with open(os.path.join(pack, "directives", "%s_DIRECTIVE.md" % d), "w",
                  encoding="utf-8") as f:
            f.write("DIRECTIVE-BODY-%s\n" % d)
    body = {"ok": "exit 0",
            "denied": "echo 'claim_denied: privileged role held by live surface' >&2; exit 1",
            "dead": "echo 'connect error' >&2; exit 1",
            "silent": "sleep 10"}[claim_mode]
    with open(os.path.join(bindir, "EZERagent"), "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/sh\necho \"EZERagent $@\" >> \"%s/calls.log\"\n"
                "case \"$1\" in claim-role) %s;; esac\nexit 0\n" % (tmp, body))
    os.chmod(os.path.join(bindir, "EZERagent"), 0o755)
    env = dict(os.environ)
    env.update({"EZERAGENT_PACK_DIR": pack, "EZERAGENT_SURFACE_ID": "3",
                "PATH": bindir + os.pathsep + env.get("PATH", "")})
    env.pop("EZERAGENT_ROLE", None)
    return env


def run_hook(env, role=None):
    e = dict(env)
    if role:
        e["EZERAGENT_ROLE"] = role
    r = subprocess.run(["sh", HOOK], capture_output=True, text=True, encoding="utf-8",
                       env=e, stdin=subprocess.DEVNULL, timeout=30)
    return r.returncode, r.stdout, r.stderr


# ── 1. role-less 안내문 계약 ──
tmp = tempfile.mkdtemp(prefix="hook-t1-")
env = setup(tmp, "ok")
code, out, _ = run_hook(env)
check("1a 안내문 exit 0", code == 0)
check("1b 단일 진입점 스크립트", "EZERagent_bootstrap.py" in out)
check("1c exit 7 인계 분기", "exit 7" in out and "인계" in out)
check("1d 인용 의무 명문", "인용" in out)
check("1e 산문 부트 지시 제거", "preflight.py --fix" not in out.replace("EZERagent_preflight", ""))
shutil.rmtree(tmp)

# ── 2. ⓐ master claim 성공 → 디렉티브 주입 ──
tmp = tempfile.mkdtemp(prefix="hook-t2-")
env = setup(tmp, "ok")
code, out, _ = run_hook(env, role="master")
check("2a ⓐ성공: 디렉티브 주입", "DIRECTIVE-BODY-MASTER" in out)
check("2b ⓐ성공: self-demote 없음", "역할 주소 상실" not in out)
# ★R13 부트 브리지: 구 산문 §0만 아는 디렉티브 기계에도(hook=system층 전파) 스크립트 경로 고지
check("2c ★R13 부트 브리지 주입(EZERagent_bootstrap 부재 시 생략)",
      "부트 브리지" not in out)  # 가짜 팩엔 bin/EZERagent_bootstrap.py 없음 → 브리지 미주입(조건부 확인)

shutil.rmtree(tmp)

# ── 2x. ★R13 브리지 존재 케이스: 팩에 EZERagent_bootstrap.py 있으면 master 주입에 브리지 동봉 ──
tmp = tempfile.mkdtemp(prefix="hook-t2x-")
env = setup(tmp, "ok")
_bs = os.path.join(env["EZERAGENT_PACK_DIR"], "bin")
os.makedirs(_bs, exist_ok=True)
open(os.path.join(_bs, "EZERagent_bootstrap.py"), "w", encoding="utf-8").write("# stub\n")
code, out, _ = run_hook(env, role="master")
check("2x1 ★R13 브리지 주입", "부트 브리지" in out and "EZERagent_bootstrap.py" in out)
check("2x2 브리지는 worker엔 미주입", "부트 브리지" not in run_hook(env, role="worker")[1])
shutil.rmtree(tmp)

# ── 3. ⓑ 명시적 거부 → self-demote·디렉티브 미주입 ──
tmp = tempfile.mkdtemp(prefix="hook-t3-")
env = setup(tmp, "denied")
code, out, _ = run_hook(env, role="master")
check("3a ⓑ거부: self-demote 지시", "역할 주소 상실" in out and "인계" in out)
check("3b ⓑ거부: 디렉티브 미주입", "DIRECTIVE-BODY-MASTER" not in out)
check("3c ⓑ거부: exit 0(hook 무해)", code == 0)
shutil.rmtree(tmp)

# ── 4. ⓒ 데몬-불가(비0·무패턴) → fail-open: 디렉티브 주입+고지 ──
tmp = tempfile.mkdtemp(prefix="hook-t4-")
env = setup(tmp, "dead")
code, out, _ = run_hook(env, role="master")
check("4a ⓒ불가: 디렉티브 주입(fail-open)", "DIRECTIVE-BODY-MASTER" in out)
check("4b ⓒ불가: 고지 1줄", "역할 재확인 불가" in out)
check("4c ⓒ불가: self-demote 없음", "역할 주소 상실" not in out)
shutil.rmtree(tmp)

# ── 5. ⓒ 무응답(timeout 상한) → fail-open ──
tmp = tempfile.mkdtemp(prefix="hook-t5-")
env = setup(tmp, "silent")
code, out, _ = run_hook(env, role="master")
check("5a ⓒ무응답: 디렉티브 주입(fail-open)", "DIRECTIVE-BODY-MASTER" in out)
shutil.rmtree(tmp)

# ── 6. worker는 재대조 미적용(권한 role 아님 — claim 왕복 0) ──
tmp = tempfile.mkdtemp(prefix="hook-t6-")
env = setup(tmp, "denied")
code, out, _ = run_hook(env, role="worker")
check("6a worker 디렉티브 주입", "DIRECTIVE-BODY-WORKER" in out)
calls = ""
if os.path.exists(os.path.join(tmp, "calls.log")):
    calls = open(os.path.join(tmp, "calls.log"), encoding="utf-8").read()
check("6b worker claim 왕복 0", "claim-role" not in calls)
shutil.rmtree(tmp)

print("\n%d FAIL" % len(fails) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
