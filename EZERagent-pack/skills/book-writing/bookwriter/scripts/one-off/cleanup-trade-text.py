"""1단계: 본문 정리.
   - 인라인 학술 인용 제거: (저자, 연도), (저자 연도, 페이지)
   - 본문 안 각주 마커 제거: "근무3)" 같은 패턴
   - 각주 정의 단락 제거: 1)…, 2)… 로 시작하는 문단
   - 인라인 그림/표 캡션 마커 제거: ❲...❳, <표 N>, <그림 N>
   - 문장 중간 단락 끊김 보정: 한글로 끝나고 한글로 시작하는 문단 → 합치기
"""
import os
import re

ROOT = "C:\\dev\\bookwriter"
MS_DIR = os.path.join(ROOT, "manuscripts", "soccer-mission-book")

# 본문 + 머리말 + 백매터의 부록만 (참고문헌 제외)
TARGETS = [
    "00-abstract.md",
    "01-collapse.md", "02-sport.md", "03-culture.md", "04-incarnation.md",
    "05-soccer.md", "06-mission.md", "07-fellow.md", "08-missional.md",
    "09-method.md", "10-voices.md", "11-numbers.md", "12-answers.md",
    "13-next.md", "14-forward.md",
    "98-appendix.md",
]


def is_cjk(c: str) -> bool:
    if not c:
        return False
    code = ord(c)
    return 0xAC00 <= code <= 0xD7AF or 0x4E00 <= code <= 0x9FFF


def remove_inline_citations(text: str) -> str:
    """Remove patterns like (김광수, 1993), (김태순 2020, 3), (Mun 2018) etc."""
    # (Korean+English author + optional comma + year + optional page)
    text = re.sub(
        r"\(\s*[가-힣A-Za-z][가-힣A-Za-z·.\s,&]{0,40}?[\s,]+\(?\d{4}\)?(?:,\s*\d+(?:[-–]\d+)?)?\s*\)",
        "",
        text,
    )
    # Bare year cite: (1993), (2020, 3) — only if not part of access date or list number
    text = re.sub(r"\(\s*\d{4}(?:,\s*\d+(?:[-–]\d+)?)?\s*\)", "", text)
    return text


def remove_footnote_markers(text: str) -> str:
    """Remove inline footnote markers like '근무3)' or '있다.4)'.
    Specifically: 1-2 digit number + closing paren immediately after a Korean
    syllable or letter or punctuation, NOT preceded by a digit.
    """
    text = re.sub(r"(?<![\d ])(?<=[가-힣A-Za-z\.\?\!\,])\d{1,2}\)", "", text)
    return text


def remove_footnote_definitions(text: str) -> str:
    """Remove paragraphs that begin with '[N)' (footnote definitions)."""
    paragraphs = re.split(r"\n\s*\n", text)
    keep = []
    for p in paragraphs:
        s = p.strip()
        if re.match(r"^\d{1,2}\)\s*", s):
            continue  # drop entire footnote-definition paragraph
        keep.append(p)
    return "\n\n".join(keep)


def remove_inline_caption_brackets(text: str) -> str:
    """Remove inline figure/table captions inserted in the middle of paragraphs.
    Patterns: ❲...❳ + caption text, <표 N>..., <그림 N>..., ❲그림 N❳... etc.
    Caption text follows up to next bracket or newline.
    """
    text = re.sub(r"❲[^❳]+❳[^\n❲<]*", "", text)
    text = re.sub(r"<\s*표\s*\d[^>]*>[^\n<]*", "", text)
    text = re.sub(r"<\s*그림\s*\d[^>]*>[^\n<]*", "", text)
    return text


def fix_midsentence_breaks(text: str) -> str:
    """Merge paragraphs that broke mid-sentence.
    Heuristic: paragraph A ends with a CJK character (no terminal punctuation),
    paragraph B begins with a CJK character → join with no space.
    Skips: headings, bullets, image markers, italic-only lines, *lines*.
    """
    paragraphs = re.split(r"\n{2,}", text)
    result: list[str] = []
    i = 0
    while i < len(paragraphs):
        cur = paragraphs[i].rstrip()
        if not cur.strip():
            i += 1
            continue
        if i + 1 < len(paragraphs):
            nxt = paragraphs[i + 1].lstrip()
            if nxt:
                # Skip merging if either piece is structural
                if (re.match(r"^#", cur.lstrip())
                    or re.match(r"^#", nxt)
                    or re.match(r"^!\[", nxt) or re.match(r"^!\[", cur)
                    or re.match(r"^\s*[-*]\s", nxt) or re.match(r"^\s*[-*]\s", cur)
                    or re.match(r"^\s*\d+[.)]\s", nxt)
                    or re.match(r"^\s*_\(", nxt) or re.match(r"^\s*_\(", cur)
                    or re.match(r"^\*", nxt) or re.match(r"^\*", cur)):
                    result.append(cur)
                    i += 1
                    continue
                last_ch = cur[-1]
                first_ch = nxt[0]
                if is_cjk(last_ch) and is_cjk(first_ch):
                    # Merge with no space
                    cur = cur + nxt
                    i += 2
                    result.append(cur)
                    continue
        result.append(cur)
        i += 1
    return "\n\n".join(result) + "\n"


def cleanup(text: str) -> str:
    text = remove_inline_caption_brackets(text)
    text = remove_inline_citations(text)
    text = remove_footnote_markers(text)
    text = remove_footnote_definitions(text)
    # Multiple passes: removals create empty parens, line breaks
    text = re.sub(r"\(\s*[\.,]?\s*\)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = fix_midsentence_breaks(text)
    return text


def main():
    for fname in TARGETS:
        path = os.path.join(MS_DIR, fname)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        new_text = cleanup(text)
        if new_text != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            saved = len(text) - len(new_text)
            print(f"  {fname}: -{saved} chars")


if __name__ == "__main__":
    main()
