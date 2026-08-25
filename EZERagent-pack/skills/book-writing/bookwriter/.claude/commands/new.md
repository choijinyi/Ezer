---
description: Start a bookwriter job, or scaffold a new manuscript. Wraps scripts/pipeline/new.ts.
---

# /new

Arguments: $ARGUMENTS

Execute exactly: `node scripts/pipeline/new.ts $ARGUMENTS`

If the script exits non-zero, surface stderr to the user verbatim. Do not retry, do not paraphrase.

## Argument forms (handled by new.ts, listed for reference)

- `--scaffold <name> [--chapters N] [--lang ko|en] [--template <id>]` — create `manuscripts/<name>/` with N body chapters (default 14).
- `<path-to-manuscript-dir>` — validate `book.json`, snapshot into `build/<job>/input/`, emit `<job-id>` to stdout.
- `<path-to-single.md>` — wrap as a 1-chapter manuscript and proceed.

Full contract: `scripts/pipeline/SPEC.md` §2.1.
