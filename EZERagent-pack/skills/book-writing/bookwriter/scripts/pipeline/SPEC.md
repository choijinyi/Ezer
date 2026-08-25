# Pipeline SPEC (Track 1)

본 문서는 `scripts/pipeline/` 아래 각 스크립트의 **계약**이다. 구현 전에 이 스펙이 합의돼야 한다.

---

## 0. 전체 구조

```
manuscripts/<name>/                       (사용자 원고)
        │
        ▼   /new
build/<job-id>/input/                     (스냅샷)
        │
        ▼   ingest.ts            ─ 결정적
build/<job-id>/source/NN-*.md
build/<job-id>/manifest.json, meta.json
        │
        ▼   structure.ts         ─ 결정적 (이상 검출 룰)
build/<job-id>/outline.json
build/<job-id>/decisions.md              (사용자 응답 게이트)
        │
        ▼   normalize.ts         ─ 결정적 (narrow editor)
build/<job-id>/edited/NN-*.md            (공백/EOL/BOM 정리만)
        │
   --polish? ─yes─▶ polish-propose.ts ─ LLM (.claude/agents/polish-proposer.md)
                          │
                          ▼
                    polish-proposals.md  (사용자 응답 게이트)
                          │
                          ▼   apply-polish.ts ─ 결정적
                    edited/NN-*.md       (승인분 반영)
        │
        ▼   render-figures.ts    ─ 결정적 (Mermaid → SVG)
build/<job-id>/figures/<id>.svg
        │
        ▼   build-cover.ts       ─ 결정적 + LLM 분기
build/<job-id>/cover.<ext>               (사용자 제공 우선, 없으면 cover-designer LLM)
        │
        ▼   typeset.ts           ─ 결정적 (pandoc -t typst → typst compile)
build/<job-id>/book.typ, preview.pdf
        │
        ▼   export.ts            ─ 결정적
dist/<job-id>/book.pdf
dist/<job-id>/manifest.json
```

오케스트레이터 = `scripts/pipeline/run.ts`. 슬래시 명령은 이 스크립트를 호출하는 얇은 래퍼.

LLM이 사용되는 지점은 단 두 곳: **polish-propose**, **build-cover (자동 생성 분기)**.

---

## 1. 공통 규약

### 1.1 state.json 스키마 (단일 소스)

```typescript
type Stage =
  | "created" | "ingested" | "structured"
  | "normalized" | "polish-proposed" | "polished"
  | "illustrated" | "typeset" | "exported";

type State = {
  jobId: string;
  manuscript: string;       // manuscripts/<name>
  stage: Stage;
  ok: boolean;
  needsApproval: boolean;
  createdAt: string;        // ISO8601
  updatedAt: string;
  template: string;         // book.json.template
  outputs: Array<"pdf"|"epub"|"web">;
  polish: boolean;          // /run --polish 시 true 박힘 (sticky)
  errors?: string[];        // 사용자에게 보여줄 에러 요지
  // 단계별 수치
  pages?: number;
  applied?: number;
  skipped?: number;
  coverSource?: "user" | "generated";
};
```

`scripts/pipeline/state.ts`에 zod 스키마. 모든 스크립트는 이 모듈을 통해서만 state를 읽고 쓴다.

### 1.2 파일 락

각 스크립트는 시작 시 `build/<job>/.lock` 생성, 종료 시 삭제. `.lock`이 이미 있으면 거부 (5초 stale 후 자동 회수). 동시 실행 방지.

### 1.3 의존성

런타임 PATH에 있어야 함:
- `node` ≥ 24
- `pandoc` ≥ 3.0 (MD → Typst)
- `typst` ≥ 0.12
- `mmdc` (Mermaid CLI, npm i -g @mermaid-js/mermaid-cli)

`scripts/check-deps.ts`가 `--version` 호출로 검사. `run.ts`가 시작 시 자동 실행.

### 1.4 LLM 호출

`scripts/pipeline/llm.ts`가 단일 진입점:
```typescript
export async function callAgent(
  agentFile: string,           // 예: ".claude/agents/polish-proposer.md"
  userMessage: string,
  opts?: { model?: string; maxTokens?: number }
): Promise<string>
```

- `agentFile`을 읽어 frontmatter 분리, 본문을 system prompt로 사용.
- Anthropic SDK 직접 호출. `ANTHROPIC_API_KEY` 환경변수 필수.
- 같은 입력에 대한 응답을 `build/<job>/llm-cache/<sha>.json`에 캐시 (재실행 시 비용 절감).

