---
name: appbuild
description: 웹/앱을 기획→검증→자율빌드로 만드는 대표 오케스트레이터 스킬. 기획(plan)→화면명세(screen-spec)→작업목록(tasks)→★감독관 검증루프(supervisor)→게이트 통과까지 자율빌드(orchestrate)를 순서대로 굴린다. ezer 워커가 웹/앱을 만들 때 **필수**. "웹/앱 만들어 / 앱 빌드 / 스펙 기반 개발 / appbuild / 코드부터 짜지 말고 기획부터" 트리거, 또는 워커가 신규 웹/앱 구현을 시작할 때 발동.
---

# appbuild

"클로드에게 만들어 달라 던지고 자고 일어나니 절반만 만들다 멈춰 있던" 문제의 해법. 바로
코드부터 짜지 않고 **기획→검증→자율빌드 루프**로 만든다. ezer 엔진(master 위임·
producer≠evaluator·autopilot·eval-driven) 위에 **스펙 기반 프런트엔드 + 감독관 계층**을 얹는다.

> 메우는 3가지 빈칸(오너 정의): ①만든 게 맞는지 **검증 루프** ②뭘 충족하면 끝인지
> **완료 게이트** ③PRD·화면·작업이 서로 안 맞아도 빌드 끝까지 모르는 문제. 핵심 철학:
> **증거 없는 완료는 인정하지 않는다** · **검증자는 만든 에이전트가 아닌 다른 페인**.

## ⚠ 워커 의무 (preflight C27 + hook 게이트가 강제)

ezer 워커는 **신규 웹/앱 구현을 코드부터 시작하지 않는다.** 이 파이프라인으로 기획·
검증·게이트를 먼저 만든 뒤 빌드한다. appbuild 프로젝트(`.appbuild/` 마커)에서는 게이트 미통과
시 소스 작성을 hook이 차단한다(`appbuild-gate.sh`). 상세 WORKER_DIRECTIVE.

## 문서 컨벤션 (ezer 자체 번호 체계 — 영상의 10종 미답습, 린하게)

프로젝트 루트 `.appbuild/` 아래:
- `01-prd.md` — 제품 요구(무엇/왜·기능·범위) — `[[appbuild-plan]]` (↔ to-prd 배선)
- `02-screens.md` — 화면 명세(흐름·화면별 상태/컴포넌트) — `[[appbuild-screen-spec]]`
- `03-architecture.md` — 스택·데이터모델·구조 — `[[appbuild-plan]]`
- `04-tasks.md` — 수직 슬라이스 작업목록 — `[[appbuild-tasks]]` (↔ to-issues 배선)
- `05-gate.md` — 완료 게이트(Definition of Done) — `[[appbuild-supervisor]]`가 **파생**
- `loop-state.json` — 루프 상태(중단·재개, ↔ SESSION_STATE 도리)

## 파이프라인 (단계 → 게이트)

```
1. appbuild-plan        → 01-prd · 03-architecture (기획 3모드)
2. appbuild-screen-spec → 02-screens
3. appbuild-tasks       → 04-tasks (수직 슬라이스)
4. ★ appbuild-supervisor → 01~04 검증(13항목)·반자동 수정·05-gate 파생  ← 감독관
5. appbuild-orchestrate → 05-gate 통과까지 멀티페인 자율 빌드
```

세부:
1. **기획** — `[[appbuild-plan]]`. 인터뷰/디베이트/퀵 3모드로 `01-prd.md`·`03-architecture.md` 작성.
2. **화면** — `[[appbuild-screen-spec]]`. `02-screens.md`(흐름 + 화면별 상태·컴포넌트).
3. **작업** — `[[appbuild-tasks]]`. `04-tasks.md`(엔드투엔드 가치 슬라이스).
4. **감독관** — `[[appbuild-supervisor]]`. 01~04를 다시 읽어 일관성·추적성·갭·품질 13항목
   검증 → 승인 후 빠진 곳만 최대 3회 수정 → `05-gate.md`(프로젝트별 완료 기준) 파생. 문서를
   *만드는* 게 아니라 *검증*하는 계층.
5. **빌드** — `[[appbuild-orchestrate]]`. master가 멀티페인(백/프론트)에 위임, **다른 페인이
   E2E 증거 검증**, 게이트 통과까지 루프. 메인은 절대 직접 수정 안 함.

## 오케스트레이션 규칙

- **코드 선행 금지**: 01~05 + 게이트 통과 전 본 소스 작성 금지(hook 강제).
- **감독관이 게이트를 만든다**: 완료 기준은 사람이 즉흥으로가 아니라 감독관이 스펙에서 파생.
- **증거 기반 완료**: 빌드 종료는 게이트 통과(E2E 증거)로만. "다 됐다"는 말 불인정.
- **엔진 재사용**: 디베이트=§6 gemini·codex 라운드, 빌드=master 위임+autopilot, 검증=
  eval-driven·producer≠evaluator. 재구현 아님 — 배선.

## 출력 계약

`.appbuild/01~05` + `loop-state.json` + 빌드 산출물. 종료 보고: 게이트 통과 증거(E2E 결과)·
구현 슬라이스·미해결 0. 게이트 미통과면 종료하지 말고 `[[appbuild-orchestrate]]` 루프 유지.
