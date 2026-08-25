---
description: 모든 책의 단계 현황 (집필 중 / 편집 중 / 완성)
---

# /book-status

인자 없음 (특정 책 이름이 오면 그 책만 상세히).

## 절차

1. 세 위치를 조사한다:
   - `bookwriter/manuscripts/*/` — 집필 원고 (`.gitkeep` 제외)
   - `BookTemplate/content/*/` — 편집 중 원고
   - `BookTemplate/output/*.pdf` — 빌드 결과물
2. 책별 단계 판별 (루트 CLAUDE.md 규칙):
   - manuscripts에만 있음 → **집필 중**
   - content에 있음 → **편집 중**
   - output에 해당 책 PDF 있음 → **완성** (PDF 파일명은 `books.py`의 `pdf_filename` 어간으로 매칭)
3. 집필 중인 책은 `bookwriter/manuscripts/<책>/.bookwriter/jobs.json`이 있으면 최근 job의 `build/<job>/state.json` stage도 표시.
4. 편집 중인 책은 `BookTemplate/books.py`의 BOOKS 등록 여부 + 손유지 파일(목차 등) 존재 여부 + 표지 이미지 존재 여부를 표시.
5. 표로 정리해 보여주고, 각 책의 다음 행동(`/book-handoff`, `/book-illustrate`, `/book-build` 등)을 제안한다.
6. **현황판 갱신**: `dashboard/board.html`의 기준일·수치·카드·표를 조사 결과로 고쳐 쓰고, 루트 CLAUDE.md의 "현황판" 섹션에 적힌 URL로 Artifact 재게시한다 (`url` 파라미터 사용, favicon 📚 유지).
