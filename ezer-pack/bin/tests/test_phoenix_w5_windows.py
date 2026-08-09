#!/usr/bin/env python3
"""W5 축D Windows 격납 — 플랫폼 무관 로직 게이트(리포 커밋). Windows Job Object kill-on-close 실거동·msvcrt
이중스폰 차단 실거동·CI 실 ezerd.exe 부활은 **Windows 러너에서만 검증 가능**(설계 D4/E1) — 이 파일은 mac/Linux
에서도 돌릴 수 있는 계약(_try_lock_nb 상호배제·lease 통합·open 모드)만 결정론 검증한다. Windows 런타임 게이트는
.github/workflows(windows-build.yml T5 real-path)·decide_auto_restore Rust 단위테스트가 담당.

실행: python3 ezer-pack/bin/tests/test_phoenix_w5_windows.py  (0=전건 PASS)
"""
import importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.normpath(os.path.join(HERE, "..", "ezer_phoenix.py"))
spec = importlib.util.spec_from_file_location("ezer_phoenix", PH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

_results = []
def check(name, cond, detail=""):
    _results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def main():
    td = tempfile.mkdtemp(prefix="phoenix-w5-")

    # ── D2 통합 락 헬퍼 _try_lock_nb: 상호배제 계약(unix flock·Windows msvcrt 공통) ──
    #   같은 파일을 두 핸들로 열어 첫 핸들이 락을 잡으면 둘째는 False(경합)여야 한다. 해제(close) 후 재획득 True.
    lockp = os.path.join(td, "x.lock")
    f1 = open(lockp, "a+")
    r1 = m._try_lock_nb(f1)
    check("D2 _try_lock_nb 최초 획득 → True", r1 is True, "r1=%s" % r1)
    f2 = open(lockp, "a+")
    r2 = m._try_lock_nb(f2)
    check("D2 _try_lock_nb 보유 중 둘째 → False(상호배제)", r2 is False, "r2=%s" % r2)
    f2.close()
    f1.close()
    f3 = open(lockp, "a+")
    r3 = m._try_lock_nb(f3)
    check("D2 _try_lock_nb 해제(close) 후 재획득 → True", r3 is True, "r3=%s" % r3)
    f3.close()

    # ── D2 restore lease: 통합 헬퍼 경유 이중 스폰 차단(보유 중 재획득 실패) ──
    home = os.path.join(td, "state", "phoenix")
    os.makedirs(home, exist_ok=True)
    sock = os.path.join(td, "state", "ezer.sock")
    m.EZER = os.path.join(td, "nonexistent-ezer")
    ok1, h1 = m._acquire_restore_lease(sock)
    check("D2 restore lease 최초 획득", ok1 is True and h1 is not None, "ok=%s" % ok1)
    ok2, h2 = m._acquire_restore_lease(sock)
    check("D2 restore lease 보유 중 재획득 → False(이중 스폰 차단·Windows fail-open 제거)",
          ok2 is False, "ok2=%s" % ok2)
    m._release_lease(h1)
    ok3, h3 = m._acquire_restore_lease(sock)
    check("D2 restore lease 해제 후 재획득 → True", ok3 is True, "ok3=%s" % ok3)
    m._release_lease(h3)

    # ── D2 roster/dept 락: 통합 헬퍼 경유(P1-8 Windows fail-open 제거) ──
    hl = m._acquire_roster_lock(sock, "roster")
    check("D2 roster lock 획득(핸들 반환)", hl is not None)
    # 보유 중 외부 핸들 획득 실패(상호배제)
    ext = open(os.path.join(home, "roster.lock"), "a+")
    check("D2 roster lock 보유 중 외부 → False", m._try_lock_nb(ext) is False)
    ext.close()
    m._release_lease(hl)

    # ── open 모드 계약: lease/lock 파일은 truncate 금지(a+)여야 Windows msvcrt byte0 영역이 일치한다 ──
    #   (회귀 핀: 과거 "w" 는 truncate 로 동시 open 시 msvcrt 영역/락이 어긋날 수 있었다 — 소스 문자열 검증.)
    src = open(PH, encoding="utf-8").read()
    check("D2 restore.lease open 모드 a+(무truncate)", 'open(lease_path, "a+")' in src)
    check("D2 roster/dept lock open 모드 a+(무truncate)", 'open(p, "a+")' in src)
    check("D2 _try_lock_nb 에 msvcrt.locking(LK_NBLCK) 배선", "msvcrt.locking" in src and "LK_NBLCK" in src)

    import shutil
    shutil.rmtree(td, ignore_errors=True)
    npass = sum(1 for c in _results if c)
    print("\n=== %d/%d PASS ===" % (npass, len(_results)))
    return 0 if npass == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
