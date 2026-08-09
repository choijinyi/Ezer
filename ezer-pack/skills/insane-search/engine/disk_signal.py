"""OPP-10: side-effect-free disk-signal disambiguator — dormant vs absent.

Why (AgentReach OPP-10): the engine's availability sense is in-memory /
runtime-only (`transport.py:37` `_Entry.warmed`, `transport.py:60-62` /
`phase0.py:42` `try: import ... except ImportError`). A fresh process therefore
cannot tell a *dormant* resource (installed on disk / a warm session cache that
just isn't loaded in THIS process) from a genuinely *absent* one, so it risks
calling a dormant resource "absent" and deprioritising it.

This module reads only **side-effect-free disk traces** to split that ambiguity
BEFORE any runtime probe:

    READY_DORMANT  disk trace present  → expect it to work once awoken
    ABSENT         no disk trace       → genuinely not installed
    UNKNOWN        could not read the signal (perm / odd state) → DO NOT demote;
                   the runtime probe (or validators.Verdict.UNKNOWN) decides

Responsibility boundary vs validators.Verdict.UNKNOWN (validators.py:91):
  * validators.UNKNOWN already covers the runtime outcome "exception / dependency
    missing" (an executed import / fetch failed). It is a *runtime* verdict.
  * disk_signal is a *pre-runtime, disk-only* pre-classification. It never
    executes the dependency, never opens a socket, never imports the target
    module (find_spec finds the loader, it does NOT run module code). ABSENT here
    is a disk fact, not a re-invention of the runtime UNKNOWN — and disk_signal's
    own UNKNOWN means "couldn't read the trace", which is deliberately
    non-demoting (the runtime path stays authoritative).

Side-effect honesty:
  * dep_signal / warm_signal are READ-ONLY (find_spec / os.stat / glob only).
  * persist_warm WRITES a new disk surface (~/.insane_search/sessions/), mitigated
    by 0o600 + atomic os.replace + never reading cookie contents. It is NOT
    "side-effect-free"; it is a new disk surface, called only after a successful
    real warmup.

No-Site-Name Rule (R3): warm-cache keys are a sha1(host)[:16] hash — the same
hashing convention as executor.py:48 (per-host Chrome profile dir), and stricter
than the plaintext-host keys in transport.py:25-26 / learning.py:56-59. No site
name is ever stored or branched here. bias_check.py auto-scans this file.

INSANE_NO_DISK_SIGNAL=1 disables warm-cache persistence (full rollback safety).
"""
from __future__ import annotations

import glob
import hashlib
import importlib.util
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Avail(str, Enum):
    READY_DORMANT = "ready_dormant"   # disk trace present — expect it to work when awoken
    ABSENT = "absent"                 # no disk trace — genuinely not installed
    UNKNOWN = "unknown"               # could not read the signal — DO NOT demote


@dataclass(frozen=True)
class Signal:
    avail: Avail
    evidence: str                     # e.g. "find_spec:curl_cffi@/.../curl_cffi/__init__.py"
    age_secs: Optional[float] = None  # warm-cache freshness; None for deps

    def to_dict(self) -> dict:
        return {"avail": self.avail.value, "evidence": self.evidence, "age_secs": self.age_secs}


# Default warm-cache freshness window (seconds). Override via INSANE_WARM_TTL.
def warm_ttl() -> int:
    try:
        return int(os.environ.get("INSANE_WARM_TTL", "1800"))
    except (TypeError, ValueError):
        return 1800


def disk_signal_enabled() -> bool:
    """warm-cache persistence master switch (mirrors transport.pool_enabled)."""
    return os.environ.get("INSANE_NO_DISK_SIGNAL", "") not in ("1", "true", "yes")


def sessions_dir() -> str:
    """Warm-session cache dir. Same parent as learning.py's learned.json."""
    base = os.environ.get("INSANE_SESSIONS_DIR")
    if base:
        return base
    return os.path.join(os.path.expanduser("~"), ".insane_search", "sessions")


def _host_hash(host: str) -> str:
    """sha1(host)[:16] — same convention as executor.py:48 (No-Site-Name)."""
    return hashlib.sha1((host or "unknown").lower().encode("utf-8", "ignore")).hexdigest()[:16]


# --- Dependency signal (READ-ONLY: importlib.util.find_spec — no import run) --
def dep_signal(modname: str) -> Signal:
    """Disk trace of a python dependency, WITHOUT importing it.

    find_spec locates the loader/metadata only; it does not execute module code,
    so this is side-effect-free (no socket, target module not added to
    sys.modules). It proves the module is *on disk*, NOT that it imports cleanly
    (a broken C-ABI extension still has a spec) — so READY_DORMANT means
    "disk trace present", and the runtime probe still confirms ok vs broken.
    """
    try:
        spec = importlib.util.find_spec(modname)
    except (ImportError, ValueError, ModuleNotFoundError, AttributeError) as e:
        # find_spec can raise on a half-broken parent package — do NOT demote to
        # ABSENT (that would be the very dormant-as-absent misread we prevent).
        return Signal(Avail.UNKNOWN, f"find_spec_error:{modname}:{type(e).__name__}")
    if spec is None:
        return Signal(Avail.ABSENT, f"find_spec:{modname}=None")
    origin = getattr(spec, "origin", None)
    if origin and origin not in ("built-in", "frozen") and os.path.exists(origin):
        return Signal(Avail.READY_DORMANT, f"find_spec:{modname}@{origin}")
    if origin in ("built-in", "frozen"):
        return Signal(Avail.READY_DORMANT, f"find_spec:{modname}@{origin}")
    # Namespace package (origin None) or origin path vanished → can't assert disk.
    locs = list(getattr(spec, "submodule_search_locations", []) or [])
    if locs:
        return Signal(Avail.READY_DORMANT, f"find_spec:{modname}@ns:{locs[0]}")
    return Signal(Avail.UNKNOWN, f"find_spec:{modname}@no-origin")