### 1.5 에러 처리 규약

스크립트는 실패 시:
1. `build/<job>/errors.log`에 단일 줄 사유 기록 (예: `ingest: chapter file not found: 03-methods.md`).
2. `state.json.ok = false`, `state.errors = [...]`.
3. 종료 코드 1.

부분 산출물 금지 — 실패한 스크립트는 자기가 쓴 모든 파일을 롤백한다 (atomic via temp dir + rename).

---

## 2. 단계별 스펙

### 2.1 `new.ts`

#### 시그니처
```
node scripts/pipeline/new.ts --scaffold <name> [--chapters N] [--lang ko|en] [--template <id>]
node scripts/pipeline/new.ts <path-to-manuscript-dir>
node scripts/pipeline/new.ts <path-to-single.md>
```

#### --scaffold 동작
1. `manuscripts/<name>/`이 이미 있으면 거부.
2. 디렉토리 생성, `templates/manuscript-default/{README.md, 00-preface.md, 99-references.md}`를 그대로 복사.
3. N(기본 14)개 본문 장 파일 동적 생성: `NN-chapter.md` (zero-pad 너비는 N의 자릿수). `lang=ko`면 본문 `# {n}장\n\n여기에 {n}장을 쓴다.\n`, `lang=en`이면 `# Chapter {n}\n\nWrite chapter {n} here.\n`.
4. `book.json` 생성 — title=`<name>`, lang, template, chapters 배열.

#### 디렉토리/파일 입력 동작
1. 디렉토리: `book.json` 존재 검증, 매니페스트의 모든 `chapters[].file`이 디스크에 정확한 케이스로 존재하는지 검사 (TI-11).
2. 단일 `.md`: 임시 1장짜리 매니페스트로 래핑.
3. job-id 생성 (`YYYYMMDD-HHMMSS-<6 random>`, UTC).
4. `build/<job>/input/`에 매니페스트와 모든 참조 파일 복사 (읽기 전용 스냅샷).
5. `state.json` 초기화: `stage: "created"`, polish=false 등.
6. job-id를 stdout과 `manuscripts/<name>/.bookwriter/jobs.json`에 기록 (TI-13).

#### 거부 사유
- 빈 파일/디렉토리
- `book.json` 파싱 실패
- `chapters[].file` 누락 또는 케이스 불일치
- v1 비허용 확장자 (`.md` 외)
- 템플릿 미존재

---

### 2.2 `ingest.ts`

#### 입력
- `build/<job>/input/` 전체

#### 출력
- `build/<job>/manifest.json` — `book.json`에 `chapters[].sourcePath`(절대) 추가
- `build/<job>/source/NN-*.md` — 정규화된 장별 사본
- `build/<job>/meta.json` — `{ title, subtitle, authors, lang, template, chapterCount, wordCount, ingestedAt, mixedLang?, emptyChapters?, userCover? }`
- `build/<job>/figures/orig/` — input의 figures/ 복사 (있을 때)
- `build/<job>/cover-user.<ext>` — input에 `cover.{svg,png,jpg,jpeg,webp}`가 있으면 첫 매치 복사. `meta.userCover`에 절대 경로 (TI-5).
- `state.json` → stage=ingested

#### 정규화 (per chapter)
1. LF 줄바꿈, BOM 제거
2. Setext 헤딩(`===`/`---`) → ATX(`#`/`##`)
3. 이미지 상대경로 재작성: `![alt](figures/x.svg)` → `![alt](figures/orig/x.svg)` 형태로 빌드 디렉토리 기준 (TI-4)
4. 빈 줄 3개 이상 → 2개로 축약
5. 본문 텍스트는 절대 변경 안 함 (단어, 문장, 문단 모두 보존)

#### 검증 / 거부
- 본문 장 (`role`이 frontmatter/backmatter 아닌 것)이 빈 경우 → 실패
- frontmatter/backmatter는 빈 채로 통과 가능, `meta.emptyChapters`에 기록
- 이미지 파일이 매니페스트가 가리키는데 디스크에 없으면 → warning만 (빌드는 계속, typesetter가 나중에 자체 처리)

---

### 2.3 `structure.ts`

#### 입력
- `build/<job>/manifest.json`, `source/*.md`

