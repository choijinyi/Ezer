#!/usr/bin/env python3
"""W6 수용 게이트 7시나리오 하네스 골격(리포 커밋). 데몬 불요(더미 EZER 로 ezer() rc127 정직 강등) —
파일 기반 상태로 각 시나리오의 phoenix 판정을 결정론 실측한다. 현 웨이브에서 검증 가능한 것은 실 단언,
다른 웨이브(W2 topology 전복원·W5 Windows 고아) 소관은 '골격+관측'으로 구조만 세우고 TODO 를 남긴다.

실행: python3 ezer-pack/bin/tests/test_phoenix_w6_scenarios.py  (0=전건 PASS)
"""
import importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.normpath(os.path.join(HERE, "..", "ezer_phoenix.py"))
spec = importlib.util.spec_from_file_location("ezer_phoenix", PH)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

_results = []
def check(n, c, d=""):
    _results.append(c); print(("PASS " if c else "FAIL ") + n + (" | " + d if d else ""))


def _sock(td, name):
    d = os.path.join(td, name)
    os.makedirs(os.path.join(d, "phoenix"), exist_ok=True)
    return os.path.join(d, "ezer.sock")


def main():
    td = tempfile.mkdtemp(prefix="phoenix-w6-")
    m.EZER = os.path.join(td, "nonexistent-ezer")  # ezer() → rc127 정직 강등(데몬 무접촉)

    # ── S1: corrupt topology → run_restore 무크래시(graceful). 전복원(tombstones_rev 가드)은 W2. ──
    s1 = _sock(td, "s1_topo")
    with open(os.path.join(td, "s1_topo", "topology.json"), "w") as f:
        f.write("{ corrupt topology ]]]")
    try:
        res = m.run_restore(s1, ticket="s1", stub=True, print_result=False)
        graceful = isinstance(res, dict) and res.get("phoenix_restore") in ("NOOP", "VERIFIED", "UNVERIFIED", "FAILED", "CORRUPT")
    except Exception as e:
        graceful = False; res = {"err": str(e)}
    check("S1 corrupt topology → 무크래시 graceful(전복원=W2 TODO)", graceful, str(res.get("phoenix_restore")))

    # ── S2: corrupt desired → CORRUPT·exit 6(C2 sentinel) ──
    s2 = _sock(td, "s2_des")
    with open(os.path.join(td, "s2_des", "phoenix", "desired_roster.json"), "w") as f:
        f.write("]]] corrupt desired")
    res = m.run_restore(s2, ticket="s2", stub=True, print_result=False)
    check("S2 corrupt desired → exit 6(silent-empty 차단)",
          m.restore_exit_code(res) == 6 and res.get("phoenix_restore") == "CORRUPT")

    # ── S3: corrupt breaker → reset(무크래시·잘못 OPEN 안 함) ──
    s3 = _sock(td, "s3_brk")
    with open(os.path.join(td, "s3_brk", "phoenix", "breaker.json"), "w") as f:
        f.write("]]] corrupt breaker")
    # 손상 breaker 로 시도 기록 → 예외 없이 (open, attempts) 반환, attempts 는 이번 1회만(리셋된 창).
    try:
        opened, attempts = m.breaker_check_and_record(s3)
        ok = (not opened) and len(attempts) == 1  # 손상=빈 창으로 리셋 후 이번 1회
    except Exception as e:
        ok = False; attempts = str(e)
    check("S3 corrupt breaker → 리셋(무크래시·오OPEN 없음)", ok, "attempts=%s" % attempts)

    # ── S4: no-target roles → NOOP(exit 0) ──
    s4 = _sock(td, "s4_noop")
    res = m.run_restore(s4, ticket="s4", stub=True, print_result=False)
    check("S4 no-target → NOOP exit0", res.get("phoenix_restore") == "NOOP" and m.restore_exit_code(res) == 0)

    # ── S5: fresh live(전 상태파일 부재) → NOOP 정상 부팅 ──
    s5 = _sock(td, "s5_fresh")  # phoenix/ 만 만들고 상태파일 전무
    res = m.run_restore(s5, ticket="s5", stub=True, print_result=False)
    check("S5 fresh-install → NOOP exit0", res.get("phoenix_restore") == "NOOP" and m.restore_exit_code(res) == 0)

    # ── S6: Windows 고아(Job Object) → W5 소관. 비-Windows 에선 골격 skip. ──
    if os.name == "nt":
        check("S6 win 고아 → (W5 실기 검증 자리)", True, "Windows 실기는 W5")
    else:
        check("S6 win 고아 골격(비-Windows skip·W5 소관)", True, "skip(non-Windows) — W5 Job Object E2E")

    # ── S7: deploy 중첩 lease → 보유 중이면 LEASE_HELD(이중 스폰 차단) ──
    s7 = _sock(td, "s7_lease")
    ok7 = True
    try:
        import fcntl
        lease_path = os.path.join(td, "s7_lease", "phoenix", "restore.lease")
        held = open(lease_path, "w")
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # 다른 restore 가 보유 중 모사
        res = m.run_restore(s7, ticket="s7", stub=True, print_result=False)
        ok7 = res.get("phoenix_restore") == "LEASE_HELD"
        fcntl.flock(held.fileno(), fcntl.LOCK_UN); held.close()
        det = res.get("phoenix_restore")
    except ImportError:
        det = "fcntl 부재(비-unix) — 골격 skip"
    check("S7 deploy 중첩 lease → LEASE_HELD(이중 스폰 차단)", ok7, det)

    import shutil
    shutil.rmtree(td, ignore_errors=True)
    npass = sum(1 for c in _results if c)
    print("\n=== %d/%d PASS ===" % (npass, len(_results)))
    return 0 if npass == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
