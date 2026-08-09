# NOTICE — Third-Party Attributions

ezer-agent is licensed under the MIT License (see `LICENSE`).
This file consolidates third-party attributions for discoverability.

## Upstream

Ezer agent is a rebranded derivative of **cys-terminal**
(https://github.com/idoforgod/cys-terminal), MIT — Copyright (c) 2026 CYSJavis.
The upstream copyright notice is retained in `LICENSE` as the MIT License requires.
All `cys`/`CYSJavis` identifiers were renamed to `ezer`/`Ezer`; the architecture,
core mechanics, and pack contents originate upstream.

## Vendored code

| Component | Path | Upstream | License |
|---|---|---|---|
| portable-pty (patched) | `vendor/portable-pty/` | wezterm (Wez Furlong) | MIT — original copyright preserved in `vendor/portable-pty/LICENSE.md` |
| insane-search | `ezer-pack/skills/insane-search/` | fivetaku/insane-search | MIT — see `ezer-pack/skills/THIRD_PARTY.md` |
| skill collections (32 skills) | `ezer-pack/skills/` | NomaDamas/k-skill · obra/superpowers · mattpocock/skills | MIT — commit-pinned attributions in `ezer-pack/skills/THIRD_PARTY.md` |

## Design-only references (no code vendored)

Voicebox (MIT) and TimesFM (Apache-2.0) informed designs; no code was copied.
Clean-room reimplementation notes are embedded at the referencing sites
(`ezer-pack/bin/ezer_*.py` headers) and in `ezer-pack/skills/THIRD_PARTY.md`.

## Dependencies

Rust crate and npm dependencies are declared in `Cargo.toml` / `src-tauri/Cargo.toml` /
`ui/package.json`; direct dependencies are MIT or MIT/Apache-2.0 dual-licensed.
SQLite (bundled via rusqlite) is public domain.
