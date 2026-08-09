#!/usr/bin/env python3
"""OPP-11 dep_doctor contract tests — install-source-aware PRESCRIPTIONS.

Invariants locked:
  1) PRESENTS ONLY: diagnose runs no install, opens no socket (side_effect_free).
  2) verdict, not score: DepVerdict carries a DepState enum + evidence + fix,
     never a numeric score.
  3) install-source detection picks the source-specific re-install command;
     UNKNOWN falls back to the conservative reversible pip --user.
  4) playwright 2-layer: package dep vs downloaded chromium binary are distinct
     deps, and binary_missing prescribes the browser download (not a reinstall).
  5) every dep has an `unknown` fail-safe prescription (no fix-less hole).
  6) irreversible (brew) source → worker autonomy WITHHELD note (owner hold).

Run:  python3 engine/tests/test_dep_doctor.py
"""
from __future__ import annotations

import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from engine import dep_doctor  # noqa: E402
from engine.dep_doctor import DepState, InstallSource, PRESCRIPTIONS  # noqa: E402


def t_diagnose_opens_no_socket():
    real = socket.socket

    def _boom(*a, **k):
        raise AssertionError("dep_doctor opened a socket")

    socket.socket = _boom  # type: ignore
    try:
        for dep in ("curl_cffi", "yt_dlp", "playwright", "playwright_chromium"):
            v = dep_doctor.diagnose(dep)
            assert v.side_effect_free is True, v
    finally:
        socket.socket = real  # type: ignore
    print("  ✓ diagnose: no socket opened (side-effect-free)")


def t_verdict_has_no_score():
    v = dep_doctor.diagnose("curl_cffi")
    d = v.to_dict()
    assert "score" not in d, d
    assert isinstance(v.state, DepState), v.state
    print("  ✓ verdict carries DepState enum + evidence + fix, no numeric score")


def t_present_dep_is_ok_no_prescription():
    # curl_cffi may or may not be installed on this machine; if present → OK.
    v = dep_doctor.diagnose("curl_cffi")
    if v.state == DepState.OK:
        assert v.prescription is None, v
        assert v.fixable is False
        print("  ✓ present dep → OK, no prescription emitted")
    else:
        # absent/broken on this machine → must carry a prescription
        assert v.prescription, v
        print("  ✓ (curl_cffi not present here) → prescription emitted: %s" % v.prescription)


def t_missing_dep_gets_conservative_prescription():
    # Force a guaranteed-absent dep by temporarily registering one.
    PRESCRIPTIONS["__fake_missing__"] = {
        "kind": "python", "module": "zzz_not_a_real_module_xyz",
        "rx": {InstallSource.UNKNOWN: "python3 -m pip install --user -U fake"},
    }
    try:
        v = dep_doctor.diagnose("__fake_missing__")
        assert v.state == DepState.MISSING, v
        assert v.prescription == "python3 -m pip install --user -U fake", v
        assert v.fixable is True
    finally:
        PRESCRIPTIONS.pop("__fake_missing__", None)
    print("  ✓ missing dep → MISSING + conservative reversible prescription")


def t_source_detection_from_origin():
    assert dep_doctor._detect_source("/Users/x/.local/pipx/venvs/yt-dlp/lib/python3.11/site-packages/yt_dlp/__init__.py") == InstallSource.PIPX
    assert dep_doctor._detect_source("/Users/x/.local/share/uv/tools/playwright/lib/playwright/__init__.py") == InstallSource.UV_TOOL
    assert dep_doctor._detect_source("/opt/homebrew/Cellar/foo/1.0/lib/foo.py") == InstallSource.BREW
    assert dep_doctor._detect_source("/Users/x/.local/lib/python3.11/site-packages/curl_cffi/__init__.py") == InstallSource.PIP_USER
    assert dep_doctor._detect_source(None) == InstallSource.UNKNOWN
    print("  ✓ install-source detection: pipx/uv/brew/pip-user/unknown")


def t_playwright_two_layer_distinct():
    # package dep and chromium binary dep are SEPARATE entries.
    assert "playwright" in PRESCRIPTIONS
    assert "playwright_chromium" in PRESCRIPTIONS
    assert PRESCRIPTIONS["playwright_chromium"]["kind"] == "browser_binary"
    v = dep_doctor.diagnose("playwright_chromium")
    if v.state == DepState.BINARY_MISSING:
        assert "install chromium" in (v.prescription or ""), v
        assert any("package != browser binary" in n for n in v.notes), v.notes
        print("  ✓ playwright 2-layer: binary_missing prescribes browser download")
    else:
        print("  ✓ playwright 2-layer: chromium present/unknown here (%s)" % v.state.value)


def t_every_dep_has_unknown_failsafe():
    for dep, spec in PRESCRIPTIONS.items():
        rx = spec.get("rx", {})
        assert InstallSource.UNKNOWN in rx, f"{dep} has no unknown fail-safe prescription"
    print("  ✓ every dep has an `unknown` fail-safe prescription (no fix-less hole)")


def t_brew_source_withholds_autonomy():
    # Simulate a broken-shim dep whose origin resolves to brew → owner-hold note.
    orig_origin = dep_doctor._module_origin
    orig_sig = dep_doctor.disk_signal.dep_signal

    class _Sig:
        avail = dep_doctor.disk_signal.Avail.UNKNOWN
        evidence = "simulated_unknown"

    dep_doctor._module_origin = lambda m: "/opt/homebrew/Cellar/curl_cffi/0.15/x.py"  # type: ignore
    dep_doctor.disk_signal.dep_signal = lambda m: _Sig()  # type: ignore
    try:
        v = dep_doctor.diagnose("curl_cffi")
        assert v.state == DepState.BROKEN_SHIM, v
        assert v.source == InstallSource.BREW, v
        assert any("owner hold" in n.lower() or "withheld" in n.lower() for n in v.notes), v.notes
    finally:
        dep_doctor._module_origin = orig_origin  # type: ignore
        dep_doctor.disk_signal.dep_signal = orig_sig  # type: ignore
    print("  ✓ brew (irreversible) source → autonomy WITHHELD / owner-hold note")


def t_hint_for_never_raises():
    s = dep_doctor.hint_for("curl_cffi", code_ref="transport.py:160")
    assert isinstance(s, str) and s
    s2 = dep_doctor.hint_for("__nonexistent_dep__")
    assert isinstance(s2, str)
    print("  ✓ hint_for returns a string, never raises")


ALL = [
    ("diagnose_opens_no_socket", t_diagnose_opens_no_socket),
    ("verdict_has_no_score", t_verdict_has_no_score),
    ("present_dep_is_ok_no_prescription", t_present_dep_is_ok_no_prescription),
    ("missing_dep_gets_conservative_prescription", t_missing_dep_gets_conservative_prescription),
    ("source_detection_from_origin", t_source_detection_from_origin),
    ("playwright_two_layer_distinct", t_playwright_two_layer_distinct),
    ("every_dep_has_unknown_failsafe", t_every_dep_has_unknown_failsafe),
    ("brew_source_withholds_autonomy", t_brew_source_withholds_autonomy),
    ("hint_for_never_raises", t_hint_for_never_raises),
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
