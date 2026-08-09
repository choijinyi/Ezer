#!/usr/bin/env python3
"""W2 묘비 remove 의미론 풀사이클 E2E(리포 커밋·codex W2 BLOCKING 수정 검증). 수제 fixture 금지 — 실 ezerd
observe 경로로 검증: ①역할 live → ②owner close(묘비 삽입·rev++) → ③observe: desired 엔트리 **보존** + restore
target **제외** → ④untomb RPC(ezer tombstone --remove) → ⑤observe: 묘비 해제 → restore target **복귀**(부활 타겟팅).
과거 pop 은 ③에서 엔트리를 파괴해 ④ untomb 를 무의미하게 만들었다(false-green) — 이제 엔트리 보존으로 즉시 부활.

바이너리 미발견 시 skip(exit 0). 라이브 무접촉.
실행: python3 ezer-pack/bin/tests/test_phoenix_w2_untomb_fullcycle.py
"""
import importlib.util, os, sys, re, json, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
DBG = os.path.join(REPO, "target", "debug")


def _find(name):
    env = os.environ.get("PHOENIX_HARNESS_" + name.upper())
    if env and os.path.exists(env):
        return env
    c = os.path.join(DBG, name)
    return c if os.path.exists(c) else shutil.which(name)


EZERD, EZER = _find("ezerd"), _find("ezer")
if not (EZERD and EZER):
    print("SKIP: ezerd/ezer 미발견(빌드 필요). skip(exit 0).")
    sys.exit(0)

os.environ["PHOENIX_HARNESS_EZERD"] = EZERD
os.environ["PATH"] = DBG + ":" + os.environ.get("PATH", "")
os.environ["PHOENIX_EZER"] = EZER
spec = importlib.util.spec_from_file_location("h", os.path.join(HERE, "..", "ezer_phoenix_harness.py"))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
h.EZER = EZER; h.EZERD = EZERD
h.guard_isolation()
PH = os.path.join(HERE, "..", "ezer_phoenix.py")
DESIRED = os.path.join(h.HARN_DIR, "phoenix", "desired_roster.json")
results = []
def check(n, c, d=""):
    results.append(c); print(("PASS " if c else "FAIL ") + n + (" | " + d if d else ""))


def _phoenix(args, timeout=60):
    env = dict(os.environ)
    env["PHOENIX_SPAWN_RETRIES"] = "0"; env["PHOENIX_POISON_FRESH_FALLBACK"] = "0"
    r = subprocess.run([sys.executable, PH, "--socket", h.HARN_SOCK] + args,
                       capture_output=True, text=True, timeout=timeout, env=env)
    i = (r.stdout or "").find("{")
    return (json.loads(r.stdout[i:]) if i >= 0 else {}), r


def _desired():
    if os.path.exists(DESIRED):
        try: return json.load(open(DESIRED))
        except Exception: return {}
    return {}


def main():
    h.teardown(verbose=False); h._fresh_harness()
    shutil.rmtree(os.path.join(h.HARN_DIR, "phoenix"), ignore_errors=True)
    for f in ("topology.json", "desired_roster.json"):
        try: os.remove(os.path.join(h.HARN_DIR, f))
        except OSError: pass
    h.start_daemon(wait=12.0)
    try:
        # ① 역할 live: worker-fc surface 생성(role 등록) + 관측 영속.
        ns = h.ezer("new-surface", "--role", "worker-fc").stdout or ""
        ref = re.search(r"(surface:\d+)", ns)
        ref = ref.group(1) if ref else None
        if ref:
            h.ezer("send", "--surface", ref, "sleep 3600"); h.ezer("send-key", "--surface", ref, "Return")
        _phoenix(["reconcile"])  # observe → desired 에 worker-fc 엔트리 영속
        d1 = _desired()
        check("① live 역할 desired 엔트리 등재", "worker-fc" in (d1.get("roster") or {}),
              "roster=%s" % list((d1.get('roster') or {}).keys()))

        # ② owner close(묘비 삽입): 데몬이 worker-fc 를 topology 묘비에 올린다(rev++).
        h.ezer("close-surface", ref)  # 기본 OwnerClose
        # ③ observe(reconcile — MISSING=부활필요·spawn 무): 엔트리 보존 + 부활 target 제외(묘비이므로 MISSING 아님).
        rec3, _ = _phoenix(["reconcile"])
        d3 = _desired()
        missing3 = rec3.get("MISSING(대장O/실측X=부활필요)") or []
        entry_preserved = "worker-fc" in (d3.get("roster") or {})
        tomb_present = "worker-fc" in (d3.get("tombstones") or [])
        check("③ 묘비 후 엔트리 보존(pop 아님)", entry_preserved, "roster=%s" % list((d3.get('roster') or {}).keys()))
        check("③ 묘비 후 부활 target 제외(MISSING 아님)", tomb_present and "worker-fc" not in missing3,
              "tombstones=%s MISSING=%s" % (d3.get("tombstones"), missing3))

        # ⑥ ★codex 재판정: 명시 --roles <tombstoned> 도 tombstone 필터 통과(우회 금지·의도삭제>강제부활).
        #    worker-fc 가 폐역인 상태에서 restore --roles worker-fc → target 미진입·NOOP + 저널 skip 사유 기록.
        res6, _ = _phoenix(["restore", "--stub", "--roles", "worker-fc", "--ticket", "fc6"])
        excluded = "worker-fc" not in (res6.get("target_roles") or [])
        noop = res6.get("phoenix_restore") == "NOOP"
        jrec = os.path.join(h.HARN_DIR, "phoenix", "journal-fc6.json")
        skip_logged = False
        if os.path.exists(jrec):
            try:
                ev = json.load(open(jrec)).get("events", [])
                skip_logged = any(e.get("status") == "skip_tombstoned" and e.get("role") == "worker-fc" for e in ev)
            except Exception:
                pass
        check("⑥ 명시 --roles <tombstoned> 필터 통과(target 미진입·NOOP)", excluded and noop,
              "target=%s verdict=%s" % (res6.get("target_roles"), res6.get("phoenix_restore")))
        check("⑥ 저널에 skip_tombstoned 사유 기록", skip_logged, "journal-fc6 events")

        # ④ untomb: ezer tombstone --remove → 데몬이 topology 묘비 해제(rev++).
        h.ezer("tombstone", "worker-fc", "--remove")
        # ⑤ observe(reconcile): 묘비 해제 → worker-fc 가 부활 target(MISSING)으로 복귀 — 엔트리 보존 덕에 즉시 부활 가능.
        rec5, _ = _phoenix(["reconcile"])
        d5 = _desired()
        missing5 = rec5.get("MISSING(대장O/실측X=부활필요)") or []
        untombed = "worker-fc" not in (d5.get("tombstones") or [])
        check("⑤ untomb 후 묘비 해제", untombed, "tombstones=%s" % d5.get("tombstones"))
        check("⑤ untomb 후 부활 target 복귀(MISSING=부활필요)", "worker-fc" in missing5,
              "MISSING=%s" % missing5)
    finally:
        h.teardown(verbose=False)

    npass = sum(1 for c in results if c)
    print("\n=== %d/%d PASS ===" % (npass, len(results)))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    try: sys.exit(main())
    finally:
        try: h.teardown(verbose=False)
        except Exception: pass