#### 출력
- `build/<job>/outline.json`:
```json
{
  "title": "...",
  "chapters": [
    {
      "id": "ch-01",
      "slug": "introduction",
      "file": "source/01-introduction.md",
      "title": "...",
      "wordCount": 1234,
      "role": "body" | "frontmatter" | "backmatter",
      "sections": [{ "id": "ch-01-s-01", "title": "...", "headingLevel": 2 }]
    }
  ]
}
```
- `build/<job>/decisions.md` — 이상 징후 질문, 또는 `# No structural decisions needed.`
- `state.json` → stage=structured, needsApproval=<true if any anomaly>

#### 알고리즘 (전부 결정적, LLM 미사용)
1. 매니페스트 순서로 outline.chapters 구성. 슬러그는 파일명에서 `^\d+-` 제거.
2. 각 장에서 `^# (.+)$` 첫 매치를 title로. 없으면 `book.json.chapters[i].title` 사용. 충돌 시 **파일 헤딩 우선** (조용히, changelog에는 나중에 typeset 단계에서 기록).
3. 섹션: `^## ` ~ `^###### `를 평탄 리스트로.
4. wordCount: 헤딩과 코드블록 제외하고 공백 분리 카운트.
5. 이상 검출 룰:
   - body 장의 wordCount < 300 → "Q: short chapter"
   - body 장의 wordCount > 10000 → "Q: long chapter"
   - meta.emptyChapters에 있는 항목 → "Q: empty chapter"
6. 질문은 `decisions.md`에 템플릿 문구로 기록:
```markdown
# Structural decisions for <job-id>

## Q1: 03-methods.md is short (217 words)
- [ ] Keep as-is
- [ ] Skip in this build
- [ ] Wait — still writing

Decided: <TODO>
```
7. 질문이 0개면 `# No structural decisions needed.` 한 줄만 쓰고 needsApproval=false.

#### 게이트 응답 형식 (TI-8)
- `Decided: <TODO>` 패턴이 미응답 표지.
- 응답: `Decided: 1` (옵션 번호) 또는 `Decided: keep` (키워드). 정확 매칭 (case-insensitive 키워드만).
- 패턴 외 텍스트는 미응답 취급. 훅이 정확히 `<TODO>` 토큰만 검사.

---

### 2.4 `normalize.ts` (narrow editor)

#### 입력
- `build/<job>/source/NN-*.md`

#### 출력
- `build/<job>/edited/NN-*.md` — 다음만 수정:
  1. 줄 끝 후행 공백 제거
  2. 빈 줄 3개 이상 → 2개로 축약
  3. 마지막 줄 정확히 한 개의 LF로 끝남
  4. (이미 ingest에서 했을) BOM/EOL 재확인
- `build/<job>/changelog.md` 정확히:
```
# Edit log for <job-id>
Mode: narrow (no --polish). No word-level edits performed.
```
- `state.json` → stage=normalized, mode=narrow

#### 자체 검사 (TI-7)
- 단어 수 변화: **0이어야 함** (1%가 아니라 0). 위반 시 abort + errors.log.
- 문단 수 변화: 0이어야 함.
- 헤딩 줄 (`^#`) 변화: 0이어야 함 (TI-3 — narrow모드에선 자명하지만 명시).

---

### 2.5 `polish-propose.ts` (LLM 호출)

`/run --polish` 시에만 실행. `state.polish=true`면 자동.

#### 입력
- `build/<job>/edited/NN-*.md` (narrow 적용본)

#### 출력
- `build/<job>/polish-proposals.md`:
```markdown
# Polish proposals for <job-id>

각 항목에 y(적용), n(스킵), 또는 빈 칸/<TODO>(스킵)을 표시.
헤딩 줄(#)은 제안 대상에서 제외됨.

## 01-introduction.md

### P1 — L42 — terminology
- before: "그 인공지능 모델은"
- after:  "그 AI 모델은"
- reason: "AI" appears 8 times, "인공지능" 2 times → drift
- Apply: <TODO>

### P2 — L88 — Korean particle
- before: "데이터들이"
- after:  "데이터가"
- reason: 무생물 명사 복수 표지
- Apply: <TODO>
```
- `state.json` → stage=polish-proposed, needsApproval=true

