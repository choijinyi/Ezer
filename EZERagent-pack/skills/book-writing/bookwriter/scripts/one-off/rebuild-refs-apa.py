"""Re-format the references chapter in APA-ish style.

Input: 99-references.md (current jumbled paragraph form)
Output: same file, with one entry per paragraph and `(year)` form.

Algorithm (best-effort regex-based):
  1. Strip noise (header line, prefix label).
  2. Split body into entries on `Name. Year.` boundaries.
  3. Resolve ditto marks (`.` after period meaning previous author).
  4. Transform each entry:
       Author. 1990. Title. ...   →   Author (1990). Title. ...
  5. Separate Internet/News subsections with their own subheadings.
  6. Write output, one entry per paragraph.
"""
import os
import re

PATH = "C:\\dev\\bookwriter\\manuscripts\\soccer-mission-book\\99-references.md"
EXTRACTED = os.path.join(os.environ.get("TEMP", "/tmp"), "extracted.txt")
# Original references span (1-based) in /tmp/extracted.txt
REF_START, REF_END = 6207, 6472

PAGE_MARKER = re.compile(r"^<<<PAGE \d+>>>\s*$")
PAGE_NUM = re.compile(r"^\s*-\s*[ivxIVXC0-9]+\s*-\s*$")

# Detects the start of a new bibliographic entry:
#   Name (Korean or English) then period+space then 4-digit year then period.
NEW_ENTRY_BOUNDARY = re.compile(
    r"(?<=\.)\s+"
    r"(?="
    r"(?:"
    r"[가-힣]{1,12}(?:[·\.,]\s?[가-힣]{1,12})*(?:\s+편|\s+외(?:\s+\d+인)?)?|"
    r"[A-Z]\.[A-Za-z]+|"
    r"[A-Z][a-zA-Z]+(?:[\s,&\.]+[A-Z][a-zA-Z\.]+){0,6}"
    r")\s*[,\.]?\s*\(?\d{4}[\)\.]"
    r")"
)

# Year pattern (handles either "1990." or "(1990)." forms):
ENTRY_RE = re.compile(
    r"^\s*([\.,\s]*)\s*"      # leading whitespace / ditto markers
    r"(.{1,80}?)\s*[,\.]\s*"  # author(s)
    r"\(?(\d{4}[a-z]?)\)?\.\s*"  # year
    r"(.+)$",                  # rest
    re.DOTALL,
)


def to_apa(entry: str, prev_author: str | None) -> tuple[str, str | None]:
    """Apply APA-ish formatting. Resolve ditto marks against prev_author."""
    s = entry.strip()
    if not s:
        return "", prev_author

    # Detect ditto: starts with a stray '.' or whitespace before year, no leading author
    m_ditto = re.match(r"^[\.,]+\s*(\(?\d{4}\)?[a-z]?)\.\s*(.+)$", s, re.DOTALL)
    if m_ditto:
        year = m_ditto.group(1).strip("().")
        rest = m_ditto.group(2).strip()
        if prev_author:
            return f"{prev_author} ({year}). {rest}", prev_author
        return f"({year}). {rest}", prev_author

    m = ENTRY_RE.match(s)
    if not m:
        return s, prev_author  # leave as-is if unparseable
    _, author, year, rest = m.groups()
    author = author.strip().rstrip(",.")
    rest = rest.strip()
    return f"{author} ({year}). {rest}", author


def split_sections(body: str) -> tuple[str, str, str]:
    """Split into (biblio, internet, news) by hand-rolled markers."""
    inet_re = re.compile(r"[<〈]\s*인터넷\s*사이트\s*[>〉]", re.IGNORECASE)
    news_re = re.compile(r"[<〈]\s*신문기사\s*[>〉]", re.IGNORECASE)
    inet_m = inet_re.search(body)
    news_m = news_re.search(body)
    end_biblio = len(body)
    if inet_m:
        end_biblio = inet_m.start()
    elif news_m:
        end_biblio = min(end_biblio, news_m.start())
    biblio = body[:end_biblio]
    internet = ""
    news = ""
    if inet_m:
        if news_m and news_m.start() > inet_m.end():
            internet = body[inet_m.end() : news_m.start()]
            news = body[news_m.end() :]
        else:
            internet = body[inet_m.end() :]
    elif news_m:
        news = body[news_m.end() :]
    return biblio, internet, news


