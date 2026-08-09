#!/usr/bin/env python3
"""W1 identity 3중 대조 테스트(리포 커밋 · embed 제외 tests/). 데몬 불요 — subprocess 를 mock 해
build_id·embedded_pack_hash·protocol_version 각 불일치→exit 6+필드명, legacy 필드부재→mismatch,
inconclusive→degraded 채택+저널 기록을 고정 검증한다.

실행: python3 EZERagent-pack/bin/tests/test_phoenix_identity.py  (0=전건 PASS)
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.normpath(os.path.join(HERE, "..", "EZERagent_phoenix.py"))

spec = importlib.util.spec_from_file_location("EZERagent_phoenix", PH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SELF = {"build_id": "abc123", "embedded_pack_hash": "H_SELF", "protocol_version": "1", "version": "0.12.20"}
FAKE_EZERAGENT = os.path.join(tempfile.gettempdir(), "fake-EZERagent-identity-test")

_results = []


def check(name, cond, detail=""):
    _results.append((name, cond, detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def _mk_run(self_id, daemon_id):
    """subprocess.run 대역 — phoenix-identity(self)와 status(daemon) 출력을 스크립트한다. None=미도달(빈 stdout)."""
    def _run(cmd, *a, **kw):
        class R:
            returncode = 0
            stderr = ""
        r = R()
        if "phoenix-identity" in cmd:
            r.stdout = json.dumps(self_id) if self_id is not None else ""
        elif "status" in cmd:
            r.stdout = json.dumps({"daemon": daemon_id}) if daemon_id is not None else ""
        else:
            r.stdout = ""
        return r
    return _run


@contextlib.contextmanager
def _mock_subprocess(self_id, daemon_id):
    orig = m.subprocess.run
    m.subprocess.run = _mk_run(self_id, daemon_id)
    try:
        yield
    finally:
        m.subprocess.run = orig


def _isolated_socket(tmp):
    """격리 소켓 경로 — 저널 write 가 tmp/phoenix 로 향하게(라이브 무접촉)."""
    return os.path.join(tmp, "EZERagent.sock")


def _resolve_expect_exit6(socket, phoenix_EZERagent, self_id, daemon_id):
    """PHOENIX_EZERAGENT 경로로 _resolve_EZERagent 호출 → SystemExit(6) 기대. (code, stderr) 반환."""
    m._EZERAGENT_IDENTITY = None
    err = io.StringIO()
    old = os.environ.get("PHOENIX_EZERAGENT")
    os.environ["PHOENIX_EZERAGENT"] = phoenix_EZERagent
    # X_OK/isfile 통과 강제(실 파일 없이도).
    oi, oa = m.os.path.isfile, m.os.access
    m.os.path.isfile = lambda p: True if p == phoenix_EZERagent else oi(p)
    m.os.access = lambda p, mode: True if p == phoenix_EZERagent else oa(p, mode)
    # 재시도 sleep 0(테스트 속도).
    m._IDENTITY_RETRY_SLEEP = 0.0
    code = None
    try:
        with _mock_subprocess(self_id, daemon_id), contextlib.redirect_stderr(err):
            m._resolve_EZERagent(socket)
    except SystemExit as e:
        code = e.code
    finally:
        m.os.path.isfile, m.os.access = oi, oa
        if old is None:
            os.environ.pop("PHOENIX_EZERAGENT", None)
        else:
            os.environ["PHOENIX_EZERAGENT"] = old
    return code, err.getvalue()


def main():
    tmp = tempfile.mkdtemp(prefix="phoenix-identity-test-")
    socket = _isolated_socket(tmp)

    # ── A. _EZERagent_identity_check 필드별 mismatch(순수 대조) ──
    with _mock_subprocess(SELF, dict(SELF)):
        st, fld, _ = m._EZERagent_identity_check(FAKE_EZERAGENT, socket)
    check("A match", st == "match", "%s/%s" % (st, fld))
    for field, bad in [("build_id", "DIFF"), ("embedded_pack_hash", "H_OTHER"), ("protocol_version", "9")]:
        dmn = dict(SELF); dmn[field] = bad
        with _mock_subprocess(SELF, dmn):
            st, fld, _ = m._EZERagent_identity_check(FAKE_EZERAGENT, socket)
        check("A mismatch %s" % field, st == "mismatch" and fld == field, "%s/%s" % (st, fld))
    # legacy: 데몬 JSON 에 필드 부재(구버전) → mismatch(필드 부재 검출)
    with _mock_subprocess(SELF, {"build_id": "abc123", "protocol_version": "1"}):  # embedded_pack_hash 없음
        st, fld, _ = m._EZERagent_identity_check(FAKE_EZERAGENT, socket)
    check("A legacy 필드부재 → mismatch", st == "mismatch" and fld == "embedded_pack_hash", "%s/%s" % (st, fld))
    # inconclusive: self-report 실패 / 데몬 미도달
    with _mock_subprocess(None, dict(SELF)):
        st, _, _ = m._EZERagent_identity_check(FAKE_EZERAGENT, socket)
    check("A inconclusive(self 실패)", st == "inconclusive", st)
    with _mock_subprocess(SELF, None):
        st, _, _ = m._EZERagent_identity_check(FAKE_EZERAGENT, socket)
    check("A inconclusive(daemon 미도달)", st == "inconclusive", st)

    # ── B. _resolve_EZERagent 필드별 mismatch → exit 6 + 필드명 stderr ──
    for field, bad in [("build_id", "DIFF"), ("embedded_pack_hash", "H_OTHER"), ("protocol_version", "9")]:
        dmn = dict(SELF); dmn[field] = bad
        code, err = _resolve_expect_exit6(socket, FAKE_EZERAGENT, SELF, dmn)
        check("B %s mismatch → exit 6 + 필드명" % field,
              code == 6 and field in err, "code=%s field_in_err=%s" % (code, field in err))
    # legacy 필드부재 → exit 6 + 필드명(embedded_pack_hash)
    code, err = _resolve_expect_exit6(socket, FAKE_EZERAGENT, SELF, {"build_id": "abc123", "protocol_version": "1"})
    check("B legacy 필드부재 → exit 6", code == 6 and "embedded_pack_hash" in err,
          "code=%s" % code)

    # ── C. inconclusive → degraded 채택(exit 없음) + EZERagent_identity + 저널 기록 ──
    m._EZERAGENT_IDENTITY = None
    m._IDENTITY_RETRY_SLEEP = 0.0
    oi, oa = m.os.path.isfile, m.os.access
    m.os.path.isfile = lambda p: True if p == FAKE_EZERAGENT else oi(p)
    m.os.access = lambda p, mode: True if p == FAKE_EZERAGENT else oa(p, mode)
    os.environ["PHOENIX_EZERAGENT"] = FAKE_EZERAGENT
    err = io.StringIO()
    got = None
    try:
        with _mock_subprocess(SELF, None), contextlib.redirect_stderr(err):  # 데몬 미도달=inconclusive
            got = m._resolve_EZERagent(socket)
    except SystemExit as e:
        got = "EXIT:%s" % e.code
    finally:
        m.os.path.isfile, m.os.access = oi, oa
        os.environ.pop("PHOENIX_EZERAGENT", None)
    check("C inconclusive → 채택(exit 없음)", got == FAKE_EZERAGENT, "got=%r" % got)
    check("C EZERagent_identity=degraded-unverified", m._EZERAGENT_IDENTITY == "degraded-unverified", str(m._EZERAGENT_IDENTITY))
    check("C stderr degraded 명시", "degraded" in err.getvalue(), err.getvalue().strip()[-80:])
    # 저널 기록 확인
    rj = os.path.join(tmp, "phoenix", "journal-resolve.json")
    recorded = False
    if os.path.exists(rj):
        try:
            ev = json.load(open(rj)).get("events", [])
            recorded = any(e.get("stage") == "resolve_EZERagent" and e.get("status") == "degraded" for e in ev)
        except Exception:
            recorded = False
    check("C degraded 저널 기록", recorded, "journal-resolve.json resolve_EZERagent/degraded")

    # ── D. gate2 BLOCKING: _which('EZERagent') PATH 후보도 identity 게이트를 우회하지 않는다 ──
    #    PHOENIX_EZERAGENT 없이 which 가 후보를 잡을 때, mismatch → exit 6(필드명). (과거엔 곧바로 return 으로 우회했다)
    os.environ.pop("PHOENIX_EZERAGENT", None)
    ow = m._which
    m._which = lambda name: FAKE_EZERAGENT if name == "EZERagent" else ow(name)
    m._IDENTITY_RETRY_SLEEP = 0.0
    dmn = dict(SELF); dmn["build_id"] = "PATHDIFF"
    m._EZERAGENT_IDENTITY = None
    err = io.StringIO(); code = None
    try:
        with _mock_subprocess(SELF, dmn), contextlib.redirect_stderr(err):
            m._resolve_EZERagent(socket)
    except SystemExit as e:
        code = e.code
    finally:
        m._which = ow
    check("D PATH(which) 후보 mismatch → exit 6 + 필드명", code == 6 and "build_id" in err.getvalue(),
          "code=%s field_in_err=%s" % (code, "build_id" in err.getvalue()))
    # PATH 후보 match → 채택+verified
    m._which = lambda name: FAKE_EZERAGENT if name == "EZERagent" else ow(name)
    m._EZERAGENT_IDENTITY = None
    got = None
    try:
        with _mock_subprocess(SELF, dict(SELF)):
            got = m._resolve_EZERagent(socket)
    except SystemExit as e:
        got = "EXIT:%s" % e.code
    finally:
        m._which = ow
    check("D PATH(which) 후보 match → 채택+verified", got == FAKE_EZERAGENT and m._EZERAGENT_IDENTITY == "verified",
          "got=%r identity=%s" % (got, m._EZERAGENT_IDENTITY))

    # ── E. W4 STRICT 하위케이스(codex W4 fix3): PHOENIX_STRICT_EZERAGENT=1 positive(주입 정상=성공)·
    #    negative(주입 부재=표준경로 폴백 차단 exit 6). B1 임베드 실행이 의존하는 EZERagent 해석을 STRICT 로 봉인 —
    #    B1 폴백이 Rust PHOENIX_EZERAGENT/PATH 주입 누락을 가리는 false-green 차단.
    os.environ["PHOENIX_STRICT_EZERAGENT"] = "1"
    # positive: STRICT + PHOENIX_EZERAGENT(X_OK·주입 정상) → 채택(폴백 불필요·성공, exit 없음).
    m._EZERAGENT_IDENTITY = None; m._IDENTITY_RETRY_SLEEP = 0.0
    os.environ["PHOENIX_EZERAGENT"] = FAKE_EZERAGENT
    oi, oa = m.os.path.isfile, m.os.access
    m.os.path.isfile = lambda p: True if p == FAKE_EZERAGENT else oi(p)
    m.os.access = lambda p, mode: True if p == FAKE_EZERAGENT else oa(p, mode)
    got = None
    try:
        with _mock_subprocess(SELF, dict(SELF)):  # identity match → verified
            got = m._resolve_EZERagent(socket)
    except SystemExit as e:
        got = "EXIT:%s" % e.code
    finally:
        m.os.path.isfile, m.os.access = oi, oa
        os.environ.pop("PHOENIX_EZERAGENT", None)
    check("E STRICT + PHOENIX_EZERAGENT 주입 정상 → 성공(채택·exit 없음)", got == FAKE_EZERAGENT,
          "got=%r identity=%s" % (got, m._EZERAGENT_IDENTITY))
    # negative: STRICT + PHOENIX_EZERAGENT 부재 + which=None → 표준경로 폴백 강제 차단 exit 6.
    ow = m._which
    m._which = lambda name: None
    code = None
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            m._resolve_EZERagent(socket)
    except SystemExit as e:
        code = e.code
    finally:
        m._which = ow
        os.environ.pop("PHOENIX_STRICT_EZERAGENT", None)
    check("E STRICT + 주입 부재 → exit 6(표준경로 폴백 차단)", code == 6, "code=%s" % code)

    npass = sum(1 for _, c, _ in _results if c)
    print("\n=== %d/%d PASS ===" % (npass, len(_results)))
    return 0 if npass == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
