"""Phase 3 of figure import:
   - Extract `## 도판` blocks from each chapter
   - Re-insert figures evenly through the body (between paragraphs)
   - Switch placeholder captions to `*원본 p<page>*` (page-reference style)
   - Switch width 80% → 60%
"""
import os
import re

ROOT = "C:\\dev\\bookwriter"
MS_DIR = os.path.join(ROOT, "manuscripts", "soccer-mission-book")
WIDTH = 60

CHAPTER_FILES = [
    "01-collapse.md",
    "02-sport.md",
    "03-culture.md",
    "04-incarnation.md",
    "05-soccer.md",
    "06-mission.md",
    "07-fellow.md",
    "08-missional.md",
    "09-method.md",
    "10-voices.md",
    "11-numbers.md",
    "12-answers.md",
    "13-next.md",
    "14-forward.md",
]

# matches an image entry under `## 도판`:
#   ![](figures/X){width=80%}
#   *<!-- 캡션을 여기에 (원본 pNN) -->*
FIG_RE = re.compile(
    r"!\[\]\((figures/[^)\s]+)\)\{width=\d+%\}\s*\n+\s*\*<!--\s*캡션을 여기에 \(원본 p(\d+)\)\s*-->\*",
    re.MULTILINE,
)
DOPAN_RE = re.compile(r"\n+##\s*도판\s*\n.*?(?=\n##\s|\Z)", re.DOTALL)


def split_paragraphs(text):
    """Split into paragraphs by blank-line boundaries (respecting code fences)."""
    lines = text.split("\n")
    paragraphs = []
    current = []
    in_fence = False
    for ln in lines:
        if re.match(r"^```", ln):
            in_fence = not in_fence
            current.append(ln)
            continue
        if not in_fence and ln.strip() == "":
            if current:
                paragraphs.append("\n".join(current))
                current = []
            continue
        current.append(ln)
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


def fig_block(path, page):
    return f"![]({path}){{width={WIDTH}%}}\n\n*원본 p{page}*"


def process(text):
    """Returns (new_text, num_figures)."""
    # 1) Extract figures from `## 도판` (if present)
    dopan = DOPAN_RE.search(text)
    figures = []
    if dopan:
        for m in FIG_RE.finditer(dopan.group(0)):
            figures.append((m.group(1), m.group(2)))
        # Remove the section
        text = text[: dopan.start()] + text[dopan.end():]

    if not figures:
        return text, 0

    paragraphs = split_paragraphs(text)
    if len(paragraphs) <= 1:
        # Body is just the heading; append figures at end
        body = "\n\n".join(paragraphs).rstrip() + "\n"
        body += "\n" + "\n\n".join(fig_block(p, pg) for (p, pg) in figures) + "\n"
        return body, len(figures)

    # Distribute: skip heading (index 0), insert figures after paragraphs
    # at positions evenly spread among paragraphs[1..n-1].
    n = len(paragraphs) - 1  # excluding heading
    f = len(figures)
    if n <= 0:
        return "\n\n".join(paragraphs) + "\n", len(figures)

    # Determine the step (paragraphs per figure).
    # Insertion indices into paragraphs: 1 + round(k * n / (f+1)), k=1..f
    insert_after = []
    for k in range(1, f + 1):
        idx = 1 + max(0, round(k * n / (f + 1)) - 1)
        idx = min(idx, len(paragraphs) - 1)
        insert_after.append(idx)

    # Build merged
    out = []
    fig_iter = iter(zip(insert_after, figures))
    next_target, next_fig = next(fig_iter, (None, None))
    for i, p in enumerate(paragraphs):
        out.append(p)
        # Insert all figures whose target is this index
        while next_target is not None and i == next_target:
            out.append(fig_block(*next_fig))
            next_target, next_fig = next(fig_iter, (None, None))

    # Any remainder (e.g., target beyond range)
    while next_target is not None:
        out.append(fig_block(*next_fig))
        next_target, next_fig = next(fig_iter, (None, None))

    return "\n\n".join(out).rstrip() + "\n", len(figures)


def main():
    total_inserted = 0
    for fn in CHAPTER_FILES:
        path = os.path.join(MS_DIR, fn)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        new_text, n_fig = process(text)
        if n_fig == 0:
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        print(f"  {fn}: distributed {n_fig} figure(s)")
        total_inserted += n_fig

    print(f"\nTotal: {total_inserted} figure(s) re-distributed")


if __name__ == "__main__":
    main()
