#!/bin/sh
# Claude Code/Codex 툴 이벤트 hook (EZERagent T7 E1-④):
#   claude가 PreToolUse/PostToolUse/Stop/SubagentStop마다 실행하는 hook. stdin으로 받은 hook
#   JSON을 EZERagentd에 push(usage.event)해 events 테이블에 툴·스킬·에이전트 호출과 exit_code를
#   적재한다(E3 스킬 TOP·반복실패 분석 토대). surface는 EZERAGENT_SURFACE_ID(에이전트 PTY 상속).
# ★불변(OBSERVABILITY hook 클래스 전용): **이 관측 hook은 절대 에이전트를 막지 않는다** —
#   PreToolUse에서 exit≠0/JSON 출력은 툴을 차단할 수 있으므로 금지. stdout 무출력·모든 실패
#   무해히 흘림·항상 exit 0(텔레메트리가 에이전트를 깨뜨려선 안 된다).
#   ※이 불변은 **관측 hook 전용** 안전규칙이지 전면 금지가 아니다. EZERagent에는 두 hook 클래스가 있다:
#     (a) OBSERVABILITY(이 EZERagent-hook.sh) = 절대 차단 금지·항상 exit 0.
#     (b) GATE(appbuild-gate.sh, role-capability-gate.sh) = 설계상 deny 가능(deny-by-default act tier).
#   GATE hook의 차단은 이 불변 위반이 아니라 별개 클래스다(차단이 목적).
IN=$(cat)
if [ -n "$IN" ] && command -v EZERagent >/dev/null 2>&1; then
  printf '%s' "$IN" | EZERagent usage-event-stdin >/dev/null 2>&1
fi
# ── 사용자 로컬 훅 오버레이(~/.EZERagent/local/hooks/<이벤트>.d/*.sh) — 업데이트 불가침 확장점 ──
# 팩 파일을 직접 고치지 않고 훅을 확장하는 공식 채널. OBSERVABILITY 클래스를 상속한다:
# 후행 실행·stdout 미노출·모든 실패 무해 흘림(사용자 훅이 에이전트를 차단할 수 없다 — 안전핵).
EV=$(printf '%s' "$IN" | sed -n 's/.*"hook_event_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
LHD="${EZERAGENT_LOCAL_DIR:-$HOME/.EZERagent/local}/hooks/${EV}.d"
if [ -n "$EV" ] && [ -d "$LHD" ]; then
  for f in "$LHD"/*.sh; do
    [ -f "$f" ] || continue
    printf '%s' "$IN" | sh "$f" >/dev/null 2>&1 || true
  done
fi
exit 0
