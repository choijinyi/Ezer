#!/bin/bash
# EZERagent 자기교정 — Stop·SessionEnd 시 ①반복신호 light scan + ③메모리 정합 verify
# 설계: 외부 메모리 아키텍처 접목 항목①③ · RSI_PROTOCOL.md ① Capture
# 역할: ① transcript의 사람 교정신호를 훑어 임계 도달 시 RSI_LEDGER.md에 SHADOW 후보 적재
#       ③ 종료 시 장기기억 색인↔파일 정합을 verify, 깨졌으면 .state_log에 경고만
# 안전: graceful, 반드시 exit 0 (hook 실패가 세션을 깨지 않게). 자동적용·자동수정 0(shadow).
set +e

INPUT=$(cat 2>/dev/null)
PACK="${EZERAGENT_PACK_DIR:-$HOME/.EZERagent/pack}"
ROOT="${EZERAGENT_ROOT:-$HOME}"

TRANSCRIPT=$(printf '%s' "$INPUT" | python3 -c "import json,sys
try: print(json.load(sys.stdin).get('transcript_path',''))
except Exception: print('')" 2>/dev/null)
CWD=$(printf '%s' "$INPUT" | python3 -c "import json,sys
try: print(json.load(sys.stdin).get('cwd',''))
except Exception: print('')" 2>/dev/null)
case "$CWD" in /*) ;; *) CWD="" ;; esac  # 절대경로만 상향탐색 (무한루프 방지)

# _round 상향탐색 (save-state.sh와 동일 규약) → fallback ACTIVE_PROJECT
DIR="$CWD"; RD=""; PREV=""
while [ -n "$DIR" ] && [ "$DIR" != "/" ] && [ "$DIR" != "$PREV" ]; do
  if [ -d "$DIR/_round" ]; then RD="$DIR/_round"; break; fi
  PREV="$DIR"
  DIR=$(dirname "$DIR")
done
if [ -z "$RD" ] && [ -f "$ROOT/_round/ACTIVE_PROJECT" ]; then
  AP=$(head -1 "$ROOT/_round/ACTIVE_PROJECT" 2>/dev/null)
  [ -n "$AP" ] && [ -d "$AP/_round" ] && RD="$AP/_round"
fi
[ -z "$RD" ] && exit 0

NOW=$(date -Iseconds 2>/dev/null || date)

# ① 반복신호 light scan → RSI_LEDGER.md SHADOW 후보 (임계3·멱등·자동적용0)
if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] && [ -f "$PACK/bin/EZERagent_reflect.py" ]; then
  python3 "$PACK/bin/EZERagent_reflect.py" scan --transcript "$TRANSCRIPT" \
    --ledger "$RD/RSI_LEDGER.md" >/dev/null 2>&1
fi

# ③ 종료 시 장기기억 정합 verify — 깨졌으면 .state_log에 경고만(자동수정 0)
if [ -f "$PACK/bin/EZERagent_memory.py" ]; then
  if ! python3 "$PACK/bin/EZERagent_memory.py" verify >/dev/null 2>&1; then
    echo "$NOW	WARN:memory	장기기억 색인↔파일 정합 깨짐 — EZERagent_memory.py verify 확인 필요" \
      >> "$RD/.state_log" 2>/dev/null
  fi
fi
exit 0
