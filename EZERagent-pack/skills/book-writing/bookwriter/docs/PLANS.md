# PLANS.md

활성 실행 계획의 진입점. 세부는 `docs/exec-plans/active/`에, 끝난 건 `completed/`로 옮긴다.

## 현재 마일스톤

### M0 — 골격 (완료)
- [x] CLAUDE.md, AGENTS.md, ARCHITECTURE.md 스캐폴드
- [x] 디렉토리/매니페스트 입력 (장 = 파일), 14장 파라미터, 표지 override, 1 job=1 스냅샷
- [x] C2 결정: editor opt-in (narrow / propose / apply)
- [x] 하이브리드 재구조화 결정: 결정적 코드 80% + LLM 20%
- [x] `scripts/pipeline/SPEC.md` 작성

### M1 — Phase 1+2 구현 (완료, 2026-05-05)
- [x] package.json + tsconfig.json (Node 24 type-stripping, zod)
- [x] `scripts/check-deps.ts` (node/pandoc/typst/mmdc/API key 점검)
- [x] `scripts/pipeline/{state,paths,llm}.ts` 토대 모듈
- [x] `scripts/pipeline/new.ts` — 14장 스캐폴드 + 디렉토리/단일파일 → job
- [x] `scripts/pipeline/ingest.ts` — book.json 검증, 정규화, meta.json
- [x] `scripts/pipeline/structure.ts` — outline + 이상 검출
- [x] `scripts/pipeline/normalize.ts` — narrow editor (단어수 0% delta 강제)
- [x] `scripts/pipeline/typeset.ts` — pandoc → typst → PDF
- [x] `scripts/pipeline/export.ts` — dist/ + sha256 manifest
- [x] `scripts/pipeline/run.ts` — 오케스트레이터, 게이트 검사
- [x] `scripts/pipeline/status.ts` — 작업 조회
- [x] **검증**: `tests/golden/short-paper-md` end-to-end PDF 생성 ✓ (40KB, PDF-1.7)

### M2 — Phase 3 LLM 단계 (완료, 2026-05-05)
- [x] `scripts/pipeline/llm.ts` — Anthropic SDK + frontmatter 파싱 + sha256 캐시
- [x] `scripts/pipeline/polish-propose.ts` — 장별 LLM 호출, strict JSON, zod 검증
- [x] `scripts/pipeline/apply-polish.ts` — 라인 역순 적용, 헤딩 보호, 백업
- [x] `scripts/pipeline/render-figures.ts` — Mermaid → SVG (mmdc), raw SVG 통과
- [x] `scripts/pipeline/build-cover.ts` — 사용자 표지 / LLM / 결정적 활자 fallback
- [x] `scripts/pipeline/illustrate.ts` — render-figures + build-cover 통합
- [x] typst-classic 템플릿: 옵션 표지 페이지 지원
- [x] run.ts: Phase 3 stage 매핑 추가, throw 제거
- [x] **검증**: 골든 manuscript end-to-end, API 키 없이도 결정적 fallback으로 PDF 생성 (42KB, 표지+본문)

### M3 — 마감 (완료, 2026-05-05)
- [x] 페이지 수 카운트 — typeset.ts가 PDF `/Type /Pages /Count N` 파싱, state.pages 기록
- [x] 골든 러너 — `scripts/run-golden.ts` (메타/outline/페이지 범위 검증) ✓ short-paper-md PASS (8 pages)
- [x] `run --polish` 강한 실패 — API 키 부재 시 polish-propose가 즉시 abort
- [x] 한국어 폰트 fallback — Source Serif 4 → Noto Serif KR → Malgun Gothic → Batang → Times New Roman
- [x] **버그 수정**: run.ts가 `process.exit()` 시 락 미해제 → exitCode 변수로 변경 (golden runner 차단 해소)

### 다음 후보 (선택)
- [ ] LLM mock 모드 (`BOOKWRITER_LLM_MOCK=1`) — golden에서 polish/cover 결정성 보장
- [ ] mmdc 자동 설치 (npm 의존성으로 추가)
- [ ] 한국어 폰트 임베드 (Noto Serif KR을 templates/fonts/에 다운로드)
- [ ] EPUB 출력 검증 — `outputs: ["pdf", "epub"]` 시 동작 확인

### M3 — Track 2 (보류)
- [ ] Next.js 16 부트스트랩
- [ ] 웹 업로드 + 미리보기, 결정 게이트 UI

### M1 — 단일 경로 MVP
- [ ] ingestor (md/pdf만)
- [ ] structurer (헤딩 위계만)
- [ ] typesetter (Typst 단일 템플릿)
- [ ] exporter (PDF만)
- 성공 조건: `npm run book -- input.md` → `dist/out.pdf`

### M2 — 다중 출력 (Track 1)
- [ ] EPUB (pandoc)
- [ ] 웹 정적 간행본 (Track 1 한정 — Next.js 아님, 단순 HTML)
- [ ] 템플릿 3종

### M3 — Track 2 (보류, 트리거 후 시작)
- [ ] Next.js 16 부트스트랩
- [ ] 웹 업로드 + 미리보기
- [ ] 결정 게이트 UI
- [ ] 게스트 1회 무료
- 트리거: Track 1이 안정화되고, "남에게 팔 만한가" 질문에 답이 생긴 시점

## 활성 계획
- (없음 — 추가 시 `docs/exec-plans/active/<slug>.md`)

## 계획 형식

각 exec-plan:
```
## Goal
한 문장 성공 조건

## Steps
1. [Action] → verify: [check]
2. ...

## Risks
- 무엇이 깨질 수 있나, 어떻게 감지하나

## Out of scope
- 일부러 안 하는 것
```

CLAUDE.md §4 (Goal-Driven Execution) 형식을 따른다.
