#!/usr/bin/env python3
"""EZERagent_bootstrap.py — master 부트 시퀀스의 결정론 격상 (BOOTSTRAP_HARDENING WP-1).

"에제르시작"(마스터 선언) 이후의 기계적 절차 전부를 단일 exit-code 체인으로 수행한다.
LLM(master)의 역할은 이 스크립트 실행·출력 인용·이후 지휘뿐이다 — 산문 단계 수행 금지.

단계 체인 (실패 시 즉시 중단·단계명+원인을 stderr와 boot-last.json에 기록):
  ① preflight --fix READY        ② EZERagent ping                ③ EZERagent claim-role master
  ④ EZERagent boot                     ⑤ orchestra check (bounded retry 3s×10 — 노드 스폰은
  비동기·check는 무대기 스냅샷이므로 레이스 봉쇄)          ⑥ 완료 마커 write
  ⑦ EZERagent-dept promote-if-pending --request-only (비대기 — 부트와 승격 동의의 분리)
  ⑧ 기계 요약 JSON 출력 (master는 이것을 인용해 보고한다)

완료 마커 ~/.EZERagent/.master-bootstrapped 는 base 데몬 전용 단일-writer 마커다:
  - writer = 이 스크립트의 성공 경로(⑤ exit 0 후 ⑥) 유일. 삭제 주체 없음(버전 필드로 stale 판정).
  - ★소켓 격리: EZERAGENT_SOCKET이 base가 아니면(부서 pane 부트) write하지 않는다 — 부서장 부트가
    base 마커를 오염시키면 CEO 승격 게이트(EZERagent-dept)가 오개방된다.

exit: 0=부트 완료 / 2=preflight / 3=ping / 7=claim 거부(이 surface는 master 아님 — 지휘 중단·인계)
      4=boot / 6=check 최종 실패 / 5=assert-ready 게이트 실패(하위 게이트 전용)
안전밸브: EZERAGENT_BOOT_GATE=warn(assert-ready 실패를 경고로 강등)|off(게이트 무력).
"""
import json
import os
import subprocess
import sys
import tempfile
import time

# ★R3(D-IMPL-3): Windows 파이프 환경(cp949/cp1252)에서 한글 출력 UnicodeEncodeError 크래시 방어 —
# PYTHONUTF8 export는 EZERagent-dept 경로에만 있어 이 스크립트의 직접 실행을 보호하지 못한다.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = os.path.expanduser("~")
EZERAGENT_DIR = os.path.join(HOME, ".EZERagent")
PACK = os.environ.get("EZERAGENT_PACK_DIR") or os.path.join(EZERAGENT_DIR, "pack")
MARKER = os.path.join(EZERAGENT_DIR, ".master-bootstrapped")
STATE_DIR = os.path.join(EZERAGENT_DIR, "state")
BOOT_LAST = os.path.join(STATE_DIR, "boot-last.json")
# ⑤ bounded retry — 무한 대기 금지(자원 거버넌스). env 오버라이드는 테스트 하네스 전용.
CHECK_RETRIES = max(1, int(os.environ.get("EZERAGENT_BOOT_CHECK_RETRIES", "10")))
CHECK_INTERVAL_S = float(os.environ.get("EZERAGENT_BOOT_CHECK_INTERVAL_S", "3"))  # 총 상한 ≈ 30초


def _atomic_write_json(path, obj):
    """CRLF 함정 회피(newline='\\n')·원자 교체 — Windows 재직렬화 원복 교훈."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-boot-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _progress(msg):
    """★R12: 단계 시작 신호(stderr 1줄) — 진행 중 무출력이면 최악 수 분의 침묵 창이 생겨
    관찰자(초보·master)가 '멈춤'으로 오인한다(실사고 증상②의 형태적 재생산 방지).
    기계 계약(exit code·⑧ JSON)과 별개의 인간 관찰자용 인터페이스."""
    sys.stderr.write("[bootstrap] %s\n" % msg)
    try:
        sys.stderr.flush()
    except Exception:
        pass


def _run(cmd, timeout=120):
    """서브프로세스 실행 — (exit, stdout+stderr 병합 텍스트). shell 미사용(경로 quoting 안전)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return 127, "명령 없음: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "timeout(%ss): %s" % (timeout, " ".join(cmd))


