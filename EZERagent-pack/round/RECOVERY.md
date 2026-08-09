# RECOVERY.md — 재기동 복원 프로토콜 (골격)

> 재부팅·세션 만료·컨텍스트 클리어 후 master가 가장 먼저 실행하는 절차.

1. **SESSION_STATE.md를 읽는다** — 현재 위치·지시 대장·노드 상태표·미해결 게이트·다음 액션.
2. `round/*_TODO.md` 를 읽어 각 노드의 미완 작업을 파악한다.
3. memory/MEMORY.md 색인에서 관련 장기기억을 회상한다.
4. `git log --oneline | head` 로 커밋 체인을 대조한다.
5. 데몬 확인: `EZERagent ping` (죽었으면 `EZERagentd &`). 세션(PTY)은 데몬 소유라 데몬이 살아 있으면
   surface들은 그대로다 — `EZERagent list`로 확인.
6. 죽은 노드를 재기동·재각성한다: `EZERagent launch-agent --role <역할> --agent <cli>`.
7. **미해결 게이트부터** 작업을 재개한다. 완료된 단계를 다시 하지 않는다.
