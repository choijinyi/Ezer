#!/usr/bin/env bash
# dedup-git-core.sh — .app 안 runtime/git 의 git-core 빌트인 중복본을 심볼릭링크로 되돌린다 (RC-23).
# ★Tauri 번들러가 bundle.resources 복사 시 dugite tar.gz의 git-core 심볼릭링크를 역참조(upstream #13219,
#   미해결)해 각 빌트인을 3.4MB 실복사본으로 부풀린다(runtime/git 141MB→608MB·DMG 434MB). 이 스크립트는
#   '.app 생성 후'에 git-core/git 과 바이트동일한 파일만 same-dir `git` 심볼릭링크로 치환해 원상복구한다.
#   build-macos-signed.sh(로컬 공증 빌드)와 .github/workflows/release.yml(CI)이 공유한다.
#
# ★기준점은 bin/git 이 아니라 libexec/git-core/git — Tauri가 역참조하는 원본이 git-core/git 이고, 서명
#   빌드에선 inside-out 재서명이 bin/git·git-core/git 을 각각 서명해 CMS 블롭(타임스탬프)이 달라 bin/git
#   대조가 0건이 되기 때문(2026-07-04 공증 풀런 실측). 미서명 CI 빌드에선 셋 다 동일하나 같은 기준으로
#   안전하게 동작한다. 링크 대상도 dugite 원본 타르볼과 동일한 same-dir `git`(=git-core/git)로 둔다.
#
# 사용: scripts/dedup-git-core.sh <path-to-EZERagent.app>
# 종료: 0=성공(dedup 후 중복 실복사본 제거됨) / 1=인자·경로 오류 또는 dedup 후에도 중복본 잔존(역참조 미해소)
set -euo pipefail

APP="${1:?usage: dedup-git-core.sh <path-to-.app>}"
RTGIT="$APP/Contents/Resources/runtime/git"
GITCORE="$RTGIT/libexec/git-core"
REF="$GITCORE/git"

[ -d "$GITCORE" ] || { echo "✗ git-core 디렉토리 없음: $GITCORE"; exit 1; }
[ -f "$REF" ]     || { echo "✗ 기준 파일 없음: $REF"; exit 1; }

REF_SIZE="$(stat -f '%z' "$REF")"
BEFORE_KB="$(du -sk "$RTGIT" | awk '{print $1}')"; N=0
while IFS= read -r -d '' f; do
  # 기준 파일 자신 제외(자기링크 방지) · 크기 일치 → cmp 바이트 대조 통과분만 치환(비동일 git-lfs·GCM
  # .dll/.dylib·remote 헬퍼 등 불가침). -type f 는 심볼릭링크를 제외하므로 재실행 멱등.
  if [ "$f" != "$REF" ] && [ "$(stat -f '%z' "$f")" = "$REF_SIZE" ] && cmp -s "$f" "$REF"; then
    ln -sf "git" "$f"; N=$((N+1))
  fi
done < <(find "$GITCORE" -type f -print0)
AFTER_KB="$(du -sk "$RTGIT" | awk '{print $1}')"
echo "✓ git-core 빌트인 ${N}개 링크화 · runtime/git $((BEFORE_KB/1024))MB → $((AFTER_KB/1024))MB"

# 성공 판정 = '이번에 링크한 수(N)'가 아니라 '잔존 중복 실복사본 수'로 한다. 정상 fat 빌드는 N≈142지만,
# ①이미 dedup된 .app 재실행 ②향후 upstream #13219 수정으로 Tauri가 심볼릭링크를 보존하는 경우엔 N=0이라도
# 트리는 정상(중복 없음)이다. 따라서 dedup 후 git-core에 기준(git-core/git)과 같은 크기의 '실파일'이
# 사실상 없어야(=1, 기준 자신) 성공으로 본다 → 멱등·upstream 수정 안전. 많이 남았다면 역참조 미해소로 중단.
REMAIN="$(find "$GITCORE" -type f -size "${REF_SIZE}c" | wc -l | tr -d ' ')"
[ "$REMAIN" -le 5 ] || { echo "✗ dedup 후에도 git-core에 ${REF_SIZE}바이트 실복사본이 ${REMAIN}개 잔존 — 역참조 미해소(트리 구조·기준 확인 후 중단)"; exit 1; }
