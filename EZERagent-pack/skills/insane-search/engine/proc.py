"""UTF-8-forced subprocess environment for cross-platform text I/O.

Clean-room port of the env-normalization contract (NOT upstream source):
child processes (node templates, yt-dlp) must decode/encode text as UTF-8
regardless of the host locale code page (Windows cp949/cp936, mojibake).

Contract (invariants — locked by tests/test_proc_utf8.py):
  - idempotent: utf8_env(utf8_env_result) == utf8_env_result
  - non-destructive: operator-set LC_ALL/LANG preserved via setdefault
    (PHIL-02 fail-safe: unknown override ignored, existing wins)
  - pure: no os.environ mutation (copy only) — PHIL-04
  - PYTHONUTF8=1 is forced unconditionally (primary defense; works even
    when C.UTF-8 is absent, e.g. macOS, and forces Python child text I/O
    to UTF-8 regardless of LANG).
"""
from __future__ import annotations
import os


def utf8_env(extra: dict | None = None) -> dict:
    env = os.environ.copy()
    # forced (the core mojibake defense — overrides any inherited value)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # fail-safe: preserve operator-explicit locale; only supply a default
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault("LANG", "C.UTF-8")
    if extra:
        env.update(extra)
    return env