def browser_binary_signal(globs: list[str]) -> Signal:
    """READ-ONLY disk trace for a downloaded browser binary (playwright chromium).

    Checks a list of candidate glob patterns; first match → READY_DORMANT.
    No glob match → ABSENT. glob raising (perm) → UNKNOWN.
    """
    try:
        for pat in globs:
            hits = glob.glob(os.path.expanduser(pat))
            if hits:
                return Signal(Avail.READY_DORMANT, f"glob:{pat}@{hits[0]}")
        return Signal(Avail.ABSENT, f"glob:{';'.join(globs)}=none")
    except OSError as e:
        return Signal(Avail.UNKNOWN, f"glob_error:{type(e).__name__}")


# Known content-channel deps → how to read their disk trace (READ-ONLY).
# kind: "module" uses dep_signal; "browser_binary" uses browser_binary_signal.
CONTENT_DEPS: dict = {
    "curl_cffi": {"kind": "module", "module": "curl_cffi"},
    "yt_dlp": {"kind": "module", "module": "yt_dlp"},
    "playwright": {"kind": "module", "module": "playwright"},
    "playwright_chromium": {
        "kind": "browser_binary",
        "globs": [
            "~/Library/Caches/ms-playwright/chromium-*/",
            "~/.cache/ms-playwright/chromium-*/",
        ],
    },
}


def content_dep_signals() -> dict:
    """Read every content-channel dependency's disk signal. READ-ONLY.

    Returns {dep_id: Signal-as-dict}. Used as a diagnostic field (fetch_chain
    result) and by the preflight C-check — never as a gate that demotes a route.
    """
    out: dict = {}
    for dep_id, spec in CONTENT_DEPS.items():
        if spec["kind"] == "browser_binary":
            sig = browser_binary_signal(spec["globs"])
        else:
            sig = dep_signal(spec["module"])
        out[dep_id] = sig.to_dict()
    return out


# --- Session warmth signal (READ-ONLY: existence + mtime; contents NOT read) --
def _warm_path(host: str, impersonate: str) -> str:
    return os.path.join(sessions_dir(), f"{_host_hash(host)}__{impersonate}.cookiejar")


def warm_signal(host: str, impersonate: str) -> Signal:
    """Disk trace of a prior warm session for (host, impersonate). READ-ONLY.

    Existence + freshness only — cookie CONTENTS are never read (privacy-0 +
    side-effect-0). Fresh (< warm_ttl) → READY_DORMANT(age_secs). Expired/missing
    → ABSENT. stat failure → UNKNOWN (fail-safe: caller does the normal warmup).
    """
    path = _warm_path(host, impersonate)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return Signal(Avail.ABSENT, f"warm:{_host_hash(host)}__{impersonate}=missing")
    except OSError as e:
        return Signal(Avail.UNKNOWN, f"warm_stat_error:{type(e).__name__}")
    age = max(0.0, time.time() - st.st_mtime)
    if age < warm_ttl():
        return Signal(Avail.READY_DORMANT, f"warm:{_host_hash(host)}__{impersonate}@{int(st.st_mtime)}", age_secs=age)
    return Signal(Avail.ABSENT, f"warm:{_host_hash(host)}__{impersonate}=stale", age_secs=age)


# --- persist_warm: WRITES a new disk surface (NOT side-effect-free) -----------
def persist_warm(host: str, impersonate: str, cookies: list) -> bool:
    """Atomically persist a warm-session marker after a successful real warmup.

    NOT side-effect-free — this is a new disk surface, mitigated by 0o600 +
    O_EXCL atomic create → os.replace (no world-readable window; learning.py:110-119
    pattern) and by storing only cookie NAMES (never values → privacy). A no-op
    when disabled (INSANE_NO_DISK_SIGNAL=1) or on any OS error (best-effort,
    never breaks a fetch). Returns True only when a file was written.
    """
    if not disk_signal_enabled():
        return False
    path = _warm_path(host, impersonate)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        names = []
        for c in cookies or []:
            try:
                n = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
            except Exception:
                n = None
            if n:
                names.append(str(n))
        payload = ("warm\t%d\t%d\t%s\n" % (int(time.time()), len(names), ",".join(names[:50]))).encode("utf-8", "ignore")
        # O_EXCL atomic create at 0o600 → no open-then-chmod race window.
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return False
