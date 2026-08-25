# Golden tests

End-to-end smoke tests. Each subdirectory is one fixture: a known input plus expected outputs.

## Running

(TBD — runner not yet implemented.)

Planned:
```
npm run test:golden                  # all goldens
npm run test:golden -- short-paper-md  # one fixture
```

The runner will:
1. Copy `input.<ext>` into a fresh `build/<job>/`
2. Execute the full pipeline (`ingest → ... → export`)
3. Validate outputs against `expected.json`
4. If `expected.pdf.sha256` is present, hash-compare. Otherwise structural checks only.

## Adding a new golden

1. `mkdir tests/golden/<name>` and put `input.<ext>` there
2. Write `expected.json` with structural expectations
3. Run the pipeline once, manually inspect the PDF
4. If the PDF is good, record `sha256(book.pdf)` into `expected.pdf.sha256`

## When goldens fail

A failing golden is **not always a regression**. Templates and engines change. The protocol:

1. Inspect the diff (PDF page images, structural JSON)
2. If the change is intentional (new template version), record the new hash
3. If unintentional, fix the bug
4. Never blanket-refresh hashes
