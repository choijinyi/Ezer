---
name: appbuild-supervisor-fix
description: 검증에서 발견된 결함을 반자동으로 교정하는 하위 스킬 — 사용자 승인을 받고, 빠진 곳만, 최대 3회 원본 스킬로 되돌려 고친 뒤 재검증한다. appbuild-supervisor 수정 관문. "반자동 수정 / 빠진 곳 교정 / 승인 후 수정 / 최대 3회" 맥락에서 발동.
---

# appbuild-supervisor-fix

감독관이 잡은 결함을 고친다 — 단 **마구 고치지 않는다.** 세 가지 제약:

## 제약 (불변)

- **승인 후에만** — 무엇을 왜 고칠지 사용자에게 보이고 승인받는다(임의 수정 금지).
- **빠진 곳만** — 발견된 결함 항목만 손댄다. 멀쩡한 부분·무관 문서 "개선" 금지.
- **최대 3회** — 검증→수정 루프는 3회까지. 그 후에도 CRITICAL이 남으면 사람에게 escalation.

## 절차

1. **수정안 제시** → 검증: findings를 결함→수정안으로 묶어 사용자에게 제시·승인 요청.
2. **원본 스킬로 되돌림** → 검증: 승인된 항목을 해당 단계로 회송해 고친다 — 기능 누락=
   `[[appbuild-plan]]`, 화면 상태 누락=`[[appbuild-screen-spec]]`, 작업 결함=`[[appbuild-tasks]]`.
   감독관이 직접 문서를 다시 쓰지 않는다(산출 권한은 원본에).
3. **재검증** → 검증: `[[appbuild-supervisor-verify]]` 재실행. 잔여 findings·루프 회수를
   `loop-state.json`에 기록.
4. **종료/격상** → 검증: CRITICAL 0이면 게이트로. 3회 후에도 CRITICAL이면 멈추고 escalation.

## 출력 계약

수정 반영된 01~04 + 갱신된 findings + 루프 회수(`loop-state.json`). 상위 `[[appbuild-supervisor]]`로
반환. 승인 없는 수정·3회 초과·무관 문서 변경은 금지.
