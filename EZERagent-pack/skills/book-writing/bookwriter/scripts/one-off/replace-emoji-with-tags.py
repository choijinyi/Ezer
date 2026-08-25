"""이모지 → 조판 라벨 교체 (전문 조판 개선).

교재 원고의 코너 이모지를 영어 라벨 칩(<span class="sec-tag">)과
조판 전통 기호로 교체한다. 라벨 칩 스타일은 BookTemplate/templates/style-pro.css.

매핑:
  ✏️ → WORKSHEET   ⚠️ → SAFETY    📌 → SUMMARY   🏠 → HOMEWORK
  📋 → PROMPT      🌿 → HARVES    📝 → PLUS
  💡 → SKILL(나만의 스킬 문맥) / POINT(헤딩) / TIP(그 외)
  ☐ → □   ✅ → ○   ❌ → ✕   (★·✕는 텍스트 글리프라 유지)
  🎓 🙂 → 제거

사용법: python replace-emoji-with-tags.py <manuscripts의 책 폴더명>
"""
import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2] / "manuscripts"
CHIP = '<span class="sec-tag">{tag}</span>'

TAGS = {
    "✏": "WORKSHEET",
    "⚠": "SAFETY",
    "📌": "SUMMARY",
    "🏠": "HOMEWORK",
    "📋": "PROMPT",
    "🌿": "HARVES",
    "📝": "PLUS",
}


def lamp_tag(line: str) -> str:
    if "나만의 스킬" in line:
        return "SKILL"
    if line.lstrip().startswith("#"):
        return "POINT"
    return "TIP"


def replace_corner(line: str, emoji: str, tag: str) -> str:
    chip = CHIP.format(tag=tag)
    # "**E 제목**" 꼴은 칩을 볼드 밖으로 빼서 마크다운 파싱을 안전하게
    line = re.sub(r"\*\*" + emoji + r"️?\s*", chip + " **", line)
    line = re.sub(emoji + r"️?\s*", chip + " ", line)
    return line


def main() -> None:
    book = sys.argv[1] if len(sys.argv) > 1 else "harves-ai-basic"
    ms = ROOT / book
    if not ms.is_dir():
        sys.exit(f"폴더 없음: {ms}")
    for f in sorted(ms.glob("*.md")):
        lines = f.read_text(encoding="utf-8").split("\n")
        changed = 0
        for i, line in enumerate(lines):
            orig = line
            for e, t in TAGS.items():
                if e in line:
                    line = replace_corner(line, e, t)
            if "💡" in line:
                line = replace_corner(line, "💡", lamp_tag(line))
            line = line.replace("☐", "□")
            line = re.sub("✅️?", "○", line)
            line = re.sub("❌️?", "✕", line)
            line = re.sub("[🎓🙂]️?\\s*", "", line).rstrip() if re.search("[🎓🙂]", line) else line
            if line != orig:
                changed += 1
                lines[i] = line
        if changed:
            f.write_text("\n".join(lines), encoding="utf-8")
        print(f"{f.name}: {changed}줄 변경")


if __name__ == "__main__":
    main()
