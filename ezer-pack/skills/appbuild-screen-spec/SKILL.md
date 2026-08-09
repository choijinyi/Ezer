---
name: appbuild-screen-spec
description: 웹/앱 화면 명세(02-screens)를 만드는 대표 스킬 — 화면 흐름·내비게이션과 화면별 상세(레이아웃·상태·컴포넌트·데이터)를 하위 스킬로 작성한다. appbuild 2단계. "화면 명세 / 스크린 스펙 / UI 명세 / 화면 설계" 트리거, 또는 appbuild 파이프라인 2단계로 발동.
---

# appbuild-screen-spec

PRD의 기능을 **화면**으로 번역한다. 산출물 `.appbuild/02-screens.md`. 화면이 빠지면 기능이
구현될 자리가 없다 — 감독관의 추적성 검증이 "기능↔화면"을 대조하므로 빠짐없이 명세한다.

## 하위 스킬

1. `[[appbuild-screen-spec-flow]]` — 화면 목록 + 내비게이션/사용자 흐름(IA).
2. `[[appbuild-screen-spec-detail]]` — 화면별 레이아웃·상태(정상/빈/에러/로딩)·컴포넌트·데이터.

## 절차

1. **흐름 설계** → 검증: `[[appbuild-screen-spec-flow]]` — `01-prd.md`의 모든 기능이 어떤
   화면에서 일어나는지, 화면 간 이동을 정의. 기능↔화면 매핑에 누락 없게.
2. **화면 상세** → 검증: `[[appbuild-screen-spec-detail]]` — 각 화면의 레이아웃·**상태 전부**
   (정상·빈·에러·로딩)·컴포넌트·필요 데이터. 데이터는 `03-architecture.md` 모델과 일치.
3. **정합 점검** → 검증: 모든 PRD 기능에 대응 화면이 있는가, 화면이 참조하는 데이터가 모델에 있는가.

## 출력 계약

`.appbuild/02-screens.md`(흐름 + 화면별 상태·컴포넌트·데이터). 상위 `[[appbuild]]`로 반환 →
`[[appbuild-tasks]]`. 디자인 품질이 중요하면 `[[vibe-design]]`을 화면 상세에 병용한다.
