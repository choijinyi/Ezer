"""One-off: split the extracted thesis text into per-chapter .md files."""
import os
import re
import sys
import json

EXTRACTED = os.path.join(os.environ.get("TEMP", "/tmp"), "extracted.txt")
DST = os.path.join("C:\\dev\\bookwriter", "manuscripts", "soccer-mission-thesis")

# (start_line_1based, end_line_1based, role, filename, title)
SECTIONS = [
    (43, 152, "frontmatter", "00-abstract.md", "국문 초록"),
    (600, 1092, "body", "01-introduction.md", "제1장 서론"),
    (1093, 2874, "body", "02-literature.md", "제2장 이론적 배경"),
    (2875, 2927, "body", "03-method.md", "제3장 연구 계획 및 방법"),
    (2928, 5814, "body", "04-results.md", "제4장 연구결과 및 분석"),
    (5815, 5930, "body", "05-conclusion.md", "제5장 결론"),
    (5931, 6206, "backmatter", "98-appendix.md", "부록"),
    (6207, 6472, "backmatter", "99-references.md", "참고문헌"),
]

PAGE_MARKER = re.compile(r"^<<<PAGE \d+>>>\s*$")
PAGE_NUM = re.compile(r"^\s*-\s*[ivxIVXC0-9]+\s*-\s*$")
SECTION_HEADER = re.compile(r"^\s*(\d+)\.\s+(.{1,40})\s*$")
SUBSECTION_HEADER = re.compile(r"^\s*(\d+)\)\s+(.{1,40})\s*$")


def clean_lines(raw_lines, title):
    """Strip page markers/numbers, drop the original chapter title (we add our own).
    Convert simple section markers (1. xxx) into ## headings if they sit on their own line.
    """
    out = [f"# {title}", ""]
    found_first_real_line = False
    in_blank = True

    for raw in raw_lines:
        ln = raw.rstrip("\n")
        if PAGE_MARKER.match(ln):
            continue
        if PAGE_NUM.match(ln):
            continue

        stripped = ln.strip()

        # Drop the original chapter heading line (we already wrote our own).
        if not found_first_real_line:
            if stripped == "":
                continue
            # If line matches "제N장 ..." or matches our title — skip it
            if re.match(r"^제\d+장\b", stripped) or stripped.startswith(title):
                found_first_real_line = True
                continue
            found_first_real_line = True

        if stripped == "":
            if not in_blank:
                out.append("")
                in_blank = True
            continue
        in_blank = False

        # Detect numbered top-level sections sitting alone on a line.
        m = SECTION_HEADER.match(ln)
        if m and len(out) >= 2 and out[-1] == "":
            # Treat as ## heading
            out.append(f"## {m.group(1)}. {m.group(2).strip()}")
            out.append("")
            in_blank = True
            continue

        out.append(ln.rstrip())

    # Trim trailing blanks
    while out and not out[-1].strip():
        out.pop()
    out.append("")
    return "\n".join(out)


def main():
    with open(EXTRACTED, "r", encoding="utf-8") as f:
        all_lines = f.readlines()

    os.makedirs(DST, exist_ok=True)

    chapters_meta = []
    for (start, end, role, filename, title) in SECTIONS:
        # Lines are 1-based per grep output
        section = all_lines[start - 1 : end]
        cleaned = clean_lines(section, title)
        out_path = os.path.join(DST, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(cleaned)
        wc = len([w for w in cleaned.split() if w])
        print(f"  {filename:30s} {role:12s} {len(section):>5} lines → {wc:>6} words")
        chapters_meta.append(
            {"file": filename, "role": role, "title": title}
        )

    # Generate book.json
    book = {
        "title": "스포츠 문화로서 축구 선교 활동이 교회에 미치는 영향에 관한 연구",
        "subtitle": "용인 서부교회 축구 선교 활동을 중심으로",
        "authors": ["김태진"],
        "lang": "ko",
        "template": "typst-classic",
        "outputs": ["pdf"],
        "chapters": chapters_meta,
    }
    with open(os.path.join(DST, "book.json"), "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nbook.json written")
    print(f"manuscript: {DST}")


if __name__ == "__main__":
    main()
