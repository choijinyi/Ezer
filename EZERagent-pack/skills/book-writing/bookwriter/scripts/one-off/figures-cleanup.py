"""One-off: filter PNG masks, then insert image refs into trade chapter .md files."""
import os
import re
import json
from collections import defaultdict

ROOT = "C:\\dev\\bookwriter"
EXTRACTED = os.path.join(os.environ.get("TEMP", "/tmp"), "extracted.txt")
FIGS_DIR = os.path.join(ROOT, "manuscripts", "soccer-mission-book", "figures")
MS_DIR = os.path.join(ROOT, "manuscripts", "soccer-mission-book")

# (start_line, end_line, title, filename)
CHAPTERS = [
    (600, 1092, "1장", "01-collapse.md"),
    (1094, 1270, "2장", "02-sport.md"),
    (1271, 1435, "3장", "03-culture.md"),
    (1436, 1934, "4장", "04-incarnation.md"),
    (1935, 2106, "5장", "05-soccer.md"),
    (2107, 2266, "6장", "06-mission.md"),
    (2267, 2840, "7장", "07-fellow.md"),
    (2841, 2874, "8장", "08-missional.md"),
    (2875, 2927, "9장", "09-method.md"),
    (2929, 4850, "10장", "10-voices.md"),
    (4851, 5689, "11장", "11-numbers.md"),
    (5690, 5814, "12장", "12-answers.md"),
    (5816, 5878, "13장", "13-next.md"),
    (5879, 5930, "14장", "14-forward.md"),
]

PNG_MASK_THRESHOLD = 0.3   # PNG ≤ 30% of JPEG size on same page → likely a mask
FILE_RE = re.compile(r"^p(\d+)-x(\d+)\.(\w+)$")


def main():
    # 1) Scan figures
    raw_files = [f for f in os.listdir(FIGS_DIR) if f != "INDEX.md"]
    info = {}
    for f in raw_files:
        m = FILE_RE.match(f)
        if not m:
            continue
        page = int(m.group(1))
        xref = int(m.group(2))
        ext = m.group(3).lower()
        path = os.path.join(FIGS_DIR, f)
        info[f] = {
            "page": page,
            "xref": xref,
            "ext": ext,
            "size": os.path.getsize(path),
        }

    # 2) For each page, drop PNG masks (PNG significantly smaller than JPEG on same page)
    by_page = defaultdict(lambda: {"png": [], "jpeg": []})
    for f, i in info.items():
        if i["ext"] == "png":
            by_page[i["page"]]["png"].append(f)
        elif i["ext"] in ("jpeg", "jpg"):
            by_page[i["page"]]["jpeg"].append(f)

    dropped = []
    for page, groups in by_page.items():
        if not groups["png"] or not groups["jpeg"]:
            continue
        max_jpeg = max(info[j]["size"] for j in groups["jpeg"])
        for png in groups["png"]:
            if info[png]["size"] < PNG_MASK_THRESHOLD * max_jpeg:
                os.remove(os.path.join(FIGS_DIR, png))
                dropped.append(png)
                del info[png]

    print(f"dropped {len(dropped)} PNG mask(s); {len(info)} files remain")

    # 3) Page → line map
    with open(EXTRACTED, "r", encoding="utf-8") as f:
        page_to_line = {}
        for i, ln in enumerate(f):
            m = re.match(r"^<<<PAGE (\d+)>>>\s*$", ln.rstrip())
            if m:
                page_to_line[int(m.group(1))] = i + 1

    def chapter_for_page(p):
        line = page_to_line.get(p, -1)
        if line < 0:
            return None
        for (s, e, title, fn) in CHAPTERS:
            if s <= line <= e:
                return (title, fn)
        return None

    # 4) Group files by chapter
    chapter_files = defaultdict(list)
    for fname in info:
        ch = chapter_for_page(info[fname]["page"])
        if ch is None:
            continue
        chapter_files[ch[1]].append((info[fname]["page"], fname, ch[0]))

    # 5) Append `## 도판` blocks (idempotent)
    for ch_filename, items in chapter_files.items():
        items.sort(key=lambda x: (x[0], x[1]))
        md_path = os.path.join(MS_DIR, ch_filename)
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "## 도판" in content:
            print(f"  skip {ch_filename} (이미 도판 섹션 있음)")
            continue

        block = "\n\n## 도판\n\n"
        for (page, fname, _) in items:
            block += (
                f"![](figures/{fname}){{width=80%}}\n\n"
                f"*<!-- 캡션을 여기에 (원본 p{page}) -->*\n\n"
            )

        with open(md_path, "a", encoding="utf-8") as f:
            f.write(block.rstrip() + "\n")
        print(f"  {ch_filename}: +{len(items)} figure(s)")

    # 6) Refresh INDEX.md to reflect remaining
    sorted_files = sorted(info.values(), key=lambda i: (i["page"], i["xref"]))
    idx_path = os.path.join(FIGS_DIR, "INDEX.md")
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write(f"# Figure index (after cleanup)\n\n")
        f.write(f"{len(sorted_files)} files retained, {len(dropped)} PNG masks removed.\n\n")
        f.write(f"| File | Page | Bytes |\n|---|---|---|\n")
        # Need filename — back-reference
        rev = {(v["page"], v["xref"]): k for k, v in info.items()}
        for v in sorted_files:
            fname = rev[(v["page"], v["xref"])]
            f.write(f"| `{fname}` | {v['page']} | {v['size']} |\n")

    print(f"\nDone. Remaining {len(info)} figures across {len(chapter_files)} chapter(s).")


if __name__ == "__main__":
    main()
