"""
원본 manuscript -> BookTemplate/content/ 형식으로 변환.

사용법:
    python convert_manuscript.py [book-name] [--force]

옵션:
    book-name : 변환할 책 (BOOKS 키 중 하나). 생략 시 기본값 사용.
    --force   : (구) content/ 가 책별 폴더로 분리된 뒤로는 불필요. 호환을 위해 받기만 하고 무시.

대상 폴더:
    content/<book-name>/ — 책마다 격리된 폴더에 출력. (예: content/soccer-mission-book/)

지원 책:
    - soccer-mission-book  (축구가 선교가 되다)

새 책 추가:
    BOOKS 딕셔너리에 항목을 추가하세요. 원본 폴더는
    C:\\dev\\bookwriter\\manuscripts\\<book>\\ 또는
    C:\\dev\\bookwriter\\manuscripts\\<book>\\.bookwriter\\ 에서 자동 탐지됩니다.

변환 동작:
    - 원본 # H1 첫 줄 제거 (chapter-title-page에 들어가므로)
    - 각 파일 상단에 chapter-title-page HTML 블록 삽입
    - pandoc 이미지 속성 {width=...} 제거
    - figures/ 경로 이미지는 ../images/figures/ 로 치환 + 캡션 italic
"""
import argparse
import io
import os
import re
import sys

from books import BOOKS, DEFAULT_BOOK

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ===========================================================
# 경로는 이 스크립트 위치 기준: <루트>/bookwriter/manuscripts → <루트>/BookTemplate/content
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MANUSCRIPTS_ROOT = os.path.join(os.path.dirname(_BASE_DIR), "bookwriter", "manuscripts")
# 책별 하위 폴더로 변환: content/<book-name>/ 에 출력한다.
DST_ROOT = os.path.join(_BASE_DIR, "content")
# ===========================================================


def chapter_title_page(label: str, number: str, title: str, verse: str, verse_ref: str) -> str:
    verse_block = ""
    if verse:
        verse_block = (
            "<div class=\"chapter-verse\">\n"
            f"<p class=\"chapter-verse-text\">{verse}</p>\n"
            f"<p class=\"chapter-verse-ref\">{verse_ref}</p>\n"
            "</div>\n"
        )
    return (
        "<div class=\"chapter-title-page\">\n"
        "<div class=\"chapter-title-inner\">\n"
        f"<p class=\"chapter-label\">{label}</p>\n"
        f"<p class=\"chapter-number\">{number}</p>\n"
        "<div class=\"chapter-title-divider\"></div>\n"
        f"<p class=\"chapter-title-text\">{title}</p>\n"
        f"{verse_block}"
        "</div>\n"
        "</div>\n\n"
    )


# pandoc-style image: ![cap](figures/xxx.jpeg){width=85%}
IMG_RE = re.compile(r"!\[([^\]]*)\]\(figures/([^)]+)\)(\{([^}]*)\})?")
WIDTH_RE = re.compile(r"width\s*=\s*([0-9.]+%?)")
ATTR_RE = re.compile(r"\{[^}]*\}")
H1_RE = re.compile(r"^#\s+.+\s*$")


def replace_image(match):
    caption = match.group(1).strip()
    filename = match.group(2)
    attrs = match.group(4) or ""
    wm = WIDTH_RE.search(attrs)
    width = wm.group(1) if wm else "100%"
    if width and not width.endswith("%"):
        width = width + "%"
    img_html = (
        f'<p><img src="../images/figures/{filename}" '
        f'style="width: {width}"></p>'
    )
    if caption:
        return f"{img_html}\n\n*{caption}*"
    return img_html


# 펜스 코드블록(``` … ```)과 인라인 코드(`…`)를 통째로 캡처 — 그 안은 변환에서 제외한다.
PROTECTED_RE = re.compile(r"(^```.*?^```|`[^`\n]+`)", re.DOTALL | re.MULTILINE)


def transform_prose(body: str) -> str:
    """이미지·pandoc 속성 변환을 코드(펜스 블록·인라인 스팬) '밖'에만 적용한다.
    코드 안의 {dict}, f-string {x}, JSON 예시 등이 ATTR_RE 에 지워지는 것을 방지."""
    out = []
    for seg in PROTECTED_RE.split(body):
        if seg and seg.startswith("`"):
            out.append(seg)  # 코드: 원본 그대로
        else:
            seg = IMG_RE.sub(replace_image, seg)
            seg = ATTR_RE.sub("", seg)
            out.append(seg)
    return "".join(out)


def convert(src_path: str, dst_path: str, label: str, number: str, title: str, verse: str, verse_ref: str):
    with open(src_path, "r", encoding="utf-8") as f:
        text = f.read()

    lines = text.splitlines()
    i = 0
    skipped_h1 = False
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if not skipped_h1 and H1_RE.match(line):
            skipped_h1 = True
            i += 1
            continue
        break
    body = "\n".join(lines[i:])

    body = transform_prose(body)

    out = chapter_title_page(label, number, title, verse, verse_ref) + body.lstrip() + "\n"
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(out)


def resolve_src_dir(book_name: str, chapters: list) -> str:
    """원본 폴더 자동 탐지: <book>/ 우선, 없으면 <book>/.bookwriter/."""
    base = os.path.join(MANUSCRIPTS_ROOT, book_name)
    expected = {row[0] for row in chapters}
    candidates = [base, os.path.join(base, ".bookwriter")]
    for cand in candidates:
        if os.path.isdir(cand) and any(
            os.path.isfile(os.path.join(cand, name)) for name in expected
        ):
            return cand
    sys.exit(
        f"[오류] '{book_name}' 원본 폴더를 찾을 수 없습니다.\n"
        f"  확인 위치:\n    - {candidates[0]}\n    - {candidates[1]}"
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="원본 manuscript -> BookTemplate/content/ 변환")
    ap.add_argument(
        "book",
        nargs="?",
        default=DEFAULT_BOOK,
        choices=sorted(BOOKS.keys()),
        help=f"변환할 책 (기본값: {DEFAULT_BOOK})",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="(사용 안 함) content/ 가 책별 폴더로 분리된 뒤 무시됨. 과거 호환용.",
    )
    return ap.parse_args()


def main():
    args = parse_args()
    book = args.book
    chapters = BOOKS[book]["chapters"]

    # 변환 가능한(소스 있는) 챕터만 분리
    src_chapters = [row for row in chapters if row[0] is not None]
    skipped_hand = [row[1] for row in chapters if row[0] is None]

    src_dir = resolve_src_dir(book, src_chapters)
    dst_dir = os.path.join(DST_ROOT, book)
    os.makedirs(dst_dir, exist_ok=True)

    print(f"[정보] 책: {book}")
    print(f"[정보] 원본: {src_dir}")
    print(f"[정보] 대상: {dst_dir}")
    if skipped_hand:
        print(f"[정보] 손-유지 파일(스킵): {', '.join(skipped_hand)}")
    print()

    converted = 0
    for src_name, dst_name, label, number, title, verse, verse_ref in src_chapters:
        src = os.path.join(src_dir, src_name)
        dst = os.path.join(dst_dir, dst_name)
        if not os.path.isfile(src):
            print(f"[경고] 원본 없음: {src}")
            continue
        convert(src, dst, label, number, title, verse, verse_ref)
        print(f"[변환] {src_name} -> {dst_name}")
        converted += 1

    print()
    print(f"[완료] '{book}' {converted}/{len(src_chapters)}개 챕터 변환됨")


if __name__ == "__main__":
    main()
