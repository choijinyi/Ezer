#!/bin/bash
# auto-release.sh — main push → 릴리스 레인·다음 버전 결정론 산출 + 본체 레인 SOT 범프.
#
# 왜: 오너 요구(2026-09-15) "저장소를 고치면 설치된 앱에 업데이트 표시가 들어오고 Update 버튼으로
#     적용돼야 한다". 앱은 releases/latest 의 latest.json(본체)·pack-manifest.json(팩)만 본다 →
#     커밋마다 릴리스가 서야 표시가 켜진다. 사람 손 절차(RELEASE.md §0 범프 6곳 + 태그)를 이 스크립트로
#     옮기고 .github/workflows/auto-release.yml 이 호출한다. 로컬에서도 같은 명령으로 재현된다.
#
# 사용:
#   bash scripts/auto-release.sh decide        # stdout 한 줄: lane=<binary|pack|none> base=<tag> next=<X.Y.Z>
#                                              # (판정 근거는 stderr)
#   bash scripts/auto-release.sh bump X.Y.Z    # 본체 레인: SOT 6곳 + Cargo.lock 워크스페이스 2항목 범프
#                                              # → version-check.sh vX.Y.Z 통과를 단언(실패=exit 1)
#
# 레인 규칙 = release-lane-check.sh 와 동일(경로만 본다):
#   pack   — 변경이 전부 EZERagent-pack/ 내부 (인테리어만 교체 · 무중단)
#   binary — 그 외 경로 변경 존재 (건물 재시공 · 재시작)
#   none   — 변경 0건, 또는 앱에 실리지 않는 경로(.github/ · docs/ · 루트 *.md)만 변경
# 버전 규칙 = 양 레인 태그(v*·pack-v*)의 최댓값 + patch 1 — pack-release.yml 머리의 두 충돌 가드
#   ("pack-v 는 직전 pack_version 보다 커야" · "다음 본체는 최신 pack-v 보다 커야")를 한 식으로 만족한다.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

max_version() {
  { git tag --list 'v*' | grep -Ev '^pack-' | sed 's/^v//'
    git tag --list 'pack-v*' | sed 's/^pack-v//'; } \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1
}

case "${1:-}" in
decide)
  BASE=$(git tag --sort=-creatordate | head -1)
  test -n "$BASE" || { echo "::error::태그 없음 — 기준 없이 자동 릴리스 불가" >&2; exit 1; }
  MAXV=$(max_version)
  test -n "$MAXV" || { echo "::error::X.Y.Z 형식 태그 없음" >&2; exit 1; }
  NEXT=$(echo "$MAXV" | awk -F. '{printf "%d.%d.%d", $1, $2, $3+1}')
  CHANGED=$(git diff --name-only "$BASE"..HEAD)
  echo "── 기준: $BASE..HEAD · 최대 버전(양 레인): $MAXV → 다음: $NEXT" >&2
  if [ -z "$CHANGED" ]; then
    echo "판정: 변경 0건 — 릴리스 불요" >&2
    echo "lane=none base=$BASE next=$NEXT"; exit 0
  fi
  SHIPPED=$(echo "$CHANGED" | grep -Ev '^(\.github/|docs/|[^/]+\.md$)' || true)
  if [ -z "$SHIPPED" ]; then
    echo "판정: 앱에 실리지 않는 경로만 변경(.github/·docs/·루트 *.md) — 릴리스 불요" >&2
    echo "lane=none base=$BASE next=$NEXT"; exit 0
  fi
  NONPACK=$(echo "$SHIPPED" | grep -v '^EZERagent-pack/' || true)
  if [ -z "$NONPACK" ]; then
    echo "판정: ★PACK-ONLY 레인 (전 변경이 EZERagent-pack/ 내부)" >&2
    echo "lane=pack base=$BASE next=$NEXT"
  else
    echo "판정: 본체(BINARY) 레인 — 팩 외 변경 $(echo "$NONPACK" | wc -l | tr -d ' ')건:" >&2
    echo "$NONPACK" | head -15 | sed 's/^/    /' >&2
    echo "lane=binary base=$BASE next=$NEXT"
  fi
  ;;

bump)
  NEW="${2:-}"
  echo "$NEW" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "::error::bump X.Y.Z 형식 필요: '$NEW'" >&2; exit 1; }
  CUR=$(grep -m1 '^version' Cargo.toml | sed -E 's/.*"([^"]+)".*/\1/')
  # SOT 6곳 — version-check.sh 가 읽는 바로 그 줄(첫 매치)만 바꾼다. 다른 곳의 같은 문자열은 건드리지 않는다.
  sed -i -E "0,/^version = \"$CUR\"/s//version = \"$NEW\"/"       Cargo.toml
  sed -i -E "0,/^version = \"$CUR\"/s//version = \"$NEW\"/"       src-tauri/Cargo.toml
  sed -i -E "0,/\"version\": \"$CUR\"/s//\"version\": \"$NEW\"/"  src-tauri/tauri.conf.json
  sed -i -E "0,/\"version\": \"$CUR\"/s//\"version\": \"$NEW\"/"  ui/package.json
  sed -i -E "/<Product /s/Version=\"$CUR\"/Version=\"$NEW\"/"     dist-win/EZERagent.wxs
  sed -i -E "/<Product /s/Version=\"$CUR\"/Version=\"$NEW\"/"     dist-win/EZERagent-x64.wxs
  # Cargo.lock — 워크스페이스 두 패키지(EZERagent·EZERagent-app) 항목만(name 줄 바로 다음 version 줄).
  # release.yml 의 cargo build 는 --locked 가 아니라 안 맞춰도 빌드는 되지만, RELEASE.md §0 절차가
  # lock 동기화를 요구하므로 결정론으로 맞춘다.
  python3 - "$CUR" "$NEW" <<'PY'
import re, sys
cur, new = sys.argv[1], sys.argv[2]
p = "Cargo.lock"
s = open(p, encoding="utf-8").read()
n = 0
for pkg in ("EZERagent", "EZERagent-app"):
    pat = re.compile(r'(name = "%s"\nversion = )"%s"' % (re.escape(pkg), re.escape(cur)))
    s, k = pat.subn(r'\g<1>"%s"' % new, s, count=1)
    n += k
if n != 2:
    print(f"::error::Cargo.lock 워크스페이스 항목 {n}/2 갱신 — lock 형식이 바뀌었나?", file=sys.stderr)
    sys.exit(1)
open(p, "w", encoding="utf-8").write(s)
PY
  sh scripts/version-check.sh "v$NEW"
  ;;

*)
  echo "사용: bash scripts/auto-release.sh decide | bump X.Y.Z" >&2
  exit 2
  ;;
esac
