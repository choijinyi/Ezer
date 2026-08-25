---
name: book-writing
description: 원고 집필부터 인쇄용 PDF까지 이어지는 책 제작 워크플로우. 집필부(bookwriter·Node)에서 원고를 쓰고 → 편집부(BookTemplate·Python+Chromium)로 이관해 신국판/B5로 조판·출력한다. 슬래시 명령 5종(book-new·book-handoff·book-illustrate·book-build·book-status)과 전문 조판 자산(내장 폰트·스타일시트)을 포함한다. "책 쓰자 / 책 만들기 / 원고 조판 / 인쇄용 PDF / 신국판 / B5 / 교재 제작 / book-new / book-build" 트리거로 발동.
---

# book-writing — 책 제작 워크플로우

원고를 쓰는 일과 책으로 만드는 일을 **분리**한 2단 구조다. 섞으면 원고가 조판에 오염되고,
조판을 고치려다 원고가 망가진다. 이 워크플로우는 그 경계를 강제한다.

```text
bookwriter/manuscripts/<책>/          ① 집필 — 원고의 단일 원천
        │
        ▼  BookTemplate/convert_manuscript.py <책>     ② 이관
BookTemplate/content/<책>/            ③ 편집 — 간지·목차·표지·도판
        │
        ▼  BookTemplate/build_book.py <책> -o output -p <1|2>
BookTemplate/output/<책>_판형_시각.pdf ④ 완성
```

## ★가장 먼저 — 작업 폴더를 팩 밖에 만들어라 (불가침)

이 스킬은 `~/.EZERagent/pack/skills/book-writing/` 에 설치된다. **팩은 업데이트 때 배포 원본으로
되돌아간다**(preflight C62 pack-heal). 그 안에서 원고를 쓰면 **다음 업데이트에 원고가 사라진다.**

착수 시 반드시 이렇게 한다:

1. 사용자에게 작업 폴더를 묻는다 (예: `~/books/` · 바탕화면 · 문서 폴더).
2. 이 스킬 디렉터리를 그 폴더로 **복사**한다 — 원본은 읽기 전용 원형으로 남긴다.
   ```bash
   cp -r "$EZERAGENT_PACK_DIR/skills/book-writing" ~/books/my-book-project
   cd ~/books/my-book-project
   ```
   (Windows PowerShell: `Copy-Item "$env:USERPROFILE\.EZERagent\pack\skills\book-writing" ~\books\my-book-project -Recurse`)
3. 이후 모든 명령은 **그 복사본 안에서** 실행한다.

## 전제 도구 (없으면 먼저 안내하고 멈춘다)

| 도구 | 용도 | Ezer 동봉 |
| --- | --- | --- |
| Git | 저장소 | ✅ 동봉 |
| Node.js 24+ | 집필부 파이프라인 | ✅ 동봉(버전 확인 필요) |
| Python 3.10+ | 편집부 빌드 | ✅ 동봉 |
| **pandoc** | 집필부 가제본(MD→Typst) | ❌ **사용자 설치** |
| **typst** | 가제본 PDF 컴파일 | ❌ **사용자 설치** |
| Mermaid CLI(`mmdc`) | 원고 속 도식 렌더링 | ❌ 선택 |

부재 시 안내(Windows):
```powershell
winget install JohnMacFarlane.Pandoc
winget install Typst.Typst
```
설치 후 **터미널을 새로 열어야** PATH가 반영된다. ★없는 도구를 있다고 가정하고 진행하지 마라 —
`pandoc --version` · `typst --version` 으로 **실측 확인 후** 다음 단계로 간다.

## 명령 5종 (원본: `.claude/commands/`)

| 명령 | 하는 일 |
| --- | --- |
| `/book-new <이름> [--chapters N] [--lang ko]` | 집필부에 원고 스캐폴드 생성 |
| `/book-handoff <이름>` | 집필부 → 편집부 이관 |
| `/book-illustrate <이름>` | 도판·도식 처리 |
| `/book-build <이름> [1\|2]` | 최종 PDF 빌드 (1=신국판 152×225 · 2=B5 188×257) |
| `/book-status` | 진행 상태 확인 |

각 명령의 정확한 절차는 `.claude/commands/<명령>.md` 를 **읽고 그대로 따른다**(요약 금지).

## 판형 선택 기준

- **신국판(152×225mm)** — 시집·에세이·신앙서적·소설
- **B5(188×257mm)** — 학술서·교재·강해서·도판 많은 책

## 조판 품질

`build_book.py ... --style style-pro.css --recto-chapters` 가 전문 조판이다
(내장 폰트·미러 마진·홀수면 장 시작). 기존 조판 재현이 필요할 때만 `--style` 을 생략한다.
빌드는 **반드시 `-o` 와 `-p` 를 명시**해 비대화형으로 돌린다 — 대화형 프롬프트에 걸리면 멈춘다.

## 원고 수정 규율

본문 오탈자·문장 수정은 `BookTemplate/content/` 를 **직접 고치지 않는다.**
`bookwriter/manuscripts/` 에서 고치고 `/book-handoff` 를 다시 돌린다(손유지 파일 제외).
content 를 직접 고치면 다음 이관에서 덮여 사라진다.

## 동봉 자산과 저작권

- 워크플로우·빌드 스크립트·스타일시트 — 오너 저작물(Ezer 와 동일 MIT).
- `BookTemplate/templates/fonts/SourceHanSerifKR/` — Adobe, **SIL OFL 1.1**
  (`LICENSE.txt` 동봉 · 재배포 허용).
- `BookTemplate/templates/fonts/KoPubWorld/` — 지적재산권 **문화체육관광부·한국출판인회의**.
  상업적 사용은 허용되나 **프로그램 내 임베딩은 권리자 별도 승인 사항**이다
  (https://www.kopus.org/biz-electronic-font2/). 사용 전 조건을 확인하라.
- `BookTemplate/content/`·`images/` — 예시 원고·도판. 실제 출판물의 표본이며 그대로 재사용하지 마라.

## 원본

https://github.com/SANGUKMA/BOOK — 이 스킬은 그 저장소를 Ezer 팩에 편입한 것이다.
상세 지침은 동봉된 `책만들기_종합_지침서.md` 와 `CLAUDE.md` 를 참조한다.
