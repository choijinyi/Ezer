#!/usr/bin/env python3
"""W2/A-S3 tombstone intent 저널 테스트(리포 커밋). 데몬 다운타임 폴백·observe 멱등 적용·절단 순서 계약
(TOCTOU: topology.json 디스크 영속 확인 후에만 절단)을 결정론 검증. 데몬 불요(ezer/read_topology mock).

실행: python3 ezer-pack/bin/tests/test_phoenix_as3_intent.py  (0=전건 PASS)
"""
import importlib.util, json, os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.normpath(os.path.join(HERE, "..", "ezer_phoenix.py"))
spec = importlib.util.spec_from_file_location("ezer_phoenix", PH)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

_results = []
def check(n, c, d=""):
    _results.append(c); print(("PASS " if c else "FAIL ") + n + (" | " + d if d else ""))

m.live_role_surfaces = lambda socket: {}
m._snapshot_roster_entries = lambda socket: {}
_ORIG_EZER = m.ezer  # 원본 ezer() 저장(시나리오 E 에서 복원 — 더미 EZER 로 rc127 강등)


class _R:
    def __init__(self, rc=0, out=""):
        self.returncode = rc; self.stdout = out; self.stderr = ""


def main():
    td = tempfile.mkdtemp(prefix="phoenix-as3-")
    sd = os.path.join(td, "node"); ph = os.path.join(sd, "phoenix"); os.makedirs(ph, exist_ok=True)
    sock = os.path.join(sd, "ezer.sock")
    ijp = os.path.join(ph, "tombstone-intents.jsonl")

    # ── A. 데몬 다운타임: cmd_tombstone RPC 실패 → intent 저널 append(desired 직접 쓰기 아님) ──
    m.EZER = os.path.join(td, "nonexistent-ezer")  # ezer() rc127 → RPC 실패
    args = types.SimpleNamespace(socket=sock, role="ghost", remove=False, dept=False)
    out = m.cmd_tombstone(args)
    check("A 다운타임 → intent 저널 폴백(via)", out.get("via") == "intent-journal", out.get("via"))
    ints = m._read_tombstone_intents(sock)
    check("A intent 저널에 add ghost 기록", any(i.get("op") == "add" and i.get("role") == "ghost" for i in ints),
          str(ints))

    # ── B. observe: 미소화 intent 를 replace 이전 멱등 적용(topology 에 아직 없어도 즉시 반영)·절단 보류 ──
    m.read_topology = lambda socket: {"schema_version": 1, "tombstones_rev": 3, "tombstones": [], "entries": []}
    m._ACTIVE_EPOCH = "sa:E1"
    # RPC 재동기도 실패(데몬 down) → 절단 보류. observe 가 intent(add ghost)를 tombstones 에 멱등 적용.
    roster, tombs = m.observe_and_persist_roster(sock)
    check("B observe 멱등 적용: ghost 폐역 반영", "ghost" in tombs and "ghost" not in roster,
          "tombs=%s" % sorted(tombs))
    check("B 절단 보류(데몬 down): intent 저널 잔존", os.path.exists(ijp))

    # ── C. 절단 순서 TOCTOU: RPC 는 성공하나 topology.json 이 아직 미반영(데몬 영속 전 크래시 모사) → 절단 금지 ──
    m.ezer = lambda *a, **k: _R(0, "tombstone ghost set")  # RPC 성공
    m.read_topology = lambda socket: {"schema_version": 1, "tombstones_rev": 3, "tombstones": [], "entries": []}  # ghost 미반영
    truncated = m._resync_intents_if_daemon_up(sock, m._read_tombstone_intents(sock))
    check("C TOCTOU: RPC 성공이나 디스크 미영속 → 절단 금지", truncated is False and os.path.exists(ijp),
          "truncated=%s exists=%s" % (truncated, os.path.exists(ijp)))

    # ── D. 절단: RPC 성공 + topology.json 에 ghost 영속 확인 → intent 절단 ──
    m.read_topology = lambda socket: {"schema_version": 1, "tombstones_rev": 4, "tombstones": ["ghost"], "entries": []}
    truncated = m._resync_intents_if_daemon_up(sock, m._read_tombstone_intents(sock))
    check("D 디스크 영속 확인 후 절단", truncated is True and not os.path.exists(ijp),
          "truncated=%s exists=%s" % (truncated, os.path.exists(ijp)))

    # ── E. remove intent **풀사이클**(codex W2: in-memory discard만 보지 말 것) — 실 observe 경로.
    #    prev desired: ghost 가 묘비+엔트리 보존 상태. remove intent(다운타임) 기록 → observe(데몬 down·RPC 재동기
    #    실패) → intent 멱등 적용으로 ghost 묘비 해제 + 엔트리 보존(부활 가능). legacy topology 로 add-merge 후 remove.
    m.EZER = os.path.join(td, "nonexistent-ezer")
    m.ezer = _ORIG_EZER  # 원본 ezer() 복원 — 더미 EZER 로 rc127(데몬 down·RPC 재동기 실패)
    sd2 = os.path.join(td, "e"); ph2 = os.path.join(sd2, "phoenix"); os.makedirs(ph2, exist_ok=True)
    sock2 = os.path.join(sd2, "ezer.sock")
    with open(os.path.join(ph2, "desired_roster.json"), "w") as f:
        json.dump({"roster": {"ghost": {"role": "ghost", "session_id": "S9"}, "cso": {"role": "cso"}},
                   "tombstones": ["ghost"], "tombstones_rev": 0, "daemon_epoch": "sa:E1"}, f)
    m.read_topology = lambda socket: {"tombstones": ["ghost"], "entries": []}  # legacy(마커 부재)→add-merge
    m._ACTIVE_EPOCH = "sa:E1"
    m._append_tombstone_intent(sock2, "ghost", True)  # 다운타임 remove intent
    roster, tombs = m.observe_and_persist_roster(sock2)
    check("E remove intent observe 풀사이클: ghost 묘비 해제", "ghost" not in tombs, "tombs=%s" % sorted(tombs))
    check("E remove intent: ghost 엔트리 보존(부활 가능)·cso 보존",
          "ghost" in roster and "cso" in roster, "roster=%s" % sorted(roster.keys()))

    import shutil; shutil.rmtree(td, ignore_errors=True)
    npass = sum(1 for c in _results if c)
    print("\n=== %d/%d PASS ===" % (npass, len(_results)))
    return 0 if npass == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
