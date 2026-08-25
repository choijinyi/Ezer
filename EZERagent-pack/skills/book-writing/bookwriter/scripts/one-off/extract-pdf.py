"""One-off: extract text from /tmp/source.pdf via PyMuPDF, page-aware."""
import pymupdf
import sys

import os
src = os.path.join(os.environ.get("TEMP", "/tmp"), "source.pdf")
doc = pymupdf.open(src)
print(f"pages: {len(doc)}", file=sys.stderr)
parts = []
for i, page in enumerate(doc):
    text = page.get_text("text")
    parts.append(f"<<<PAGE {i+1}>>>")
    parts.append(text)
sys.stdout.reconfigure(encoding="utf-8")
print("\n".join(parts))
