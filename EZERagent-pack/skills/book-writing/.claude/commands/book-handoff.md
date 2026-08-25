---
description: 집필 → 편집 이관. 원고 검증 후 books.py 등록, content/ 변환까지.
---

# /book-handoff

인자: $ARGUMENTS (책 이름 = `bookwriter/manuscripts/` 하위 폴더명)

집필이 끝난 원고를 편집부(BookTemplate)로 넘긴다. 아래 순서를 지키고, **게이트에서 승인 없이 진행하지 않는다.**

## 1. 집필 완료 검증

- `bookwriter/manuscripts/<책>/book.json` 존재 + 파싱 가능
- `chapters[].file`이 전부 디스크에 존재하고, 본문 장이 비어있지 않음
- 스캐폴드 문구("여기에 N장을 쓴다" 류)가 남아 있으면 미완성으로 보고 중단, 해당 장 목록을 보여준다
- 검증 실패 시: 무엇이 부족한지 알리고 끝낸다 (이관 강행 금지)

## 2. books.py 등록 (게이트)

- `BookTemplate/books.py`의 `BOOKS`에 `<책>` 키가 있는지 확인
- 없으면 항목 초안을 작성해 **사용자 승인 후** 추가:
  - title/subtitle/author ← `book.json`
  - `pdf_filename` ← 제목 기반 (한글 제목 + `.pdf`)
  - `chapters` 7-tuple 매핑 ← 원고 파일 순서 + 각 파일의 H1. 간지 label(CHAPTER/PROLOGUE/…)과 간지용 짧은 제목은 초안으로 제시하고 사용자가 다듬는다
  - 손유지 행(목차 등)은 `(None, "00_목차.md", None, None, None, None, None)` 형식으로 포함
- 기존 등록이 있으면 원고 챕터 구성과 어긋나는 항목만 보고한다

## 3. 변환 실행

작업 디렉토리 = `BookTemplate/`:
```
python convert_manuscript.py <책>
```
- `content/<책>/`가 이미 있으면: 변환 대상 파일은 덮어써지고 손유지 파일(source=None)은 건드리지 않는다는 점을 먼저 알린다. content/에만 있는 수기 수정이 의심되면 중단하고 확인받는다.

## 4. 편집부 초기 세팅

변환 후 체크리스트를 점검하고 부족한 것을 채운다:

- [ ] `content/<책>/00_목차.md` — 없으면 변환된 장들의 간지 제목·H2로 목차 초안 생성 (형식은 기존 책 목차 참조)
- [ ] 손유지 전면부 파일 (추천사·지은이소개·머리말) — 필요 여부를 사용자에게 확인
- [ ] 표지 이미지 (`BookTemplate/images/`) — 없으면 `/book-illustrate <책>` 제안
- [ ] 본문 도판 (`images/figures/`) — 원고의 figures 참조가 실제 파일과 매칭되는지 확인

완료되면: "편집 준비 완료 — `/book-build <책>`으로 빌드 가능"을 알린다.
