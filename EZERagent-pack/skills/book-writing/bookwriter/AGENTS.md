# AGENTS.md

bookwriter는 **하이브리드 파이프라인**이다. 80%는 결정적 코드, 20%는 LLM. 이 문서는 LLM이 호출되는 지점만 다룬다.

> **결정적 단계의 계약은 `scripts/pipeline/SPEC.md`에 있다.** 이 문서와 SPEC.md를 함께 읽어야 전체 그림이 보인다.

## 왜 하이브리드인가

- 공백 정규화, 매니페스트 검증, pandoc 호출, typst 컴파일 등은 **기계적**이다 — LLM에 맡기면 비용·신뢰성·재현성이 모두 깨진다.
- 진짜로 LLM이 필요한 것은 **사람의 글에 대한 판단**과 **시각적 시안 생성**뿐이다.

## LLM 에이전트 (2개)

### `polish-proposer`
- **언제 호출**: `/run --polish` 시 `scripts/pipeline/polish-propose.ts`가 장별로 1회씩 호출
- **입력**: 한 장의 본문 (헤딩 줄 제외)
- **출력**: 제안 목록을 strict JSON으로
- **허용 카테고리**: spelling, particle, terminology drift, paragraph-internal repetition, punctuation
- **금지**: 문장 재작성, 단락 추가/삭제/재배열, 헤딩 변경, 인용/수식/코드 변경
- **결정 권한**: 0 — 모두 사용자 응답 게이트 통과 후 적용

### `cover-designer`
- **언제 호출**: `scripts/pipeline/build-cover.ts`가 사용자 표지 미존재 시 1회 호출
- **입력**: title / subtitle / authors / lang
- **출력**: 단일 자체완결 SVG 문서
- **제약**: A5 비율(viewBox 1480×2100), 시스템 폰트, 최대 3색, 활자만 (이미지·아이콘·패턴 금지)
- **fallback**: 출력이 파싱 안 되면 build-cover.ts가 내장 결정적 템플릿으로 대체

## 결정적 스크립트 (10개)

`scripts/pipeline/`의 다음 파일이 파이프라인의 뼈대다. **LLM 미사용**.

| 스크립트 | 역할 |
|---|---|
| `new.ts` | 매니페스트 검증, 스캐폴드, job-id 발급, 입력 스냅샷 |
| `ingest.ts` | LF/BOM 정리, 이미지 경로 재작성, meta.json 생성 |
| `structure.ts` | outline 트리 + 이상 검출 룰 (단어수 임계, 빈 장) |
| `normalize.ts` | narrow editor — 공백/EOL/BOM만 (단어 미변경 보장) |
| `apply-polish.ts` | 승인된 폴리시 제안을 역순으로 적용 |
| `render-figures.ts` | `<!-- fig: -->` 마커 → Mermaid CLI로 SVG |
| `build-cover.ts` | 사용자 표지 복사 또는 cover-designer 호출 |
| `typeset.ts` | pandoc -t typst → 템플릿 치환 → typst compile |
| `export.ts` | dist/ 결과물 + 해시 매니페스트 |
| `run.ts` | 오케스트레이터 |

## 단일 진입점

LLM 호출은 모두 `scripts/pipeline/llm.ts`를 통한다. `.claude/agents/<name>.md`의 frontmatter+본문을 시스템 프롬프트로 로드, Anthropic SDK 호출, 응답 캐시. 다른 진입점 금지.

## 사용자 명령

`.claude/commands/{new,run,status}.md`는 위 스크립트의 얇은 래퍼다. Claude Code가 없는 환경에서는 `node scripts/pipeline/*.ts`를 직접 호출.
