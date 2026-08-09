#!/usr/bin/env python3
"""W6/E2 정기화 배선 검증(리포 커밋). ★B2-1(W3) 진화: phoenix 세대 스냅샷 6h + 주간 격리 드릴 잡은
이제 팩 schedule.json 배달이 아니라 **ezerd 코드(schedule.rs builtin_jobs)** 가 소유하고 데몬 부트 시
idempotent ensure 한다 — schedule.json 이 user-owned 로 전환돼(사용자 `ezer schedule add` 잡 보존) 팩
강제갱신이 사용자 잡을 소실시키지 않게 하기 위함. 따라서 이 테스트는 ①팩 schedule.json 에는 phoenix
잡이 **부재**(코드로 이전) ②schedule.rs 에 두 built-in 잡이 올바른 주기·명령으로 정의 ③main.rs 부트가
ensure_builtin_jobs 를 호출하는지 확인한다. Job 스키마 내용 정합(주기·명령·중복0)은 Rust 테스트
schedule::tests::builtin_jobs_ensure_idempotent_and_versioned 가 담당(typed 검증).

실행: python3 ezer-pack/bin/tests/test_phoenix_e2_schedule.py  (0=전건 PASS)
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCHED = os.path.normpath(os.path.join(HERE, "..", "..", "schedule.json"))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SCHED_RS = os.path.join(ROOT, "src", "bin", "ezerd", "schedule.rs")
MAIN_RS = os.path.join(ROOT, "src", "bin", "ezerd", "main.rs")

_results = []
def check(n, c, d=""):
    _results.append(c); print(("PASS " if c else "FAIL ") + n + (" | " + d if d else ""))


def main():
    # ① 팩 schedule.json 에는 phoenix built-in 잡이 부재해야 한다(코드로 이전 — B2-1). 사용자/하트비트 잡은 잔존.
    d = json.load(open(SCHED))
    pack_ids = {j["id"] for j in d.get("jobs", [])}
    check("① 팩 schedule.json 에 phoenix-snapshot-6h 부재(코드 이전)", "phoenix-snapshot-6h" not in pack_ids)
    check("① 팩 schedule.json 에 phoenix-drill-weekly 부재(코드 이전)", "phoenix-drill-weekly" not in pack_ids)
    check("① 하트비트 잡은 잔존(팩 배달 유지)", "owner-progress-report-5min" in pack_ids, str(sorted(pack_ids)))

    # ② schedule.rs builtin_jobs 가 두 잡을 올바른 주기·명령으로 정의.
    rs = open(SCHED_RS, encoding="utf-8").read()
    check("② schedule.rs builtin_jobs 정의 존재", "fn builtin_jobs()" in rs and "fn ensure_builtin_jobs()" in rs)
    check("② phoenix-snapshot-6h 정의(6h·snapshot)",
          bool(re.search(r'"id":\s*"phoenix-snapshot-6h"', rs))
          and bool(re.search(r'"every_minutes":\s*360', rs))
          and "ezer_state_snapshot.py" in rs
          and "snapshot 2>&1" in rs)
    check("② phoenix-drill-weekly 정의(7일·self-test)",
          bool(re.search(r'"id":\s*"phoenix-drill-weekly"', rs))
          and bool(re.search(r'"every_minutes":\s*10080', rs))
          and "self-test" in rs)
    check("② built-in 버전 마커(idempotent ensure 기준)", "_builtin_version" in rs and "BUILTIN_JOBS_VERSION" in rs)

    # ③ 데몬 부트가 ensure_builtin_jobs 를 스케줄러 기동 전에 호출.
    mn = open(MAIN_RS, encoding="utf-8").read()
    check("③ main.rs 부트가 ensure_builtin_jobs 호출", "schedule::ensure_builtin_jobs()" in mn)
    check("③ ensure 가 spawn_scheduler 보다 먼저",
          mn.find("ensure_builtin_jobs") < mn.find("spawn_scheduler") if "ensure_builtin_jobs" in mn else False)

    npass = sum(1 for c in _results if c)
    print("\n=== %d/%d PASS ===" % (npass, len(_results)))
    return 0 if npass == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
