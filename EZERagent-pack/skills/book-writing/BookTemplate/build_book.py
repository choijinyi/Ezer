"""
build_book.py - 마크다운 원고를 PDF 책으로 빌드하는 스크립트

사용법:
    python build_book.py [book-name]

옵션:
    book-name : 빌드할 책 이름 (books.BOOKS 키 중 하나).
                생략 시 DEFAULT_BOOK 사용.

필요 라이브러리:
    pip install markdown jinja2 playwright
    playwright install chromium
"""

import argparse
import io
import os
import sys

# Windows 환경 설정 (라이브러리 import 전에 실행)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    _conda_prefix = os.environ.get("CONDA_PREFIX", "")
    _fc_conf = os.path.join(_conda_prefix, "Library", "etc", "fonts", "fonts.conf")
    if os.path.isfile(_fc_conf) and "FONTCONFIG_FILE" not in os.environ:
        os.environ["FONTCONFIG_FILE"] = _fc_conf

import re
import markdown
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

from books import BOOKS, DEFAULT_BOOK

CHAPTER_TITLE_RE = re.compile(
    r'<p class="chapter-title-text">(.*?)</p>',
    re.DOTALL,
)

# ===== 경로 설정 =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 책별 하위 폴더: content/<book-name>/ 에서 그 책의 원고를 읽는다.
CONTENT_ROOT = os.path.join(BASE_DIR, "content")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# ===== 판형(Trim Size) 옵션 =====
# 용도에 따라 빌드 시 선택합니다.
#  - 신국판: 시집·에세이·신앙서적·소설 등 휴대성을 중시하는 단행본
#  - B5    : 학술서·교재·강해서·사진/도판이 많은 책 등 큰 판형이 필요한 도서
PAGE_SIZES = {
    "1": {"name": "신국판", "label": "152×225mm", "width": 152, "height": 225},
    "2": {"name": "B5",     "label": "188×257mm", "width": 188, "height": 257},
}
DEFAULT_PAGE_SIZE_KEY = "2"
# ===========================================================


def collect_markdown_files(content_dir, book_meta):
    """BOOKS[book]['chapters'] 순서대로 content/ 의 출력 파일을 모은다.
    누락 파일은 경고 후 스킵, 책에 속하지 않는 파일은 무시(고립 파일 보호).
    """
    files = []
    missing = []
    for row in book_meta["chapters"]:
        dst_name = row[1]
        path = os.path.join(content_dir, dst_name)
        if os.path.isfile(path):
            files.append(path)
        else:
            missing.append(dst_name)
    if missing:
        print("[경고] content/ 에 없는 파일(스킵):")
        for m in missing:
            print(f"  - {m}")
    if not files:
        print(f"[경고] 빌드할 파일이 없습니다. 먼저 convert_manuscript.py 를 실행하세요.")
    else:
        print(f"[정보] {len(files)}개 파일 빌드 대상:")
        for f in files:
            print(f"  - {os.path.basename(f)}")
    return files


def convert_md_to_html(md_files):
    """마크다운 파일들을 읽어 하나의 HTML 문자열로 변환한다.
    각 파일별로 named page(@page pg-NN)를 자동 생성하여
    홀수 페이지 우측 푸터에 그 장의 제목이 표시되게 한다.
    """
    extensions = ["extra", "smarty", "toc"]
    md = markdown.Markdown(extensions=extensions)
    parts = []

    for idx, filepath in enumerate(md_files):
        with open(filepath, "r", encoding="utf-8") as f:
            md_text = f.read()

        # chapter-title-text에서 푸터용 제목 추출
        m = CHAPTER_TITLE_RE.search(md_text)
        footer_title = ""
        if m:
            footer_title = (
                m.group(1)
                .replace("<br>", " ")
                .replace("<br/>", " ")
                .replace("<br />", " ")
                .strip()
            )
            # CSS content 문자열 안에서 안전하도록 역슬래시·큰따옴표 escape
            footer_title = footer_title.replace("\\", "\\\\").replace('"', '\\"')

        html_fragment = md.reset().convert(md_text)

        page_id = f"pg-{idx:02d}"
        if footer_title:
            page_css = (
                f"<style>"
                f"@page {page_id}:right {{ "
                f"@bottom-right {{ "
                f'content: "{footer_title}"; '
                f"font-size: 8pt; "
                f'font-family: "Noto Serif KR", "Batang", serif; '
                f"color: #888; "
                f"}} "
                f"}}"
                f"</style>"
            )
            wrapped = (
                f"{page_css}\n"
                f'<div class="chap-wrap" style="page: {page_id}">\n'
                f"{html_fragment}\n"
                f"</div>"
            )
        else:
            wrapped = html_fragment

        parts.append(f"\n<!-- {os.path.basename(filepath)} -->\n{wrapped}\n")

    return "".join(parts)


