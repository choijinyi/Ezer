---
name: appbuild-supervisor-collect
description: 감독관 검증의 입력을 수집·정규화하는 하위 스킬 — 01~04 문서와 기능↔화면↔데이터↔작업 매핑·ID를 모아 검증 가능한 형태로 만든다. appbuild-supervisor 수집 관문. "기획 문서 수집 / 매핑 정규화 / 검증 입력 준비" 맥락에서 발동.
---

# appbuild-supervisor-collect

검증 전에 자료를 모은다. 흩어진 문서를 **추적 가능한 한 장의 그림**으로 정규화한다.

## 절차

1. **문서 로드** → 검증: `.appbuild/01-prd.md`·`02-screens.md`·`03-architecture.md`·
   `04-tasks.md`를 읽는다. 누락 문서가 있으면 그 자체가 결함(보고).
2. **엔티티 추출** → 검증: PRD 기능(FR ID)·화면(S ID)·데이터 엔티티/필드·작업(T ID)·각
   ID와 상호 참조를 추출한다.
3. **매핑 구성** → 검증: `기능↔화면↔데이터↔작업↔수용기준` 양방향 매핑 표를 만든다(추적성
   검증의 토대). 용어 사전(같은 개념의 표기들)도 수집(용어 드리프트 검출용).

## 출력 계약

정규화된 매핑·ID·용어 사전을 상위 `[[appbuild-supervisor]]`에 반환 →
`[[appbuild-supervisor-verify]]`의 입력. 문서 누락은 즉시 보고(검증 진행 불가).
