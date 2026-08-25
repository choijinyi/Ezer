"""Two clean-ups for the trade book manuscript:

  1. Remove long URLs (and their access-date trailers) from body chapters
     (except 99-references.md, where URLs are intentional in the bibliography).
  2. Replace the empty `## 학습 목표` placeholder in chapters 01–13 with
     content-driven objectives derived from the chapter content.
"""
import os
import re

ROOT = "C:\\dev\\bookwriter"
MS_DIR = os.path.join(ROOT, "manuscripts", "soccer-mission-book")

URL_CLEAN_FILES = [
    "00-abstract.md",
    "01-collapse.md", "02-sport.md", "03-culture.md", "04-incarnation.md",
    "05-soccer.md", "06-mission.md", "07-fellow.md", "08-missional.md",
    "09-method.md", "10-voices.md", "11-numbers.md", "12-answers.md",
    "13-next.md", "14-forward.md",
    "98-appendix.md",
]

# Learning objectives, derived from the actual chapter content (extracted from the thesis).
OBJECTIVES = {
    "01-collapse.md": [
        "한국 교회가 처한 환경적 위기와 그 원인을 이해한다.",
        "2003년 주 5일제와 2019년 팬데믹이 교회 사역에 미친 영향을 파악한다.",
        "전통적 사역 방식의 한계를 인식하고 새로운 접근의 필요성을 자각한다.",
        "다음 세대를 위한 사역 컨텐츠 개발의 시급성을 깨닫는다.",
    ],
    "02-sport.md": [
        "스포츠의 정의와 본질을 이해한다.",
        "스포츠가 갖는 사회적·문화적 기능을 파악한다.",
        "스포츠와 건강·인격 형성의 관계를 설명할 수 있다.",
    ],
    "03-culture.md": [
        "문화의 정의와 구성 요소를 이해한다.",
        "선교의 본질과 성서적 근거를 파악한다.",
        "복음 전파에서 문화가 갖는 역할을 인식한다.",
    ],
    "04-incarnation.md": [
        "성육신 신학의 핵심 개념을 이해한다.",
        "선교적 교회(missional church)의 정의와 특징을 파악한다.",
        "성육신 신학과 선교적 교회의 관계를 설명할 수 있다.",
        "현 시대 교회의 정체성과 사명을 재고한다.",
    ],
    "05-soccer.md": [
        "축구가 세계적으로 사랑받는 이유를 이해한다.",
        "축구의 단순성이 가진 선교적 잠재력을 파악한다.",
        "한국에서 축구의 위상과 발전 과정을 설명할 수 있다.",
    ],
    "06-mission.md": [
        "축구 선교 활동의 정의와 특징을 이해한다.",
        "축구를 선교 도구로 삼는 신학적 근거를 파악한다.",
        "일반적 축구 활동과 축구 선교 활동의 차이를 구분한다.",
    ],
    "07-fellow.md": [
        "한국 교회의 다양한 축구 선교 사례를 알 수 있다.",
        "각 사례의 특징과 성과를 비교한다.",
        "축구 선교의 다양한 형태와 적용 가능성을 파악한다.",
        "사례에서 발견되는 공통 원리와 교훈을 정리한다.",
    ],
    "08-missional.md": [
        "선교적 교회 패러다임 안에서 축구 선교의 위치를 이해한다.",
        "축구 선교가 교회의 본질적 사명에 부합하는 이유를 설명한다.",
    ],
    "09-method.md": [
        "본 연구의 방법론과 절차를 이해한다.",
        "질적 연구와 양적 연구를 결합한 혼합 연구 설계를 파악한다.",
        "연구 대상 선정 기준과 윤리적 고려사항을 인식한다.",
    ],
    "10-voices.md": [
        "다양한 축구 선교사들의 실제 경험을 통해 현장의 모습을 이해한다.",
        "축구 선교 활동이 사역자와 공동체에 미친 영향을 파악한다.",
        "현장에서 마주하는 도전과 보람을 알 수 있다.",
        "13명의 인터뷰가 제공하는 풍부한 통찰을 정리한다.",
    ],
    "11-numbers.md": [
        "축구 선교 활동의 효과를 양적 자료로 검증할 수 있다.",
        "7개 연구 질문에 대한 통계적 응답 결과를 해석한다.",
        "양적 자료가 보여주는 의미와 한계를 인식한다.",
    ],
    "12-answers.md": [
        "축구 선교 활동이 교회 공동체에 미치는 영향을 7가지 측면에서 정리한다.",
        "양적·질적 연구 결과의 통합적 해석을 이해한다.",
        "본 연구가 제시한 핵심 발견을 요약할 수 있다.",
    ],
    "13-next.md": [
        "본 연구가 다음 세대 사역에 시사하는 바를 이해한다.",
        "축구 선교가 청소년·청년 사역에서 갖는 잠재력을 파악한다.",
        "세대 간 통합 사역의 가능성을 모색한다.",
    ],
}


