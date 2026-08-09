#!/usr/bin/env python3
"""W4 C2 sentinel 테스트(리포 커밋) — missing≠corrupt 구분 + corrupt desired 부활 차단 + fresh-install NOOP.
데몬 불요: EZERAGENT 를 더미로 두면 EZERagent() 가 rc127 로 정직 강등되어 전 EZERagent 호출이 빈 결과 → 파일 기반 sentinel 만 작동.

실행: python3 EZERagent-pack/bin/tests/test_phoenix_c2_sentinel.py  (0=전건 PASS)
"""
import importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.normpath(os.path.join(HERE, "..", "EZERagent_phoenix.py"))
spec = importlib.util.spec_from_file_location("EZERagent_phoenix", PH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

_results = []
def check(name, cond, detail=""):
    _results.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def main():
    # ── A. _roster_file_status 3분류(순수) ──
    td = tempfile.mkdtemp(prefix="phoenix-c2-")
    missing = os.path.join(td, "nope.json")
    valid = os.path.join(td, "valid.json")
    corrupt = os.path.join(td, "corrupt.json")
    with open(valid, "w") as f:
        json.dump({"roster": {}, "tombstones": []}, f)
    with open(corrupt, "w") as f:
        f.write("{ this is not json ]]]")
    check("A missing → 'missing'", m._roster_file_status(missing) == "missing")
    check("A valid → 'valid'", m._roster_file_status(valid) == "valid")
    check("A corrupt → 'corrupt'(≠missing)", m._roster_file_status(corrupt) == "corrupt",
          m._roster_file_status(corrupt))

    # 더미 EZERAGENT — EZERagent() 가 rc127 로 정직 강등(데몬 무접촉).
    m.EZERAGENT = os.path.join(td, "nonexistent-EZERagent")

    # ── B. fresh-install(전 상태파일 부재) → 정상 NOOP(exit 0) ──
    sd_fresh = os.path.join(td, "fresh")
    os.makedirs(sd_fresh, exist_ok=True)
    sock_fresh = os.path.join(sd_fresh, "EZERagent.sock")  # 파일 미생성 — state_dir=sd_fresh(비 LIVE)
    res = m.run_restore(sock_fresh, ticket="fresh", stub=True, print_result=False)
    check("B fresh-install → NOOP", res.get("phoenix_restore") == "NOOP",
          "verdict=%s" % res.get("phoenix_restore"))
    check("B fresh-install exit=0", m.restore_exit_code(res) == 0, "exit=%s" % m.restore_exit_code(res))

    # ── C. corrupt desired → 부활 차단(CORRUPT·exit 6), silent-empty 통과 금지 ──
    sd_c = os.path.join(td, "corruptcase")
    ph_home = os.path.join(sd_c, "phoenix")
    os.makedirs(ph_home, exist_ok=True)
    with open(os.path.join(ph_home, "desired_roster.json"), "w") as f:
        f.write("{ CORRUPTED desired ]]] not json")
    sock_c = os.path.join(sd_c, "EZERagent.sock")
    res = m.run_restore(sock_c, ticket="corrupt", stub=True, print_result=False)
    check("C corrupt desired → CORRUPT", res.get("phoenix_restore") == "CORRUPT",
          "verdict=%s" % res.get("phoenix_restore"))
    check("C corrupt → corruption=True", res.get("corruption") is True)
    check("C corrupt → exit 6", m.restore_exit_code(res) == 6, "exit=%s" % m.restore_exit_code(res))
    check("C corrupt_file 명시", res.get("corrupt_file") == "desired_roster", res.get("corrupt_file"))

    # ── D. corrupt dept_roster 도 차단 ──
    sd_d = os.path.join(td, "deptcase")
    ph_home_d = os.path.join(sd_d, "phoenix")
    os.makedirs(ph_home_d, exist_ok=True)
    with open(os.path.join(ph_home_d, "dept_roster.json"), "w") as f:
        f.write("]]] corrupt dept")
    sock_d = os.path.join(sd_d, "EZERagent.sock")
    res = m.run_restore(sock_d, ticket="dept", stub=True, print_result=False)
    # ★W3 진화: dept_roster 는 glob(EZERagent-dept-*)∪registry 로 재발견 가능하므로 corrupt 를 hard-fail(exit 6)이 아니라
    #   격리+discovery 복원→degraded(exit 3)로 다룬다(폴백 체인). silent-empty 통과는 여전히 차단(fresh 로 진행 안 함)
    #   — 다른 exit/event(DEGRADED·escalation)로 구분됨. 상세 시나리오는 test_phoenix_w3_corruption.py.
    check("D corrupt dept_roster → DEGRADED(exit 3·W3 폴백 복원)",
          m.restore_exit_code(res) == 3 and res.get("phoenix_restore") == "DEGRADED",
          "verdict=%s exit=%s" % (res.get("phoenix_restore"), m.restore_exit_code(res)))
    check("D corrupt dept_roster → degraded 에 dept_roster 명시(silent-empty 아님)",
          any(d.get("file") == "dept_roster" for d in (res.get("degraded") or [])),
          "degraded=%s" % res.get("degraded"))

    import shutil
    shutil.rmtree(td, ignore_errors=True)
    npass = sum(1 for c in _results if c)
    print("\n=== %d/%d PASS ===" % (npass, len(_results)))
    return 0 if npass == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
