#!/bin/bash
# ezer 영속성 — PreCompact·Stop 시 작업기억 write-ahead hook
# 설계: _round/PERSISTENCE_ARCHITECTURE.md §6 G1
# 역할: 압축·종료 직전 SESSION_STATE '최종 갱신' 타임스탬프 갱신 + .state_log append.
#        (본문은 master가 채운 것 보존 — 자동화는 타임스탬프·로그 세이프가드만)
# 경로: ROOT는 환경변수 EZER_ROOT로 오버라이드 가능(미설정 시 $HOME). cwd 상향탐색이 우선 동작.
# 안전: graceful, 반드시 exit 0
set +e

INPUT=$(cat 2>/dev/null)
# 인터프리터 해소 — Windows는 python3 명령이 없고 python/py만 있는 경우가 흔하다(미해소 시 graceful degrade).
EZER_PY="$(command -v python3 || command -v python || command -v py || echo python3)"
CWD=$(printf '%s' "$INPUT" | "$EZER_PY" -c "import json,sys
try: print(json.load(sys.stdin).get('cwd',''))
except Exception: print('')" 2>/dev/null)
case "$CWD" in /*) ;; *) CWD="" ;; esac  # 절대경로만 상향탐색 (무한루프 방지)
EVENT=$(printf '%s' "$INPUT" | "$EZER_PY" -c "import json,sys
try:
 d=json.load(sys.stdin); print(d.get('hook_event_name', d.get('trigger','event')))
except Exception: print('event')" 2>/dev/null)

ROOT="${EZER_ROOT:-$HOME}"
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
# append-only 로그 (write-ahead 증거)
echo "$NOW	$EVENT	cwd=$CWD" >> "$RD/.state_log" 2>/dev/null

# SESSION_STATE '최종 갱신' 타임스탬프 갱신 — 압축 직전(PreCompact)에만 (Stop은 로그만 = git noise 방지)
SS="$RD/SESSION_STATE.md"
if [ "$EVENT" = "PreCompact" ] && [ -f "$SS" ] && grep -q "최종 갱신:" "$SS" 2>/dev/null; then
  # 치환문 삽입 전 delimiter(#)·백슬래시·& 이스케이프 — NOW·EVENT 값 오염이 sed 치환식을 깨지 않게(H-HOOK).
  NOW_E=$(printf '%s' "$NOW" | sed 's/[#\\&]/\\&/g')
  EVENT_E=$(printf '%s' "$EVENT" | sed 's/[#\\&]/\\&/g')
  sed -i '' "s#^\(> *최종 갱신:\).*#\1 ${NOW_E} (auto write-ahead: ${EVENT_E})#" "$SS" 2>/dev/null \
    || sed -i "s#^\(> *최종 갱신:\).*#\1 ${NOW_E} (auto write-ahead: ${EVENT_E})#" "$SS" 2>/dev/null
fi

# ---------- (A) SESSION_STATE 비대 워치 (스냅샷 규율을 기계가 감시 — 백서 §6) ----------
# SESSION_STATE는 '덮어쓰기 스냅샷'이어야 한다. 임계 초과 = 완료항목 미정리 신호 → 로그에 WARN만(자동삭제 금지).
SS_MAX=8192
if [ -f "$SS" ]; then
  SZ=$(wc -c < "$SS" 2>/dev/null | tr -d ' ')
  if [ -n "$SZ" ] && [ "$SZ" -gt "$SS_MAX" ]; then
    echo "$NOW	WARN:bloat	SESSION_STATE=${SZ}B>${SS_MAX} — 완료항목 정리(스냅샷 유지) 필요" >> "$RD/.state_log" 2>/dev/null
  fi
fi

# ---------- (B) .state_log 회전 (append-only 무한증가 차단) ----------
LOG="$RD/.state_log"; LOG_MAX=1000; LOG_KEEP=200
if [ -f "$LOG" ]; then
  LC=$(wc -l < "$LOG" 2>/dev/null | tr -d ' ')
  if [ -n "$LC" ] && [ "$LC" -gt "$LOG_MAX" ]; then
    mkdir -p "$RD/archive" 2>/dev/null
    head -n $((LC - LOG_KEEP)) "$LOG" >> "$RD/archive/state_log_archive" 2>/dev/null
    tail -n "$LOG_KEEP" "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG" 2>/dev/null
    echo "$NOW	rotate	.state_log>${LOG_MAX} → archive (kept ${LOG_KEEP})" >> "$LOG" 2>/dev/null
  fi
fi
exit 0