def clean_urls(text: str) -> str:
    """Aggressively strip URLs and their broken fragments."""
    # 1. Parenthetical that contains a URL
    text = re.sub(r"\([^()]*https?://[^()]*\)", "", text, flags=re.IGNORECASE)
    # 2. Bare URLs (any length, until whitespace)
    text = re.sub(r"https?://\S+", "", text, flags=re.IGNORECASE)
    # 3. URL-encoded fragments orphaned by line wraps (e.g. "%B9%CC%B5%F0...")
    text = re.sub(r"(?:%[0-9A-Fa-f]{2})+[\w%./?=&-]*", "", text)
    # 4. Domain/path fragments without scheme (e.g. "namu.wiki/w/...")
    text = re.sub(r"\b[a-zA-Z0-9.-]+\.(?:com|net|org|kr|info|wiki|tv|or)\S*", "", text, flags=re.IGNORECASE)
    # 5. Common orphan path snippets from PDF line wraps
    text = re.sub(r"\b(?:dia/act|combination_element|PaperHTM|statisticsList|encyclopedia/view)\S*", "", text, flags=re.IGNORECASE)
    # 6. Query string remnants (`&param=value`)
    text = re.sub(r"&[\w%-]+=[\w%-]*", "", text)
    # 7. Access-date markers
    text = re.sub(r"\(\s*(?:Accessed|검색일자|검색일|search)[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*검색일자\s*[^)]*$", "", text, flags=re.MULTILINE)  # unterminated
    # 8. ":=" markers leftover
    text = re.sub(r":=\s*", "", text)
    # 9. Stray empty parens
    text = re.sub(r"\(\s*[\.\s]*\)", "", text)
    # 10. Hollow footnote markers (alone on a line)
    text = re.sub(r"^\s*\d+\)\s*$", "", text, flags=re.MULTILINE)
    # 11. Whitespace cleanup
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def replace_objectives(text: str, filename: str) -> str:
    """Replace empty 학습 목표 placeholder block with curated objectives."""
    if filename not in OBJECTIVES:
        return text

    placeholder_re = re.compile(
        r"## 학습 목표\s*\n+"                 # heading
        r"_\([^)]*채워주세요\.\)_\s*\n+"      # italic guide
        r"(?:- ?\s*\n)+",                      # 3 empty bullets
    )
    if not placeholder_re.search(text):
        return text  # already filled in or pattern changed

    bullets = "\n".join(f"- {obj}" for obj in OBJECTIVES[filename])
    new_block = f"## 학습 목표\n\n{bullets}\n\n"
    return placeholder_re.sub(new_block, text, count=1)


def main():
    url_count = 0
    obj_count = 0
    for fname in URL_CLEAN_FILES:
        path = os.path.join(MS_DIR, fname)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        new_text = clean_urls(text)
        new_text = replace_objectives(new_text, fname)
        if new_text != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            saved = len(text) - len(new_text)
            print(f"  {fname}: -{saved} chars")
            url_count += 1
            if fname in OBJECTIVES:
                obj_count += 1
    print(f"\n{url_count} files cleaned, {obj_count} objectives populated")


if __name__ == "__main__":
    main()
