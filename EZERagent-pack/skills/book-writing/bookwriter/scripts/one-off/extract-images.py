"""One-off: extract images from /tmp/source.pdf, dedupe, map to trade chapters."""
import os
import re
import json
import pymupdf

PDF = os.path.join(os.environ.get("TEMP", "/tmp"), "source.pdf")
EXTRACTED = os.path.join(os.environ.get("TEMP", "/tmp"), "extracted.txt")
DST_DIR = os.path.join("C:\\dev\\bookwriter", "manuscripts", "soccer-mission-book", "figures")
MIN_SIZE_PX = 100  # skip tiny decorations

# Trade chapter line ranges (matches split-trade.py)
CHAPTERS = [
    (43, 152, "초록"),
    (600, 1092, "1장 무너지는 교회 앞에서"),
    (1094, 1270, "2장 스포츠라는 문화"),
    (1271, 1435, "3장 문화로 전하는 복음"),
    (1436, 1934, "4장 성육신과 선교적 교회"),
    (1935, 2106, "5장 세상이 사랑하는 게임"),
    (2107, 2266, "6장 축구가 선교가 되다"),
    (2267, 2840, "7장 함께 뛴 사람들"),
    (2841, 2874, "8장 선교적 교회와 축구"),
    (2875, 2927, "9장 연구의 길"),
    (2929, 4850, "10장 현장의 이야기"),
    (4851, 5689, "11장 숫자가 말하는 것"),
    (5690, 5814, "12장 일곱 가지 질문에 답하다"),
    (5816, 5878, "13장 다음 세대로 이어지는 발걸음"),
    (5879, 5930, "14장 더 멀리 차는 공"),
    (5931, 6206, "부록"),
    (6207, 6472, "참고문헌"),
]


def build_page_to_line(extracted_text):
    """Returns dict: page_number → start_line in extracted.txt (1-based)."""
    out = {}
    for i, ln in enumerate(extracted_text.splitlines()):
        m = re.match(r"^<<<PAGE (\d+)>>>\s*$", ln)
        if m:
            out[int(m.group(1))] = i + 1
    return out


def chapter_for_line(line_num):
    for start, end, title in CHAPTERS:
        if start <= line_num <= end:
            return title
    return "(out of range)"


def main():
    with open(EXTRACTED, "r", encoding="utf-8") as f:
        page_to_line = build_page_to_line(f.read())

    os.makedirs(DST_DIR, exist_ok=True)
    doc = pymupdf.open(PDF)
    print(f"PDF: {len(doc)} pages")

    seen_xrefs = {}      # xref → filename (first occurrence)
    extracted_info = []  # entries for INDEX.md

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen_xrefs:
                # reused image — record reuse but don't re-write file
                for e in extracted_info:
                    if e["xref"] == xref:
                        e["pages_seen"].append(page_num)
                        break
                continue

            base = doc.extract_image(xref)
            w, h = base["width"], base["height"]
            if w < MIN_SIZE_PX or h < MIN_SIZE_PX:
                continue
            ext = base["ext"]
            filename = f"p{page_num:03d}-x{xref:04d}.{ext}"
            with open(os.path.join(DST_DIR, filename), "wb") as f:
                f.write(base["image"])

            line_num = page_to_line.get(page_num, -1)
            chapter = chapter_for_line(line_num) if line_num > 0 else "?"

            seen_xrefs[xref] = filename
            extracted_info.append({
                "xref": xref,
                "filename": filename,
                "first_page": page_num,
                "pages_seen": [page_num],
                "width": w,
                "height": h,
                "size_bytes": len(base["image"]),
                "ext": ext,
                "chapter": chapter,
            })

    # Sort by first_page
    extracted_info.sort(key=lambda e: e["first_page"])

    # Write INDEX.md
    idx_path = os.path.join(DST_DIR, "INDEX.md")
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write(f"# Figure index\n\n")
        f.write(f"Extracted {len(extracted_info)} images (>={MIN_SIZE_PX}px).\n\n")
        f.write(f"| File | First page | Reused on | Size (px) | Bytes | Chapter |\n")
        f.write(f"|---|---|---|---|---|---|\n")
        for e in extracted_info:
            reused = (
                ", ".join(map(str, e["pages_seen"][1:]))
                if len(e["pages_seen"]) > 1
                else "-"
            )
            f.write(
                f"| `{e['filename']}` | {e['first_page']} | {reused} | "
                f"{e['width']}×{e['height']} | {e['size_bytes']} | {e['chapter']} |\n"
            )
        f.write(f"\nTo embed: `![설명](figures/orig/<filename>)` in the relevant chapter .md.\n")

    # Group by chapter for summary
    by_chapter = {}
    for e in extracted_info:
        by_chapter.setdefault(e["chapter"], []).append(e["filename"])

    print(f"\nExtracted {len(extracted_info)} unique images:")
    for chap, files in sorted(by_chapter.items()):
        print(f"  {chap}: {len(files)} image(s)")
        for fn in files:
            print(f"    {fn}")
    print(f"\nFigures dir: {DST_DIR}")
    print(f"Index: {idx_path}")


if __name__ == "__main__":
    main()
