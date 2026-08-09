# Contributing

Thanks for your interest in EZERagent.

## Ground rules

- **Before large PRs, open an issue first** — the project has strong conventions
  (deterministic gates, fail-closed guards, Korean-first docs) and we want to
  align direction before you invest time.
- Match the existing style of the file you touch (comment density, naming, 한국어 주석 유지).
- Every changed line should be traceable to the issue/PR intent (surgical diffs).

## Checks that must pass

```bash
cargo test --bin EZERagentd            # daemon unit tests
cargo check -p EZERagent-app           # desktop app
bash ui/build.sh                 # UI bundle
bash scripts/secret-scan.sh --all  # secret/PII gate (fail-closed)
sh scripts/version-check.sh      # version SOT consistency (release PRs only)
```

## Licensing

By contributing you agree your contributions are licensed under the MIT License.
Third-party code must be MIT/Apache-2.0-compatible and attributed in `NOTICE.md`
(and `EZERagent-pack/skills/THIRD_PARTY.md` for pack skills).
