#!/usr/bin/env python3
"""W6 cross-layer 재시도 증거(리포 커밋 · 설계 W6 행 f53f5ab).

ezerd loop_auto_restore 의 지연 재시도가 '중복 스폰 0'을 시스템 속성으로 내는 근거는 **재시도가 phoenix
run_restore 를 재실행하고, run_restore 가 현재 상태로 target 을 재산정**한다는 데 있다. 이 속성을 결정론으로
실증한다: attempt0(비0·미부활) → 라이브 상태 변경(수동복원 모사=desired tombstone) → attempt1(재실행)이
현재 상태에서 target 재산정 → NOOP·spawn 0. (Rust decision-loop 는 main.rs 단위 6건이 재시도 1회·5/6 무재시도를
증명하고, E1 E2E 는 실 ezerd 재시도 loop 발화를 관측한다 — 본 테스트는 그 사이 'python 재산정' 층을 봉인.)

데몬 불요(더미 EZER 로 ezer() rc127 강등 → 스폰 실패 결정론). 라이브 무접촉.
실행: python3 ezer-pack/bin/tests/test_phoenix_e2e_crosslayer.py
"""
import importlib.util, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.normpath(os.path.join(HERE, "..", "ezer_phoenix.py"))
spec = importlib.util.spec_from_file_location("ezer_phoenix", PH)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

_results = []
def check(n, c, d=""):
    _results.append(c); print(("PASS " if c else "FAIL ") + n + (" | " + d if d else ""))


# lease 핸들 캡처 — 프로덕션은 attempt0·1 이 별도 ezerd 스폰(=별도 프로세스·별도 lease, atexit 로 각자 해제)이나
# 본 테스트는 단일 프로세스이므로 attempt 사이 명시 해제로 별도 프로세스를 모사(lease 는 cross-layer 재산정과 직교).
_handles = []


def main():
    td = tempfile.mkdtemp(prefix="phoenix-xlayer-")
    m.EZER = os.path.join(td, "nonexistent-ezer")   # ezer() rc127 → 스폰 실패 결정론
    m.POISON_FRESH_FALLBACK = False               # launch-agent(실 에이전트) 차단
    os.environ["PHOENIX_SPAWN_RETRIES"] = "0"; m.SPAWN_RETRIES = 0
    _orig_lease = m._acquire_restore_lease

    def _cap_lease(socket):
        ok, h = _orig_lease(socket)
        _handles.append(h)
        return ok, h
    m._acquire_restore_lease = _cap_lease

    def _release_all():
        for h in _handles:
            if h is not None:
                m._release_lease(h)
        _handles.clear()
    sd = os.path.join(td, "node")
    ph = os.path.join(sd, "phoenix")
    os.makedirs(ph, exist_ok=True)
    sock = os.path.join(sd, "ezer.sock")
    desired = os.path.join(ph, "desired_roster.json")

    # attempt0: seeded dead role → 타겟·미부활(비0).
    with open(desired, "w") as f:
        json.dump({"roster": {"worker-x": {"role": "worker-x"}}, "tombstones": [], "updated_at": 0}, f)
    r0 = m.run_restore(sock, ticket="a0", stub=True, print_result=False)
    targeted0 = "worker-x" in (r0.get("target_roles") or [])
    nonzero0 = m.restore_exit_code(r0) != 0
    check("attempt0: worker-x 타겟 + 비0(미부활)", targeted0 and nonzero0,
          "target=%s verdict=%s exit=%s" % (r0.get("target_roles"), r0.get("phoenix_restore"), m.restore_exit_code(r0)))

    _release_all()  # attempt0 프로세스 종료 모사(lease 해제) — 프로덕션은 별도 스폰

    # ★수동복원 모사(codex W6): worker-x 를 desired 에 **그대로 유지**하되, master 가 수동복원해 역할이 **live**가
    #   된 상태를 만든다 — live_role_surfaces 가 worker-x exited=false 를 반환하도록 monkeypatch. attempt2 는
    #   desired 에서 worker-x 를 제거(폐역)한 게 아니라, **_alive(worker-x) liveness 재산정** 때문에 target 에서
    #   빠져 NOOP 이 되어야 한다(tombstone/desired-shrink 경로가 아니라 liveness 경로 봉인).
    #   desired 는 worker-x 유지(폐역 아님).
    _orig_live = m.live_role_surfaces
    m.live_role_surfaces = lambda socket: {"worker-x": [{"surface": "surface:1", "pid": 4242, "exited": False}]}

    # attempt1: 재실행(ezerd 지연 재시도 상당) → live 재산정으로 worker-x alive → target 제외 → NOOP·spawn 0.
    r1 = m.run_restore(sock, ticket="a1", stub=True, print_result=False)
    m.live_role_surfaces = _orig_live
    # desired 에 worker-x 가 여전히 남아있음을 확인(폐역 아님 — liveness 경로임을 증명).
    dj = json.load(open(desired))
    still_desired = "worker-x" in (dj.get("roster") or {}) and "worker-x" not in (dj.get("tombstones") or [])
    check("attempt1: worker-x desired 유지(폐역 아님 — liveness 경로)", still_desired,
          "roster=%s tombstones=%s" % (list((dj.get('roster') or {}).keys()), dj.get("tombstones")))
    check("attempt1: liveness 재산정 → NOOP(수동복원으로 live)", r1.get("phoenix_restore") == "NOOP",
          "verdict=%s" % r1.get("phoenix_restore"))
    check("attempt1: 중복 스폰 0(target_roles 비었음·_alive 로 제외)", (r1.get("target_roles") or []) == [],
          "target=%s" % r1.get("target_roles"))
    check("attempt1: exit 0", m.restore_exit_code(r1) == 0, "exit=%s" % m.restore_exit_code(r1))

    # attempt1 저널에 spawn 이벤트 0 확인(재산정으로 스폰 자체가 안 일어남).
    jpath = m.journal_path(sock, "a1")
    spawn_events = 0
    if os.path.exists(jpath):
        j = json.load(open(jpath))
        spawn_events = sum(1 for e in j.get("events", []) if e.get("stage") == "spawn")
    check("attempt1: 저널 spawn 이벤트 0", spawn_events == 0, "spawn_events=%d" % spawn_events)

    import shutil
    shutil.rmtree(td, ignore_errors=True)
    npass = sum(1 for c in _results if c)
    print("\n=== %d/%d PASS ===" % (npass, len(_results)))
    return 0 if npass == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