def split_internal_dittos(entry: str) -> list[str]:
    """If an entry contains an embedded `. . YYYY.` ditto pattern, split it
    into two entries (the second being the ditto)."""
    out = [entry]
    while True:
        changed = False
        new_out = []
        for e in out:
            m = re.search(r"\.\s+\.\s+(?=\(?\d{4}[\)\.])", e)
            if m:
                new_out.append(e[: m.start()].rstrip() + ".")
                new_out.append(". " + e[m.end():].lstrip())
                changed = True
            else:
                new_out.append(e)
        out = new_out
        if not changed:
            break
    return out


def parse_biblio(text: str) -> list[str]:
    text = text.strip()
    text = re.sub(r"^\s*참고문헌\s*\(Reference List\)\s*", "", text)

    parts = NEW_ENTRY_BOUNDARY.split(text)
    out: list[str] = []
    prev: str | None = None
    for p in parts:
        for sub in split_internal_dittos(p):
            joined = join_wrapped(sub)  # collapse line-wrapping within entry
            formatted, prev = to_apa(joined, prev)
            if formatted:
                out.append(formatted)
    return out


def parse_internet(text: str) -> list[str]:
    """Web entries — one per paragraph. Each ends with `(검색일자: YYYY.MM.DD)`."""
    text = join_wrapped(text)
    # Split AFTER the closing paren of `(검색일자: ...)`
    parts = re.split(r"(?<=\))\s*\.?\s*(?=\S)", text)
    out: list[str] = []
    for p in parts:
        s = p.strip().rstrip(".")
        if not s:
            continue
        # Ensure access-date paren is closed
        if "검색일자" in s and "(" in s and not s.endswith(")"):
            s = s + ")"
        out.append(s)
    return out


def parse_news(text: str) -> list[str]:
    text = join_wrapped(text)
    # Split before each newspaper name occurrence (one entry = newspaper + year + date)
    parts = re.split(
        r"(?<=[\.\s])(?=(?:경향신문|국민일보|동아일보|중앙일보|조선일보|한겨레|문화일보|매일경제|한국일보|서울신문|기독공보|cts뉴스|기독교신문|뉴스앤조이)[\.,\s])",
        text,
    )
    out = []
    for p in parts:
        s = p.strip().rstrip(".,")
        if not s:
            continue
        formatted, _ = to_apa(s, None)
        out.append(formatted or s)
    return out


def is_cjk(c: str) -> bool:
    if not c:
        return False
    code = ord(c)
    return 0xAC00 <= code <= 0xD7AF or 0x4E00 <= code <= 0x9FFF


def join_wrapped(text: str) -> str:
    """Join hard-wrapped lines within a single entry. CJK+CJK → no space, else space."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""
    out = lines[0]
    for ln in lines[1:]:
        if not out:
            out = ln
            continue
        if is_cjk(out[-1]) and is_cjk(ln[0]):
            out += ln
        else:
            out += " " + ln
    return out


def load_raw_body() -> str:
    """Load raw references body from original PyMuPDF extraction (idempotent)."""
    with open(EXTRACTED, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    section = all_lines[REF_START - 1 : REF_END]
    cleaned: list[str] = []
    for raw in section:
        ln = raw.rstrip("\n")
        if PAGE_MARKER.match(ln) or PAGE_NUM.match(ln):
            continue
        cleaned.append(ln)
    body = "\n".join(cleaned).strip()
    # Normalize variant separators to standard middle dot
    body = body.replace("․", "·").replace("．", ".")
    body = re.sub(r"^\s*참고문헌\s*\(Reference List\)\s*", "", body)
    return body


def main():
    title = "# 참고문헌\n"
    body = load_raw_body()

    biblio_raw, internet_raw, news_raw = split_sections(body)
    biblio = parse_biblio(biblio_raw)
    internet = parse_internet(internet_raw)
    news = parse_news(news_raw)

    out = [title.rstrip(), ""]
    out.append("> APA 형식 (한국어 단행본 약식). 한 항목씩 줄바꿈으로 구분.")
    out.append("")
    seen = set()
    for b in biblio:
        if b in seen:
            continue
        seen.add(b)
        out.append(b)
        out.append("")

    # 단행본 형식: 인터넷/웹 자료는 모두 제외 (사용자 요청)
    _ = internet  # discarded

    if news:
        out.append("## 신문 자료")
        out.append("")
        for n in news:
            out.append(n)
            out.append("")

    final = "\n".join(out).rstrip() + "\n"
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(final)
    print(f"biblio entries:  {len(biblio)}")
    print(f"internet items:  {len(internet)}")
    print(f"news items:      {len(news)}")
    print(f"output: {PATH}")


if __name__ == "__main__":
    main()
