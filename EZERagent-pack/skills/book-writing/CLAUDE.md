# BOOK — 책 제작 메타 템플릿

이 폴더는 두 하위 템플릿을 **순서대로** 잇는 상위 워크플로다.

1. **집필부** = `bookwriter/` — 원고를 쓰고 다듬는다.
2. **편집부** = `BookTemplate/` — 넘겨받은 원고를 책으로 조판한다.

```text
bookwriter/manuscripts/<책>/          ← 1단계: 집필 (원고의 단일 원천)
        │
        ▼  BookTemplate/convert_manuscript.py <책>     ← 2단계: 이관(handoff)
BookTemplate/content/<책>/            ← 3단계: 편집 (간지·목차·표지·도판)
        │
        ▼  BookTemplate/build_book.py <책> -o output -p <1|2>
BookTemplate/output/<책>_판형_시각.pdf ← 완성
```

## 역할 분담 (어느 부서가 무엇을 하는가)

| | 집필부 `bookwriter/` | 편집부 `BookTemplate/` |
|---|---|---|
| 본문 텍스트 작성·수정 | ✅ (유일한 원천) | ❌ 하지 않음 |
| 구조 검증·교정 제안 | ✅ (`/run --polish` 게이트) | ❌ |
| Mermaid 도식 | ✅ (`<!-- fig: -->` 마커) | — |
| 간지(chapter-title-page)·목차 | ❌ | ✅ (`books.py` 매핑 + 손유지 파일) |
| 표지·본문 이미지 | (가제본용 자동 표지만) | ✅ (`images/`, `images/figures/`) |
| 판형·디자인·최종 PDF | (typst 가제본 미리보기만) | ✅ (신국판/B5, Playwright PDF) |

**핵심 원칙 — 본문의 단일 원천은 `bookwriter/manuscripts/`다.**
`content/`는 파생물이므로 본문 오탈자·문장 수정이 필요하면 manuscripts에서 고치고 다시 이관한다.
예외: `books.py`에서 `source_filename=None`인 **손유지 파일**(목차, 추천사, 지은이 소개 등)은 `content/`에서 직접 유지하며, 이관 시 덮어쓰지 않는다.

## 단계 판별 규칙

- `bookwriter/manuscripts/<책>/`만 있음 → **집필 중**
- `BookTemplate/content/<책>/` 있음 → **편집 중**
- `BookTemplate/output/`에 그 책의 PDF 있음 → **완성** (재편집 가능)

## 메타 명령어 (이 폴더에서 사용)

| 명령 | 단계 | 역할 |
|---|---|---|
| `/book-new <이름>` | 집필 | 새 원고 스캐폴드 생성 |
| `/book-status` | 전체 | 모든 책의 단계 현황 |
| `/book-handoff <이름>` | 이관 | 집필 완료 검증 → books.py 등록 → content/ 변환 |
| `/book-illustrate <이름>` | 편집 | Higgsfield로 표지·삽화 생성 |
| `/book-build <이름>` | 편집 | 최종 PDF 빌드 |

하위 템플릿 자체 명령(`bookwriter/`의 `/new` `/run` `/status`)은 집필 단계 안에서 그대로 쓴다.
각 하위 템플릿의 세부 규칙은 `bookwriter/AGENTS.md`, `bookwriter/scripts/pipeline/SPEC.md`, `BookTemplate/책만들기_종합_지침서.md` 참조.

## 외부 도구 연동 (권장)
        
- **Higgsfield MCP** (연결됨) — 편집부 그림 담당. 표지 원화·장 간지 일러스트·본문 삽화는 `generate_image`, 인쇄 대비 해상도는 `upscale_image`(2K/4K), 표지 판형 비율 맞춤은 `outpaint_image`, 누끼는 `remove_background`. 산출물은 `BookTemplate/images/`(표지) 및 `BookTemplate/images/figures/`(본문 도판)에 저장. → `/book-illustrate`
- **Canva MCP** (연결됨) — 표지 타이포그래피 마감. Higgsfield 원화를 업로드해 제목·저자 텍스트를 얹고 PNG로 export. `books.py`의 `cover.mode="image", overlay_text=False`와 궁합.
- **NotebookLM MCP + `/deep-research` 스킬** — 집필부 자료조사. 참고문헌 PDF를 소스로 넣고 근거 질의, 인용 검증.
- **Mermaid CLI** (`mmdc`) — 도식·차트는 이미지 생성 AI가 아니라 Mermaid로 (집필 단계 `<!-- fig: -->` 마커, 결정적·수정 가능).

도식/차트 = Mermaid(집필부), 사진·일러스트·표지 = Higgsfield(편집부)로 구분한다.
