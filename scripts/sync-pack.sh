#!/usr/bin/env bash
# sync-pack.sh — 배포본(~/.ezer/pack) → 정본(ezer-pack) 정제 동기화 (오너 2026-06-14).
# 목적: 정본이 배포본보다 뒤처지는 드리프트(예: boot_node 누락·directive 미반영)를 제거하되,
#       개인정보 회귀(개인경로·계정·memory)를 막는다. 항상 dry-run 기본 + 시크릿 게이트 fail-closed.
#
# 동작:
#   1) rsync 배포본→정본 (개인 산출물 제외, --delete 안 함 — 정본 큐레이션 보존)
#   2) (--apply 시) 동기화분에 최소 제네릭화 transform (오너→오너)
#   3) secret-scan.sh --all 게이트 — 개인경로/프로필/계정/토큰 잔존 시 차단
#   4) 변경은 staged-안-함 상태로 남긴다 — 사람이 검토 후 직접 커밋(자동 커밋·push 없음)
#
# 사용: scripts/sync-pack.sh            # dry-run (무엇이 바뀔지만 표시)
#       scripts/sync-pack.sh --apply    # 실제 반영 + 게이트 (커밋은 수동)
#
# 한계(정직): transform은 best-effort(오너→오너만). 경로·프로필·계정 정제는 자동 치환하지 않고
#            secret-scan이 '차단'하여 사람이 고치게 한다(잘못된 자동치환으로 코드 깨짐 방지).
#            정본이 SOT인 항목(.gitignore·scripts·docs·repo 전용 agents.json)은 동기화 대상 아님.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "git repo 아님"; exit 2; }
SRC="${EZER_PACK_DIR:-$HOME/.ezer/pack}"
DST="$ROOT/ezer-pack"
APPLY="${1:-}"
[ -d "$SRC" ] || { echo "배포본 없음: $SRC"; exit 2; }
command -v rsync >/dev/null || { echo "rsync 필요"; exit 2; }

# 제외: 개인 memory(정본은 수동 큐레이션)·백업·캐시·작업로그·환경전용 agents.json
EXCLUDES=(
  --exclude 'memory/'         # 개인 기억 전체 (정본 memory는 손큐레이션만)
  --exclude '*.bak-*'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude 'round/'          # _round 작업로그 (.gitignore와 정합)
  --exclude 'agents.json'     # 환경전용(개인 절대경로) — 정본은 제네릭 템플릿 유지
  --exclude '.install-manifest.json'  # 생성 아티팩트(배포본 해시 — repo 제네릭 파일과 불일치)
)

flags=(-rlpt --itemize-changes "${EXCLUDES[@]}")
[ "$APPLY" = "--apply" ] || flags+=(--dry-run)

echo "== sync-pack: $SRC/ → $DST/  ($([ "$APPLY" = "--apply" ] && echo APPLY || echo DRY-RUN)) =="
rsync "${flags[@]}" "$SRC/" "$DST/"

if [ "$APPLY" != "--apply" ]; then
  echo "(dry-run — 실제 반영: scripts/sync-pack.sh --apply)"
  exit 0
fi

echo "== 최소 제네릭화 transform (오너 → 오너) =="
# 텍스트 파일만, 동기화된 ezer-pack 안에서만.
while IFS= read -r f; do
  LC_ALL=C grep -Iq . "$f" 2>/dev/null || continue   # 바이너리 skip
  if grep -q '오너' "$f" 2>/dev/null; then
    sed -i.synctmp 's/오너/오너/g' "$f" && rm -f "$f.synctmp"
    echo "  transform: $f"
  fi
done < <(find "$DST" -type f \( -name '*.md' -o -name '*.py' -o -name '*.sh' -o -name '*.json' -o -name '*.txt' \))

echo "== 시크릿 게이트 (fail-closed) =="
if ! "$ROOT/scripts/secret-scan.sh" --all; then
  echo "✗ 동기화분에 개인정보/시크릿 잔존 — 커밋 금지. 위 항목을 정제 후 재실행하라."
  exit 1
fi
echo "✓ sync 완료 + 게이트 통과. 'git diff'로 검토 후 직접 커밋하라(자동 커밋·push 없음)."
