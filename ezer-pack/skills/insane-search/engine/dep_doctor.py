"""OPP-11: broken-hint diagnosis — install-source-aware re-install PRESCRIPTIONS.

Why (AgentReach OPP-11): content deps (curl_cffi / yt-dlp / playwright) are sensed
binary "there / not there". When one is *broken* the engine surfaces only a flat
string — `transport.py:159-160` returns "curl_cffi not installed",
`executor.py:57-63` `_chrome_channel_available()` is a node/npx heuristic that
can't tell "playwright PACKAGE installed" from "chromium BINARY not downloaded".
There is no "WHY is it broken and which single command fixes it (for THIS install
source)" mapping, so a worker guesses `pip install` and can corrupt the machine
(e.g. `pip --user` over a uv-tool install = two broken copies).

Design (per worker directive — the report's Rust diagnosis engine is ABANDONED):
  * Diagnosis lives in the SAME Python layer as the strings it diagnoses
    (transport.py / phase0.py / executor.py are Python), so the prescription
    lives there too. No Rust crate, no `probe.py`, no `cli.py`, no `base.py`
    (those AR upstream files do not exist in ezer — phantom coordinates).
  * The prescription mapping is declarative Python data (PRESCRIPTIONS), not a
    toml embedded in a Rust binary.
  * It PRESCRIBES ONLY — it never runs an install. Actual execution is the
    worker's job inside the autonomous-pilot boundary, or preflight --fix /
    OPP-17 (--dry-run / --safe Mutation gate). dep_doctor itself opens no socket
    and changes no system state beyond a side-effect-free probe.

Verdict vocabulary (eval-driven §7): enum + evidence + fix, NO score. Reuses
disk_signal.Avail for the disk pre-classification; DepState carries the broken
sub-state. Aligns with VALIDATION_VERDICT_VOCAB.md spirit (non-terminal vs fix-
able), never the prose status AR rejected.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from . import disk_signal


class DepState(str, Enum):
    OK = "ok"                      # disk trace present (import not asserted here)
    MISSING = "missing"            # no disk trace → genuinely absent
    BROKEN_SHIM = "broken_shim"    # disk trace present but loader/shim severed
    BINARY_MISSING = "binary_missing"  # package present, downloaded binary absent (playwright chromium)
    UNKNOWN = "unknown"            # could not read the signal → DO NOT demote


class InstallSource(str, Enum):
    UV_TOOL = "uv_tool"
    PIPX = "pipx"
    BREW = "brew"
    PIP_USER = "pip_user"
    PIP_VENV = "pip_venv"
    NPM_GLOBAL = "npm_global"
    NODE_LOCAL = "node_local"
    GIT_SOURCE = "git_source"
    SYSTEM = "system"
    UNKNOWN = "unknown"


@dataclass
class DepVerdict:
    dep_id: str
    state: DepState
    source: InstallSource
    prescription: Optional[str] = None   # single command STRING — presented, never run
    evidence: str = ""                   # the actual side-effect-free observation
    code_ref: str = ""                   # source location of the flat error this replaces
    fixable: bool = False
    side_effect_free: bool = True        # this diagnosis ran no install / opened no socket
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dep_id": self.dep_id,
            "state": self.state.value,
            "source": self.source.value,
            "prescription": self.prescription,
            "evidence": self.evidence,
            "code_ref": self.code_ref,
            "fixable": self.fixable,
            "side_effect_free": self.side_effect_free,
            "notes": self.notes,
        }

    def hint_text(self) -> str:
        """One-line human-readable hint. Presents the prescription; never runs it."""
        if self.state == DepState.OK:
            return f"{self.dep_id}: ok ({self.evidence})"
        head = f"{self.dep_id}: {self.state.value} [source={self.source.value}]"
        if self.prescription:
            return f"{head} → fix (run manually, in-boundary): {self.prescription}"
        return f"{head} (no prescription — investigate; do NOT guess pip install)"


# --- Prescription mapping (declarative DATA — presented, never executed) ------
# Per (dep_id, source) → a single re-install command STRING. `unknown` is the
# conservative fail-safe (pip --user, reversible). brew is flagged irreversible
# (worker boundary → owner hold). `binary_missing` deps prescribe the browser
# download, NOT a package reinstall (the playwright 2-layer distinction AR lacks).
PRESCRIPTIONS: dict = {
    "curl_cffi": {
        "kind": "python", "module": "curl_cffi", "min_version": "0.15",
        "rx": {
            InstallSource.UV_TOOL: "uv tool install --reinstall 'curl_cffi>=0.15'",
            InstallSource.PIPX: "pipx runpip curl_cffi install -U 'curl_cffi>=0.15'  # or: pipx reinstall curl_cffi",
            InstallSource.BREW: "brew reinstall curl_cffi",
            InstallSource.PIP_USER: "python3 -m pip install --user -U 'curl_cffi>=0.15'",
            InstallSource.PIP_VENV: "python3 -m pip install -U 'curl_cffi>=0.15'",
            InstallSource.UNKNOWN: "python3 -m pip install --user -U 'curl_cffi>=0.15'",
        },
    },
    "yt_dlp": {
        "kind": "python", "module": "yt_dlp",
        "rx": {
            InstallSource.UV_TOOL: "uv tool install --reinstall yt-dlp",
            InstallSource.PIPX: "pipx reinstall yt-dlp",
            InstallSource.BREW: "brew reinstall yt-dlp",
            InstallSource.PIP_USER: "python3 -m pip install --user -U yt-dlp",
            InstallSource.PIP_VENV: "python3 -m pip install -U yt-dlp",
            InstallSource.UNKNOWN: "python3 -m pip install --user -U yt-dlp",
        },
    },
    "playwright": {
        "kind": "python", "module": "playwright",
        "rx": {
            InstallSource.UV_TOOL: "uv tool install --reinstall playwright",
            InstallSource.PIPX: "pipx reinstall playwright",
            InstallSource.PIP_USER: "python3 -m pip install --user -U playwright",
            InstallSource.PIP_VENV: "python3 -m pip install -U playwright",
            InstallSource.NPM_GLOBAL: "npm install -g playwright",
            InstallSource.NODE_LOCAL: "npm install playwright",
            InstallSource.UNKNOWN: "python3 -m pip install --user -U playwright",
        },
    },
    # ★ package != downloaded browser binary — a separate dep (AR's missing 2nd layer).
    "playwright_chromium": {
        "kind": "browser_binary",
        "rx": {
            InstallSource.NODE_LOCAL: "npx playwright install chromium",
            InstallSource.NPM_GLOBAL: "npx playwright install chromium",
            InstallSource.UNKNOWN: "python3 -m playwright install chromium  # or: npx playwright install chromium",
        },
    },
}

# Sources whose re-install command can remove system packages → irreversible →
# worker autonomy withheld (autonomous-pilot denylist: owner hold).
_IRREVERSIBLE_SOURCES = frozenset({InstallSource.BREW})


def _detect_source(origin: Optional[str]) -> InstallSource:
    """Infer the install source from a module's on-disk origin path.

    Path-substring heuristic only (no execution). Returns UNKNOWN when it can't
    tell — the conservative branch (a reversible pip --user prescription)."""
    if not origin:
        return InstallSource.UNKNOWN
    p = origin.replace("\\", "/").lower()
    if "/pipx/venvs/" in p or "/pipx/" in p:
        return InstallSource.PIPX
    if "/uv/tools/" in p or "/uv/tool/" in p:
        return InstallSource.UV_TOOL
    if "/cellar/" in p or "/opt/homebrew/" in p or "/homebrew/" in p:
        return InstallSource.BREW
    if p.endswith(".egg-link") or "/site-packages/__editable__" in p or ".pth" in p:
        return InstallSource.GIT_SOURCE
    # ~/.local/lib (PEP 370 user site)
    user_base = (os.environ.get("PYTHONUSERBASE") or os.path.join(os.path.expanduser("~"), ".local")).replace("\\", "/").lower()
    if user_base and user_base in p:
        return InstallSource.PIP_USER
    if "/.local/lib/" in p:
        return InstallSource.PIP_USER
    # Active venv?
    venv = (sys.prefix or "").replace("\\", "/").lower()
    base = (getattr(sys, "base_prefix", sys.prefix) or "").replace("\\", "/").lower()
    if venv and venv != base and venv in p:
        return InstallSource.PIP_VENV
    return InstallSource.UNKNOWN


def _module_origin(modname: str) -> Optional[str]:
    """Side-effect-free origin path of a module (find_spec — no import run)."""
    try:
        import importlib.util
        spec = importlib.util.find_spec(modname)
    except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
        return None
    if spec is None:
        return None
    return getattr(spec, "origin", None)


def _lookup_rx(dep_id: str, source: InstallSource) -> Optional[str]:
    rx = (PRESCRIPTIONS.get(dep_id) or {}).get("rx") or {}
    return rx.get(source) or rx.get(InstallSource.UNKNOWN)


def diagnose(dep_id: str, *, code_ref: str = "") -> DepVerdict:
    """Side-effect-free diagnosis of a content dependency → DepVerdict.

    Reads disk_signal (no import run, no socket, no install) → maps the disk
    fact to a DepState → detects the install source → looks up the single
    re-install command STRING. PRESCRIBES ONLY; never executes anything.
    """
    spec = PRESCRIPTIONS.get(dep_id)
    if spec is None:
        return DepVerdict(dep_id, DepState.UNKNOWN, InstallSource.UNKNOWN,
                          evidence=f"unknown_dep:{dep_id}", code_ref=code_ref)

    if spec.get("kind") == "browser_binary":
        sig = disk_signal.browser_binary_signal(
            disk_signal.CONTENT_DEPS.get(dep_id, {}).get("globs", []))
        if sig.avail == disk_signal.Avail.READY_DORMANT:
            return DepVerdict(dep_id, DepState.OK, InstallSource.UNKNOWN,
                              evidence=sig.evidence, code_ref=code_ref)
        if sig.avail == disk_signal.Avail.UNKNOWN:
            return DepVerdict(dep_id, DepState.UNKNOWN, InstallSource.UNKNOWN,
                              evidence=sig.evidence, code_ref=code_ref,
                              notes=["could not read disk signal — runtime probe authoritative"])
        # ABSENT browser binary → BINARY_MISSING (package may still be present).
        node_local = shutil.which("npx") is not None
        source = InstallSource.NODE_LOCAL if node_local else InstallSource.UNKNOWN
        rx = _lookup_rx(dep_id, source)
        return DepVerdict(dep_id, DepState.BINARY_MISSING, source, prescription=rx,
                          evidence=sig.evidence, code_ref=code_ref, fixable=bool(rx),
                          notes=["package != browser binary — this prescribes the browser download, not a package reinstall"])

    # python module dep
    modname = spec.get("module", dep_id)
    sig = disk_signal.dep_signal(modname)
    if sig.avail == disk_signal.Avail.READY_DORMANT:
        return DepVerdict(dep_id, DepState.OK, _detect_source(_module_origin(modname)),
                          evidence=sig.evidence, code_ref=code_ref)
    if sig.avail == disk_signal.Avail.ABSENT:
        rx = _lookup_rx(dep_id, InstallSource.UNKNOWN)
        return DepVerdict(dep_id, DepState.MISSING, InstallSource.UNKNOWN, prescription=rx,
                          evidence=sig.evidence, code_ref=code_ref, fixable=bool(rx))
    # UNKNOWN disk signal: find_spec raised → likely a severed shim / broken parent.
    # DO NOT demote to absent; prescribe a source-aware reinstall but mark the
    # uncertainty (runtime probe stays authoritative).
    source = _detect_source(_module_origin(modname))
    rx = _lookup_rx(dep_id, source)
    verdict = DepVerdict(dep_id, DepState.BROKEN_SHIM, source, prescription=rx,
                         evidence=sig.evidence, code_ref=code_ref, fixable=bool(rx),
                         notes=["disk signal unreadable — broken shim suspected; runtime probe authoritative"])
    if source in _IRREVERSIBLE_SOURCES:
        verdict.notes.append("prescription is irreversible (brew may remove system pkgs) — worker autonomy WITHHELD, owner hold")
    return verdict


def hint_for(dep_id: str, *, code_ref: str = "") -> str:
    """Convenience: a one-line presented hint string (never runs anything)."""
    try:
        return diagnose(dep_id, code_ref=code_ref).hint_text()
    except Exception as e:
        return f"{dep_id}: dep_doctor error ({type(e).__name__}) — investigate manually"
