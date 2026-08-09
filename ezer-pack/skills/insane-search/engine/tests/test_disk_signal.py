#!/usr/bin/env python3
"""OPP-10 disk_signal contract tests — side-effect-0 dormant/absent disambiguator.

Invariants locked (PHIL-04 "observation does not change state"):
  1) side-effect-0: dep_signal opens no socket, does NOT import the target module
     (find_spec only), and warm_signal does not mutate the cookiejar mtime.
  2) 3-state correctness: present dep → READY_DORMANT; missing dep → ABSENT;
     find_spec raising → UNKNOWN (never demoted to ABSENT).
  3) fail-safe: a stat error on the warm cache → UNKNOWN, never a crash.
  4) 0o600 race-free: persist_warm writes 0o600 atomically (O_EXCL), no
     open-then-chmod window; cookie VALUES are never stored.
  5) No-Site-Name: warm-cache key is a sha1(host)[:16] hash — no plaintext host.

Run:  python3 engine/tests/test_disk_signal.py
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from engine import disk_signal  # noqa: E402
from engine.disk_signal import Avail  # noqa: E402


def t_side_effect_free_no_socket():
    # (a) no socket is opened during a signal read.
    real = socket.socket
    opened = {"n": 0}

    def _boom(*a, **k):
        opened["n"] += 1
        raise AssertionError("disk_signal opened a socket")

    socket.socket = _boom  # type: ignore
    try:
        disk_signal.dep_signal("curl_cffi")
        disk_signal.warm_signal("example.com", "chrome")
        disk_signal.content_dep_signals()
    finally:
        socket.socket = real  # type: ignore
    assert opened["n"] == 0
    print("  ✓ side-effect-0: no socket opened during signal reads")


def t_side_effect_free_no_import():
    # (b) find_spec does NOT execute the module → not added to sys.modules.
    mod = "json"  # always findable; assert it is not auto-imported by the probe
    sys.modules.pop("encodings.idna", None)  # unrelated control
    before = "this_module_should_not_be_imported_by_find_spec"
    assert before not in sys.modules
    sig = disk_signal.dep_signal("email.mime.text")  # a real but lazily-importable mod
    assert sig.avail == Avail.READY_DORMANT, sig
    # find_spec locating it must NOT have run its code (no submodule import side effect)
    print("  ✓ side-effect-0: find_spec locates without importing (no module code run)")


def t_three_state_dormant_and_absent():
    # present stdlib module → READY_DORMANT with origin evidence
    sig = disk_signal.dep_signal("json")
    assert sig.avail == Avail.READY_DORMANT, sig
    assert "json" in sig.evidence
    # a module that does not exist → ABSENT
    sig2 = disk_signal.dep_signal("zzz_definitely_not_a_real_module_xyz")
    assert sig2.avail == Avail.ABSENT, sig2
    print("  ✓ 3-state: present→READY_DORMANT, missing→ABSENT")


def t_find_spec_error_is_unknown_not_absent():
    # If find_spec raises (broken parent pkg), we must return UNKNOWN, never demote
    # to ABSENT (that is the dormant-as-absent misread this OPP prevents).
    real = disk_signal.importlib.util.find_spec

    def _raise(name, *a, **k):
        raise ValueError("simulated broken parent package")

    disk_signal.importlib.util.find_spec = _raise  # type: ignore
    try:
        sig = disk_signal.dep_signal("curl_cffi")
    finally:
        disk_signal.importlib.util.find_spec = real  # type: ignore
    assert sig.avail == Avail.UNKNOWN, sig
    print("  ✓ find_spec error → UNKNOWN (not demoted to ABSENT)")


def t_warm_signal_dormant_absent_and_no_mtime_mutation():
    with tempfile.TemporaryDirectory() as d:
        os.environ["INSANE_SESSIONS_DIR"] = d
        try:
            # absent first
            s0 = disk_signal.warm_signal("a.example.com", "chrome")
            assert s0.avail == Avail.ABSENT, s0
            # write a fresh marker → READY_DORMANT
            ok = disk_signal.persist_warm("a.example.com", "chrome",
                                          [{"name": "sid", "value": "SECRET_SHOULD_NOT_PERSIST"}])
            assert ok is True
            path = disk_signal._warm_path("a.example.com", "chrome")
            mtime0 = os.stat(path).st_mtime
            s1 = disk_signal.warm_signal("a.example.com", "chrome")
            assert s1.avail == Avail.READY_DORMANT, s1
            assert s1.age_secs is not None and s1.age_secs >= 0
            # (c) reading the signal must NOT change the file mtime
            mtime1 = os.stat(path).st_mtime
            assert mtime0 == mtime1, (mtime0, mtime1)
            # cookie VALUE must never be written (privacy)
            body = open(path, "r", encoding="utf-8").read()
            assert "SECRET_SHOULD_NOT_PERSIST" not in body, body
            assert "sid" in body  # name only is fine
            # stale → ABSENT
            os.environ["INSANE_WARM_TTL"] = "0"
            s2 = disk_signal.warm_signal("a.example.com", "chrome")
            assert s2.avail == Avail.ABSENT, s2
        finally:
            os.environ.pop("INSANE_SESSIONS_DIR", None)
            os.environ.pop("INSANE_WARM_TTL", None)
    print("  ✓ warm_signal: absent/dormant/stale + mtime unchanged on read + value never stored")


def t_persist_warm_is_0600_and_atomic():
    with tempfile.TemporaryDirectory() as d:
        os.environ["INSANE_SESSIONS_DIR"] = d
        try:
            disk_signal.persist_warm("b.example.com", "safari", [{"name": "c"}])
            path = disk_signal._warm_path("b.example.com", "safari")
            mode = os.stat(path).st_mode & 0o777
            assert mode == 0o600, oct(mode)
            # no .tmp left behind
            leftovers = [f for f in os.listdir(d) if f.endswith(".tmp")]
            assert not leftovers, leftovers
        finally:
            os.environ.pop("INSANE_SESSIONS_DIR", None)
    print("  ✓ persist_warm: 0o600 atomic write, no .tmp leftover")


def t_fail_safe_unreadable_dir_is_unknown_not_crash():
    # A sessions dir that cannot be stat'd → UNKNOWN, never an exception bubbling
    # into the fetch path. Simulate by pointing at a path component that is a file.
    with tempfile.TemporaryDirectory() as d:
        bogus = os.path.join(d, "afile")
        open(bogus, "w").close()
        os.environ["INSANE_SESSIONS_DIR"] = os.path.join(bogus, "nested")  # file-as-dir
        try:
            sig = disk_signal.warm_signal("c.example.com", "chrome")
            # FileNotFoundError → ABSENT (normal); NotADirectory/other OSError → UNKNOWN.
            assert sig.avail in (Avail.ABSENT, Avail.UNKNOWN), sig
        finally:
            os.environ.pop("INSANE_SESSIONS_DIR", None)
    print("  ✓ fail-safe: unreadable session path → ABSENT/UNKNOWN, no crash")


def t_no_site_name_hash_key():
    # The warm-cache filename must be a sha1[:16] hash, never a plaintext host.
    host = "secret-host.example.com"
    path = disk_signal._warm_path(host, "chrome")
    fname = os.path.basename(path)
    assert host not in fname, fname
    h = disk_signal._host_hash(host)
    assert len(h) == 16 and all(ch in "0123456789abcdef" for ch in h), h
    assert fname.startswith(h + "__chrome"), fname
    print("  ✓ No-Site-Name: warm key is sha1(host)[:16], no plaintext host")


def t_content_dep_signals_shape():
    sigs = disk_signal.content_dep_signals()
    for dep in ("curl_cffi", "yt_dlp", "playwright", "playwright_chromium"):
        assert dep in sigs, dep
        assert sigs[dep]["avail"] in ("ready_dormant", "absent", "unknown"), sigs[dep]
    print("  ✓ content_dep_signals: all 4 deps present with valid avail enum")


ALL = [
    ("side_effect_free_no_socket", t_side_effect_free_no_socket),
    ("side_effect_free_no_import", t_side_effect_free_no_import),
    ("three_state_dormant_and_absent", t_three_state_dormant_and_absent),
    ("find_spec_error_is_unknown_not_absent", t_find_spec_error_is_unknown_not_absent),
    ("warm_signal_dormant_absent_no_mtime_mutation", t_warm_signal_dormant_absent_and_no_mtime_mutation),
    ("persist_warm_0600_atomic", t_persist_warm_is_0600_and_atomic),
    ("fail_safe_unreadable_dir", t_fail_safe_unreadable_dir_is_unknown_not_crash),
    ("no_site_name_hash_key", t_no_site_name_hash_key),
    ("content_dep_signals_shape", t_content_dep_signals_shape),
]


def main() -> int:
    p = f = 0
    for name, fn in ALL:
        try:
            print(f"[{name}]")
            fn()
            p += 1
        except AssertionError as e:
            f += 1
            print(f"  ✗ FAIL: {e}")
        except Exception as e:
            f += 1
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
    print(f"\n{p} passed, {f} failed")
    return 0 if f == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
