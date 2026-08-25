# ARCHITECTURE.md

## 시스템 개요

bookwriter는 **하이브리드 파이프라인**을 가진 로컬 집필 도구다 (Track 1). 결정적 Node/TypeScript 스크립트가 80%를 처리하고, 사람의 글 판단과 표지 시안에서만 LLM을 호출한다.

핵심 원칙:
1. **파일이 진실의 원천** — 메모리/세션 상태에 의존하지 않는다.
2. **결정적 우선** — LLM은 진짜 필요한 곳에서만.
3. **1 job = 1 스냅샷** — 원고를 수정하면 새 job-id를 발급한다 (콘텐츠 해시 비교 없음).
4. **승인 게이트** — 비가역 결정은 사람이 통과시킨다 (`decisions.md`, `polish-proposals.md`).
5. **포맷 중립** — 입력은 Markdown 한 종, 중간물은 모두 검사 가능한 텍스트, 최종은 PDF/EPUB.

## 디렉토리 레이아웃

```
bookwriter/
├── CLAUDE.md
├── AGENTS.md                  # LLM 에이전트(2개) 명세
├── ARCHITECTURE.md            # 본 문서
├── .claude/
│   ├── agents/
│   │   ├── polish-proposer.md # LLM 에이전트
│   │   └── cover-designer.md  # LLM 에이전트
│   ├── commands/              # /new /run /status (스크립트 래퍼)
│   ├── hooks/                 # check-stage-gate, verify-decisions
│   └── settings.json
├── scripts/
│   ├── pipeline/
│   │   ├── SPEC.md            # 모든 스크립트의 계약 (단일 소스)
│   │   ├── README.md          # 운영 안내
│   │   ├── new.ts ingest.ts structure.ts normalize.ts
│   │   ├── polish-propose.ts apply-polish.ts
│   │   ├── render-figures.ts build-cover.ts
│   │   ├── typeset.ts export.ts run.ts
│   │   ├── state.ts llm.ts paths.ts
│   └── check-deps.ts
├── prompts/                   # (현재 비어있음. 필요 시 보조 프롬프트)
├── docs/                      # 설계 문서
├── templates/
│   ├── manuscript-default/    # 원고 스캐폴드 (README + 머리말 + 참고문헌)
│   └── typst-classic/         # 조판 템플릿
├── manuscripts/<name>/        # 사용자 원고
│   ├── book.json
│   ├── 00-preface.md
│   ├── 01-chapter.md
│   ├── ...
│   └── 99-references.md
├── build/<job-id>/            # 파이프라인 중간 산출물 (gitignore)
├── dist/<job-id>/             # 최종 간행본 (gitignore)
└── tests/golden/              # end-to-end 스모크 테스트
```

## 입력 형식

원고는 **장별 .md 파일 + book.json 매니페스트**로 구성된 디렉토리. 기본 골격은 14장. v1은 **Markdown만** 받는다.

```
manuscripts/mybook/
├── book.json
├── 00-preface.md          (선택, role: frontmatter)
├── 01-chapter.md
├── ...
├── 14-chapter.md
└── 99-references.md       (선택, role: backmatter)
```

`book.json.chapters` 배열이 진실. 파일명 prefix `NN-`은 정렬 보조일 뿐이다.

표지는 선택: `manuscripts/<name>/cover.{svg,png,jpg,jpeg,webp}`이 있으면 사용, 없으면 자동 생성.

## 파이프라인 (하이브리드)

```
manuscripts/<name>/                                         (원고)
        │
        ▼  /new (= new.ts)                                  결정적
build/<job>/input/                                          (스냅샷)
        │
        ▼  ingest.ts                                        결정적
build/<job>/source/NN-*.md, manifest.json, meta.json
        │
        ▼  structure.ts                                     결정적 (룰 기반)
build/<job>/outline.json, decisions.md
        │ ── 게이트: decisions.md 미응답 시 halt
        ▼  normalize.ts                                     결정적 (narrow)
build/<job>/edited/NN-*.md
        │
   --polish?
        │ yes
        ▼  polish-propose.ts → polish-proposer LLM         LLM
        polish-proposals.md
        │ ── 게이트: 미응답 시 halt
        ▼  apply-polish.ts                                  결정적
        edited/NN-*.md (적용본)
        │ no/done
        ▼  render-figures.ts (Mermaid → SVG)                결정적
        build/<job>/figures/<id>.svg
        │
        ▼  build-cover.ts                                   결정적 ± LLM
        build/<job>/cover.<ext>
        │     사용자 제공 → 복사
        │     없음 → cover-designer LLM
        ▼  typeset.ts (pandoc → typst → PDF)                결정적
build/<job>/book.typ, preview.pdf
        │
        ▼  export.ts                                        결정적
dist/<job>/book.pdf, manifest.json
```

각 단계의 정확한 입출력·에러 처리는 `scripts/pipeline/SPEC.md` 참조.

## 결정 게이트

비가역/고비용 작업 전 사용자 승인이 필요한 두 지점:

1. **structure → normalize** — `decisions.md`에 이상 검출 질문이 있으면 사용자 응답 필요. 응답 표지: `Decided: <TODO>` 토큰을 채움.
2. **polish-propose → apply-polish** — `polish-proposals.md`의 `Apply: <TODO>` 토큰을 `y`/`n`로 응답.

`<TODO>` 토큰을 placeholder로 사용하는 이유: 정규식 한 줄로 미응답 검출이 견고함 (TI-8). 훅이 prompt마다 검사.

## 트랙 분리

- **Track 1 (현재)**: 로컬 집필 도구. Node 스크립트 + Claude Code 슬래시 명령.
- **Track 2 (보류)**: 웹 서비스화. `docs/FRONTEND.md`, 시나리오 B 등이 이 트랙. M3 이전에는 작업 대상 아님.

## 기술 스택 (Track 1)

| 레이어 | 선택 | 비고 |
|---|---|---|
| 언어 | TypeScript (Node 24+) | strict, ESM |
| Markdown 파싱 | `unified` + `remark-parse` + `remark-gfm` | outline/normalize에 사용 |
| MD → Typst | `pandoc` ≥ 3.0 (CLI 호출) | typesetter 단계 |
| 조판 | `typst` ≥ 0.12 (CLI 호출) | --root build/<job> |
| 도식 | `mmdc` (Mermaid CLI) | render-figures |
| EPUB | `pandoc` (선택) | export 옵션 |
| LLM | Anthropic SDK (`@anthropic-ai/sdk`) | API 키 필수 시점에만 |
| 검증 | `zod` | state.json, manifest.json 모두 |

## 비목표

- 다중 입력 포맷 (pdf/docx/tex) — v1은 .md만.
- 실시간 협업 편집기.
- 부분 재컴파일 (장 단위 캐시) — 1 job = 1 스냅샷 원칙으로 단순화.
- AI가 사용자 본문에 임의로 손대기 — polish는 항상 제안 + 게이트.
