#!/bin/sh
# W0-1 Stop hook 래퍼 — 라이브 배선 승인 시 ~/.EZERagent/pack/hooks/ 로 복사 등록.
# 격리 기간엔 이 원본만 존재(설계서 §6 규약).
PACK="${EZERAGENT_PACK_DIR:-$HOME/.EZERagent/pack}"
# 대상 존재 가드 — .py 부재 시 exec 실패로 hook이 exit 2(오류)를 내는 걸 막고 조용히 통과(H-HOOK-2).
[ -f "$PACK/bin/EZERagent_completion_guard.py" ] || exit 0
exec python3 "$PACK/bin/EZERagent_completion_guard.py"
