---
name: appbuild-supervisor
description: 이미 만든 기획 문서(01~04)를 다시 읽고 검증하는 대표 감독관 스킬 — 수집→13항목 검증→반자동 수정(승인 후·빠진 곳만·최대 3회)→완료 게이트 파생을 하위 스킬로 굴린다. 문서를 만드는 게 아니라 검증한다. appbuild 4단계·빌드 전 게이트. "기획 검증 / 감독관 / 일관성 추적성 검증 / 완료 게이트 파생 / planning supervisor" 트리거.
---

# appbuild-supervisor

★ appbuild의 주인공 — **감독관**. PRD·화면·아키텍처·작업(01~04)을 *만들지 않고* **다시 읽어
검증**한다. 기존 파이프라인 위에 한 겹 얹는 계층이다(spec-kit `/analyze`·Kiro 분석 게이트와
동일 위치: tasks 다음·빌드 전, 읽기전용 검증 → 심각도 태깅 → 게이트 산출).

> 메우는 빈칸: ①검증 루프 ②완료의 정의 ③문서 간 불일치를 빌드 끝까지 모르는 문제. CRITICAL
> 발견은 빌드를 막는다. 상태는 `loop-state.json`(중단·재개).

## 하위 스킬 (루프: 수집→검증→수정→게이트)

1. `[[appbuild-supervisor-collect]]` — 01~04 + 추적 메타를 수집·정규화.
2. `[[appbuild-supervisor-verify]]` — **13항목 검증**(일관성·추적성·갭·품질), 심각도 태깅.
3. `[[appbuild-supervisor-fix]]` — **반자동 수정**: 사용자 승인 후·빠진 곳만·**최대 3회**.
4. `[[appbuild-supervisor-gate]]` — 프로젝트별 **완료 게이트**(`05-gate.md`) 파생.

## 절차 (루프)

1. **수집** → 검증: `[[appbuild-supervisor-collect]]` — 문서·매핑을 모은다.
2. **검증** → 검증: `[[appbuild-supervisor-verify]]` — 13항목 실행 → CRITICAL/HIGH/MED/LOW
   findings + 커버리지% 표. **CRITICAL이 있으면 빌드 금지.**
3. **수정 루프** → 검증: findings가 있으면 `[[appbuild-supervisor-fix]]` — **사용자 승인을
   받고** 빠진 곳만 해당 원본 스킬로 되돌려 수정 → 재검증. **최대 3회**, 그 후에도 CRITICAL이
   남으면 사람에게 escalation(무한 루프 금지).
4. **게이트 파생** → 검증: 검증이 깨끗해지면 `[[appbuild-supervisor-gate]]` — `05-gate.md`
   (기능별 수용 + 전역 DoD + 비기능 + 교차정합) 파생.
5. **상태 영속** → 검증: 각 단계를 `loop-state.json`에 기록(중단 시 그 지점부터 재개).

## 철학 (불변)

- **만들지 않고 검증한다** — 산출 권한은 원본 스킬에, 감독관은 검증·게이트 권한.
- **게이트는 감독관이 스펙에서 파생** — 사람이 즉흥으로 정하지 않는다.
- **producer≠evaluator** — 검증은 만든 주체가 아닌 이 감독관(+빌드 단계의 다른 페인).

## 출력 계약

`.appbuild/05-gate.md` + findings 리포트(심각도·커버리지%) + `loop-state.json`. CRITICAL 0 ·
게이트 파생 완료라야 상위 `[[appbuild]]`가 `[[appbuild-orchestrate]]`로 진행. 미통과면 빌드 차단.
