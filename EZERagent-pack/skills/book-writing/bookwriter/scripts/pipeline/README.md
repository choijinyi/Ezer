# scripts/pipeline

bookwriter 파이프라인의 결정적 코드. **이 디렉토리의 스크립트가 빌드의 80%를 담당**한다 (LLM은 polish-propose, build-cover의 일부 분기에서만 호출).

## 사전 요구

- Node.js 24+
- `pandoc` ≥ 3.0 (Markdown → Typst)
- `typst` ≥ 0.12
- `mmdc` (Mermaid CLI, `npm i -g @mermaid-js/mermaid-cli`)
- `ANTHROPIC_API_KEY` 환경변수 (polish/cover LLM 단계에서만 필요)

`scripts/check-deps.ts`로 한 번에 검사 가능.

## 호출 방식

### Claude Code 세션 안에서
```
/new --scaffold mybook --chapters 14
/new manuscripts/mybook
/run <job-id>
/run <job-id> --polish
/status <job-id>
```
슬래시 명령은 이 디렉토리의 스크립트를 호출하는 얇은 래퍼다.

### 일반 터미널에서
```
node scripts/pipeline/new.ts --scaffold mybook --chapters 14
node scripts/pipeline/new.ts manuscripts/mybook
node scripts/pipeline/run.ts <job-id>
```
같은 효과. Claude Code 의존 없음.

## 단계별 스크립트

| 파일 | 역할 | 결정적? |
|---|---|---|
| `new.ts` | 매니페스트 검증·스캐폴드·job 발급 | ✓ |
| `ingest.ts` | 입력 정규화, 스냅샷 | ✓ |
| `structure.ts` | outline + 이상 검출 | ✓ |
| `normalize.ts` | narrow editor (공백/EOL/BOM) | ✓ |
| `polish-propose.ts` | 폴리시 제안 생성 | LLM (`polish-proposer`) |
| `apply-polish.ts` | 승인된 제안 적용 | ✓ |
| `render-figures.ts` | Mermaid → SVG | ✓ (mmdc) |
| `build-cover.ts` | 표지 (사용자/자동) | LLM 분기 (`cover-designer`) |
| `typeset.ts` | pandoc → typst → PDF | ✓ |
| `export.ts` | dist/ 결과물 + manifest | ✓ |
| `run.ts` | 오케스트레이터 | ✓ |

## 기타 모듈

- `state.ts` — state.json zod 스키마 + 락 관리
- `llm.ts` — Anthropic SDK 단일 진입점, 캐시 포함
- `paths.ts` — `build/<job>/...` 경로 헬퍼

## 정확한 계약은 `SPEC.md` 참조

상위 디렉토리에 있는 `SPEC.md`가 각 스크립트의 입출력·에러·알고리즘의 단일 소스다. 이 README는 운영 안내일 뿐이다.
