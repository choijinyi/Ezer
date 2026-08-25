"""One-off: re-arrange thesis text into 14-chapter trade book."""
import os
import re
import json

EXTRACTED = os.path.join(os.environ.get("TEMP", "/tmp"), "extracted.txt")
DST = os.path.join("C:\\dev\\bookwriter", "manuscripts", "soccer-mission-book")

# (start, end, role, filename, title, notes)
# Order matches the manuscript's intended reading order.
SECTIONS = [
    (43, 152, "frontmatter", "00-abstract.md", "초록", "thesis 국문초록"),

    # 1부 — 왜 축구 선교인가
    (600, 1092, "body", "01-collapse.md",   "무너지는 교회 앞에서", "제1장 전체"),
    (1094, 1270, "body", "02-sport.md",      "스포츠라는 문화",         "2-1"),
    (1271, 1435, "body", "03-culture.md",    "문화로 전하는 복음",      "2-2 + 2-3"),
    (1436, 1934, "body", "04-incarnation.md","성육신과 선교적 교회",    "2-4"),

    # 2부 — 축구라는 길
    (1935, 2106, "body", "05-soccer.md",     "세상이 사랑하는 게임",    "2-5"),
    (2107, 2266, "body", "06-mission.md",    "축구가 선교가 되다",      "2-6 + 2-7"),
    (2267, 2840, "body", "07-fellow.md",     "함께 뛴 사람들",          "2-8 사례"),
    (2841, 2874, "body", "08-missional.md",  "선교적 교회와 축구",      "2-9"),

    # 3부 — 무엇을 보았는가
    (2875, 2927, "body", "09-method.md",     "연구의 길",                "제3장"),
    (2929, 4850, "body", "10-voices.md",     "현장의 이야기",            "4-1 질적"),
    (4851, 5689, "body", "11-numbers.md",    "숫자가 말하는 것",         "4-2 양적"),
    (5690, 5814, "body", "12-answers.md",    "일곱 가지 질문에 답하다", "4-3"),

    # 4부 — 앞으로
    (5816, 5878, "body", "13-next.md",       "다음 세대로 이어지는 발걸음", "5-1 요약"),
    (5879, 5930, "body", "14-forward.md",    "더 멀리 차는 공",          "5-2 제안"),

    # backmatter
    (5931, 6206, "backmatter", "98-appendix.md",   "부록",        "부록"),
    (6207, 6472, "backmatter", "99-references.md", "참고문헌",     "참고문헌"),
]

PAGE_MARKER = re.compile(r"^<<<PAGE \d+>>>\s*$")
PAGE_NUM = re.compile(r"^\s*-\s*[ivxIVXC0-9]+\s*-\s*$")
NUMBERED_HEADER = re.compile(r"^\s*(\d+)\.\s+(.{1,50}?)\s*$")
CHAPTER_HEADER = re.compile(r"^\s*제\d+장\b.*$")


def clean(raw_lines, new_title):
    """Build a trade-chapter .md from the source slice.

    Strategy:
      - Add `# <new_title>` at top.
      - Strip page markers and page numbers.
      - Skip the original 제N장 line if found before any content.
      - Skip the very first numbered-header line (since the new title replaces it).
      - For any subsequent numbered headers on their own line, render as `## `.
    """
    out = [f"# {new_title}", ""]
    skipped_initial_header = False
    last_blank = True

    for raw in raw_lines:
        ln = raw.rstrip("\n")
        if PAGE_MARKER.match(ln):
            continue
        if PAGE_NUM.match(ln):
            continue
        stripped = ln.strip()

        # Drop original chapter headings (제N장 ...)
        if CHAPTER_HEADER.match(stripped):
            continue

        # Skip the first numbered header that introduces this section.
        if not skipped_initial_header:
            if stripped == "":
                continue
            mm = NUMBERED_HEADER.match(stripped)
            if mm:
                skipped_initial_header = True
                continue
            # If we hit content before any header, just continue and turn the flag off.
            skipped_initial_header = True

        if stripped == "":
            if not last_blank:
                out.append("")
                last_blank = True
            continue
        last_blank = False

        # Subsequent numbered headers (alone on a line, after a blank line) → ##
        if last_blank or (out and out[-1] == ""):
            mm = NUMBERED_HEADER.match(ln)
            if mm:
                out.append(f"## {mm.group(2).strip()}")
                out.append("")
                last_blank = True
                continue

        out.append(ln.rstrip())

    while out and not out[-1].strip():
        out.pop()
    out.append("")
    return "\n".join(out)


def main():
    with open(EXTRACTED, "r", encoding="utf-8") as f:
        all_lines = f.readlines()

    os.makedirs(DST, exist_ok=True)

    chapters_meta = []
    print(f"writing to: {DST}")
    for (start, end, role, filename, title, notes) in SECTIONS:
        section = all_lines[start - 1 : end]
        cleaned = clean(section, title)
        out_path = os.path.join(DST, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(cleaned)
        wc = len([w for w in cleaned.split() if w])
        print(f"  {filename:25s}  {role:12s}  {wc:>5} words  ({notes})")
        chapters_meta.append({"file": filename, "role": role, "title": title})

    book = {
        "title": "스포츠 문화로서 축구 선교 활동이 교회에 미치는 영향에 관한 연구",
        "subtitle": "단행본 14장 구성",
        "authors": ["김태진"],
        "lang": "ko",
        "template": "typst-classic",
        "outputs": ["pdf"],
        "chapters": chapters_meta,
    }
    with open(os.path.join(DST, "book.json"), "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nbook.json: {len(chapters_meta)} chapters")


if __name__ == "__main__":
    main()
