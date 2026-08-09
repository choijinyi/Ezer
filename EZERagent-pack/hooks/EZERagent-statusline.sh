#!/bin/sh
# Claude Code statusline 래퍼 (EZERagent T5 Phase 2-A):
#   claude가 매 assistant 메시지마다 실행하는 statusline command. stdin으로 받은 statusline
#   JSON을 EZERagentd에 push(usage.report)해 pane 헤더 배지에 ctx%·5h·7d rate limit을 띄우고,
#   사람용 statusline 한 줄을 stdout으로 돌려준다. surface는 EZERAGENT_SURFACE_ID(claude PTY 상속).
# ★불변: statusline 경로는 **절대 claude를 막지 않는다** — 모든 실패는 무해히 흘린다(exit 0).
IN=$(cat)
if [ -n "$EZERAGENT_PREV_STATUSLINE" ]; then
  # 기존 statusline이 있었으면 사람용 줄은 그 명령에 위임하고 배지 push만 수행(체인 보존).
  command -v EZERagent >/dev/null 2>&1 && printf '%s' "$IN" | EZERagent usage-report-stdin --quiet >/dev/null 2>&1
  printf '%s' "$IN" | sh -c "$EZERAGENT_PREV_STATUSLINE"
elif command -v EZERagent >/dev/null 2>&1; then
  # push + 사람용 한 줄 출력 (EZERagent 자기완결 — python 등 외부 의존 없음).
  printf '%s' "$IN" | EZERagent usage-report-stdin
fi
exit 0
