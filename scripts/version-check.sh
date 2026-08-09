#!/bin/sh
# version-check.sh — 버전 SOT 6곳 일치 검증 (드리프트 차단)
#
# 왜: 릴리스 버전이 Cargo/tauri/ui/wxs 6곳에 흩어져 수동 동기화된다(docs/RELEASE.md §0).
#     0.4.0→0.4.1 범프에서 wxs 2곳이 누락돼 드리프트가 발생한 적이 있다.
#     이 가드를 release.yml build job 첫 step + 로컬 preflight로 걸면 불일치 시 빌드/발행이 차단된다.
#
# 사용:
#   sh scripts/version-check.sh            # 6곳 상호 일치만 검사
#   sh scripts/version-check.sh v0.4.1     # 그 값(태그)과도 일치 검사 (발행 직전 단언)
#
# 종료코드: 0=일치, 1=불일치(또는 추출 실패)
set -eu
cd "$(dirname "$0")/.."

row() { printf '  %-30s %s\n' "$1" "$2"; }

V_CARGO=$(grep -m1 '^version'   Cargo.toml                  | sed -E 's/.*"([^"]+)".*/\1/')
V_TCARGO=$(grep -m1 '^version'  src-tauri/Cargo.toml        | sed -E 's/.*"([^"]+)".*/\1/')
V_CONF=$(grep -m1 '"version"'   src-tauri/tauri.conf.json   | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')
V_PKG=$(grep -m1 '"version"'    ui/package.json             | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')
V_WXS=$(grep -m1 'Product'      dist-win/ezer.wxs            | sed -E 's/.*Version="([^"]+)".*/\1/')
V_WXS64=$(grep -m1 'Product'    dist-win/ezer-x64.wxs        | sed -E 's/.*Version="([^"]+)".*/\1/')

echo "버전 SOT 6곳:"
row "Cargo.toml"                "$V_CARGO"
row "src-tauri/Cargo.toml"      "$V_TCARGO"
row "src-tauri/tauri.conf.json" "$V_CONF"
row "ui/package.json"           "$V_PKG"
row "dist-win/ezer.wxs"          "$V_WXS"
row "dist-win/ezer-x64.wxs"      "$V_WXS64"
echo ""

NUNIQ=$(printf '%s\n' "$V_CARGO" "$V_TCARGO" "$V_CONF" "$V_PKG" "$V_WXS" "$V_WXS64" | sort -u | wc -l | tr -d ' ')
UNIQ=$(printf '%s\n' "$V_CARGO" "$V_TCARGO" "$V_CONF" "$V_PKG" "$V_WXS" "$V_WXS64" | sort -u | tr '\n' ' ')

rc=0
if [ "$NUNIQ" != "1" ]; then
  echo "❌ 버전 불일치 — 6곳이 갈렸다: [ $UNIQ]"
  rc=1
else
  echo "✅ 6곳 일치: $V_CARGO"
fi

# 발행 직전 단언: 태그(vX.Y.Z)와 소스 버전이 같은지
if [ "${1:-}" != "" ]; then
  EXPECT="${1#v}"
  if [ "$NUNIQ" != "1" ] || [ "$V_CARGO" != "$EXPECT" ]; then
    echo "❌ 기대 버전($EXPECT)과 불일치 (소스=$V_CARGO)"
    rc=1
  else
    echo "✅ 기대 버전 일치: $EXPECT"
  fi
fi

exit $rc
