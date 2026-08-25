---
description: Run pipeline stages for a job. Wraps scripts/pipeline/run.ts.
---

# /run

Arguments: $ARGUMENTS

Execute exactly: `node scripts/pipeline/run.ts $ARGUMENTS`

If the script exits non-zero, surface stderr verbatim and stop.

If the script exits with code 2 (= gate halt — unanswered `decisions.md` or `polish-proposals.md`), tell the user which file to fill in and stop. Do not auto-fill.

## Argument forms (handled by run.ts, listed for reference)

```
/run <job-id>                     # run all remaining stages
/run <job-id> <stage>             # run one stage
/run <job-id> --polish            # opt into polish proposals
```

Stages: `ingest`, `structure`, `normalize`, `polish-propose`, `apply-polish`, `illustrate`, `typeset`, `export`, `all` (default).

Full contract: `scripts/pipeline/SPEC.md` §2.11.
