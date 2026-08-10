#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EZERagent_phoenix_win_smoke.py — 불사조(무손실 복원) Windows 전용 경량 스모크(S6 · CI hang 수리판)

목적: Windows 패리티(EZERagent_phoenix.py S1~S5)를 windows-latest CI 러너에서 결정론·자기완결로 실측한다.
      unix 하네스(EZERagent_phoenix_harness.py)는 macOS 검증 도구로 존치 — 이 스모크는 그와 별개(하네스 무접촉).

★hang 방지(CI run 28733378888 케이스③ 12분 hang 수리):
  · 모든 EZERagent 호출은 phoenix.EZERagent(=Windows 임시파일 캡처 _run_capture)로 라우팅 — detached EZERagentd 파이프 상속 hang 소멸.
  · 롤링 워치독(체크포인트마다 리셋·무진전 시 정직 비0 exit + 마지막 체크포인트) + 개별 subprocess hard timeout.
  · 케이스③ 재기동은 lazy-spawn(EZERagent list) 대신 throwaway schtasks 태스크 /Run(라이브 managed 경로와 동형·대표성↑).

케이스(전부 결정론·자기완결·정리 포함):
  ① 경로/파이프 매핑 단위검증
  ② supervisor(schtasks) 실조작 — throwaway 태스크 create/query/delete(실 schtasks·EZERagentd 무접촉·정리)
  ③ 재시작 프리미티브 E2E — 테스트 데몬 기동→identify→taskkill→파이프 해제 폴링→★schtasks /Run 재기동→pong+boot-epoch delta
  ④ snapshot + 독립 runbook(.ps1) + LIVE default_sources LOCALAPPDATA 포착(권고#1)
  ⑤ stub restore E2E — 기존 --stub surrogate 백엔드로 M9 VERIFIED·COMPLETE
  ⑥ deploy --plan + exit code 계약 — 무실행·exit0·부작용 0
  ⑦ ★진짜 KeepAlive respawn E2E — 실 EZERagentd 스케줄러 태스크(RestartOnFailure): taskkill(crash)→유발 없이 스케줄러
     자동 재기동(간격 PT1M)만 관측→pong+epoch delta. 정직 evidence(경과 시간)·정리 finally.

mac(비-Windows)에서 실행 시: "Windows 전용" 정직 안내 후 exit 0(skip).

환경: PHOENIX_EZERAGENT(EZERagent.exe)·PHOENIX_EZERAGENTD(EZERagentd.exe) 미설정 시 PATH. 자기 stdout·phoenix 하위프로세스는 utf-8 고정.
"""

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time

IS_WIN = os.name == "nt"
HERE = os.path.dirname(os.path.abspath(__file__))
PHOENIX = os.path.join(HERE, "EZERagent_phoenix.py")

WATCHDOG_SECS = 120   # 체크포인트 무진전 상한(개별 subprocess timeout 보다 넉넉·전체는 CI 12분보다 작다)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_FAILS = []
_RESULTS = {}
_LAST_CP = "init"
_WD = None
_PH = None          # phoenix 모듈(전역 — 워치독 evidence 접근)
EZERAGENT_BIN = None
EZERAGENTD_BIN = None


def log(msg):
    sys.stdout.write("[win-smoke] %s\n" % msg)
    sys.stdout.flush()


def check(name, cond, detail=""):
    ok = bool(cond)
    _RESULTS[name] = ok
    if not ok:
        _FAILS.append(name)
    log(("PASS " if ok else "FAIL ") + name + (" :: " + str(detail)[:200] if detail else ""))
    return ok


# ------------------------------------------------------------------ 워치독(정직 실패)

def _wd_boom():
    sys.stderr.write("[win-smoke][WATCHDOG] %ss 무진전 — 마지막 체크포인트=%r 에서 hang. 정직 비0 exit.\n"
                     % (WATCHDOG_SECS, _LAST_CP))
    sys.stderr.flush()
    print(json.dumps({"win_smoke": "HANG", "last_checkpoint": _LAST_CP, "results": _RESULTS,
                      "win_smoke_pass": False}, ensure_ascii=False, indent=2))
    sys.stdout.flush()
    os._exit(3)   # 조용한 hang 금지 — 어디서 멈췄는지 evidence 와 함께 비0


def _cp(name):
    """체크포인트 — 워치독 리셋(무진전 감시창 재시작). 진행이 멈추면 여기 마지막 이름이 evidence."""
    global _WD, _LAST_CP
    _LAST_CP = name
    if _WD is not None:
        _WD.cancel()
    _WD = threading.Timer(WATCHDOG_SECS, _wd_boom)
    _WD.daemon = True
    _WD.start()


def _wd_stop():
    global _WD
    if _WD is not None:
        _WD.cancel()
        _WD = None


# ------------------------------------------------------------------ 실행 헬퍼(전부 바운드)

def _phoenix_env(extra=None):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("AITERM_SOCKET", "AITERM_SURFACE_ID"):
        env.pop(k, None)
    if extra:
        env.update(extra)
    return env


def EZERagentcall(pipe, *args, timeout=20):
    """모든 EZERagent 호출 = phoenix.EZERagent(Windows 임시파일 캡처 _run_capture) 경유 — 파이프 상속 hang 소멸."""
    return _PH.EZERagent(*args, socket=pipe, timeout=timeout)


def _ping_pong(pipe, timeout=6):
    r = EZERagentcall(pipe, "ping", timeout=timeout)
    return getattr(r, "returncode", 1) == 0 and "pong" in (getattr(r, "stdout", "") or "")


def run_phoenix(pipe, *args, timeout=90):
    """phoenix.py 서브프로세스 실행(케이스⑤⑥) — _run_capture 로 바운드(직접자식 종료만 대기·hang 없음)."""
    cmd = [sys.executable, PHOENIX, "--socket", pipe] + [str(a) for a in args]
    return _PH._run_capture(cmd, _phoenix_env({"PHOENIX_EZERAGENT": EZERAGENT_BIN}), timeout)


def spawn_test_daemon(pipe):
    """테스트 전용 파이프에 EZERagentd 직접 기동(EZERAGENT_SOCKET 오버라이드). 반환 Popen(추적·정리용)."""
    env = _phoenix_env({"EZERAGENT_SOCKET": pipe})
    CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0
    return subprocess.Popen([EZERAGENTD_BIN], env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=CREATE_NO_WINDOW)


def _state_dir(pipe):
    try:
        return _PH._win_state_dir_for_socket(pipe)
    except Exception:
        return None


def teardown_daemon(pipe, state_dir=None, tracked=None):
    try:
        r = EZERagentcall(pipe, "identify", timeout=6)
        txt = getattr(r, "stdout", "") or ""
        i = txt.find("{")
        if i >= 0:
            pid = json.loads(txt[i:]).get("daemon_pid")
            if isinstance(pid, int):
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, text=True, timeout=10)
    except Exception:
        pass
    if tracked is not None:
        try:
            tracked.kill()
        except Exception:
            pass
    if state_dir:
        import shutil
        shutil.rmtree(state_dir, ignore_errors=True)


# ------------------------------------------------------------------ 케이스

def case1_path_mapping():
    _cp("① path mapping")
    cases = {r"\\.\pipe\EZERagent": "EZERagent", r"\\.\pipe\EZERagent-dept-alpha": "EZERagent-dept-alpha",
             "//./pipe/EZERagent": "EZERagent", r"\\.\pipe\EZERagent_x.1": "EZERagent_x1"}
    for pipe, exp in cases.items():
        check("① slug %s" % exp, _PH._win_pipe_slug(pipe) == exp, _PH._win_pipe_slug(pipe))
    la = os.environ.get("LOCALAPPDATA") or ""
    d0 = _PH._win_state_dir_for_socket(r"\\.\pipe\EZERagent").replace("\\", "/")
    dd = _PH._win_state_dir_for_socket(r"\\.\pipe\EZERagent-dept-alpha").replace("\\", "/")
    check("① default pipe->%LOCALAPPDATA%\\EZERagent", d0.endswith("/EZERagent") and la.replace("\\", "/").lower() in d0.lower(), d0)
    check("① dept pipe->...\\EZERagent\\EZERagent-dept-alpha", dd.endswith("/EZERagent/EZERagent-dept-alpha"), dd)


def case2_schtasks():
    _cp("② schtasks")
    task = "phoenix-win-smoke-tmp"
    _PH._schtasks("/Delete", "/TN", task, "/F")
    cr = _PH._schtasks("/Create", "/TN", task, "/TR", "cmd /c exit", "/SC", "ONLOGON", "/RL", "LIMITED", "/F")
    check("② schtasks /Create rc0", getattr(cr, "returncode", 1) == 0, getattr(cr, "stderr", ""))
    check("② 등록됨->managed", _PH._schtasks_status(task).get("state") == "managed")
    dl = _PH._schtasks("/Delete", "/TN", task, "/F")
    check("② schtasks /Delete rc0", getattr(dl, "returncode", 1) == 0)
    check("② 삭제후->unmanaged", _PH._schtasks_status(task).get("state") == "unmanaged")
    real = _PH.supervisor_status("EZERagentd")
    check("② supervisor_status('EZERagentd') 분류(읽기전용)",
          real.get("supervisor") == "schtasks" and real.get("state") in ("managed", "orphan", "unmanaged"), real)


def case3_restart_primitive():
    """★결정론화: 재기동을 lazy-spawn(EZERagent list) 대신 throwaway schtasks 태스크 /Run 으로(라이브 managed 경로 동형)."""
    _cp("③ restart setup")
    import shutil
    pipe = r"\\.\pipe\EZERagent-phxsmoke-r3"
    task = "phoenix-win-smoke-r3"
    sd = _state_dir(pipe)
    tracked = None
    bat = os.path.join(os.environ.get("TEMP") or ".", "EZERagent_phxsmoke_r3.bat")
    try:
        if sd:
            shutil.rmtree(sd, ignore_errors=True)
        _PH._schtasks("/Delete", "/TN", task, "/F")
        # 재기동 태스크: EZERAGENT_SOCKET=테스트파이프 로 EZERagentd 를 detached 기동하는 bat(EZERagentd 는 env 만 읽음 — argv 소켓 없음).
        with open(bat, "w", encoding="ascii") as f:
            f.write("@echo off\r\nset EZERAGENT_SOCKET=%s\r\nstart \"\" \"%s\"\r\n" % (pipe, EZERAGENTD_BIN))
        cr = _PH._schtasks("/Create", "/TN", task, "/TR", bat, "/SC", "ONLOGON", "/RL", "LIMITED", "/F")
        if not check("③ 재기동 태스크 등록(schtasks /Create)", getattr(cr, "returncode", 1) == 0, getattr(cr, "stderr", "")):
            return
        tracked = spawn_test_daemon(pipe)   # 초기 데몬 직접 기동(안정적) → identify 대상
        up = False
        for _ in range(50):
            _cp("③ waiting initial daemon")
            if _ping_pong(pipe):
                up = True
                break
            time.sleep(0.3)
        if not check("③ 테스트 데몬 기동(ping pong)", up):
            return
        _cp("③ restart primitive")
        _PH.EZERAGENT = EZERAGENT_BIN
        _PH.SUPERVISOR_LABEL = task          # managed → 재기동 유발이 schtasks /Run /TN <task> 경로를 타게
        epoch1 = _PH.get_boot_epoch(pipe)
        res = _PH._win_restart_daemon(pipe, timeout=30)   # 내부 폴링·retrigger 전부 바운드
        check("③ identify→daemon_pid 획득", isinstance(res.get("daemon_pid"), int), res.get("daemon_pid"))
        check("③ taskkill 수행(rc0)", res.get("taskkill_rc") == 0, res.get("taskkill_out"))
        check("③ 파이프 해제(socket_death) 관측 후 retrigger", res.get("socket_death_observed") is True, res.get("retrigger"))
        check("③ retrigger=schtasks /Run(managed 경로)", "schtasks /Run" in (res.get("retrigger") or ""), res.get("retrigger"))
        revived = False
        for _ in range(100):
            _cp("③ waiting revival")
            if _ping_pong(pipe):
                revived = True
                break
            time.sleep(0.4)
        epoch2 = _PH.get_boot_epoch(pipe)
        check("③ 재기동 후 pong 복귀", revived)
        check("③ boot-epoch delta(실제 새 세대·조용한 오복원 아님)",
              epoch1 is not None and epoch2 is not None and epoch1 != epoch2, "%s->%s" % (epoch1, epoch2))
    finally:
        _cp("③ teardown")
        teardown_daemon(pipe, state_dir=sd, tracked=tracked)
        _PH._schtasks("/Delete", "/TN", task, "/F")
        try:
            os.remove(bat)
        except OSError:
            pass


def case4_snapshot_runbook():
    _cp("④ snapshot")
    import shutil
    pipe = r"\\.\pipe\EZERagent-phxsmoke-snap"
    sd = _state_dir(pipe)
    try:
        os.makedirs(sd, exist_ok=True)
        with open(os.path.join(sd, "topology.json"), "w", encoding="utf-8") as f:
            json.dump({"entries": [{"role": "worker", "agent": "claude", "session_id": "S1"},
                                   {"role": "cso", "agent": "claude", "session_id": "S2"}], "updated_at": 0}, f)
        _PH.EZERAGENT = EZERAGENT_BIN
        roster = {"worker": {"agent": "claude"}, "cso": {"agent": "claude"}}
        snap = _PH._deploy_snapshot(pipe, roster)
        check("④ 세대 스냅샷 생성", snap.get("ok") and snap.get("gen"), snap.get("error") or snap.get("gen"))
        rb = snap.get("runbook") or ""
        check("④ runbook=MANUAL_RESTORE.ps1 존재", rb.endswith("MANUAL_RESTORE.ps1") and os.path.exists(rb), rb)
        body = open(rb, encoding="utf-8-sig").read() if os.path.exists(rb) else ""
        selfcontained = ("EZERagent daemon install" in body and "schtasks /Query /TN" in body
                         and "EZERagent list" in body and "EZERagent ping" in body
                         and all(("--role %s" % r) in body for r in roster)
                         and "EZERagent_phoenix" not in body and "launchctl" not in body)
        check("④ runbook 자기완결(schtasks+EZERagent만·집행/launchctl 미호출)", selfcontained)
        # ★권고#1: LIVE default_sources 가 %LOCALAPPDATA%\EZERagent L1 상태를 포착(unix ~/.local/state 로 미누출)
        import EZERagent_state_snapshot as snapmod
        la = (os.environ.get("LOCALAPPDATA") or "").replace("\\", "/").lower()
        live_srcs = [s.replace("\\", "/").lower() for s in snapmod.default_sources()]
        # ★live_srcs·la 는 위에서 소문자화됐다 — 비교 대상도 반드시 소문자화한다.
        #   제품명에 대문자가 있으므로(EZERagent) 리터럴을 그대로 쓰면 main_ok 는 영원히 False,
        #   no_unix_leak 는 영원히 True(공허한 참)가 되어 누출 가드가 침묵한다.
        main_ok = bool(la) and any(s == (la + "/EZERagent/topology.json").lower() for s in live_srcs)
        no_unix_leak = not any("/.local/state/EZERagent/topology.json".lower() in s for s in live_srcs)
        check("④ 권고#1: LIVE default_sources 가 %LOCALAPPDATA%\\EZERagent L1 상태 포착",
              main_ok and no_unix_leak, "la=%s main_ok=%s no_unix_leak=%s" % (la, main_ok, no_unix_leak))
    finally:
        shutil.rmtree(sd, ignore_errors=True)


def case5_stub_restore():
    _cp("⑤ stub restore setup")
    import shutil
    pipe = r"\\.\pipe\EZERagent-phxsmoke-restore"
    sd = _state_dir(pipe)
    tracked = None
    try:
        shutil.rmtree(sd, ignore_errors=True)
        tracked = spawn_test_daemon(pipe)
        up = False
        for _ in range(50):
            _cp("⑤ waiting daemon")
            if _ping_pong(pipe):
                up = True
                break
            time.sleep(0.3)
        os.makedirs(sd, exist_ok=True)
        with open(os.path.join(sd, "topology.json"), "w", encoding="utf-8") as f:
            json.dump({"entries": [{"role": "worker", "agent": "stub", "session_id": "SID-W-1",
                                    "cwd": sd, "title": "w"}], "updated_at": 0}, f)
        if not check("⑤ 테스트 데몬 기동", up):
            return
        _cp("⑤ restore")
        r = run_phoenix(pipe, "restore", "--ticket", "WS", "--stub", timeout=90)
        txt = r.stdout or ""
        i = txt.find("{")
        j = json.loads(txt[i:]) if i >= 0 else {}
        check("⑤ phoenix_restore=VERIFIED", j.get("phoenix_restore") == "VERIFIED", j.get("phoenix_restore"))
        check("⑤ completeness=COMPLETE", j.get("completeness") == "COMPLETE", j.get("completeness"))
    finally:
        _cp("⑤ teardown")
        teardown_daemon(pipe, state_dir=sd, tracked=tracked)


def case6_deploy_plan():
    _cp("⑥ deploy plan")
    pipe = r"\\.\pipe\EZERagent-phxsmoke-plan"
    r = run_phoenix(pipe, "deploy", "--plan", "--ticket", "PLAN", "--stub", timeout=30)
    txt = r.stdout or ""
    i = txt.find("{")
    j = json.loads(txt[i:]) if i >= 0 else {}
    check("⑥ --plan exit 0", r.returncode == 0, r.returncode)
    check("⑥ stages 출력(무실행)", j.get("deploy") == "PLAN" and isinstance(j.get("stages"), list) and j.get("stages"), j.get("stages"))


def case7_keepalive_respawn():
    """★진짜 KeepAlive(RestartOnFailure) 실 respawn E2E — 실 EZERagentd 스케줄러 태스크로 검증(실기 대표성).
    EZERagent daemon install(RestartOnFailure XML)→schtasks /Run 으로 데몬 기동(=태스크 action 인스턴스)→taskkill /F
    (비정상 종료=action exit≠0)→★재기동 유발 없이 순수 스케줄러 RestartOnFailure 만 관측.
    ★1차 성공 기준 = boot-epoch delta(스케줄러가 실제로 새 세대를 띄웠다는 정직한 증거). pong 복귀 '시간'은 evidence
    (Task Scheduler 실전 재기동 지연은 PT1M 설정보다 김·실측 ~4분). 예산 420s + grace 1회(경계 도착 보호).
    정리(태스크 uninstall→데몬 kill)는 finally."""
    _cp("⑦ keepalive setup")
    default_pipe = r"\\.\pipe\EZERagent"
    task = "EZERagentd"
    installed = False
    try:
        # 클린 시작: 잔류 EZERagentd 제거 + 기존 태스크 해제
        subprocess.run(["taskkill", "/IM", "EZERagentd.exe", "/F"], capture_output=True, timeout=15)
        _PH.EZERagent("daemon", "uninstall", socket=None, timeout=20)
        time.sleep(1)
        inst = _PH.EZERagent("daemon", "install", socket=None, timeout=30)
        installed = getattr(inst, "returncode", 1) == 0
        check("⑦ EZERagent daemon install(RestartOnFailure XML)", installed, (getattr(inst, "stdout", "") or getattr(inst, "stderr", ""))[:160])
        check("⑦ 태스크에 RestartOnFailure(진짜 KeepAlive) 존재", _PH._schtasks_has_restart_on_failure(task))
        if not installed:
            return
        # 데몬 기동 = schtasks /Run(태스크 action 인스턴스여야 kill 시 RestartOnFailure 발화 — lazy-spawn 아님)
        _cp("⑦ schtasks /Run")
        _PH._schtasks("/Run", "/TN", task, timeout=15)
        up = False
        for _ in range(60):
            _cp("⑦ waiting daemon")
            if _ping_pong(default_pipe):
                up = True
                break
            time.sleep(0.4)
        if not check("⑦ 태스크 데몬 기동(schtasks /Run → pong)", up):
            return
        epoch1 = _PH.get_boot_epoch(default_pipe)
        pid = _PH._win_identify_daemon_pid(default_pipe)
        check("⑦ daemon_pid 획득", isinstance(pid, int), pid)
        # ★비정상 종료(crash 시뮬레이션): taskkill /F → action exit≠0 → 스케줄러 RestartOnFailure
        _cp("⑦ taskkill (crash)")
        if isinstance(pid, int):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True, timeout=15)
        t0 = time.time()
        # ★순수 관측: 재기동 유발(EZERagent list·schtasks /Run) 없이 ping(autostart 안 함)만 폴링 — 되살리면 스케줄러 뿐.
        #   ★판정 재정의(CI run 28736698338 교훈): Task Scheduler 실전 재기동 지연은 PT1M 설정보다 길다(실측 ~4분·
        #   실패감지 주기 특성). pong 복귀 '시간'은 evidence 로만 기록하고, 1차 성공 기준은 boot-epoch delta(정직한
        #   '새 세대' 증거)로 둔다. 예산 420s(4분 실측+여유). ★status(get_boot_epoch)는 autostart 하므로 데몬이
        #   ping 으로 살아있음을 확인한 뒤에만 epoch 을 조회한다(우리가 status autostart 로 되살리는 오검출 방지).
        BUDGET = 420
        revived_pong = False
        pong_elapsed = None
        while time.time() - t0 < BUDGET:
            _cp("⑦ waiting scheduler RestartOnFailure respawn")
            if _ping_pong(default_pipe):
                revived_pong = True
                pong_elapsed = time.time() - t0
                break
            time.sleep(3)
        # ★grace 1회(경계 직후 도착을 억울하게 놓치지 않게 — 이번 실패가 정확히 경계 +1~2s 였다)
        if not revived_pong:
            time.sleep(5)
            if _ping_pong(default_pipe):
                revived_pong = True
                pong_elapsed = time.time() - t0
        elapsed = time.time() - t0
        # 데몬이 (ping 으로) 살아있을 때만 epoch 조회(status autostart 로 우리가 되살리는 것 차단)
        epoch2 = _PH.get_boot_epoch(default_pipe) if revived_pong else None
        pong_ev = ("%.0fs" % pong_elapsed) if pong_elapsed is not None else "미관측"
        respawned = epoch1 is not None and epoch2 is not None and epoch1 != epoch2
        ev = "epoch %s->%s · pong복귀=%s · elapsed=%.0fs(예산 %ds)" % (epoch1, epoch2, pong_ev, elapsed, BUDGET)
        # ★라벨 전환(박사님 승인 2026-07-05 · CI run 28736698338 vs 28737327371 실증): Task Scheduler 의
        #   RestartOnFailure 반응 시점은 OS 내부 사정으로 비결정(+242s 부활 vs 425s 미부활) — 실시간 관측을
        #   per-commit CI hard gate 로 두면 가짜 빨간불이 CI 신뢰를 갉는다. 예산 내 부활=PASS(경과시간 evidence),
        #   미부활=FAIL 아닌 OBSERVED-TIMEOUT 정직 라벨(능력 은폐 아님 — 검증 자리 이동: 설정·수동 /Run 재기동은
        #   T3-1b·케이스③⑦ 전반부 hard gate 유지, 실시간 자동부활 확정은 오너 실기·1차 run +242s CI 실증 보유).
        if respawned:
            check("⑦ 스케줄러 자동 재기동 = boot-epoch delta(새 세대·유발 없이 순수 관측)", True, ev)
        else:
            log("OBSERVED-TIMEOUT ⑦ 스케줄러 자동 재기동 예산 내 미관측(비결정 타이밍·informational — hard gate 아님) :: " + ev)
            _RESULTS["⑦ 스케줄러 자동 재기동(informational)"] = True  # 정직 라벨로 기록·CI 비차단
    finally:
        _cp("⑦ teardown")
        if installed:
            _PH.EZERagent("daemon", "uninstall", socket=None, timeout=20)  # ★태스크 먼저 제거(추가 respawn 차단)
        subprocess.run(["taskkill", "/IM", "EZERagentd.exe", "/F"], capture_output=True, timeout=15)


def _alive_pid(pid):
    """Windows: PID 생존 여부(tasklist 필터). 죽었으면 'No tasks' 출력(pid 미포함)."""
    try:
        r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                           capture_output=True, text=True, timeout=10)
        return str(pid) in (r.stdout or "")
    except Exception:
        return False


def case9_job_kill_on_close():
    """★D3(W5) ConPTY 자식 트리 Job-close 종료 전파 E2E(CI Windows 러너 전용·mac 은 run() 조기 SKIP): EZERagentd 를
    /T 없이 taskkill 해도 KILL_ON_JOB_CLOSE 로 PTY 자식·손자가 동반사망하는지 관측. Job Object 부재(P2-9)면 고아
    생존. ★관측 견고화: ConPTY 가 자식을 conhost 하위로 reparent 하므로 ParentProcessId 탐지 대신 '손자가 자기
    pid 를 마커파일에 self-report' 방식 — 손자는 Job 상속으로 자동 편입되므로 손자 동반사망이 곧 트리 전파 증명."""
    _cp("⑨ job kill-on-close setup")
    import shutil
    pipe = r"\\.\pipe\EZERagent-phxsmoke-jobkill"
    sd = _state_dir(pipe)
    tracked = None
    gpid = None
    marker = os.path.join(sd, "grandchild.pid") if sd else None
    try:
        shutil.rmtree(sd, ignore_errors=True)
        os.makedirs(sd, exist_ok=True)
        tracked = spawn_test_daemon(pipe)
        up = False
        for _ in range(50):
            _cp("⑨ waiting daemon")
            if _ping_pong(pipe):
                up = True
                break
            time.sleep(0.3)
        if not check("⑨ 테스트 데몬 기동", up):
            return
        _cp("⑨ create surface")
        r = EZERagentcall(pipe, "new-surface", timeout=15)
        ref = None
        for tok in (getattr(r, "stdout", "") or "").split():
            if tok.startswith("surface:"):
                ref = tok
                break
        if not check("⑨ surface 생성(PTY 자식·ref)", bool(ref),
                     "out=%r" % ((getattr(r, "stdout", "") or "")[:120])):
            return
        # 손자 스폰: 셸에 python3 one-liner 주입 — 자기 pid 를 마커에 기록 후 장시간 sleep(600s).
        #   EZERagentd 가 runtime PATH 를 주입하므로 python3.exe 는 PATH 로 해소된다(주입 우회 아님).
        py_prog = ("import os,time; open(r'%s','w').write(str(os.getpid())); time.sleep(600)" % marker)
        cmd = 'python3.exe -c "%s"' % py_prog.replace('"', '\\"')
        EZERagentcall(pipe, "send", "--surface", ref, cmd, timeout=15)
        EZERagentcall(pipe, "send-key", "--surface", ref, "Return", timeout=10)
        _cp("⑨ waiting grandchild self-report")
        for _ in range(40):  # ~20s
            _cp("⑨ waiting grandchild self-report")
            if os.path.exists(marker):
                try:
                    gpid = int(open(marker).read().strip())
                except Exception:
                    gpid = None
                if gpid:
                    break
            time.sleep(0.5)
        if not check("⑨ 손자 프로세스 스폰(self-report pid)", bool(gpid), "marker=%s" % marker):
            return
        check("⑨ 손자 생존(kill 전)", _alive_pid(gpid), "gpid=%s" % gpid)
        # ★EZERagentd 만 /F kill(자식 트리 /T 아님) → Job KILL_ON_JOB_CLOSE 로만 손자가 죽어야 한다.
        _cp("⑨ taskkill EZERagentd (no /T)")
        subprocess.run(["taskkill", "/PID", str(tracked.pid), "/F"], capture_output=True, timeout=10)
        dead = False
        for _ in range(30):  # ~15s
            _cp("⑨ waiting grandchild co-death")
            if not _alive_pid(gpid):
                dead = True
                break
            time.sleep(0.5)
        check("⑨ EZERagentd 사후 손자 동반사망(Job KILL_ON_JOB_CLOSE 트리 전파·P2-9 봉인)", dead,
              "gpid=%s alive=%s" % (gpid, _alive_pid(gpid)))
    finally:
        _cp("⑨ teardown")
        try:
            if gpid and _alive_pid(gpid):
                subprocess.run(["taskkill", "/PID", str(gpid), "/F"], capture_output=True, timeout=8)
        except Exception:
            pass
        teardown_daemon(pipe, state_dir=sd, tracked=tracked)


def case8_real_autorestore():
    """★D4(W5) 실경로 auto-restore(주입 우회 금지): 설치된 EZERagentd.exe 를 콜드부트해 EZERagentd **자체**
    decide_auto_restore(동봉 python3.exe 절대경로 + PATH 선두주입 + exe옆 EZERagent.exe)로 phoenix 를 스폰하는지
    관측한다. env 에서 PHOENIX_EZERAGENT 를 명시 제거해 '주입 없이' 실경로가 살아있음을 증명(P0-7·P1-9 첫 스폰 단절
    회귀 차단). 관측: state_dir/phoenix-restore.log 에 헤더 + [phoenix] 출력이 남으면 실경로 성공(FileNotFoundError/
    빈 로그면 실패). ★기존 케이스⑤는 phoenix 를 PHOENIX_EZERAGENT 주입해 직접 실행 → EZERagentd auto-restore 실경로 미검증이었다."""
    _cp("⑧ real auto-restore setup")
    import shutil
    pipe = r"\\.\pipe\EZERagent-phxsmoke-realauto"
    sd = _state_dir(pipe)
    tracked = None
    try:
        shutil.rmtree(sd, ignore_errors=True)
        # desired 로스터에 죽은 역할 seed(auto-restore 대상 존재) — phoenix_home = state_dir/phoenix.
        ph_home = os.path.join(sd, "phoenix")
        os.makedirs(ph_home, exist_ok=True)
        with open(os.path.join(ph_home, "desired_roster.json"), "w", encoding="utf-8") as f:
            json.dump({"roster": {"worker": {"role": "worker"}}, "tombstones": []}, f)
        # ★주입 금지: EZERagentd env 에서 PHOENIX_EZERAGENT 제거 — EZERagentd 자체 해석만으로 phoenix 를 스폰해야 한다.
        env = _phoenix_env({"EZERAGENT_SOCKET": pipe})
        env.pop("PHOENIX_EZERAGENT", None)
        # ★진단(CI 28780215417: auto-restore 스레드 std/time.rs panic — 라인:컬럼·메시지·프레임 필요): RUST_BACKTRACE
        #   로 panic 백트레이스를 켠다 — '<unnamed>' 스레드가 auto-restore 인지 다른 부트 스레드(scheduler/watchdog/
        #   usage)인지 프레임으로 교차확정하고, 근본 time 연산(파일:라인)을 특정한다.
        env["RUST_BACKTRACE"] = "1"
        CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0
        # ★진단(CI 28778120380 head=''): EZERagentd stderr 를 파일로 포착한다 — resolve_phoenix_source ABORT·자동복원
        #   skip·디스크폴백 거부·스레드 panic 백트레이스는 EZERagentd stderr 로만 드러나는데 과거 DEVNULL 이라 불가시였다.
        EZERagentd_err_path = os.path.join(sd, "EZERagentd.stderr.log")
        EZERagentd_err = open(EZERagentd_err_path, "w", encoding="utf-8", errors="replace")
        tracked = subprocess.Popen([EZERAGENTD_BIN], env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=EZERagentd_err,
                                   creationflags=CREATE_NO_WINDOW)
        _cp("⑧ waiting cold-boot auto-restore log")
        log_path = os.path.join(sd, "phoenix-restore.log")
        # open_restore_log 는 primary 실패 시 %TEMP%\EZERagent-phoenix-restore.log 로 폴백한다 — 그 경로도 확인.
        temp_fallback = os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or ".",
                                     "EZERagent-phoenix-restore.log")
        content = ""
        for _ in range(120):  # ~60s(콜드부트 임베드추출+self-test+phoenix 관측 여유 상향)
            _cp("⑧ waiting cold-boot auto-restore log")
            if os.path.exists(log_path):
                content = open(log_path, encoding="utf-8", errors="replace").read()
                if "phoenix auto-restore @ epoch=" in content and "[phoenix]" in content:
                    break
            time.sleep(0.5)
        # 진단 수집: primary 비었으면 EZERagentd stderr·temp 폴백을 함께 노출(다음 판정에 원인 직결).
        try:
            EZERagentd_err.flush()
        except Exception:
            pass
        err_full = ""
        if os.path.exists(EZERagentd_err_path):
            err_full = open(EZERagentd_err_path, encoding="utf-8", errors="replace").read()
        tmp_tail = ""
        if os.path.exists(temp_fallback):
            tmp_tail = open(temp_fallback, encoding="utf-8", errors="replace").read()[-800:]
        # ★EZERagentd stderr **전문** 을 stdout(=CI 로그)으로 dump — tail 슬라이스가 panic 라인:컬럼·메시지·백트레이스를
        #   자르던 문제 해소(팀리드 지시: 최소 panic 라인+메시지+백트레이스 수십 줄). 판정 detail 은 tail 4000 유지.
        log("⑧ EZERagentd.stderr 전문 dump ↓↓↓ (%d bytes)" % len(err_full))
        for _ln in err_full.splitlines():
            log("  [EZERagentd.stderr] %s" % _ln)
        log("⑧ EZERagentd.stderr 전문 dump ↑↑↑")
        err_tail = err_full[-4000:]
        diag = "head=%r | temp_fallback=%r | EZERagentd.stderr(tail4000)=%r" % (content[:120], tmp_tail, err_tail)
        check("⑧ 실경로 auto-restore 로그 생성(EZERagentd 자체 스폰)",
              "phoenix auto-restore @ epoch=" in content, diag)
        check("⑧ phoenix 실제 실행(주입 없이 python+EZERagent 해석 성공·[phoenix] 출력)",
              "[phoenix]" in content, "tail=%r" % content[-300:])
        # ★첫 스폰 단절/스레드 즉사 흔적 없음: content + EZERagentd stderr 전문(ABORTED/FileNotFoundError/panic).
        _spawn_ok = (("FileNotFoundError" not in content) and ("실행 불가" not in content)
                     and ("ABORTED" not in err_full) and ("FileNotFoundError" not in err_full)
                     and ("panicked" not in err_full))
        check("⑧ 첫 스폰 단절/스레드 즉사 흔적 없음(FileNotFoundError/실행 불가/ABORTED/panic 아님)", _spawn_ok,
              "err_tail=%r" % err_tail)
        try:
            EZERagentd_err.close()
        except Exception:
            pass
    finally:
        _cp("⑧ teardown")
        teardown_daemon(pipe, state_dir=sd, tracked=tracked)