def _is_base_socket():
    """base 데몬 컨텍스트 판정(§4.1 소켓 격리). EZERAGENT_SOCKET 미설정=base.
    설정 시 basename이 'EZERagent'(win pipe) 또는 'EZERagent.sock'(unix 기본)일 때만 base —
    부서 소켓(EZERagent-dept-<name>[.sock])·커스텀 소켓은 전부 비-base(보수 판정: 오염 차단 우선)."""
    sock = os.environ.get("EZERAGENT_SOCKET", "").strip()
    if not sock:
        return True
    base = os.path.basename(sock.replace("\\", "/"))
    return base in ("EZERagent", "EZERagent.sock")


def _pack_version():
    v = None
    for cand in (os.path.join(EZERAGENT_DIR, ".pack-version"), os.path.join(PACK, ".pack-version")):
        try:
            with open(cand, encoding="utf-8") as f:
                v = f.read().strip() or None
            if v:
                break
        except OSError:
            continue
    return v or "unknown"


def _binary_version():
    code, out = _run(["EZERagent", "--version"], timeout=10)
    return out.strip().splitlines()[0] if code == 0 and out.strip() else "unknown"


class _Log:
    """단계 결과를 boot-last.json에 누적(진단 가시성 — 각 retry 시도 포함)."""

    def __init__(self):
        self.data = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": [],
                     "socket": os.environ.get("EZERAGENT_SOCKET", ""), "base_socket": _is_base_socket()}

    def step(self, name, code, detail=""):
        self.data["steps"].append({"step": name, "exit": code,
                                   "detail": detail.strip()[-2000:]})
        _atomic_write_json(BOOT_LAST, self.data)

    def fail(self, name, code, detail, exit_code):
        self.step(name, code, detail)
        self.data["result"] = {"ok": False, "failed_step": name, "exit": exit_code}
        _atomic_write_json(BOOT_LAST, self.data)
        sys.stderr.write("[bootstrap] 단계 실패: %s (exit %d)\n%s\n" % (name, code, detail.strip()))
        return exit_code