#### 동작
1. 각 장의 본문에서 헤딩 줄(`^#`)을 **제외한** 텍스트만 LLM 입력으로 전달 (TI-3).
2. 한 번의 호출당 한 장. 14장이면 14번 호출 (캐시 활용).
3. LLM은 strict JSON으로 응답 (system prompt에 스키마):
```json
{ "proposals": [{ "line": 42, "before": "...", "after": "...", "category": "terminology|particle|spelling|repetition|punctuation", "reason": "..." }] }
```
4. 스크립트가 JSON 파싱 → markdown 변환 → polish-proposals.md.
5. JSON 파싱 실패 시 그 장만 스킵, errors.log에 기록, 다른 장은 계속.

#### LLM 정의
`.claude/agents/polish-proposer.md` 본문이 system prompt. 허용 카테고리 외 제안은 스크립트가 후처리에서 버림.

---

### 2.6 `apply-polish.ts`

#### 입력
- `build/<job>/edited/NN-*.md`
- `build/<job>/polish-proposals.md` (모든 `Apply:`가 응답된 상태)

#### 출력
- `build/<job>/edited/NN-*.md` (제안 적용본으로 덮어쓰기, 원본은 `edited.pre-polish/`에 백업)
- `build/<job>/changelog.md` — 적용/스킵 항목별 기록
- `build/<job>/apply.log` — 매칭 실패한 항목
- `state.json` → stage=polished, applied=N, skipped=M

#### 알고리즘 (TI-6)
1. polish-proposals.md를 파싱: `Apply: y/yes` (case-insensitive) → 적용 대상.
2. 장별로 그룹핑.
3. **각 장 내에서 라인 번호 내림차순으로 정렬**해 적용 (역순). 라인 번호 어긋남 방지.
4. 각 적용:
   - 해당 라인에서 `before` 정확 매치 검색 → 첫 매치를 `after`로 교체.
   - 매치 실패 시 스킵 + apply.log 기록.
5. 헤딩 줄에 걸친 제안은 거부 (TI-3 재방어).
6. 자체 검사 (TI-7):
   - 단어 수 변화: 적용된 제안 수에 비례한 절대치 ±2N 이내
   - 문단 수 변화: 0
   - 헤딩 줄 변화: 0

---

### 2.7 `render-figures.ts`

#### 입력
- `build/<job>/edited/NN-*.md` 안의 `<!-- fig: ... -->` 마커
- `build/<job>/figures/orig/` (사용자 도식)

#### 출력
- `build/<job>/figures/<id>.svg` — 마커별 렌더 결과
- `build/<job>/figures/<id>.caption.txt`
- `state.json` 변경 없음 (build-cover와 합쳐 illustrated 단계 형성)

#### 마커 문법
```
<!-- fig: id=arch-01 type=mermaid caption="Pipeline overview" -->
flowchart LR
  ingest --> structure --> normalize --> typeset
<!-- /fig -->
```

#### 처리
- `type=mermaid` → `mmdc` 호출, SVG 생성.
- `type=raw` → 마커 사이 내용을 SVG로 그대로 저장.
- 그 외 type → caption-only 스텁 + decisions.md에 경고.

---

### 2.8 `build-cover.ts`

#### 입력
- `build/<job>/cover-user.<ext>` (있다면) 또는
- `build/<job>/meta.json` (LLM 분기)

#### 출력
- `build/<job>/cover.<ext>` — 표지 (확장자는 입력에 따라)
- `meta.json` 갱신: `coverFile` 필드에 절대 경로 (TI-5)
- `state.json` → stage=illustrated, coverSource=user|generated

#### 분기
1. `meta.userCover`가 set이면 그 파일을 `cover.<ext>`로 복사. coverSource=user. 끝.
2. 아니면 `.claude/agents/cover-designer.md` LLM 호출:
   - 입력: title, subtitle, authors, lang
   - 출력: 단일 자체완결 SVG
   - 검증: 유효 SVG인지 파싱, A5 비율(148:210) 권장, 글꼴 임베드 없이 시스템 폰트 사용
3. 검증 실패 시 fallback: 단순 활자만의 결정적 SVG 템플릿(스크립트 내장)으로 만듦. coverSource=generated, errors.log에 LLM 실패 기록.

---

### 2.9 `typeset.ts`

#### 입력
- `build/<job>/edited/NN-*.md`, `manifest.json`, `outline.json`, `figures/`, `cover.<ext>`, `meta.json`
- `templates/<template-id>/template.typ`, `style.json`

