"""Re-join hard-wrapped lines within paragraphs.

PDF extraction preserves visual line breaks (line wrap) which break Korean
words mid-syllable. This script joins lines within a paragraph using:
  - CJK + CJK boundary → no space (e.g. "유소" + "년과" → "유소년과")
  - any other boundary → single space (e.g. "the" + "boy" → "the boy")

Skipped: heading lines, image lines, blank lines, code fences, list-marker lines.
"""
import os
import re

ROOT = "C:\\dev\\bookwriter"
MS_DIR = os.path.join(ROOT, "manuscripts", "soccer-mission-book")

CHAPTER_FILES = [
    "00-abstract.md",
    "01-collapse.md", "02-sport.md", "03-culture.md", "04-incarnation.md",
    "05-soccer.md", "06-mission.md", "07-fellow.md", "08-missional.md",
    "09-method.md", "10-voices.md", "11-numbers.md", "12-answers.md",
    "13-next.md", "14-forward.md",
    "98-appendix.md", "99-references.md",
]

HEADING_RE = re.compile(r"^#{1,6}\s")
IMAGE_RE = re.compile(r"^\s*!\[")
LIST_RE = re.compile(r"^\s*([-*+]\s|\d+[.)]\s)")
FENCE_RE = re.compile(r"^```")
ITALIC_LINE_RE = re.compile(r"^\s*\*[^*]+\*\s*$")  # *원본 p131* alone on line


def is_cjk(c: str) -> bool:
    if not c:
        return False
    code = ord(c)
    # Hangul syllables
    if 0xAC00 <= code <= 0xD7AF:
        return True
    # CJK unified ideographs
    if 0x4E00 <= code <= 0x9FFF:
        return True
    # Hangul Jamo
    if 0x1100 <= code <= 0x11FF:
        return True
    return False


def join_lines(lines: list[str]) -> str:
    """Join paragraph lines with smart whitespace."""
    out = ""
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if not out:
            out = s
            continue
        last = out[-1]
        first = s[0]
        if is_cjk(last) and is_cjk(first):
            out += s
        else:
            out += " " + s
    return out


def is_atomic(line: str) -> bool:
    """Lines that should NOT be joined with siblings (kept on their own line)."""
    s = line.lstrip()
    if HEADING_RE.match(s):
        return True
    if IMAGE_RE.match(s):
        return True
    if LIST_RE.match(s):
        return True
    if ITALIC_LINE_RE.match(line):
        return True
    return False


def process(text: str) -> str:
    lines = text.split("\n")
    result: list[str] = []
    buffer: list[str] = []
    in_fence = False

    def flush():
        if buffer:
            result.append(join_lines(buffer))
            buffer.clear()

    for ln in lines:
        if FENCE_RE.match(ln):
            flush()
            result.append(ln)
            in_fence = not in_fence
            continue
        if in_fence:
            result.append(ln)
            continue
        if ln.strip() == "":
            flush()
            result.append("")
            continue
        if is_atomic(ln):
            flush()
            result.append(ln)
            continue
        buffer.append(ln)

    flush()

    # Collapse 3+ consecutive blank lines to 2
    out = "\n".join(result)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.rstrip() + "\n"


def main():
    total = 0
    for fn in CHAPTER_FILES:
        path = os.path.join(MS_DIR, fn)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            old = f.read()
        new = process(old)
        if new != old:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            print(f"  {fn}: {len(old):>6} → {len(new):>6} chars")
            total += 1
    print(f"\n{total} file(s) updated")


if __name__ == "__main__":
    main()
