# BOOK — 책 제작 메타 템플릿

원고 집필부터 인쇄용 PDF까지 이어지는 책 제작 워크플로입니다.

```text
bookwriter/manuscripts/<책>/          ← 1단계: 집필 (원고의 단일 원천)
        │
        ▼  BookTemplate/convert_manuscript.py <책>     ← 2단계: 이관
BookTemplate/content/<책>/            ← 3단계: 편집 (간지·목차·표지·도판)
        │
        ▼  BookTemplate/build_book.py <책> -o output -p <1|2>
BookTemplate/output/<책>_판형_시각.pdf ← 완성
```

- **집필부 `bookwriter/`** — 원고 작성·다듬기 (Node.js 파이프라인)
- **편집부 `BookTemplate/`** — 원고를 책으로 조판, PDF 출력 (Python + Chromium)

---

## 설치 절차

### 0. 사전 준비물

| 도구 | 용도 | 필수 여부 |
| --- | --- | --- |
| Git | 저장소 받기 | 필수 |
| Node.js **24 이상** | 집필부 파이프라인 (TS 직접 실행) | 필수 |
| Python 3.10 이상 | 편집부 빌드 | 필수 |
| pandoc | 집필부 가제본 (MD → Typst 변환) | 필수 |
| typst | 집필부 가제본 PDF 컴파일 | 필수 |
| Mermaid CLI (`mmdc`) | 원고 속 도식 렌더링 | 선택 |
| ANTHROPIC_API_KEY | 교정 제안 등 LLM 단계 | 선택 |

Windows에서는 아래 한 줄씩 실행하면 됩니다 (PowerShell 또는 명령 프롬프트):

```powershell
winget install Git.Git
winget install OpenJS.NodeJS          # 24 이상인지 확인: node --version
winget install Python.Python.3.12
winget install JohnMacFarlane.Pandoc
winget install Typst.Typst
```

설치 후 **터미널을 새로 열어야** PATH가 반영됩니다.

### 1. 저장소 받기

```bash
git clone https://github.com/SANGUKMA/BOOK.git
cd BOOK
```

### 2. 집필부(bookwriter) 설치

```bash
cd bookwriter
npm install
npm run deps        # 의존성 점검 — 전부 [✓]가 나와야 함
cd ..
```

`npm run deps` 결과에서 `node` `pandoc` `typst`는 필수입니다.
`mmdc`와 `ANTHROPIC_API_KEY`는 `[·]`(미설치)여도 기본 실습은 가능합니다.

- Mermaid 도식까지 실습하려면: `npm install -g @mermaid-js/mermaid-cli`
- LLM 교정 단계까지 실습하려면: 환경변수 `ANTHROPIC_API_KEY` 설정

### 3. 편집부(BookTemplate) 설치

```bash
cd BookTemplate
pip install -r requirements.txt
playwright install chromium
cd ..
```

`playwright install chromium`은 PDF 변환용 브라우저(약 150MB)를 내려받습니다.
폰트는 저장소(`BookTemplate/templates/fonts/`)에 포함되어 있어 따로 설치할 필요 없습니다.

### 4. 설치 확인 — 예제 책 빌드

```bash
cd BookTemplate
python build_book.py --help
```

`--help`의 `book` 항목에 등록된 책 목록이 나옵니다. 그중 하나를 골라:

```bash
python build_book.py <책이름> -o output -p 2
```

`output/` 폴더에 PDF가 생기면 설치 성공입니다.
(참고: 장 간지를 홀수면에서 시작시키는 `--recto-chapters` 옵션을 쓰려면 `pip install pymupdf`가 추가로 필요합니다.)

---

## 자주 나오는 문제

- **`node scripts/...` 실행 오류 / 문법 에러** → Node 버전이 24 미만입니다. `node --version`으로 확인 후 재설치하세요.
- **`Executable doesn't exist ... chromium`** → `playwright install chromium`을 빼먹은 경우입니다.
- **터미널 한글 깨짐 (Windows)** → 명령 프롬프트에서 `chcp 65001` 실행 후 다시 시도하세요.
- **`pip` / `python`이 없다고 나옴** → 설치 후 터미널을 새로 열지 않았거나, `python` 대신 `py`로 실행해야 하는 환경입니다.

---

## 워크플로 실습 순서 (요약)

1. **집필** — `bookwriter/`에서 새 원고 스캐폴드 생성 후 `manuscripts/<책>/`에 장별 마크다운 작성
2. **이관** — `BookTemplate/books.py`에 책 등록 → `python convert_manuscript.py <책>`
3. **편집** — `content/<책>/`에서 목차·간지 손질, `images/`에 표지 배치
4. **빌드** — `python build_book.py <책> -o output -p <1|2>` (1=신국판, 2=B5)

세부 규칙은 `CLAUDE.md`(전체 흐름), `bookwriter/AGENTS.md`(집필부), `BookTemplate/책만들기_종합_지침서.md`(편집부)를 참고하세요.
