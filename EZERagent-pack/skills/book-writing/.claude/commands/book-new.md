---
description: 새 책 시작 — 집필부(bookwriter)에 원고 스캐폴드 생성
---

# /book-new

인자: $ARGUMENTS (형식: `<책이름> [--chapters N] [--lang ko|en]`)

## 절차

1. 책 이름이 없으면 사용자에게 묻는다. 이름은 영문 kebab-case 권장 (예: `soccer-mission-book`).
2. `bookwriter/manuscripts/<이름>/`이 이미 있으면 중단하고 알린다.
3. 실행 (작업 디렉토리 = `bookwriter/`):
   ```
   node scripts/pipeline/new.ts --scaffold <이름> [--chapters N] [--lang ko]
   ```
4. 생성된 `manuscripts/<이름>/book.json`의 title/subtitle/authors를 사용자에게 확인받아 채운다.
5. 사용자에게 안내:
   - 집필은 `manuscripts/<이름>/NN-*.md`에서 진행 (본문의 단일 원천)
   - 도식이 필요하면 `<!-- fig: -->` Mermaid 마커 사용 (`bookwriter/scripts/pipeline/SPEC.md` §2.7)
   - 집필 중 검증·가제본은 bookwriter의 `/new` `/run` `/status` 사용
   - 집필이 끝나면 `/book-handoff <이름>`으로 편집부에 이관
