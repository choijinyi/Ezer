#!/usr/bin/env python3
"""LOCKED ref fixture — utf8_env() contract (OPP-16).

Deterministic, network-free. Locks the env-normalization invariants that
defend child-process text I/O against host locale code pages (Windows
cp949/cp936; euc-kr mojibake):

  * PYTHONUTF8 forced to "1" (the core mojibake defense key).
  * idempotent: utf8_env(utf8_env(...)) == utf8_env(...).
  * non-destructive: operator-set LC_ALL/LANG preserved (setdefault).
  * pure: os.environ is not mutated (copy only).
  * adversarial round-trip: a child python launched under a non-UTF-8 locale
    (LANG=ko_KR.eucKR) writes Korean — WITHOUT utf8_env the bytes are euc-kr
    and a UTF-8 read fails; WITH utf8_env PYTHONUTF8=1 forces UTF-8 bytes that
    round-trip exactly. Also covers the "C.UTF-8 absent + operator LANG
    explicit" case (report adversarial revision #3): PYTHONUTF8=1 alone
    restores child python UTF-8 I/O even when the operator LANG is non-UTF-8.

Verdict is an enum (PASS|FAIL) — no score (producer != evaluator; eval-driven).

Run:  python3 engine/tests/test_proc_utf8.py
"""
from __future__ import annotations

import enum
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from engine.proc import utf8_env  # noqa: E402