def resolve_bins():
    import shutil
    EZERagent = os.environ.get("PHOENIX_EZERAGENT") or shutil.which("EZERagent") or shutil.which("EZERagent.exe")
    EZERagentd = os.environ.get("PHOENIX_EZERAGENTD")
    if not EZERagentd and EZERagent:
        cand = os.path.join(os.path.dirname(EZERagent), "EZERagentd.exe")
        EZERagentd = cand if os.path.exists(cand) else (shutil.which("EZERagentd") or shutil.which("EZERagentd.exe"))
    return EZERagent, EZERagentd


def run():
    global _PH, EZERAGENT_BIN, EZERAGENTD_BIN
    if not IS_WIN:
        log("이 스모크는 Windows 전용입니다 — mac/Unix 에서는 skip(정직). 실측은 windows-latest CI 러너.")
        log("(mac 무회귀·Windows 분기 단위검증은 phoenix-p12-deploy/p9-ci 및 별도 단위검증으로 수행)")
        print(json.dumps({"win_smoke": "SKIP(non-windows)", "platform": os.name, "skipped": True},
                         ensure_ascii=False, indent=2))
        return 0

    spec = importlib.util.spec_from_file_location("EZERagent_phoenix", PHOENIX)
    _PH = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_PH)

    EZERAGENT_BIN, EZERAGENTD_BIN = resolve_bins()
    log("EZERagent=%s EZERagentd=%s" % (EZERAGENT_BIN, EZERAGENTD_BIN))
    if not EZERAGENT_BIN or not EZERAGENTD_BIN:
        check("바이너리 해소(EZERagent·EZERagentd)", False, "EZERagent=%s EZERagentd=%s" % (EZERAGENT_BIN, EZERAGENTD_BIN))
        print(json.dumps({"win_smoke": "FAIL", "failed": _FAILS, "results": _RESULTS}, ensure_ascii=False, indent=2))
        return 1
    _PH.EZERAGENT = EZERAGENT_BIN

    for fn in (case1_path_mapping, case2_schtasks, case3_restart_primitive,
               case4_snapshot_runbook, case5_stub_restore, case6_deploy_plan,
               case7_keepalive_respawn, case8_real_autorestore, case9_job_kill_on_close):
        try:
            fn()
        except Exception as e:
            check("%s 예외" % fn.__name__, False, repr(e))
    _wd_stop()

    ok = not _FAILS
    print(json.dumps({"win_smoke": "PASS" if ok else "FAIL", "failed": _FAILS,
                      "results": _RESULTS, "win_smoke_pass": ok}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
