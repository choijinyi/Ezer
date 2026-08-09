#!/bin/sh
# W0-2 PostToolUse(Task|Agent) hook 래퍼 — 라이브 배선 승인 시 ~/.ezer/pack/hooks/ 로 복사 등록.
# 1차 라이브 대상은 master 프로필(위임 수신자) — 등록은 승인 후 master 집행(설계서 §3.2).
PACK="${EZER_PACK_DIR:-$HOME/.ezer/pack}"
# 대상 존재 가드 — .py 부재 시 exec 실패로 hook이 exit 2(오류)를 내는 걸 막고 조용히 통과(H-HOOK-2).
[ -f "$PACK/bin/ezer_verify_reminder.py" ] || exit 0
exec python3 "$PACK/bin/ezer_verify_reminder.py"