def render_template(content_html, page_size, book_meta, style_name="style.css"):
    """Jinja2 템플릿에 본문·메타정보·판형 치수를 삽입한다."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("base.html")

    cover = book_meta.get("cover", {"mode": "image", "image": "cover.png"})

    style_template = env.get_template(style_name)
    style_css = style_template.render(
        page_width=page_size["width"],
        page_height=page_size["height"],
        book_title=book_meta["title"].replace("<br>", " "),
        cover=cover,
    )

    # 미리보기 HTML을 어느 폴더에 저장하든 ../images/... 상대경로가
    # 프로젝트 images/ 를 가리키도록 문서 기준 URL(<base>)을 고정한다.
    base_href = Path(DEFAULT_OUTPUT_DIR).as_uri() + "/"

    rendered = template.render(
        title=book_meta["title"],
        subtitle=book_meta["subtitle"],
        author=book_meta["author"],
        content=content_html,
        style=style_css,
        cover=cover,
        base_href=base_href,
    )
    return rendered


def build_pdf(html_path, pdf_path, page_size):
    """저장된 HTML 파일을 Playwright(Chromium)으로 PDF로 변환한다."""
    print("[정보] Chromium으로 PDF 변환 중... (시간이 걸릴 수 있습니다)")
    # 상대경로·한글·공백 경로도 안전하게 file:// URL로 변환
    file_url = Path(html_path).resolve().as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(file_url, wait_until="networkidle")
        page.pdf(
            path=pdf_path,
            width=f"{page_size['width']}mm",
            height=f"{page_size['height']}mm",
            print_background=True,
        )
        browser.close()
    print(f"[정보] PDF 저장 완료: {pdf_path}")


def ask_output_dir():
    """매 빌드 시 출력 경로를 확인받는다."""
    print(f"\n[출력 경로] 기본 경로: {DEFAULT_OUTPUT_DIR}")
    user_input = input("  위 경로로 출력할까요? (Enter=예 / 다른 경로 입력): ").strip().strip('"')
    if user_input:
        output_dir = user_input
    else:
        output_dir = DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    print(f"  → 출력 경로: {output_dir}")
    return output_dir


def ask_page_size():
    """책의 용도에 맞는 판형을 사용자에게 선택받는다."""
    print("\n[판형 선택]")
    print("  책의 목적에 맞는 판형을 고르세요.")
    print("    1. 신국판 (152×225mm) — 시집·에세이·신앙서적·소설 등 휴대성 중시")
    print("    2. B5     (188×257mm) — 학술서·교재·강해서·도판이 많은 책")
    user_input = input(f"  번호 입력 (Enter={DEFAULT_PAGE_SIZE_KEY}): ").strip()
    key = user_input or DEFAULT_PAGE_SIZE_KEY
    if key not in PAGE_SIZES:
        print(f"  [경고] 잘못된 입력입니다. 기본값({DEFAULT_PAGE_SIZE_KEY})으로 진행합니다.")
        key = DEFAULT_PAGE_SIZE_KEY
    selected = PAGE_SIZES[key]
    print(f"  → 선택: {selected['name']} ({selected['label']})")
    return selected


def parse_args():
    ap = argparse.ArgumentParser(description="마크다운 원고 -> PDF 책 빌드")
    ap.add_argument(
        "book",
        nargs="?",
        default=DEFAULT_BOOK,
        choices=sorted(BOOKS.keys()),
        help=f"빌드할 책 (기본값: {DEFAULT_BOOK})",
    )
    ap.add_argument(
        "--output", "-o",
        default=None,
        help="출력 폴더 (생략 시 대화형 질문). 비대화형 빌드용.",
    )
    ap.add_argument(
        "--page-size", "-p",
        default=None,
        choices=sorted(PAGE_SIZES.keys()),
        help="판형 키 (1=신국판, 2=B5; 생략 시 대화형 질문). 비대화형 빌드용.",
    )
    ap.add_argument(
        "--style",
        default="style.css",
        help="templates/ 안의 스타일시트 파일명 (기본 style.css, 전문 조판은 style-pro.css)",
    )
    ap.add_argument(
        "--recto-chapters",
        action="store_true",
        help="장 간지를 홀수(오른쪽) 면에서 시작하도록 2-pass로 백면을 삽입 (출판 관행)",
    )
    return ap.parse_args()


# ===== 홀수면 장 시작 (2-pass) =====
CHAPTER_DIV_MARK = '<div class="chapter-title-page">'


def _is_dark_page(page):
    """간지 감지: 전면 배경이 어두운 페이지 (여백까지 채워진 풀블리드 색면)."""
    import pymupdf
    pix = page.get_pixmap(matrix=pymupdf.Matrix(0.1, 0.1))
    def dark(x, y):
        r, g, b = pix.pixel(x, y)[:3]
        return (r + g + b) / 3 < 120
    # 좌상단·우하단 모두 어두우면 풀블리드 색면으로 판단
    return dark(2, 2) and dark(pix.width - 3, pix.height - 3)


def compute_recto_inserts(pdf_path, full_html):
    """pass-1 PDF에서 짝수 폴리오에 앉은 간지를 찾아, 백면을 넣을 간지 서수 목록을 반환."""
    import pymupdf
    # 폴리오 계산: 표지=물리 0. half-title이 있으면 counter-reset으로 폴리오=물리,
    # 없으면 폴리오=물리+1. (CSS에도 half-title-page 선택자가 있으므로 반드시 div 마커로 검사)
    offset = 0 if '<div class="half-title-page"' in full_html else 1
    inserts = []
    shift = 0          # 앞서 삽입된 백면 수 (이후 페이지를 밀어냄)
    ordinal = 0        # 몇 번째 간지인가 (HTML 등장 순서와 동일)
    with pymupdf.open(pdf_path) as doc:
        for i in range(1, doc.page_count):
            if _is_dark_page(doc[i]):
                ordinal += 1
                folio = i + offset + shift
                if folio % 2 == 0:   # 짝수 폴리오(왼쪽 면) → 백면 삽입 필요
                    inserts.append(ordinal)
                    shift += 1
    return inserts


def insert_blank_versos(full_html, ordinals):
    """k번째 간지 div 앞에 백면 div를 삽입한 HTML을 반환."""
    parts = full_html.split(CHAPTER_DIV_MARK)
    out = [parts[0]]
    for k, part in enumerate(parts[1:], start=1):
        if k in ordinals:
            out.append('<div class="blank-verso"></div>')
        out.append(CHAPTER_DIV_MARK + part)
    return "".join(out)


def main():
    args = parse_args()
    book = args.book
    book_meta = BOOKS[book]

    print("=" * 50)
    print(f"  {book_meta['title']} - PDF 빌드 시작")
    print("=" * 50)

    content_dir = os.path.join(CONTENT_ROOT, book)
    if not os.path.isdir(content_dir):
        print(f"[오류] content 폴더가 없습니다: {content_dir}")
        print(f"       먼저 convert_manuscript.py {book} 를 실행하세요.")
        sys.exit(1)

    if args.output is not None:
        output_dir = args.output
        os.makedirs(output_dir, exist_ok=True)
        print(f"\n[출력 경로] {output_dir}")
    else:
        output_dir = ask_output_dir()

    if args.page_size is not None:
        page_size = PAGE_SIZES[args.page_size]
        print(f"[판형] {page_size['name']} ({page_size['label']})")
    else:
        page_size = ask_page_size()

    md_files = collect_markdown_files(content_dir, book_meta)
    if not md_files:
        print("[오류] 빌드할 마크다운 파일이 없습니다. 종료합니다.")
        sys.exit(1)

    print("\n[정보] 마크다운을 HTML로 변환 중...")
    content_html = convert_md_to_html(md_files)

    print(f"[정보] HTML 템플릿 렌더링 중... (스타일: {args.style})")
    full_html = render_template(content_html, page_size, book_meta, style_name=args.style)

    html_output = os.path.join(output_dir, "book_preview.html")
    with open(html_output, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"[정보] HTML 미리보기 저장: {html_output}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(book_meta["pdf_filename"])
    size_tag = page_size["name"]
    pdf_filename = f"{base}_{size_tag}_{timestamp}{ext or '.pdf'}"
    pdf_output = os.path.join(output_dir, pdf_filename)
    build_pdf(html_output, pdf_output, page_size)

    if args.recto_chapters:
        inserts = compute_recto_inserts(pdf_output, full_html)
        if inserts:
            print(f"[정보] 짝수 면에 앉은 간지 {len(inserts)}곳({inserts}) 앞에 백면 삽입 → 재빌드")
            full_html = insert_blank_versos(full_html, set(inserts))
            with open(html_output, "w", encoding="utf-8") as f:
                f.write(full_html)
            build_pdf(html_output, pdf_output, page_size)
        else:
            print("[정보] 모든 간지가 이미 홀수 면에서 시작 — 백면 삽입 불필요")

    print("\n" + "=" * 50)
    print("  빌드 완료!")
    print(f"  HTML: {html_output}")
    print(f"  PDF : {pdf_output}")
    print("=" * 50)


if __name__ == "__main__":
    main()
