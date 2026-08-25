"""모든 본문 장을 raw extracted.txt에서 재추출/재정리/템플릿 적용까지 한 번에 처리.

기존 fill-content.py + cleanup-trade-text.py + textbook-template.py가
순서·각주 처리·중간 끊김에서 미흡했던 점을 한 패스로 수정.

추가:
- 영문 abstract 별도 챕터(00b-abstract-en.md)로 분리
- 각주 정의 제거를 가장 먼저 (마커 제거 전에)
- 학습 목표 다음 본문 시작 전에 빈 줄 보강
- 한글-한글 단락 합치기 더 공격적
"""
import json
import os
import re
from typing import Optional

ROOT = "C:\\dev\\bookwriter"
MS_DIR = os.path.join(ROOT, "manuscripts", "soccer-mission-book")
EXTRACTED = os.path.join(os.environ.get("TEMP", "/tmp"), "extracted.txt")

# (start, end, role, filename, title, kind)
# kind: "abstract-ko" | "abstract-en" | "body" | "closing" | "backmatter"
SECTIONS = [
    (43, 94,   "frontmatter", "00-abstract.md",     "초록",        "abstract-ko"),
    (95, 144,  "frontmatter", "00b-abstract-en.md", "Abstract",    "abstract-en"),
    (600, 1092, "body", "01-collapse.md",     "무너지는 교회 앞에서",     "body"),
    (1094, 1270, "body", "02-sport.md",       "스포츠라는 문화",         "body"),
    (1271, 1435, "body", "03-culture.md",     "문화로 전하는 복음",       "body"),
    (1436, 1934, "body", "04-incarnation.md", "성육신과 선교적 교회",     "body"),
    (1935, 2106, "body", "05-soccer.md",      "세상이 사랑하는 게임",     "body"),
    (2107, 2266, "body", "06-mission.md",     "축구가 선교가 되다",       "body"),
    (2267, 2840, "body", "07-fellow.md",      "함께 뛴 사람들",           "body"),
    (2841, 2874, "body", "08-missional.md",   "선교적 교회와 축구",       "body"),
    (2875, 2927, "body", "09-method.md",      "연구의 길",                "body"),
    (2929, 4850, "body", "10-voices.md",      "현장의 이야기",            "body"),
    (4851, 5689, "body", "11-numbers.md",     "숫자가 말하는 것",         "body"),
    (5690, 5814, "body", "12-answers.md",     "일곱 가지 질문에 답하다",  "body"),
    (5816, 5878, "body", "13-next.md",        "다음 세대로 이어지는 발걸음", "body"),
    (5879, 5930, "body", "14-forward.md",     "책을 닫으며 — 더 멀리 차는 공", "closing"),
    (5931, 6206, "backmatter", "98-appendix.md",   "부록",      "backmatter"),
]

# 99-references.md는 별도 처리됨 (rebuild-refs-apa.py가 관리)

PAGE_MARKER = re.compile(r"^<<<PAGE \d+>>>\s*$")
PAGE_NUM = re.compile(r"^\s*-\s*[ivxIVXC0-9]+\s*-\s*$")


def is_cjk(c: str) -> bool:
    if not c:
        return False
    code = ord(c)
    return 0xAC00 <= code <= 0xD7AF or 0x4E00 <= code <= 0x9FFF


# ── Cleanup steps (운용 순서가 중요) ────────────────────────────

def strip_markers(lines: list[str]) -> list[str]:
    return [
        ln for ln in lines
        if not PAGE_MARKER.match(ln) and not PAGE_NUM.match(ln)
    ]


FOOTNOTE_LINE_START = re.compile(r"^\s*\d{1,2}\)\s*(.+)$")
# 소제목 후보: 한글/공백/숫자/?만 있고 ≤30자
KO_HEADING_CHARS = re.compile(r"^[가-힣\s\d?!\.]+$")


def is_subsection_heading_line(ln: str) -> bool:
    """`N) [짧은 한글 제목]` 패턴. 영문·URL·괄호·따옴표 미포함."""
    m = FOOTNOTE_LINE_START.match(ln)
    if not m:
        return False
    rest = m.group(1).strip()
    if len(rest) > 30:
        return False
    return bool(KO_HEADING_CHARS.match(rest))


def is_footnote_def_line(ln: str) -> bool:
    """이 줄이 각주 정의의 시작인지.
    한글 소제목(예: `1) 문화는 무엇인가?`, `3) 선교란`)은 각주가 아님."""
    if not FOOTNOTE_LINE_START.match(ln):
        return False
    if is_subsection_heading_line(ln):
        return False
    return True


