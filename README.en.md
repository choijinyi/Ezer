# EZERagent

**An orchestration terminal for commanding fleets of AI agents.** Cross-platform: macOS & Windows.

A terminal multiplexer, a local daemon, and a mission-control dashboard in one body.
Run multiple CLI agents (Claude Code, Codex, …) in parallel under distinct roles
(master / worker / reviewer), let them talk to each other over sockets, and monitor
cost, context, and hardware in real time.

> Most of this codebase was **written by AI agents under human direction** — the
> `Co-Authored-By` chain in the commit log is the record of that process. The
> repository itself is a working proof that AI-fleet orchestration is real.

*한국어 문서(전체 레퍼런스 포함)는 [README.md](README.md)를 보세요.*

## Docs

- **[Architecture & Philosophy](ARCHITECTURE-AND-PHILOSOPHY.md)** — design theses, system architecture, security model, invariants (Korean)
- **[User Manual](USER-MANUAL.md)** — install to fleet operations, full CLI/env/protocol reference (Korean)

## Why

Existing terminals and multiplexers are built for humans typing commands. Run several
AI agents in them and you hit three walls fast: panes cannot talk to each other, orphan
servers left by agents pile up until the machine chokes, and nobody can see who is
spending what. EZERagent is an independent, from-scratch implementation that makes
those three problems first-class features.

## Design Principles (ABSOLUTE)

1. **Bidirectional socket communication** — no one-way send + capture polling.
   Every pane on the same socket is an **equal node** that can actively push to any
   other pane by surface ID (`EZERagent send` → injected directly into the target PTY stdin
   → arrives as a new user turn). Server→client is the `EZERagent events` push stream
   (sequence numbers, resume on reconnect).
2. **Resource governance as a first-class feature** — built-in mitigation for orphan
   server accumulation (→ load explosion → 401/hang): process ledger, watchdog,
   scoped execution with lifecycle-enforced teardown.
3. **Core/UI separation** — the daemon (`EZERagentd`) runs independently of any UI. Even if
   the UI hangs, the socket control channel stays alive (out-of-band recovery).

## Highlights

- **Agent fleet orchestration** — `EZERagent launch-agent --role worker --agent claude`
  boots role-based nodes (directives auto-injected); route messages by role address
  (`--to worker`); department-level daemon isolation for parallel projects.
- **Control Center** — fleet state, tokens/cost (per model, per org tier), session
  timelines with transcript excerpts, skill/tool stats with failure rates and p50
  durations, real-time hardware (per-core CPU, GPU, NPU, memory), approval feed.
- **Signed pack system** — skills/directives/tools ship as a minisign-signed pack;
  zero-downtime pack updates (sessions and daemon survive) are separate from app
  binary updates (Tauri updater), both fail-closed on signature verification.
- **Jarvis-native operations** — self-reported agent status, context-cycle executor,
  agent-death detection and recovery, directive drift detection/reinjection,
  transcript hash-chain attestation, kill-switch, one-shot timers, typing guards.

## Install

Grab the latest from [Releases](https://github.com/choijinyi/Ezer/releases/latest).
No separate daemon setup — the app boots it and installs the pack automatically.

- **macOS**: `EZERagent_<version>_aarch64.dmg` (Apple Silicon) — drag to install, launch, done.
- **Windows**: `EZERagent_<version>_x64-setup.exe` — daemon, CLI, and runtime bundled (self-contained).
- Optional 24/365 daemon: `EZERagent daemon install` (launchd KeepAlive / Task Scheduler).
- Use `EZERagent` from external terminals: app Control Center → **"Install EZERagent to shell"** (one click).

Details: [docs/INSTALL.md](docs/INSTALL.md).

## Quick Start

```bash
EZERagent identify                                  # who am I (surface address)
EZERagent launch-agent --role worker --agent claude # boot a role node (directives auto-injected)
EZERagent send --to worker "status report, please"  # push by role address
EZERagent send-key --to worker Return               # confirm submission
EZERagent status --json                             # one-call fleet snapshot
EZERagent events --reconnect                        # push event stream (replaces polling)
EZERagent run --scoped -- python -m http.server     # lifecycle-managed scoped execution
```

## Architecture

```
EZERagent.app  Tauri desktop app: terminal UI (xterm.js) + Control Center — thin client of the daemon
EZERagentd     headless core daemon: NDJSON socket server (UDS / Windows named pipe),
         PTY (portable-pty: openpty / ConPTY), vt100 screen reconstruction, event bus,
         watchdog & process ledger, usage/cost collectors, persistent analytics (SQLite)
EZERagent      CLI: the equal-node client used by the AI inside each pane
pack     EZERagent-pack/: skills, directives, hooks, tools (embedded at build, signed at distribution)
```

Every pane process gets `EZERAGENT_SURFACE_ID`, `EZERAGENT_SURFACE_REF`, `EZERAGENT_SOCKET` injected
automatically — the AI inside a pane learns its own address instantly via `EZERagent identify`.

## Security model

- No network listener — user-owned Unix socket (macOS) / DACL-sealed named pipe (Windows).
- Dual-signed updates — app binaries via Tauri updater signatures, packs via minisign
  (public key pinned in the binary).
- External URL opening is gated by a hard host allowlist (extendable only via local
  config `~/.EZERagent/url-allow-hosts`). Approvals are human-in-the-loop; nothing auto-answers.
- Pre-publish secret/PII gate: `scripts/secret-scan.sh --all` (fail-closed).

Report vulnerabilities per [SECURITY.md](SECURITY.md).

## Full reference

Protocol methods/events, environment variables, governance tables, the 19 Jarvis-native
features, approval feed, in-flight queue semantics, and source-build instructions are
documented in the Korean [README.md](README.md) and the
[User Manual](USER-MANUAL.md) (the canonical references).

## Contributing · License

See [CONTRIBUTING.md](CONTRIBUTING.md) and [NOTICE.md](NOTICE.md) (third-party attributions).
MIT License ([LICENSE](LICENSE)) · Contact: **ezer.agent@gmail.com**
