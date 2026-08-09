---
name: autonomous-pilot-mandate
description: 자율주행 위임권(앵커6) — 3축 완전 자율주행·denylist에서만 정지·kill-switch 최우선 (🔒색인 상주 필수)
metadata:
  type: feedback
---

오너 제정(절대지침 6차): master는 승인된 로드맵을 오너 수동개입 없이 자율 완주한다.
**축1** 게이트 4자 수렴(agy+codex+master+기계검증, `ezer_orchestra.py gate-status`로
결정론 판정)+로컬 커밋+SESSION_STATE 갱신=다음 단계 자동 착수("지시 대기" 폐기).
**축2 (★CSO 주도 주인 대리 clear · 2026-06-18 오너 개정)** master self-clear 절대 금지 —
컨텍스트 clear는 **CSO가 "주인(오너)을 대신하여"** 집행(주인이 직접 친 것과 동일 인가). 6단계:
①master 60% 자기보고 ②CSO 시점 판단·통보(개시) ③master 준비(SESSION_STATE·TODO·로컬커밋·
checksum)·"준비 완료" ack ④CSO 재독·검증 후 `ezer cycle-agent --role master --verifier <cso>`로
주인 대신 `/clear` ⑤master 자동복구. 무응답 시 CSO 독립검증 후 조건부 집행(신선=집행·낡음=오너
escalation). **축3** 작업 단위 종료→`ezer_orchestra.py next-action`으로 다음
미완 작업 자가 착수(완료 push/`ezer schedule add --in` 원샷 웨이크업 트리거).

**Why:** "진행해줘" 수동개입이 자율주행을 무력화한다 — denylist(로드맵 이탈·soul/CLAUDE/
디렉티브 변경·외부 발행/발송·비가역 삭제·오너 보유 결정권)에서만 멈추고 나머지는 무정지.

**How to apply:** MASTER_DIRECTIVE §14를 따른다. kill-switch(오너 아무 입력=즉시 일시정지)
최우선·매 Phase 종료 1줄 push·자원 한계 중단·품질 게이트 불변(자율화=전환 주체만).
🔒이 메모리는 색인 상주 필수 — 제거 금지: 빠지면 master가 매 단계 오너 수동개입 대기로
자율주행이 무력화된다.