#### 출력
- `build/<job>/body.md` — 매니페스트 순서로 concat (frontmatter → body → backmatter)
- `build/<job>/body.typ` — `pandoc body.md -t typst -o body.typ`로 변환 (TI-9 명시)
- `build/<job>/book.typ` — 템플릿의 `{{title}}`, `{{author}}`, `{{lang}}`, `{{body}}`, `{{cover_path}}` 치환
- `build/<job>/preview.pdf` — `typst compile --root build/<job> book.typ preview.pdf`
- `build/<job>/typeset.log` — pandoc/typst stderr 캡처
- `state.json` → stage=typeset, pages=N

#### 페이지/품질 검증
- pandoc 실패 → abort + errors.log
- typst 비-zero exit → abort
- pages > (총 wordCount / 200) × 2 → warning (템플릿/데이터 부조화 의심)
- typst 경고 중 widow/orphan 카운트 → state에 기록

---

### 2.10 `export.ts`

#### 입력
- `build/<job>/preview.pdf`, `book.typ`, `meta.json`
- `state.json.outputs` (`["pdf"]` | `["pdf","epub"]` 등)

#### 출력
- `dist/<job>/book.pdf` — preview.pdf를 PDF 메타데이터 임베드 후 복사 (`exiftool` 또는 typst 자체 메타)
- `dist/<job>/book.epub` — `outputs`에 epub 있을 때만 (`pandoc body.md -o book.epub --metadata-file=meta.json`)
- `dist/<job>/manifest.json` — `{ files: [...], sha256: {...}, builtAt }`
- `dist/<job>/web/` — `outputs`에 web 있을 때만 (단순 HTML, M2)
- `state.json` → stage=exported

#### 포맷별 독립 실패 (TI 추가)
- PDF 실패 → 전체 abort.
- PDF 성공 + EPUB 실패 → PDF는 살리고 manifest에 `{ "epub": { "ok": false, "reason": "..." } }` 기록.

---

### 2.11 `run.ts` (오케스트레이터)

#### 시그니처
```
node scripts/pipeline/run.ts <job-id> [stage|all] [--polish]
```

#### 동작
1. `check-deps.ts` 실행.
2. job 락 획득.
3. state.json 읽음. `polish` 플래그 합성 (`--polish` OR 기존 `state.polish`).
4. 다음 단계 결정:
   - `all`이면 마지막 성공 단계 다음부터.
   - 특정 stage면 그 단계만.
5. 게이트 검사: 다음 단계가 game-changing(`structure → normalize`, `polish-propose → apply-polish`)인 경우, 응답 미완료면 즉시 halt.
6. 단계별 스크립트를 자식 프로세스로 실행. 종료 코드 0이 아니면 stop.
7. 락 해제.

#### 단계 매핑
| stage 인자 | 호출 | state 전이 |
|---|---|---|
| `ingest` | ingest.ts | created → ingested |
| `structure` | structure.ts | ingested → structured |
| `normalize` 또는 `edit` | normalize.ts | structured → normalized |
| `polish-propose` | polish-propose.ts | normalized → polish-proposed |
| `apply-polish` | apply-polish.ts | polish-proposed → polished |
| `illustrate` | render-figures.ts + build-cover.ts | normalized\|polished → illustrated |
| `typeset` | typeset.ts | illustrated → typeset |
| `export` | export.ts | typeset → exported |
| `all` | 위 순서대로 (polish 분기는 state.polish에 따름) | |

---

## 3. 골든 테스트 러너 (`scripts/run-golden.ts`)

### 동작
1. `tests/golden/<name>/manuscript/`를 임시 작업 공간에 복사
2. 위 파이프라인 전체 실행 (LLM 단계는 캐시 또는 mock)
3. 산출물을 `expected.json`과 대조:
   - 출력 파일 목록 매치
   - meta.json 핵심 필드 매치 (title, lang, chapterCount)
   - state 추이 매치
   - PDF 페이지 수 범위 매치
4. `expected.pdf.sha256`이 있으면 byte-exact 비교 (mock LLM일 때만 의미 있음).

---

## 4. 미해결 / Track 2

본 스펙에서 일부러 미루는 것:
- 다중 포맷 입력 (pdf/docx/tex) — v1은 .md만 (Q2 결정)
- 사용자별 인증/멀티테넌시
- 실시간 미리보기
- 이미 빌드된 chapter만 부분 재컴파일 (H1 결정으로 항상 새 job)

위 항목이 필요해지면 본 스펙에 새 절을 추가한다.
