#!/usr/bin/env python3
"""W6/E3 시계 역행 가드 테스트(리포 커밋) — 세대 GC 가 mtime 병행 실효 시각으로 monotonic 하게 동작해
시계 역행 시 lexical 오선택·오삭제(P2-5)를 막는지 결정론 검증.

실행: python3 ezer-pack/bin/tests/test_phoenix_e3_gc.py  (0=전건 PASS)
"""
import importlib.util, os, sys, tempfile, shutil
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.normpath(os.path.join(HERE, "..", "ezer_state_snapshot.py"))
spec = importlib.util.spec_from_file_location("ezer_state_snapshot", SNAP)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

_results = []
def check(n, c, d=""):
    _results.append(c); print(("PASS " if c else "FAIL ") + n + (" | " + d if d else ""))


def _dt(s):
    return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def main():
    KEEP = m.KEEP_RECENT  # 48
    now = _dt("20260706T120000Z")

    # KEEP 개의 '정상' 최근 세대(이름=실효 시각 일치) + 1개 '시계 역행' 세대(이름은 아주 옛날인데 실효는 최근).
    normal = ["20260705T12%02d00Z" % i for i in range(KEEP)]  # 20260705T1200~1247(분 단위·유효)
    regressed = "00010101T000000Z"  # 이름은 서기 1년(lexically 최소) — 시계 역행으로 만들어진 실 최근 세대
    gens = normal + [regressed]  # KEEP+1 개 → recent-KEEP 규칙상 하나는 삭제 대상

    # ① 이름 기준(하위호환 기본 dt_of): regressed 는 이름이 최소라 '가장 오래됨'→ 삭제된다(P2-5 버그).
    keep_name, del_name = m.compute_gc(gens, now=now)
    check("① 이름 기준 GC: 시계 역행 세대 오삭제(P2-5 버그 재현)", regressed in del_name,
          "regressed in delete=%s" % (regressed in del_name))

    # ② mtime 병행 실효(dt_eff): regressed 의 실효 시각을 '지금'으로 → 최근으로 인식되어 보관(P2-5).
    def dt_eff(name):
        if name == regressed:
            return now  # 실제로 방금 만든 세대(mtime 최근) — 이름과 무관하게 최근
        return m._parse_stamp(name)
    keep_eff, del_eff = m.compute_gc(gens, now=now, dt_of=m._parse_stamp, dt_eff=dt_eff)
    check("② P2-5: 시계 역행 세대 보관(오삭제 방어)", regressed in keep_eff and regressed not in del_eff,
          "regressed kept=%s" % (regressed in keep_eff))

    # ③ ★gemini W6: mtime 오염(cp/touch)이 진짜 최근 세대를 밀어내지 않는다.
    #    old_name(과거 이름)이 실효(mtime)만 '지금'으로 오염 + real_recent(최근 이름·정상). union 이므로
    #    real_recent 는 명목-recent 로 보존되고, 오염 세대는 실효-recent 로 추가 잔존(무해).
    real_recent = "20260706T110000Z"  # 진짜 최근(이름=실효 일치)
    polluted_old = "20200101T000000Z"  # 과거 이름인데 mtime 만 지금으로 오염(cp/touch)
    # KEEP 개 채워 real_recent 가 명목-recent 경계 근처에 오게: normal(48개) 중 가장 오래된 것을 real_recent 로 대체.
    gens2 = normal[:-1] + [real_recent, polluted_old]  # 총 KEEP+1 → 하나는 삭제 대상
    def dt_eff2(name):
        if name == polluted_old:
            return now  # cp/touch 오염(실효만 미래)
        return m._parse_stamp(name)
    keep2, del2 = m.compute_gc(gens2, now=now, dt_of=m._parse_stamp, dt_eff=dt_eff2)
    check("③ 오염 가드: 진짜 최근(real_recent) 오삭제 안 됨(명목-recent 보존)",
          real_recent in keep2 and real_recent not in del2, "real_recent kept=%s" % (real_recent in keep2))
    check("③ 오염 세대는 실효-recent 로 잔존(무해)·명목-recent 미침해", polluted_old in keep2,
          "polluted kept=%s del=%s" % (polluted_old in keep2, del2))

    # ③ _gen_effective_dt: 이름 vs mtime 중 더 나중을 취한다(디스크 실측).
    td = tempfile.mkdtemp(prefix="phoenix-e3-")
    d = os.path.join(td, regressed)
    os.makedirs(d)  # 방금 생성 → mtime=지금
    eff = m._gen_effective_dt(td, regressed)
    nominal = m._parse_stamp(regressed)
    check("③ _gen_effective_dt = max(이름, mtime) → mtime(최근) 채택", eff is not None and eff > nominal,
          "eff=%s nominal=%s" % (eff, nominal))
    shutil.rmtree(td, ignore_errors=True)

    npass = sum(1 for c in _results if c)
    print("\n=== %d/%d PASS ===" % (npass, len(_results)))
    return 0 if npass == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