def cmd_run():
    log = _Log()
    py = sys.executable or "python3"

    # ★TCC 보조 경고(오너 2026-07-15): macOS 폴더 권한 리셋(서명 변경 업그레이드) 시 pane 자식이
    # EPERM으로 죽는 실사고 — 부트가 살아있는 세션에서라도 조기 경고(주 안내는 GUI perm-warning).
    if sys.platform == "darwin":
        try:
            os.listdir(os.path.join(HOME, "Desktop"))
        except PermissionError:
            _progress("⚠ macOS 데스크탑 폴더 접근 거부 — 시스템 설정→개인정보 보호 및 보안→"
                      "파일 및 폴더에서 EZERagent 허용 후 앱 재시작(미허용 시 pane의 claude가 EPERM으로 꺼짐)")
        except OSError:
            pass

    # ① preflight --fix — READY 판정은 preflight exit code가 사실(자연어 재추론 금지)
    preflight = os.path.join(PACK, "bin", "EZERagent_preflight.py")
    if os.path.isfile(preflight):
        _progress("① preflight --fix 실행 중(최대 300s)…")
        code, out = _run([py, preflight, "--fix"], timeout=300)
        log.step("①preflight", code, out)
        if code != 0:
            return log.fail("①preflight", code, out, 2)
    else:
        log.step("①preflight", 0, "preflight 부재 — 생략(팩 불완전 가능·계속)")

    # ② 데몬 생존 — 이후 ③의 비정상 exit를 '거부'로 해석하는 전제(데몬 생존 보증)
    _progress("② 데몬 생존 확인…")
    code, out = _run(["EZERagent", "ping"], timeout=15)
    log.step("②ping", code, out)
    if code != 0:
        return log.fail("②ping", code, out, 3)

    # ③ claim-role master — 거부=exit 7(유령 master 차단: 이 surface는 master가 아니다)
    _progress("③ master 역할 등록…")
    code, out = _run(["EZERagent", "claim-role", "master"], timeout=15)
    log.step("③claim-role", code, out)
    if code != 0:
        msg = ("이 surface는 master가 아님(claim 거부). 살아있는 master가 레지스트리에 존재한다 — "
               "선언을 중단하고 기존 master에 인계하라.\n%s" % out)
        return log.fail("③claim-role", code, msg, 7)

    # ④ 4종 의무 노드 기동
    _progress("④ 4종 의무 노드 기동 중(최대 300s)…")
    code, out = _run(["EZERagent", "boot"], timeout=300)
    log.step("④boot", code, out)
    if code != 0:
        return log.fail("④boot", code, out, 4)

    orchestra = os.path.join(PACK, "bin", "EZERagent_orchestra.py")

    # ④-b 리뷰어 감지·무구독 폴백(R1·D-IMPL-1 — 산문 §0 ④-b의 코드 전사): EZERagent boot는 미설치
    # CLI를 건너뛰므로 agy/codex 부재 기계(초보 전원)에서 대체 리뷰어(reviewer-claude-*)를 기동할
    # 주체가 없으면 ⑤ check가 영영 실패한다. 실패=기록만(best-effort) — 최종 게이트는 ⑤ check.
    _progress("④-b 리뷰어 감지·폴백 기동 중(최대 320s — 대체 리뷰어 2슬롯 순차)…")
    code, out = _run([py, orchestra, "boot-reviewers"], timeout=320)
    log.step("④b-boot-reviewers", code, out)

    # ⑤ orchestra check — bounded retry(노드 ready는 비동기·check는 스냅샷)
    _progress("⑤ 노드 생존 결정론 확인(check · 최대 %d회×%.0fs 재시도)…" % (CHECK_RETRIES, CHECK_INTERVAL_S))
    code, out = 1, "orchestra 부재"
    for attempt in range(1, CHECK_RETRIES + 1):
        code, out = _run([py, orchestra, "check"], timeout=60)
        log.step("⑤check#%d" % attempt, code, out)
        if code == 0:
            break
        if attempt < CHECK_RETRIES:
            time.sleep(CHECK_INTERVAL_S)
    if code != 0:
        return log.fail("⑤check", code,
                        "%d회 재시도 후에도 의무 노드 미기동:\n%s" % (CHECK_RETRIES, out), 6)

    # ⑥ 완료 마커 — ⑤ exit 0에서만 도달. base 소켓 가드(부서 부트는 base 마커 무접촉).
    if _is_base_socket():
        _atomic_write_json(MARKER, {
            "pack_version": _pack_version(), "binary_version": _binary_version(),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "surface_ref": os.environ.get("EZERAGENT_SURFACE_ID", ""),
            "socket": os.environ.get("EZERAGENT_SOCKET", ""), "orchestra_check": "exit 0"})
        log.step("⑥marker", 0, MARKER)
        marker_note = "base 마커 기록"
    else:
        log.step("⑥marker", 0, "부서 소켓 컨텍스트 — base 마커 무접촉(부서장 부트 완료)")
        marker_note = "부서장 부트 — base 마커 무접촉"

    # ⑦ 승격 pending 해소 요청(비대기) — 동의·실제 승격은 부트 밖(배지/feed·차기 lifecycle)
    if _is_base_socket():
        dept = os.path.join(PACK, "bin", "EZERagent-dept")
        if os.path.isfile(dept):
            code, out = _run(["bash", dept, "promote-if-pending", "--request-only"], timeout=30)
            log.step("⑦promote-request", code, out)  # best-effort — 실패해도 부트는 성공
        else:
            log.step("⑦promote-request", 0, "EZERagent-dept 부재 — 생략")
    else:
        log.step("⑦promote-request", 0, "부서 컨텍스트 — 생략")

    # ⑧ 기계 요약 — master는 이 JSON을 인용해 '기동 완료'를 보고한다(다른 근거 인용 금지)
    summary = {"ok": True, "marker": marker_note,
               "steps": [(s["step"], s["exit"]) for s in log.data["steps"]],
               "boot_last": BOOT_LAST}
    log.data["result"] = {"ok": True}
    _atomic_write_json(BOOT_LAST, log.data)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def cmd_status():
    print(json.dumps({"marker": _read_json(MARKER), "boot_last": _read_json(BOOT_LAST),
                      "base_socket": _is_base_socket()}, ensure_ascii=False, indent=1))
    return 0


def cmd_assert_ready():
    """하위 게이트 전용: 마커 부재/pack_version 불일치 → exit 5.
    stale 정책(설계 §4.1): assert-ready는 버전 대조(ceo_promote 게이트는 존재만 — EZERagent-dept 측)."""
    gate = os.environ.get("EZERAGENT_BOOT_GATE", "").strip().lower()
    if gate == "off":
        return 0
    m = _read_json(MARKER)
    ok = bool(m) and m.get("pack_version") == _pack_version()
    if ok:
        return 0
    why = "마커 부재" if not m else "pack_version 불일치(%s≠%s) — 재부트 필요" % (
        m.get("pack_version"), _pack_version())
    sys.stderr.write("[bootstrap assert-ready] %s\n" % why)
    return 0 if gate == "warn" else 5


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "run"
    return {"run": cmd_run, "status": cmd_status,
            "assert-ready": cmd_assert_ready}.get(cmd, cmd_run)()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
