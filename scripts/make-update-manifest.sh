#!/bin/sh
# 자동 업데이트 manifest(latest.json) 생성 — tauri build가 만든 서명(.sig)을 모아
# Tauri updater가 읽는 표준 포맷으로 묶는다.
#
# 전제: `bun x @tauri-apps/cli build`를 TAURI_SIGNING_PRIVATE_KEY(+PASSWORD)로 실행해
#       createUpdaterArtifacts 산출물(.app.tar.gz + .app.tar.gz.sig)이 생성돼 있어야 한다.
#
# 사용:  sh scripts/make-update-manifest.sh <version> <github_owner> [repo]
# 예:    sh scripts/make-update-manifest.sh 0.2.0 ezerfuturist ezer-agent
set -e
cd "$(dirname "$0")/.."

VERSION="${1:?usage: make-update-manifest.sh <version> <owner> [repo]}"
OWNER="${2:?owner required}"
REPO="${3:-ezer-agent}"
NOTES="${UPDATE_NOTES:-ezer $VERSION}"

BUNDLE="target/release/bundle/macos"
SIG_FILE="$BUNDLE/ezer.app.tar.gz.sig"
TARBALL="$BUNDLE/ezer.app.tar.gz"

if [ ! -f "$SIG_FILE" ]; then
  echo "error: $SIG_FILE 없음 — 먼저 서명 키로 tauri build를 실행하라:" >&2
  echo "  TAURI_SIGNING_PRIVATE_KEY=\$(cat ~/.tauri/ezer-updater.key) bun x @tauri-apps/cli build" >&2
  exit 1
fi

SIGNATURE="$(cat "$SIG_FILE")"
# 업로드 자산 이름(릴리스에 올릴 표준 이름) — latest.json의 url과 일치해야 한다
ASSET="ezer-${VERSION}-macos-aarch64.app.tar.gz"
URL="https://github.com/${OWNER}/${REPO}/releases/download/v${VERSION}/${ASSET}"
PUBDATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p dist-update
cp "$TARBALL" "dist-update/${ASSET}"
cat > dist-update/latest.json <<JSON
{
  "version": "${VERSION}",
  "notes": "${NOTES}",
  "pub_date": "${PUBDATE}",
  "platforms": {
    "darwin-aarch64": {
      "signature": "${SIGNATURE}",
      "url": "${URL}"
    }
  }
}
JSON

echo "생성됨:"
echo "  dist-update/latest.json"
echo "  dist-update/${ASSET}"
echo ""
echo "GitHub 릴리스에 올릴 자산: 위 두 파일 + DMG"
echo "  gh release create v${VERSION} \\"
echo "    dist-update/latest.json \\"
echo "    dist-update/${ASSET} \\"
echo "    dist-mac/ezer-${VERSION}-macos-arm64.dmg"
echo ""
echo "⚠ Intel(x86_64)·Windows 플랫폼 키는 각 타깃 빌드 후 platforms에 추가하라(RELEASE.md)."
