---
description: Show job status. Wraps scripts/pipeline/status.ts.
---

# /status

Arguments: $ARGUMENTS

Execute exactly: `node scripts/pipeline/status.ts $ARGUMENTS`

Read-only. Never modifies state.

- No argument → list latest 20 jobs.
- `<job-id>` → details: stage, ok, pages, file tree, errors.log if any, decisions/polish answer counts.
