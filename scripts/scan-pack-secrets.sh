#!/usr/bin/env bash
# scan-pack-secrets.sh — EZERagent-pack 콘텐츠 발행 hard-gate (Task 1, 2026-06-29).
#
# 목적: pack 전체통합으로 git-추적 EZERagent-pack 전 트리가 바이너리/DMG에 자동 임베드되므로,
#       gitignore가 못 잡는 *콘텐츠 누출*(개인 홈경로·이메일·키토큰)을 발행 전에 fail-closed로
#       차단한다. 계정 핸들(ysfuture·cysinsight)·placeholder 경로(/Users/x/ 등)는 아키텍처
#       식별자로 허용한다(오너 결정). 본 주석의 /Users/x/ 표기는 placeholder 예시다.
#
# 스캔 대상: `git ls-files EZERagent-pack` 전수(추적 파일만 — untracked 개인파일은 임베드 안 됨).
# 차단 규칙(비0 종료):
#   - 실홈경로 /Users/<실유저> (placeholder x·you·NAME 제외) · /home/<user> (동일 placeholder 제외)
#   - 이메일 (example.com·noreply·anthropic 제외)
#   - 키/토큰 (sk-…·ghp_…·Bearer …·api_key="…")
# 허용: 계정 핸들 ysfuture·cysinsight (홈경로/이메일/토큰 형태가 아니면 자연 통과) · placeholder 경로.
#
# 한계(정직): 정적 패턴 매칭이다 — 난독화·신종 토큰·이미지 내 텍스트는 못 잡는다(회귀 1차선).
# exit 0=clean("OK") / 1=발견(file:line 출력) / 2=환경 오류.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "git repo 아님" >&2; exit 2; }

# 스캔 대상 — git-추적 EZERagent-pack 전수 (NUL 구분, bash 3.2 호환 read 루프)
files=()
while IFS= read -r -d '' f; do files+=("$f"); done < <(git ls-files -z EZERagent-pack)
[ "${#files[@]}" -gt 0 ] || { echo "scan 대상 0건 — git 인덱스 부재? (EZERagent-pack 미추적)" >&2; exit 2; }

# 바이너리·잠금파일 노이즈 제외(시크릿이 살지 않고 오탐만 만드는 파일)
skip_re='\.(lock|png|jpe?g|gif|ico|svg|woff2?|ttf|wasm|pdf|zip|gz|tar|dmg|exe)$|(^|/)\.DS_Store$'
# placeholder 사용자명(허용) — /Users/<ph>·/home/<ph>
ph_re='^(x|you|NAME)$'
# 이메일 허용(오탐·의도된 공개 연락처)
email_allow_re='example\.com|noreply|anthropic'
# 키/토큰: 길이 하한으로 'task-prompt'(sk-p)·'resolve_api_key()' 등 식별자 오탐 배제.
#   api_key 류는 *따옴표 친 리터럴 값*(>=12자)만 매칭 → 함수호출·변수참조 오탐 제외.
token_re='sk-ant-[A-Za-z0-9]|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{16,}|Bearer [A-Za-z0-9._-]{16,}|(api[_-]?key)["'"'"' ]*=[ ]*["'"'"'][A-Za-z0-9/+=_-]{12,}'

findings="$(mktemp)"; trap 'rm -f "$findings"' EXIT

for f in "${files[@]}"; do
  [ -f "$f" ] || continue
  if printf '%s' "$f" | grep -qE "$skip_re"; then continue; fi

  # 1) 실홈경로 /Users/<user> — placeholder(x·you·NAME)는 match 단위로 제외
  while IFS=: read -r ln m; do
    [ -n "$ln" ] || continue
    name=${m#/Users/}
    if printf '%s' "$name" | grep -qE "$ph_re"; then continue; fi
    printf '%s:%s:%s\n' "$f" "$ln" "$m" >> "$findings"
  done < <(grep -noE '/Users/[A-Za-z0-9._-]+' "$f" 2>/dev/null || true)

  # 2) /home/<user> — 동일 placeholder 제외
  while IFS=: read -r ln m; do
    [ -n "$ln" ] || continue
    name=${m#/home/}
    if printf '%s' "$name" | grep -qE "$ph_re"; then continue; fi
    printf '%s:%s:%s\n' "$f" "$ln" "$m" >> "$findings"
  done < <(grep -noE '/home/[A-Za-z0-9._-]+' "$f" 2>/dev/null || true)

  # 3) 이메일 — 허용 도메인 제외 (match 단위 필터)
  grep -noE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' "$f" 2>/dev/null \
    | grep -viE "$email_allow_re" \
    | sed "s|^|$f:|" >> "$findings" || true

  # 4) 키/토큰
  grep -noE "$token_re" "$f" 2>/dev/null \
    | sed "s|^|$f:|" >> "$findings" || true
done

n=$(wc -l < "$findings" | tr -d ' ')
if [ "$n" -gt 0 ]; then
  echo "✗ scan-pack-secrets: $n 건 발견 — 콘텐츠 발행 차단(fail-closed):" >&2
  sort -u "$findings" | head -50 >&2
  [ "$n" -gt 50 ] && echo "  …(외 $((n-50))건)" >&2
  echo "→ 개인 홈경로/이메일/토큰을 제거하거나 placeholder(/Users/x/)·env로 치환 후 재시도하라." >&2
  exit 1
fi
echo "OK"
exit 0
