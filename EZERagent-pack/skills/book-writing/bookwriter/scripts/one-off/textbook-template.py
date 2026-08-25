"""Apply uniform textbook structure to chapters 1-13 and reshape 14 as closing."""
import os
import re
import json

ROOT = "C:\\dev\\bookwriter"
MS_DIR = os.path.join(ROOT, "manuscripts", "soccer-mission-book")

# Body chapters that get the standard 학습 목표 / 요약 / 생각해볼 거리 / 더 읽을거리 template
BODY_FILES = [
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
]
CLOSING_FILE = "14-forward.md"
CLOSING_TITLE = "책을 닫으며 — 더 멀리 차는 공"

DOPAN_RE = re.compile(r"\n##\s*도판.*?(?=\n##\s|\Z)", re.DOTALL)


def split_chapter(text: str) -> tuple[str, str, str]:
    """Return (title_line, body_without_dopan, dopan_section_or_empty)."""
    m = re.match(r"^(#\s+[^\n]+)\n", text)
    if m:
        title = m.group(1)
        rest = text[m.end():]
    else:
        title = "# (제목 없음)"
        rest = text

    d = DOPAN_RE.search("\n" + rest)  # leading newline so the regex anchors
    if d:
        # d.start() is offset in `\n+rest`
        body = ("\n" + rest)[: d.start()]
        dopan = ("\n" + rest)[d.start():].strip()
        body = body.lstrip("\n").rstrip()
        return title, body, dopan
    return title, rest.strip(), ""


def textbook_block(title: str, body: str, dopan: str) -> str:
    parts: list[str] = [
        title,
        "",
        "## 학습 목표",
        "",
        "_(이 장을 통해 알 수 있는 것 3–5가지를 채워주세요.)_",
        "",
        "- ",
        "- ",
        "- ",
        "",
        body.strip(),
        "",
        "## 요약",
        "",
        "_(본 장의 핵심을 5–7줄로 정리해주세요.)_",
        "",
        "## 생각해볼 거리",
        "",
        "_(독자가 묵상하거나 토론할 질문 3–5개를 채워주세요.)_",
        "",
        "1. ",
        "2. ",
        "3. ",
        "",
        "## 더 읽을거리",
        "",
        "_(본 장 이해에 도움되는 참고문헌 2–3편을 채워주세요.)_",
        "",
        "- ",
        "- ",
    ]
    if dopan:
        parts.extend(["", dopan.strip()])
    return "\n".join(parts).rstrip() + "\n"


def closing_block(body: str, dopan: str) -> str:
    parts: list[str] = [
        f"# {CLOSING_TITLE}",
        "",
        "## 우리가 함께 본 것",
        "",
        "_(이 책 전체를 1–2쪽으로 정리해주세요. 1장부터 13장까지 흐름을 회고하는 글.)_",
        "",
        "## 다음 발걸음을 위해",
        "",
        body.strip(),
        "",
        "## 독자에게",
        "",
        "_(저자가 독자에게 보내는 마지막 글. 책을 덮고 어떤 발걸음을 떼었으면 하는지 격려와 권면. 1–2쪽 분량 권장.)_",
    ]
    if dopan:
        parts.extend(["", dopan.strip()])
    return "\n".join(parts).rstrip() + "\n"


def update_book_json():
    """Update title for chapter 14 in book.json."""
    path = os.path.join(MS_DIR, "book.json")
    with open(path, "r", encoding="utf-8") as f:
        book = json.load(f)
    for ch in book.get("chapters", []):
        if ch.get("file") == "14-forward.md":
            ch["title"] = CLOSING_TITLE
    with open(path, "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    # Body chapters 1-13
    for filename in BODY_FILES:
        path = os.path.join(MS_DIR, filename)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        if "## 학습 목표" in text:
            print(f"  {filename}: 이미 템플릿 적용됨 (skip)")
            continue
        title, body, dopan = split_chapter(text)
        new_text = textbook_block(title, body, dopan)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        print(f"  {filename}: 교재 템플릿 적용")

    # Chapter 14 — closing
    path = os.path.join(MS_DIR, CLOSING_FILE)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        if "책을 닫으며" in text:
            print(f"  {CLOSING_FILE}: 이미 작별 형식 (skip)")
        else:
            _, body, dopan = split_chapter(text)
            new_text = closing_block(body, dopan)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            print(f"  {CLOSING_FILE}: 작별 형식 적용 → '{CLOSING_TITLE}'")

    update_book_json()
    print(f"\nbook.json 14장 제목 갱신")


if __name__ == "__main__":
    main()
