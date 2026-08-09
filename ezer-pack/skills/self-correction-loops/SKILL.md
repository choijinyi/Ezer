---
name: self-correction-loops
description: 코드·난제를 객관 성공기준까지 자율로 끌어올리는 적대적 자기교정 루프 — eval LOCK 후 implement→독립채점→적대적검증 반복. "self-correction loop / 자가 교정 루프 / 코드 자율 디버깅 / 자율 디버깅" 트리거로 발동
---

# self-correction-loops

루프의 신뢰는 검증의 땅에 달려 있다. 객관 eval을 먼저 LOCK하고, producer≠evaluator로 채점하며,
reward hacking을 기계로 차단한다. (Fable 챌린지 2라운드 완성으로 실증)

## 언제 쓰나
- 코드를 기계검증 가능한 성공 기준까지 자율로 완성·디버깅할 때
- "self-correction loop / 자가 교정 / 코드 자율 디버깅 / RSI" 자연어 트리거

## 순서
1. 성공 기준을 먼저 **객관 테스트(LOCKED eval)**로 못박는다 — 모두 만족해야 종료. master 소유, 해시 락.
2. reward hacking 차단을 **테스트로 박제** — 예: 금지 단어 0회를 grep 테스트로 (이미지 #2 패턴).
3. baseline 실행 → 전부 red 확인.
4. 라운드 루프(Workflow): impl(eval 읽기만, 스스로 테스트 자가교정) → score(독립, 실행만+무변조 확인) → 녹색 시 verify(적대적, 변조 실험으로 정당성).
5. master가 LOCKED eval **직접 재채점**(이중). bug-ledger에 교훈 누적. 전 기준 녹색까지 반복(예산 상한).

## 주의할 점 (함정 — 겪을 때마다 한 줄씩 누적하라)
- eval을 producer가 수정 = reward hacking — 해시 락 + 무변조 검증 필수.
- 기계 녹색 ≠ 정당 — FPS 부풀리기·하드코딩 result는 adversarial verify(변조 실험)로만 잡힌다.
- 무한 반복·자원 폭주 금지 — 예산 상한, 수정은 로컬 커밋(가역), push·비가역 삭제 금지.

## 확인하는 방법 (검증 — 겪을 때마다 한 줄씩 누적하라)
- eval이 baseline red → 완성 시 전부 green → 무변조 OK 인가
- adversarial verify가 변조 실험으로 정당성 증명(findings 0) 했는가
- bug-ledger에 라운드 교훈이 쌓여 다음 실행이 빨라지는가
