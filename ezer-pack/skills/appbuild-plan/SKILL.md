---
name: appbuild-plan
description: 웹/앱 기획 산출물(01-prd·03-architecture)을 만드는 대표 스킬 — 인터뷰/디베이트/퀵 3모드로 요구·스택·데이터모델을 도출한다. appbuild 1단계(소크라테스 기획). "앱 기획 / PRD 작성 / 요구 도출 / 기획 모드" 트리거, 또는 appbuild 파이프라인 1단계로 발동.
---

# appbuild-plan

빌드 전에 "무엇을·왜·어떻게"를 문서로 못박는다. 산출물 `.appbuild/01-prd.md`(제품 요구)
+ `.appbuild/03-architecture.md`(스택·데이터모델·구조). 깊이는 3모드로 사용자가 고른다.

## 하위 스킬 — 기획 3모드 (택1)

1. `[[appbuild-plan-interview]]` — 소크라테스식 인터뷰로 요구를 캐낸다(↔ grill-me·grill-with-docs).
2. `[[appbuild-plan-debate]]` — AI 2명이 10턴+ 토론해 기획을 좁힌다(↔ §6 gemini·codex 라운드).
3. `[[appbuild-plan-quick]]` — 질문 최소로 바로 산출물(간단/숙련 사용자용).

## 절차

1. **모드 선택** → 검증: 프로젝트 규모·사용자 숙련도에 따라 3모드 중 하나. 모호하면 인터뷰 권장.
2. **요구 도출** → 검증: 선택 모드 실행 → 핵심 기능·범위(MVP 경계)·차별점·비기능 요구 확정.
   사용자가 산출물을 검토·수정하거나 추가 라운드를 요청할 수 있다(디베이트는 재토론).
3. **PRD 작성** → 검증: `01-prd.md` — 목적·타깃·**기능 목록(각 기능에 수용 기준)**·범위·비범위.
4. **아키텍처 작성** → 검증: `03-architecture.md` — 프런트/백 스택·**데이터 모델(엔티티·필드)**·
   저장·구조. (영상 예: React+Vite·SQLite — 사용자가 스택 결정.)

## 출력 계약

`.appbuild/01-prd.md` · `.appbuild/03-architecture.md`. 각 기능에 수용 기준, 데이터 모델 명시
(뒤 `[[appbuild-supervisor]]`의 추적성 검증이 이걸 화면·작업과 대조한다). 상위 `[[appbuild]]`로
반환 → `[[appbuild-screen-spec]]`.
