#!/usr/bin/env python3
"""W6/E1 데몬 교체 시뮬레이션 E2E(리포 커밋·mac 게이트) — a07cc7f Not-tested 봉인.

격리 상태 디렉터리에서 실 EZERagentd 를 기동해 auto-restore(임베드 추출→phoenix restore --auto)가 데몬 자신의
소켓/상태를 타는지(W6 --socket enabler), 그리고 세 게이트 시나리오를 실측한다:
  ① no-target-roles → NOOP(fresh live)
  ② PHOENIX_STRICT_EZERAGENT=1 → Rust PHOENIX_EZERAGENT/PATH 주입으로 phoenix 해석 성공(폴백 아님·exit6 아님)
  ③ 재기동 후 seeded dead role → 부활 대상 타겟팅(kill→재기동→부활 경로 발화)

바이너리(EZERagentd/EZERagent)는 PHOENIX_HARNESS_EZERAGENTD·PATH 또는 <repo>/target/debug 에서 찾는다. 없으면 SKIP(exit 0) —
CI 는 빌드 후 실행(게이트), 로컬 무빌드 실행은 skip. 라이브 무접촉(guard_isolation·격리 소켓 전용).

실행: python3 EZERagent-pack/bin/tests/test_phoenix_e2e_replacement.py
"""
import importlib.util, os, sys, time, json, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))  # tests/../../.. = repo root
DBG = os.path.join(REPO, "target", "debug")


def _find(name):
    env = os.environ.get("PHOENIX_HARNESS_" + name.upper())
    if env and os.path.exists(env):
        return env
    cand = os.path.join(DBG, name)
    if os.path.exists(cand):
        return cand
    return shutil.which(name)


EZERAGENTD = _find("EZERagentd")
EZERAGENT = _find("EZERagent")
if not (EZERAGENTD and EZERAGENT):
    print("SKIP: EZERagentd/EZERagent 바이너리 미발견(빌드 필요) — CI 게이트는 빌드 후 실행. skip(exit 0).")
    sys.exit(0)

os.environ["PHOENIX_HARNESS_EZERAGENTD"] = EZERAGENTD
os.environ["PATH"] = DBG + ":" + os.environ.get("PATH", "")
os.environ["PHOENIX_EZERAGENT"] = EZERAGENT  # 하네스 self 대조용(EZERagentd 는 자체 주입)
os.environ["EZERAGENT_NO_AUTORESTORE"] = "0"  # ★E1 은 EZERagentd auto-restore 를 검증하므로 명시 활성화(하네스 기본=비활성)

HARNMOD = os.path.join(HERE, "..", "EZERagent_phoenix_harness.py")
spec = importlib.util.spec_from_file_location("h", HARNMOD)
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
h.EZERAGENT = EZERAGENT; h.EZERAGENTD = EZERAGENTD
h.guard_isolation()

LOG = os.path.join(h.HARN_DIR, "phoenix-restore.log")
results = []


def check(n, c, d=""):
    results.append(c); print(("PASS " if c else "FAIL ") + n + (" | " + d if d else ""))


def _wipe_state():
    h.teardown(verbose=False)  # 실행 중 데몬 밑에서 state 를 지우지 않게 먼저 kill
    shutil.rmtree(os.path.join(h.HARN_DIR, "phoenix"), ignore_errors=True)
    for f in ("topology.json", "desired_roster.json", "phoenix-restore.log"):
        try: os.remove(os.path.join(h.HARN_DIR, f))
        except OSError: pass
    # 이전 추출 잔재
    shutil.rmtree(os.path.join(h.HARN_DIR, "phoenix-embed"), ignore_errors=True)


def _boot_and_capture(wait=20.0, want="티켓="):
    """★교체 시뮬레이션: 기존 데몬 kill → 새 EZERagentd 기동(=교체) → auto-restore 가 phoenix-restore.log 에 판정을
    쓸 때까지 폴링(콜드부트 추출+python 기동 변동 흡수) → 로그 반환 후 teardown. teardown 선행이 없으면
    소켓 점유로 새 데몬이 안 뜨고 auto-restore 재발화가 없다(교체 관측 불가)."""
    h.teardown(verbose=False)  # 기존 데몬 kill = 교체의 'kill' 축
    h.start_daemon(wait=12.0)  # 새 데몬 = 교체의 '재기동' 축
    t0 = time.time()
    body = ""
    while time.time() - t0 < wait:
        time.sleep(0.5)
        if os.path.exists(LOG):
            body = open(LOG).read()
            if want in body:
                break
    h.teardown(verbose=False)
    return body


def main():
    h.teardown(verbose=False)
    h._fresh_harness()

    # ── ① no-target NOOP + --socket enabler(격리 dir 에 로그 생성) ──
    _wipe_state()
    body = _boot_and_capture()
    check("① 격리 phoenix-restore.log 생성(--socket enabler 작동)", os.path.exists(LOG) and len(body) > 0,
          "size=%d" % len(body))
    check("① no-target → NOOP(fresh live)", ("죽은 역할 0" in body) or ('"phoenix_restore": "NOOP"' in body),
          body.strip()[-100:].replace("\n", " "))

    # ── ② PHOENIX_STRICT_EZERAGENT=1 → Rust 주입으로 해석 성공(폴백 차단인데도 phoenix 가 돎·exit6/FATAL 없음) ──
    _wipe_state()
    os.environ["PHOENIX_STRICT_EZERAGENT"] = "1"
    try:
        body = _boot_and_capture()
    finally:
        os.environ.pop("PHOENIX_STRICT_EZERAGENT", None)
    ran = ("죽은 역할 0" in body) or ("phoenix_restore" in body) or ("티켓=" in body)
    no_fatal = "[phoenix][FATAL]" not in body and "표준경로 폴백 금지" not in body
    check("② STRICT=1 에서 Rust 주입으로 phoenix 해석·실행 성공", ran and no_fatal,
          "ran=%s no_fatal=%s" % (ran, no_fatal))

    # ── ③ 재기동 후 seeded dead role → 부활 대상 타겟팅(kill→재기동→부활 경로) ──
    _wipe_state()
    ph = os.path.join(h.HARN_DIR, "phoenix")
    os.makedirs(ph, exist_ok=True)
    with open(os.path.join(ph, "desired_roster.json"), "w") as f:
        json.dump({"roster": {"worker-e2e": {"role": "worker-e2e"}}, "tombstones": [], "updated_at": 0}, f)
    # fresh-fallback(launch-agent=실 에이전트) 차단 — 타겟팅만 관측(실 스폰 회피).
    os.environ["PHOENIX_POISON_FRESH_FALLBACK"] = "0"
    try:
        body = _boot_and_capture(wait=8.0)
    finally:
        os.environ.pop("PHOENIX_POISON_FRESH_FALLBACK", None)
    check("③ 재기동 auto-restore 가 seeded dead role 타겟팅(부활 경로 발화)", "worker-e2e" in body,
          body.strip()[-140:].replace("\n", " "))
    check("③ 부활이 격리 desired_roster(라이브 아님)에서 대상 산출", "대상역할=" in body,
          "대상역할 라인 존재")

    npass = sum(1 for c in results if c)
    print("\n=== %d/%d PASS ===" % (npass, len(results)))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        try: h.teardown(verbose=False)
        except Exception: pass
