#!/usr/bin/env python3
"""test_bootstrap_chain.py — ezer_bootstrap.py 스텁 결정론 CI (BOOTSTRAP_HARDENING T0).

실 데몬·실 Claude 없이: 임시 HOME + 가짜 팩(스텁 preflight/orchestra/ezer-dept) + PATH 선두
`ezer` 스텁으로 부트 체인의 exit-code 계약을 핀한다. 설계 v1.1 검증 핀:
  ⓐ 부서 소켓 컨텍스트에서 전 단계 성공해도 base 마커 미생성(소켓 격리)
  ⓑ check 스텁 "N회 실패 후 성공" 시퀀스에서 부트 성공 / 전부 실패 시 상한 내 종료(retry)
  ⓒ (hook 3상태는 test_session_start_hook.py — 본 파일 아님)
  ⓓ ⑦ 호출이 promote-if-pending --request-only(비대기 인자)로 기록됨
+ 기본 매트릭스: happy path·preflight/ping/boot/claim 실패·assert-ready 3상태·롤백 불변식
  (마커·상태 파일 삭제 = 게이트 전부 현행 거동 복귀 — 부재=제약 없음).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

SELF = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(SELF, "..", "ezer_bootstrap.py")
PY = sys.executable or "python3"

fails = []


def check(name, cond, detail=""):
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, (" — " + detail) if detail else ""))
    if not cond:
        fails.append(name)


def make_env(tmp, *, claim_exit=0, ping_exit=0, boot_exit=0, preflight_exit=0,
             check_fail_times=0, check_final=0, socket="", check_needs_reviewers=False,
             br_exit=0):
    """임시 HOME + 가짜 팩 + 스텁 생성 → 환경 dict 반환."""
    home = os.path.join(tmp, "home")
    pack = os.path.join(home, ".ezer", "pack")
    bindir = os.path.join(tmp, "stubbin")
    for d in (os.path.join(pack, "bin"), bindir):
        os.makedirs(d, exist_ok=True)

    def w(path, body, mode=0o755):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        os.chmod(path, mode)

    # 스텁 ezer — 서브커맨드별 exit·호출 기록(calls.log)
    w(os.path.join(bindir, "ezer"), (
        "#!/bin/sh\n"
        "echo \"ezer $@\" >> \"%s/calls.log\"\n"
        "case \"$1\" in\n"
        "  ping) exit %d;;\n"
        "  claim-role) [ %d -ne 0 ] && echo 'claim_denied: privileged role held by live surface' >&2; exit %d;;\n"
        "  boot) exit %d;;\n"
        "  --version) echo 'ezer 0.0.0-stub'; exit 0;;\n"
        "esac\nexit 0\n") % (tmp, ping_exit, claim_exit, claim_exit, boot_exit))
    # 스텁 preflight
    w(os.path.join(pack, "bin", "ezer_preflight.py"),
      "import sys; sys.exit(%d)\n" % preflight_exit, 0o644)
    # 스텁 orchestra — 서브커맨드 분기: boot-reviewers=마커 생성(④-b 재현), check=카운터
    # (+needs_reviewers면 마커 없을 때 실패 — "ezer boot만으론 리뷰어 0" 시나리오).
    w(os.path.join(pack, "bin", "ezer_orchestra.py"), (
        "import os,sys\n"
        "mode=sys.argv[1] if len(sys.argv)>1 else ''\n"
        "open('%s/orch.log','a').write(mode+'\\n')\n"
        "if mode=='boot-reviewers':\n"
        "    open('%s/reviewers.flag','w').write('1')\n"
        "    sys.exit(%d)\n"
        "if mode!='check': sys.exit(0)\n"
        "c='%s/check.count'\n"
        "n=int(open(c).read()) if os.path.exists(c) else 0\n"
        "open(c,'w').write(str(n+1))\n"
        "if %d and not os.path.exists('%s/reviewers.flag'): sys.exit(1)\n"
        "sys.exit(1 if n < %d else %d)\n")
      % (tmp, tmp, br_exit, tmp, 1 if check_needs_reviewers else 0, tmp,
         check_fail_times, check_final), 0o644)
    # 스텁 ezer-dept — 인자 기록
    w(os.path.join(pack, "bin", "ezer-dept"),
      "#!/bin/sh\necho \"ezer-dept $@\" >> \"%s/calls.log\"\nexit 0\n" % tmp)

    env = dict(os.environ)
    env.update({"HOME": home, "PATH": bindir + os.pathsep + env.get("PATH", ""),
                "EZER_BOOT_CHECK_RETRIES": "4", "EZER_BOOT_CHECK_INTERVAL_S": "0.05",
                "EZER_SURFACE_ID": "7"})
    env.pop("EZER_PACK_DIR", None)
    env.pop("EZER_BOOT_GATE", None)
    if socket:
        env["EZER_SOCKET"] = socket
    else:
        env.pop("EZER_SOCKET", None)
    return env, home


def run(env, *args):
    r = subprocess.run([PY, SCRIPT] + list(args), capture_output=True, text=True,
                       encoding="utf-8", env=env, timeout=60)
    return r.returncode, r.stdout, r.stderr


def marker_path(home):
    return os.path.join(home, ".ezer", ".master-bootstrapped")


def calls(tmp):
    p = os.path.join(tmp, "calls.log")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


# ── 1. happy path: exit 0 · 마커 생성 · ⑧ JSON · ⑦ --request-only(ⓓ) ──
tmp = tempfile.mkdtemp(prefix="boot-t1-")
env, home = make_env(tmp)
code, out, err = run(env)
check("1a happy exit 0", code == 0, "exit=%d err=%s" % (code, err[-200:]))
check("1b 마커 생성", os.path.exists(marker_path(home)))
m = json.load(open(marker_path(home), encoding="utf-8")) if os.path.exists(marker_path(home)) else {}
check("1c 마커에 orchestra 증거", m.get("orchestra_check") == "exit 0")
try:
    summary = json.loads(out.strip().splitlines()[-1])
except Exception:
    summary = {}
check("1d ⑧ 기계 요약 JSON(ok)", summary.get("ok") is True)
check("1e ⓓ ⑦ 비대기 인자", "promote-if-pending --request-only" in calls(tmp))
check("1f boot-last 단계 누적",
      bool((json.load(open(os.path.join(home, ".ezer", "state", "boot-last.json"),
                           encoding="utf-8")) or {}).get("steps")))
check("1g ★R12 진행 신호(침묵 창 방지 — 단계 시작 stderr)",
      "[bootstrap] ①" in err and "[bootstrap] ⑤" in err, err[:200])
src_boot = open(SCRIPT, encoding="utf-8").read()
check("1h ★R6 ④-b timeout≥320(2슬롯×130s 순차 — 스텁은 즉시 반환이라 정적 핀·실기 미검증 정직 표기)",
      "timeout=320" in src_boot)
shutil.rmtree(tmp)

# ── 2. ⓐ 부서 소켓 컨텍스트: 성공해도 base 마커 미생성·⑦ 생략 ──
tmp = tempfile.mkdtemp(prefix="boot-t2-")
env, home = make_env(tmp, socket="/tmp/x/ezer-dept-dept-3.sock")
code, out, err = run(env)
check("2a 부서 부트 exit 0", code == 0)
check("2b ⓐ base 마커 미생성(소켓 격리)", not os.path.exists(marker_path(home)))
check("2c 부서 컨텍스트 ⑦ 생략", "promote-if-pending" not in calls(tmp))
shutil.rmtree(tmp)

# ── 2w. windows pipe 이름도 base로 인정 ──
tmp = tempfile.mkdtemp(prefix="boot-t2w-")
env, home = make_env(tmp, socket=r"\\.\pipe\ezer")
code, out, err = run(env)
check("2w pipe ezer=base(마커 생성)", code == 0 and os.path.exists(marker_path(home)))
shutil.rmtree(tmp)

# ── 3. ⓑ check 3회 실패 후 성공 → 부트 성공(retry) ──
tmp = tempfile.mkdtemp(prefix="boot-t3-")
env, home = make_env(tmp, check_fail_times=3, check_final=0)
code, out, err = run(env)
check("3a ⓑ retry 후 성공", code == 0, "exit=%d" % code)
check("3b 마커 생성", os.path.exists(marker_path(home)))
shutil.rmtree(tmp)

# ── 4. ⓑ check 전부 실패 → exit 6·마커 무·시도수=상한 ──
tmp = tempfile.mkdtemp(prefix="boot-t4-")
env, home = make_env(tmp, check_fail_times=99)
code, out, err = run(env)
check("4a check 최종 실패 exit 6", code == 6, "exit=%d" % code)
check("4b 마커 미생성", not os.path.exists(marker_path(home)))
attempts = int(open(os.path.join(tmp, "check.count"), encoding="utf-8").read())
check("4c 시도수=상한(4)", attempts == 4, "attempts=%d" % attempts)
shutil.rmtree(tmp)

# ── 5. claim 거부 → exit 7·boot 미호출·마커 무 ──
tmp = tempfile.mkdtemp(prefix="boot-t5-")
env, home = make_env(tmp, claim_exit=1)
code, out, err = run(env)
check("5a claim 거부 exit 7", code == 7, "exit=%d" % code)
check("5b 마커 미생성", not os.path.exists(marker_path(home)))
check("5c 거부 후 boot 미호출", "ezer boot" not in calls(tmp))
check("5d 인계 지시 출력", "인계" in err)
shutil.rmtree(tmp)

# ── 6. 선행 단계 실패 exit 매핑: preflight=2 · ping=3 · boot=4 ──
for name, kw, want in (("preflight", {"preflight_exit": 1}, 2),
                       ("ping", {"ping_exit": 1}, 3),
                       ("boot", {"boot_exit": 1}, 4)):
    tmp = tempfile.mkdtemp(prefix="boot-t6-")
    env, home = make_env(tmp, **kw)
    code, out, err = run(env)
    check("6 %s 실패 exit %d" % (name, want), code == want, "exit=%d" % code)
    check("6 %s 실패 시 마커 무" % name, not os.path.exists(marker_path(home)))
    shutil.rmtree(tmp)

# ── 7. assert-ready: 부재=5 · warn=0 · off=0 · 버전 불일치=5 · 일치=0 ──
tmp = tempfile.mkdtemp(prefix="boot-t7-")
env, home = make_env(tmp)
code, _, _ = run(env, "assert-ready")
check("7a 마커 부재 exit 5", code == 5)
env2 = dict(env); env2["EZER_BOOT_GATE"] = "warn"
check("7b 밸브 warn=0", run(env2, "assert-ready")[0] == 0)
env3 = dict(env); env3["EZER_BOOT_GATE"] = "off"
check("7c 밸브 off=0", run(env3, "assert-ready")[0] == 0)
code, _, _ = run(env)  # 정상 부트로 마커 생성(.pack-version 부재 → 'unknown' 일치)
check("7d 부트 후 assert-ready=0", code == 0 and run(env, "assert-ready")[0] == 0)
with open(os.path.join(home, ".ezer", ".pack-version"), "w", encoding="utf-8") as f:
    f.write("9.9.9")  # 현재 pack_version만 전진 → 마커 stale
check("7e 버전 불일치 exit 5", run(env, "assert-ready")[0] == 5)
shutil.rmtree(tmp)

# ── 9. ④-b 리뷰어 폴백 (D-IMPL-1 재현 핀 · 산문 §0 ④-b 전사) ──
# 9a: check가 리뷰어 폴백 마커를 요구(=agy/codex 부재 기계) → ④-b가 체인에 있어야만 부트 성공.
tmp = tempfile.mkdtemp(prefix="boot-t9a-")
env, home = make_env(tmp, check_needs_reviewers=True)
code, out, err = run(env)
check("9a ④-b 폴백으로 부트 성공(agy/codex 부재 기계)", code == 0, "exit=%d" % code)
orch = open(os.path.join(tmp, "orch.log"), encoding="utf-8").read().split() if \
    os.path.exists(os.path.join(tmp, "orch.log")) else []
check("9b ④-b가 check보다 선행", orch[:1] == ["boot-reviewers"], "order=%s" % orch[:3])
shutil.rmtree(tmp)
# 9c: ④-b 자체 실패는 비중단(best-effort — 최종 게이트는 ⑤ check).
tmp = tempfile.mkdtemp(prefix="boot-t9c-")
env, home = make_env(tmp, br_exit=1)
code, out, err = run(env)
check("9c ④-b 실패해도 체인 계속(check green이면 부트 성공)", code == 0, "exit=%d" % code)
shutil.rmtree(tmp)

# ── 8. 롤백 불변식: 마커·상태 삭제 = 부재 상태로 완전 복귀(재부트로 재생성 가능) ──
tmp = tempfile.mkdtemp(prefix="boot-t8-")
env, home = make_env(tmp)
run(env)
os.remove(marker_path(home))
shutil.rmtree(os.path.join(home, ".ezer", "state"))
check("8a 삭제 후 assert-ready=5(게이트=순수 추가 제약)", run(env, "assert-ready")[0] == 5)
check("8b 재부트로 재생성", run(env)[0] == 0 and os.path.exists(marker_path(home)))
shutil.rmtree(tmp)

print("\n%d FAIL" % len(fails) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
