"""Move all image blocks back to a chapter-end `## 도판 (디자인 단계 위치 결정)` section.

Reverses earlier auto-distribution. Photo positions in the manuscript text are
left to the design phase; here we just keep them grouped per chapter for review.
"""
import os
import re

ROOT = "C:\\dev\\bookwriter"
MS_DIR = os.path.join(ROOT, "manuscripts", "soccer-mission-book")

CHAPTER_FILES = [
    "01-collapse.md", "02-sport.md", "03-culture.md", "04-incarnation.md",
    "05-soccer.md", "06-mission.md", "07-fellow.md", "08-missional.md",
    "09-method.md", "10-voices.md", "11-numbers.md", "12-answers.md",
    "13-next.md", "14-forward.md",
]

# Image block pattern:
#   ![](figures/X){width=60%}
#   <blank line>
#   *원본 p123*       (or any caption — capture entire next non-blank line if italicized)
FIG_RE = re.compile(
    r"!\[\]\((figures/[^)\s]+)\)\{width=\d+%\}\s*\n+\s*\*([^*\n]+)\*",
    re.MULTILINE,
)

DOPAN_HEADER_RE = re.compile(r"\n+##\s*도판.*?(?=\n##\s|\Z)", re.DOTALL)


def main():
    total = 0
    for fn in CHAPTER_FILES:
        path = os.path.join(MS_DIR, fn)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

        # 1) Drop any existing ## 도판 section first (idempotent re-run)
        text = DOPAN_HEADER_RE.sub("", text)

        # 2) Find every figure block in body
        figures = []
        for m in FIG_RE.finditer(text):
            figures.append((m.group(1), m.group(2)))

        if not figures:
            continue

        # 3) Remove all figure blocks from body
        text = FIG_RE.sub("", text)

        # 4) Tidy: collapse 3+ blank lines
        text = re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"

        # 5) Append `## 도판` section at end
        block = "\n\n## 도판 (디자인 단계 위치 결정)\n\n"
        for path_ref, caption in figures:
            block += f"![]({path_ref}){{width=60%}}\n\n*{caption}*\n\n"

        text = text + block.rstrip() + "\n"

        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"  {fn}: collected {len(figures)} figure(s) to chapter end")
        total += len(figures)

    print(f"\n{total} figure(s) total")


if __name__ == "__main__":
    main()
