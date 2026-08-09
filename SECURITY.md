# Security Policy

## Reporting a vulnerability

Please report security issues privately to **ezer.agent@gmail.com**.
Do not open public issues for vulnerabilities. You should receive a response
within a few days; coordinated disclosure is appreciated.

## Scope notes

- The desktop app talks to a local daemon (`EZERagentd`) over a user-owned Unix socket
  (macOS/Linux) or a DACL-sealed named pipe (Windows). No network listener is opened.
- Updates are verified: app binaries via Tauri updater signatures, packs via
  minisign (`pack-manifest.json.minisig`, key pinned in the binary).
- External URL opening is gated by a hard host allowlist
  (`~/.EZERagent/url-allow-hosts` / `EZERAGENT_URL_ALLOW_HOSTS` extend it locally only).
- A pre-publish secret/PII gate exists at `scripts/secret-scan.sh --all`
  (fail-closed; static pattern matching — see its header for honest limits).
