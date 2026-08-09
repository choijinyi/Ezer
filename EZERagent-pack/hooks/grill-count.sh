#!/bin/sh
# PostToolUse(matcher AskUserQuestion) — grill-me 결정축 카운트(evaluator).
# ★역할 분리(eval-driven 무결성): 질문하는 LLM(producer)과 distinct를 세는 이 hook
#   (evaluator)과 차단하는 grill-gate.sh(gatekeeper)를 분리한다. begin/check/end만
#   배선하고 이 count를 빠뜨리면 distinct가 영원히 0 → fail-CLOSED 마비가 된다.
# ★이 hook은 차단 게이트가 아니다 — grill_gate.py count는 마커에 누적만 하고 절대
#   exit≠0을 내지 않는다(관측·누적 성격). 따라서 항상 exit 0(에이전트 비차단).
command -v python3 >/dev/null 2>&1 || exit 0
HOOK_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || exit 0
GATE_PY="$HOOK_DIR/../bin/grill_gate.py"
[ -f "$GATE_PY" ] || exit 0
python3 "$GATE_PY" count >/dev/null 2>&1   # stdin(hook JSON) → count, 결과·실패 무시
exit 0
