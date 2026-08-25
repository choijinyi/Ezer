---
description: 편집부 최종 PDF 빌드 (BookTemplate, 신국판/B5)
---

# /book-build

인자: $ARGUMENTS (형식: `<책이름> [판형: 1=신국판 | 2=B5]`)

## 절차

1. `BookTemplate/content/<책>/`이 없으면 중단하고 `/book-handoff <책>` 안내.
2. 판형이 지정되지 않았으면 사용자에게 질문:
   - `1` 신국판 (152×225mm) — 시집·에세이·신앙서적·소설
   - `2` B5 (188×257mm) — 학술서·교재·강해서·도판 많은 책
3. 실행 (작업 디렉토리 = `BookTemplate/`, 반드시 비대화형 플래그 사용):
   ```
   python build_book.py <책> -o output -p <1|2> --style style-pro.css --recto-chapters
   ```
   대화형 프롬프트에 걸리지 않도록 `-o`와 `-p`를 항상 명시한다.
   `--style style-pro.css --recto-chapters` = 전문 조판(내장 폰트·미러 마진·홀수면 장 시작, 루트 CLAUDE.md "출판 품질 도구체인" 참조). 기존 조판 재현이 필요할 때만 `--style` 생략.
4. 출력 확인:
   - 스크립트가 경고한 누락 파일(`content/에 없는 파일(스킵)`)이 있으면 그대로 보고
   - `output/book_preview.html`과 생성된 PDF 경로·페이지 수 보고
5. 본문 오탈자·문장 수정이 필요해지면 content/를 직접 고치지 말고 `bookwriter/manuscripts/`에서 수정 → `/book-handoff` 재실행을 안내한다 (손유지 파일 제외).