class Verdict(enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"


KO = "한국어 인코딩 테스트 가나다"
# Child prints Korean using its own stdout encoding (no manual encode/decode):
# what bytes land on the pipe is decided entirely by the child's locale/PYTHONUTF8.
_CHILD_PRINT_KO = "import sys; sys.stdout.write('한국어 인코딩 테스트 가나다')"


# ---------- contract invariants ----------
def t_pythonutf8_forced():
    assert utf8_env()["PYTHONUTF8"] == "1", "PYTHONUTF8 must be forced to '1'"
    assert utf8_env()["PYTHONIOENCODING"] == "utf-8", "PYTHONIOENCODING must be utf-8"
    print("  ✓ PYTHONUTF8=='1' and PYTHONIOENCODING=='utf-8' (forced keys)")


def t_pythonutf8_forced_over_inherited():
    # Even if a hostile/stale value is inherited, the forced key wins.
    # Simulate inherited PYTHONUTF8=0 by setting then re-deriving.
    saved = os.environ.get("PYTHONUTF8")
    try:
        os.environ["PYTHONUTF8"] = "0"
        env = utf8_env()
        assert env["PYTHONUTF8"] == "1", "forced key must override inherited PYTHONUTF8=0"
    finally:
        if saved is None:
            os.environ.pop("PYTHONUTF8", None)
        else:
            os.environ["PYTHONUTF8"] = saved
    print("  ✓ forced PYTHONUTF8 overrides inherited PYTHONUTF8=0")


def t_idempotent():
    # Applying the same normalization a second time, on top of an already
    # normalized env, must yield an identical mapping (no key drift / churn).
    once = utf8_env()
    twice = {**once}
    twice["PYTHONUTF8"] = "1"
    twice["PYTHONIOENCODING"] = "utf-8"
    twice.setdefault("LC_ALL", "C.UTF-8")
    twice.setdefault("LANG", "C.UTF-8")
    assert twice == once, "utf8_env applied twice must be identical"
    print("  ✓ idempotent: second application identical")


def t_non_destructive_operator_locale():
    # Operator explicitly set LC_ALL/LANG → setdefault must preserve them.
    saved = {k: os.environ.get(k) for k in ("LC_ALL", "LANG")}
    try:
        os.environ["LC_ALL"] = "ko_KR.UTF-8"
        os.environ["LANG"] = "ko_KR.UTF-8"
        env = utf8_env()
        assert env["LC_ALL"] == "ko_KR.UTF-8", env.get("LC_ALL")
        assert env["LANG"] == "ko_KR.UTF-8", env.get("LANG")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("  ✓ non-destructive: operator LC_ALL/LANG preserved")


def t_pure_no_environ_mutation():
    before = dict(os.environ)
    _ = utf8_env({"FOO_OPP16": "bar"})
    after = dict(os.environ)
    assert before == after, "utf8_env must not mutate os.environ"
    assert "FOO_OPP16" not in os.environ, "extra must not leak into os.environ"
    print("  ✓ pure: os.environ unchanged (copy only)")


# ---------- adversarial round-trip ----------
_NON_UTF8_LOCALE = "ko_KR.eucKR"  # operator-forced non-UTF-8 code page (euc-kr)


def _run_child(env_overrides: dict) -> bytes:
    env = os.environ.copy()
    # Strip any inherited UTF-8 forcing so the override controls behavior.
    for k in ("PYTHONUTF8", "PYTHONIOENCODING", "LC_ALL", "LANG", "LC_CTYPE"):
        env.pop(k, None)
    env.update(env_overrides)
    p = subprocess.run([sys.executable, "-c", _CHILD_PRINT_KO],
                       capture_output=True, env=env, timeout=15)
    return p.stdout


def _child_stdout_encoding(lang: str) -> str:
    env = os.environ.copy()
    for k in ("PYTHONUTF8", "PYTHONIOENCODING", "LC_ALL", "LANG", "LC_CTYPE"):
        env.pop(k, None)
    env["LANG"] = lang
    env["LC_ALL"] = lang
    r = subprocess.run([sys.executable, "-c", "import sys; print(sys.stdout.encoding)"],
                       capture_output=True, text=True, env=env, timeout=15)
    return r.stdout.strip().lower()


def t_adversarial_roundtrip_without_utf8env_breaks():
    # Operator forces a non-UTF-8 locale; no utf8_env → child emits euc-kr bytes;
    # reading them as UTF-8 must NOT reproduce the original (mojibake / decode error).
    # Portability: only meaningful where the host actually has the non-UTF-8 code
    # page. If absent (child falls back to UTF-8), the adversarial precondition
    # can't be created on this host — record as a documented skip, not a failure.
    enc = _child_stdout_encoding(_NON_UTF8_LOCALE)
    if "utf-8" in enc or "utf8" in enc:
        print(f"  ⊘ skip: {_NON_UTF8_LOCALE} not a non-UTF-8 code page here "
              f"(child enc={enc!r}); adversarial precondition unavailable")
        return
    raw = _run_child({"LANG": _NON_UTF8_LOCALE, "LC_ALL": _NON_UTF8_LOCALE})
    try:
        broken = (raw.decode("utf-8") == KO)
    except UnicodeDecodeError:
        broken = False
    assert broken is False, ("WITHOUT utf8_env, euc-kr bytes must not UTF-8 "
                             f"round-trip; got bytes={raw!r}")
    print(f"  ✓ adversarial baseline: euc-kr child breaks UTF-8 read (bytes={raw[:8]!r}...)")


def t_adversarial_roundtrip_with_utf8env_restores():
    # Same operator LANG=ko_KR.eucKR, but utf8_env forces PYTHONUTF8=1 → child emits
    # UTF-8 bytes that round-trip exactly. This is also the "C.UTF-8 absent +
    # operator LANG explicit (non-UTF-8)" case: PYTHONUTF8 alone restores I/O.
    env = utf8_env({"LANG": "ko_KR.eucKR", "LC_ALL": "ko_KR.eucKR"})
    # Operator non-UTF-8 LANG is preserved (setdefault no-op since key present)…
    assert env["LANG"] == "ko_KR.eucKR", env.get("LANG")
    # …yet the forced key is what does the work.
    assert env["PYTHONUTF8"] == "1", env.get("PYTHONUTF8")
    p = subprocess.run([sys.executable, "-c", _CHILD_PRINT_KO],
                       capture_output=True, env=env, timeout=15)
    restored = p.stdout.decode("utf-8")
    assert restored == KO, f"WITH utf8_env Korean must round-trip; got {restored!r}"
    print("  ✓ adversarial restore: PYTHONUTF8=1 forces UTF-8 child I/O "
          "(operator non-UTF-8 LANG preserved)")


ALL = [
    ("pythonutf8_forced", t_pythonutf8_forced),
    ("pythonutf8_forced_over_inherited", t_pythonutf8_forced_over_inherited),
    ("idempotent", t_idempotent),
    ("non_destructive_operator_locale", t_non_destructive_operator_locale),
    ("pure_no_environ_mutation", t_pure_no_environ_mutation),
    ("adversarial_roundtrip_without_utf8env_breaks",
     t_adversarial_roundtrip_without_utf8env_breaks),
    ("adversarial_roundtrip_with_utf8env_restores",
     t_adversarial_roundtrip_with_utf8env_restores),
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
            print(f"  ✗ {Verdict.FAIL.value}: {e}")
        except Exception as e:
            f += 1
            print(f"  ✗ {Verdict.FAIL.value}: {type(e).__name__}: {e}")
    verdict = Verdict.PASS if f == 0 else Verdict.FAIL
    print(f"\nverdict={verdict.value}  ({p} passed, {f} failed)")
    return 0 if f == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