def remove_footnote_definitions_pre_join(lines: list[str]) -> list[str]:
    """각주 정의 블록만 제거. 짧은 한글 sub-section 헤딩(예: '3) 선교란')은 보존."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if is_footnote_def_line(ln):
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() == "":
                    i += 1
                    break
                if is_footnote_def_line(nxt):
                    break
                i += 1
            continue
        # sub-section heading은 별도 단락으로 분리되도록 빈 줄 보강
        if is_subsection_heading_line(ln):
            if out and out[-1].strip() != "":
                out.append("")
            out.append(ln)
            out.append("")
            i += 1
            continue
        out.append(ln)
        i += 1
    return out


CHAPTER_HEADER_RE = re.compile(r"^\s*제\s*\d+\s*장\b.*$")
NUMBERED_SECTION_RE = re.compile(r"^\s*(\d+)\.\s+(.{1,60}?)\s*$")
NUMBERED_SUB_RE = re.compile(r"^\s*\(?\d+\)\s+(.{1,60}?)\s*$")


def transform_chapter_headers(lines: list[str]) -> list[str]:
    """원본 챕터 헤딩 제거, 번호 섹션 헤딩을 ## 로 변환.
    헤딩 앞뒤 빈 줄 보장 → 단락 분리/병합이 깨끗해짐."""
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if CHAPTER_HEADER_RE.match(s):
            continue
        m = NUMBERED_SECTION_RE.match(ln)
        if m:
            title = m.group(2).strip()
            if out and out[-1].strip() != "":
                out.append("")
            out.append(f"## {title}")
            out.append("")
            continue
        out.append(ln)
    return out


def remove_inline_footnote_chunks(text: str) -> str:
    """본문 안 mid-line 각주 정의 블록 제거.
    매치 조건: `\\d+\\)` 직후가 따옴표/괄호 OR 공백+실제 내용. 공백+개행 (= 본문 끝
    마커의 트레일링 스페이스) 은 제외해야 본문 단락이 잡아먹히지 않음."""
    return re.sub(
        r"(?<!\d)\b\d{1,2}\)(?:['\"\(]|[ \t]+(?=\S)).+?(?=\n\s*\n|\Z)",
        "",
        text,
        flags=re.DOTALL,
    )


def remove_inline_footnote_markers(text: str) -> str:
    """본문 안에 박혀 있는 N) 마커 제거 (앞이 한글/영문/구두점)."""
    text = re.sub(
        r"(?<![\d ])(?<=[가-힣A-Za-z\.\?\!\,\)\'\"])\d{1,2}\)",
        "",
        text,
    )
    return text


def remove_urls(text: str) -> str:
    text = re.sub(r"\([^()]*https?://[^()]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:%[0-9A-Fa-f]{2})+[\w%./?=&-]*", "", text)
    text = re.sub(r"\b[a-zA-Z0-9.-]+\.(?:com|net|org|kr|info|wiki|tv|or)\S*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:dia/act|combination_element|PaperHTM|statisticsList|encyclopedia/view)\S*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"&[\w%-]+=[\w%-]*", "", text)
    text = re.sub(r"\(\s*(?:Accessed|검색일자|검색일|search)[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r":=\s*", "", text)
    return text


def remove_inline_citations(text: str) -> str:
    """제거: (저자, 연도) (저자 연도, 페이지) (1990) 등."""
    text = re.sub(
        r"\(\s*[가-힣A-Za-z][가-힣A-Za-z·.\s,&]{0,40}?[\s,]+\(?\d{4}\)?(?:,\s*\d+(?:[-–]\d+)?)?\s*\)",
        "",
        text,
    )
    text = re.sub(r"\(\s*\d{4}(?:,\s*\d+(?:[-–]\d+)?)?\s*\)", "", text)
    return text


def remove_inline_caption_brackets(text: str) -> str:
    text = re.sub(r"❲[^❳]+❳[^\n❲<]*", "", text)
    text = re.sub(r"<\s*표\s*\d[^>]*>[^\n<]*", "", text)
    text = re.sub(r"<\s*그림\s*\d[^>]*>[^\n<]*", "", text)
    return text


def cleanup_residue(text: str) -> str:
    # Source PDF typo correction (no space — 하나님나라가 한 단어)
    text = text.replace("한나나라", "하나님나라")
    text = text.replace("하나님 나라", "하나님나라")

    # Empty parens
    text = re.sub(r"\(\s*[\.,]?\s*\)", "", text)
    # Dangling open paren at end of line / paragraph
    text = re.sub(r"\(\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\(\s*(?=\n)", "", text)
    # Lone close paren at start of line
    text = re.sub(r"^\s*\)\s*", "", text, flags=re.MULTILINE)
    # Open paren followed by punctuation only
    text = re.sub(r"\(\s*[\.,;:]+\s*", "", text)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def join_cjk_lines(text: str) -> str:
    """한 단락 안에서 줄바꿈으로 깨진 한글 텍스트를 합침.
       - 한글로 끝나고 한글로 시작하는 인접 줄: 공백 없이 결합
       - 그 외: 공백 한 칸으로 결합
       - 헤딩/이미지/리스트 줄은 보존
    """
    paragraphs = re.split(r"\n\s*\n+", text)
    out_paragraphs = []
    for p in paragraphs:
        lines = p.split("\n")
        # Skip joining if any line is structural
        if any(re.match(r"^\s*(#|!\[|[-*]\s|\d+[.)]\s|>)", ln) for ln in lines):
            out_paragraphs.append(p)
            continue
        joined = ""
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            if not joined:
                joined = s
                continue
            if is_cjk(joined[-1]) and is_cjk(s[0]):
                joined += s
            else:
                joined += " " + s
        out_paragraphs.append(joined)
    return "\n\n".join(out_paragraphs).rstrip() + "\n"


_STRUCT_RE = re.compile(r"^[#!\[>]|^\s*[-*]\s|^\s*\d+[.)]\s")


def _is_struct(s: str) -> bool:
    return bool(_STRUCT_RE.match(s))


def merge_midsentence_paragraphs(text: str) -> str:
    """카스케이드 합치기: 각 단락을 이전 단락 끝과 비교해서 한글-한글 경계면 합침."""
    paragraphs = re.split(r"\n\s*\n+", text)
    result: list[str] = []
    for p in paragraphs:
        s = p.strip()
        if not s:
            continue
        if result:
            prev = result[-1]
            if (prev and not _is_struct(prev) and not _is_struct(s)
                and is_cjk(prev[-1]) and is_cjk(s[0])):
                result[-1] = prev + s
                continue
        result.append(s)
    return "\n\n".join(result).rstrip() + "\n"


# ── Main per-chapter pipeline ──────────────────────────────────────

def clean_chapter_body(raw_lines: list[str]) -> str:
    """raw lines → cleaned body text."""
    # readlines() retains trailing \n on each entry; normalize to plain content
    lines = [ln.rstrip("\n").rstrip("\r") for ln in raw_lines]
    lines = strip_markers(lines)
    lines = remove_footnote_definitions_pre_join(lines)
    lines = transform_chapter_headers(lines)
    text = "\n".join(lines)

    # NOTE: inline footnote chunk removal disabled — too risky (could eat body
    # paragraphs that just happen to have a "N)" marker after a period).
    # The line-based remove_footnote_definitions_pre_join handles real footnotes.
    text = join_cjk_lines(text)
    text = remove_inline_footnote_markers(text)
    text = remove_urls(text)
    text = remove_inline_citations(text)
    text = remove_inline_caption_brackets(text)
    text = cleanup_residue(text)
    text = merge_midsentence_paragraphs(text)
    return text.strip() + "\n"


# ── Content for placeholders (이전 fill-content.py에서 가져옴) ────

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

SUMMARIES = {
    "01-collapse.md": "한국 교회는 1885년 첫 선교사 도래 이후 한 세기 동안 빠르게 성장하며 신앙 공동체로 자리 잡았다. 그러나 2003년 주 5일제 근무제도 도입과 2019년 코로나19 팬데믹은 교회의 모임 형태와 일정에 큰 변화를 가져왔다. 출산율 저하로 인한 학령 인구 감소, 사회적 가치관 변화, 그리고 교회 내부 갈등이 겹치면서 어린이와 청소년, 청년 세대의 이탈이 가속화되었다. 본 장은 이러한 환경적 구조적 위기 속에서 전통적 사역 방식만으로는 다음 세대를 품을 수 없음을 진단하며, 시대에 맞는 새로운 사역 컨텐츠와 접근의 필요성을 제기한다.",
    "02-sport.md": "스포츠는 신체 활동을 매개로 사람과 사람을 연결하는 문화 활동이다. 본 장은 스포츠가 단순한 운동이 아니라 사회적 관계를 형성하고 가치를 공유하며 인격을 다듬는 종합적 문화 양식임을 살펴본다. 건강 증진, 정서 안정, 공동체 형성, 갈등 해결 등 스포츠가 가진 다양한 사회적 기능은 교회 사역에서도 의미 있는 자원이 될 수 있다. 스포츠를 문화로 이해할 때 비로소 그것이 어떻게 복음을 담는 그릇이 될 수 있는지 보이기 시작한다.",
    "03-culture.md": "문화는 한 공동체가 공유하는 삶의 양식이며, 복음은 그 문화의 옷을 입고 사람에게 가닿는다. 본 장은 문화의 정의와 구성 요소를 살피고, 선교의 본질이 문화 속에서 그리스도를 증언하는 것임을 성서적 근거로 제시한다. 복음과 문화의 관계는 적대도 동일시도 아닌, 문화의 옷을 입은 복음이 사람과 사람을 만나게 하는 다리임을 강조한다. 문화로 전하는 복음은 교회가 세상에서 어떻게 살아야 하는지를 묻는 근본적인 질문이기도 하다.",
    "04-incarnation.md": "하나님이 사람의 몸을 입고 우리 가운데 오신 성육신은 단순한 신학적 사건이 아니라, 교회가 어떻게 세상에 존재해야 하는지를 가르치는 모범이다. 본 장은 성육신 신학을 토대로 선교적 교회의 정체성과 사명을 살펴본다. 선교적 교회는 교회 안에 머무르지 않고 세상으로 나아가, 사람들의 삶 속에 자리 잡고 그 자리에서 그리스도를 증언하는 공동체다. 한국 교회가 지금 마주한 변화 속에서 회복해야 할 핵심은 바로 이 성육신적 자세다.",
    "05-soccer.md": "축구는 단순한 규칙과 공 하나로 누구나 참여할 수 있는, 세계에서 가장 널리 사랑받는 스포츠다. 본 장은 축구의 보편성과 단순성, 그리고 세계 인구의 절반 가까이가 어떤 형태로든 즐기는 이 게임의 매력을 살펴본다. 한국에서도 1882년 영국 군함 선원들이 인천에서 처음 공을 차며 축구가 시작된 이래, 학교와 동네 골목에서 자라난 축구는 한국인의 일상 깊숙이 자리 잡았다. 이 단순하면서도 보편적인 게임이 어떻게 사람을 모으고 마음을 잇는 도구가 될 수 있는지를 본 장은 보여준다.",
    "06-mission.md": "축구 선교는 축구라는 문화를 매개로 복음을 전하고 신앙 공동체를 세우는 활동이다. 본 장은 일반적 축구 활동과 축구 선교 활동의 차이를 명확히 구분한다. 핵심은 ‘공만 차고 즐기는 것’이 아니라 ‘복음과 그 가치를 함께 나누는 시간’이라는 점이다. 신학적으로 축구 선교는 성육신적 접근, 곧 사람들이 사랑하는 자리로 교회가 찾아가는 자세를 구체적 형태로 실천하는 것이다.",
    "07-fellow.md": "본 장은 한국 교회에서 축구를 매개로 펼쳐진 다양한 선교 활동 사례들을 모아 살펴본다. 할렐루야 축구단, 임마누엘 축구단, 글로리아 선교 축구단을 비롯해 지역 교회 단위의 작은 모임에 이르기까지, 각 사례는 서로 다른 출발점과 방식에도 불구하고 공통된 마음을 가진다. 사람을 만나고 복음을 나누며 공동체를 세우는 마음이다. 이 사례들에서 발견되는 원리들은 새로 시작하는 교회들에게 실제적 지침이 된다.",
    "08-missional.md": "선교적 교회는 자신의 문턱을 넘어 세상으로 나아가는 공동체다. 본 장은 축구 선교가 단순히 사역의 한 프로그램이 아니라, 선교적 교회 패러다임을 구체적으로 실천하는 형태임을 보여준다. 축구라는 문화 속으로 들어가 사람들과 함께 뛰고 땀 흘리며 신앙을 나누는 행위는, 교회의 본질적 사명인 그리스도의 증언을 가장 실제적인 모습으로 드러낸다.",
    "09-method.md": "본 연구는 축구 선교 활동이 교회에 미치는 영향을 양적·질적 두 축으로 살피기 위해 혼합 연구 방법을 채택했다. 질적 연구로는 13명의 축구 선교사 및 사역자를 인터뷰하고, 양적 연구로는 용인서부교회 성도들을 대상으로 설문을 시행했다. 연구 윤리와 대상 보호를 위한 절차를 명확히 따랐으며, 두 자료원이 서로를 보완하도록 설계되었다.",
    "10-voices.md": "본 장은 13명의 인터뷰를 통해 축구 선교 현장의 실제 모습을 들려준다. 목사, 전도사, 장로, 축구 감독·코치, 사업가에 이르기까지 다양한 배경의 사역자들이 각자의 자리에서 펼쳐온 활동과 그 안에서 만난 사람들의 변화를 증언한다. 이들의 목소리에서 공통적으로 드러나는 것은, 축구는 사람을 모으는 데 강력하지만 그것이 선교가 되려면 의도적 설계와 인내가 필요하다는 사실이다. 현장의 이야기는 이론을 넘어 실천의 깊이를 보여준다.",
    "11-numbers.md": "용인서부교회 성도들을 대상으로 한 설문은 7개 연구 질문, 곧 공동체 친밀성, 전도와 봉사, 효과적 선교, 다음 세대 전략, 담임목사와의 관계, 신앙 성숙, 심리적 안정감에 대한 정량적 응답을 수집했다. 통계 분석은 축구 선교 활동이 거의 모든 영역에서 의미 있는 긍정적 영향을 미쳤음을 보여준다. 본 장은 그 수치들을 해석하고, 그것이 가리키는 바와 동시에 자료가 가진 한계도 함께 다룬다.",
    "12-answers.md": "본 장은 양적·질적 두 자료를 통합하여 7개 연구 질문에 대한 답을 종합한다. 축구 선교 활동은 공동체의 친밀성을 강화하고, 전도와 봉사로 이끌며, 다음 세대를 향한 통로를 열고, 담임목사와 성도 간의 관계에 긍정적 영향을 미친다. 무엇보다도 신앙의 성숙과 정서적 안정에 기여한다는 점이 인상적이다. 일곱 질문에 대한 답은 분리되지 않고 서로 맞물려 하나의 그림을 완성한다.",
    "13-next.md": "교회가 다음 세대를 잃어가는 시대, 본 장은 축구 선교가 청소년·청년 사역에 어떤 가능성을 가지는지 살펴본다. 운동장에서 함께 뛰는 동안 형성되는 신뢰는 교실이나 강당에서 얻기 어려운 것이며, 이것은 다음 세대를 향한 가장 자연스러운 통로 중 하나다. 또한 축구 선교는 세대를 분리하지 않고 통합할 수 있는 드문 사역의 형태로, 가족과 교회 공동체를 함께 묶는 가능성을 가진다.",
}

REFLECTIONS = {
    "01-collapse.md": [
        "우리 교회가 마주한 가장 큰 환경 변화는 무엇이었으며, 어떻게 응답해 왔는가?",
        "다음 세대를 위해 우리 교회가 마련하고 있는 컨텐츠와 사역 방식은 어떤 것이 있는가?",
        "주 5일제 근무가 시행된 이후 교회의 토요일·주일 일정은 어떻게 달라졌는가?",
        "교회 내부의 갈등이 외부에 미치는 영향을 줄이려면 무엇이 필요한가?",
    ],
    "02-sport.md": [
        "스포츠는 단순한 운동인가, 아니면 그 이상의 문화인가?",
        "우리 사회에서 가장 영향력 있는 스포츠 문화는 무엇이며, 왜 그러한가?",
        "스포츠가 사람들의 가치관과 인격에 미치는 영향을 어떻게 평가하는가?",
    ],
    "03-culture.md": [
        "문화와 복음의 관계를 어떻게 이해해야 하는가?",
        "우리 교회가 속한 지역 문화의 특징은 무엇이며, 그것을 어떻게 활용할 수 있는가?",
        "문화에 적응하는 것과 문화에 동화되는 것의 차이는 무엇인가?",
    ],
    "04-incarnation.md": [
        "우리 교회는 ‘교회 안의 교회’인가, 아니면 ‘세상 속의 교회’인가?",
        "성육신 신학이 우리 사역의 구체적 모습에 어떻게 반영되어야 하는가?",
        "선교적 교회로 거듭나기 위해 우리 공동체가 가장 먼저 내려놓아야 할 것은 무엇인가?",
    ],
    "05-soccer.md": [
        "축구가 세계적으로 사랑받는 이유는 무엇인가?",
        "한국에서 축구가 갖는 사회적·문화적 의미는 무엇인가?",
        "우리가 가진 다른 스포츠 종목 중에서 축구만큼의 보편성을 가진 것은 무엇인가?",
    ],
    "06-mission.md": [
        "일반 축구 동호회와 축구 선교 활동단의 가장 큰 차이는 무엇인가?",
        "축구 선교 활동에서 ‘복음의 자리’는 어디에 있어야 하는가?",
        "축구 외에 우리 교회가 활용할 수 있는 다른 문화적 도구는 무엇이 있을까?",
    ],
    "07-fellow.md": [
        "소개된 사례 중 우리 교회가 본받을 만한 것은 무엇이며, 왜인가?",
        "사례마다 다른 출발점에도 불구하고 공통적으로 발견되는 원리는 무엇인가?",
        "우리 교회의 자원과 환경에 맞는 축구 선교 활동의 첫걸음은 어떻게 시작할 수 있을까?",
    ],
    "08-missional.md": [
        "선교적 교회의 관점에서 우리 교회의 사역은 어디에 위치해 있는가?",
        "축구 선교가 ‘선교적 교회의 한 표현’이 되기 위해 필요한 신학적·실천적 조건은 무엇인가?",
        "축구 선교 외에 선교적 교회가 가질 수 있는 다른 형태는 무엇이 있을까?",
    ],
    "09-method.md": [
        "양적 연구와 질적 연구를 함께 사용하는 것의 장점은 무엇인가?",
        "우리 교회의 사역을 평가할 때 어떤 자료를 모을 수 있을까?",
        "연구 윤리에서 가장 중요하게 지켜져야 할 원칙은 무엇이라 생각하는가?",
    ],
    "10-voices.md": [
        "인터뷰 중 가장 인상 깊었던 사례는 무엇이며, 왜인가?",
        "사역자들이 공통적으로 강조한 어려움은 무엇이었으며, 우리 교회는 이를 어떻게 준비할 수 있을까?",
        "인터뷰에서 드러난 ‘의도적 설계’는 구체적으로 무엇을 의미하는가?",
    ],
    "11-numbers.md": [
        "7개 연구 질문 중 가장 중요한 발견은 무엇이라 생각하는가?",
        "양적 자료의 강점과 한계는 각각 무엇인가?",
        "우리 교회에서 비슷한 설문을 한다면 어떤 항목을 추가하고 싶은가?",
    ],
    "12-answers.md": [
        "일곱 영향 중 우리 교회에서 가장 우선적으로 기대하고 싶은 것은 무엇인가?",
        "양적 자료와 질적 자료가 같은 결론을 가리키는 부분은 어디이며, 다른 부분은 어디인가?",
        "이 일곱 영향을 우리 교회의 다른 사역에서도 볼 수 있는 방법이 있을까?",
    ],
    "13-next.md": [
        "우리 교회의 다음 세대 사역에서 가장 큰 결핍은 무엇이라 보는가?",
        "축구 외에 세대 통합이 자연스럽게 일어날 수 있는 활동은 무엇이 있을까?",
        "다음 세대가 교회를 떠나지 않게 하기 위해 우리가 지금 시작할 수 있는 한 가지는 무엇인가?",
    ],
}

FURTHER = {
    "01-collapse.md": ["한국일 (2019). 선교적 교회의 실체. 서울: 장로회신학교 출판부.", "마이클 프로스트, 앨런 허쉬 (2021). 새로운 교회가 온다. 서울: 한국기독학생출판부."],
    "02-sport.md": ["김범식 외 (2002). 현대사회와 스포츠. 서울: 도서출판 홍경.", "이천희 (1996). 스포츠의 철학적 탐구. 서울: 고려대학교출판부."],
    "03-culture.md": ["김성태 (2000). 현대 선교학 총론. 서울: 도서출판 이레서원.", "안승오·박보경 (2011). 현대선교학 개론. 서울: 대한기독교서회."],
    "04-incarnation.md": ["김지호 (2021). 성육신 신학과 선교적 교회. 칼빈대학교 국제목회교육원.", "Craig Van Gelder (2015). 교회의 본질. 서울: CLC.", "Darrll L. Guder (2013). 선교적 교회: 북미교회의 파송을 위한 비전. 인천: 주안대학원대학교 출판부."],
    "05-soccer.md": ["김성원 (2006). 한국축구발전사. 경기: 살림 출판사.", "손영래·홍대선 (2010). 축구는 문화다. 서울: 책마루."],
    "06-mission.md": ["김민섭 (1998). 스포츠 선교의 이론과 실재. 서울: 성광문화사.", "송용필 (1996). 스포츠 선교의 현황과 중요성. 서울: 도서출판 횃불."],
    "07-fellow.md": ["류영수 (2011). 세계를 가슴에 품은 축구 선교. 서울: 도서출판 누가.", "박두규 (2003). 축구목회를 통한 신앙 공동체 형성. 박사학위논문, 드루대학교."],
    "08-missional.md": ["한국일 (2019). 선교적 교회의 실체. 서울: 장로회신학교 출판부.", "이상훈 (2018). 처치 시프트 — 선교적 교회사역 패러다임. 서울: 위심리더미디어."],
    "09-method.md": ["김은식 (2016). 스포츠 선교를 통한 효과적인 교회성장 전략 연구. 석사학위논문, 총신대학교 선교대학원.", "정승연 (2008). 스포츠가 선교에 미치는 영향. 석사학위논문, 칼빈대학교 신학대학원."],
    "10-voices.md": ["박두규 (2003). 축구목회를 통한 신앙 공동체 형성. 박사학위논문, 드루대학교.", "박민재 (2006). 스포츠 활동을 통한 교회성장전략. 박사학위논문, 풀러 신학대학원."],
    "11-numbers.md": ["김은식 (2016). 스포츠 선교를 통한 효과적인 교회성장 전략 연구. 석사학위논문, 총신대학교 선교대학원.", "정승연 (2008). 스포츠가 선교에 미치는 영향. 석사학위논문, 칼빈대학교 신학대학원."],
    "12-answers.md": ["이정숙 (2007). 선교 활동에 있어서 스포츠의 역할과 그 중요성. 박사학위논문, 아세아연합신학대학교 대학원.", "홍영식 (2007). 칼빈주의에서 본 축구 선교. 신학박사논문, 고려신학교 신학원."],
    "13-next.md": ["마이클 프로스트, 앨런 허쉬 (2021). 새로운 교회가 온다. 서울: 한국기독학생출판부.", "한국일 (2019). 선교적 교회의 실체. 서울: 장로회신학교 출판부."],
}

CLOSING_RECAP = (
    "이 책은 한국 교회가 마주한 환경적 위기에서 출발했다. "
    "1장에서 우리는 주 5일제 근무제도와 2019년 팬데믹이 교회의 모습을 어떻게 바꾸어 놓았는지, 그리고 다음 세대 사역의 공백이 얼마나 깊었는지를 살펴보았다.\n\n"
    "2장에서 4장까지는 새로운 길의 신학적 토대를 다졌다. "
    "스포츠가 갖는 문화적 의미, 문화로 복음을 전하는 선교의 본질, 그리고 성육신 신학이 그리는 선교적 교회의 모습 — 이 세 기둥은 축구 선교라는 구체적 실천의 근거가 되었다.\n\n"
    "5장부터 8장까지는 축구라는 문화 자체로 시선을 옮겼다. "
    "단순함과 보편성으로 세계가 사랑하는 게임이 어떻게 선교의 도구가 될 수 있는지, 한국 교회의 다양한 사례들을 통해 확인했고, 그것이 선교적 교회 패러다임 안에서 어떤 위치를 가지는지 정리했다.\n\n"
    "9장에서 12장까지는 실증적 연구가 펼쳐진다. "
    "13명의 축구 선교사 인터뷰와 200명이 넘는 성도 설문을 통해 축구 선교 활동이 교회 공동체에 미치는 영향을 일곱 가지 측면에서 검증했다. "
    "결론은 분명했다. 축구 선교는 친밀성, 전도, 다음 세대, 담임목사 관계, 신앙 성숙, 정서적 안정 모두에서 의미 있는 변화를 일으켰다.\n\n"
    "13장에서는 그 변화가 다음 세대로 어떻게 이어질 수 있는지 모색했다. "
    "책 전체를 관통하는 메시지는 분명하다. 축구는 단지 운동이 아니라, 사람을 모으고 관계를 회복시키며 복음을 나누는 다리가 될 수 있다."
)

CLOSING_FAREWELL = (
    "이 책을 손에 든 당신께 묻고 싶다.\n\n"
    "당신의 교회에는 어떤 사람들이 모이고 있는가? 그리고 그들과 함께 어떤 이야기를 만들어 가고 싶은가?\n\n"
    "축구 선교는 정답이 아니다. 한 가지 길이다. "
    "이 책에서 만난 13명의 사역자들이 그러했듯, 자신이 가진 도구와 마음으로 누군가에게 다가가는 것 — 그것이 결국 우리의 사명이다.\n\n"
    "당신이 가진 도구는 무엇인가? "
    "축구일 수도 있고, 음악일 수도, 요리나 글쓰기, 작은 이웃에 대한 따뜻한 시선일 수도 있다. "
    "무엇이든 좋다. 그저 사람을 향해 한 걸음 내딛는 것이 시작이다.\n\n"
    "더 멀리 차는 공처럼, 당신의 발걸음이 누군가의 마음에 가닿기를. "
    "부디 이 책이 당신의 다음 발걸음을 위한 작은 격려가 되기를 바란다.\n\n"
    "함께 뛰어주셔서 감사합니다."
)

# 도판 보존: 기존 파일에서 ## 도판 섹션을 추출해 새로 빌드한 파일 끝에 다시 붙임
DOPAN_RE = re.compile(r"\n+##\s*도판.*?(?=\n##\s|\Z)", re.DOTALL)


def extract_existing_dopan(filename: str) -> str:
    path = os.path.join(MS_DIR, filename)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = DOPAN_RE.search(text)
    if not m:
        return ""
    return m.group(0).strip()


# ── Output formatters ─────────────────────────────────────────────

def render_body_chapter(filename: str, title: str, body: str, dopan: str) -> str:
    parts: list[str] = [f"# {title}", "", "## 학습 목표", ""]
    for obj in OBJECTIVES.get(filename, []):
        parts.append(f"- {obj}")
    # 학습 목표 다음 한 줄 띄움 (요청: "한줄 띄고 시작")
    parts.append("")
    parts.append("&nbsp;")  # 빈 단락 마커 — typst에서 시각적 띄움 제공
    parts.append("")
    parts.append(body.strip())
    parts.append("")
    parts.append("## 요약")
    parts.append("")
    parts.append(SUMMARIES.get(filename, "_(요약을 채워주세요)_"))
    parts.append("")
    parts.append("## 생각해볼 거리")
    parts.append("")
    for i, q in enumerate(REFLECTIONS.get(filename, []), start=1):
        parts.append(f"{i}. {q}")
    parts.append("")
    parts.append("## 더 읽을거리")
    parts.append("")
    for ref in FURTHER.get(filename, []):
        parts.append(f"- {ref}")
    if dopan:
        parts.append("")
        parts.append(dopan)
    return "\n".join(parts).rstrip() + "\n"


def render_closing_chapter(title: str, body: str, dopan: str) -> str:
    parts = [
        f"# {title}",
        "",
        "## 우리가 함께 본 것",
        "",
        CLOSING_RECAP,
        "",
        "## 다음 발걸음을 위해",
        "",
        body.strip(),
        "",
        "## 독자에게",
        "",
        CLOSING_FAREWELL,
    ]
    if dopan:
        parts.append("")
        parts.append(dopan)
    return "\n".join(parts).rstrip() + "\n"


def render_abstract_ko(title: str, body: str) -> str:
    return f"# {title}\n\n{body.strip()}\n"


def render_abstract_en(title: str, body: str) -> str:
    return f"# {title}\n\n{body.strip()}\n"


def render_backmatter(title: str, body: str) -> str:
    return f"# {title}\n\n{body.strip()}\n"


# ── Main pipeline ─────────────────────────────────────────────────

def main():
    with open(EXTRACTED, "r", encoding="utf-8") as f:
        all_lines = f.readlines()

    book_chapters_meta: list[dict] = []

    for (start, end, role, filename, title, kind) in SECTIONS:
        section = all_lines[start - 1 : end]
        body_clean = clean_chapter_body(section)

        # render
        if kind == "body":
            dopan = extract_existing_dopan(filename)
            content = render_body_chapter(filename, title, body_clean, dopan)
        elif kind == "closing":
            dopan = extract_existing_dopan(filename)
            content = render_closing_chapter(title, body_clean, dopan)
        elif kind == "abstract-ko":
            content = render_abstract_ko(title, body_clean)
        elif kind == "abstract-en":
            content = render_abstract_en(title, body_clean)
        elif kind == "backmatter":
            content = render_backmatter(title, body_clean)
        else:
            content = body_clean

        path = os.path.join(MS_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        wc = sum(1 for _ in content.split())
        print(f"  {filename:25s}  {role:12s}  {wc:>6} words")

        book_chapters_meta.append({
            "file": filename,
            "title": title,
            "role": role,
        })

    # Add 99-references.md to manifest (preserved as-is)
    book_chapters_meta.append({
        "file": "99-references.md",
        "title": "참고문헌",
        "role": "backmatter",
    })

    # Update book.json
    book_path = os.path.join(MS_DIR, "book.json")
    with open(book_path, "r", encoding="utf-8") as f:
        book = json.load(f)
    book["chapters"] = book_chapters_meta
    with open(book_path, "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nbook.json: {len(book_chapters_meta)} chapters")


if __name__ == "__main__":
    main()
