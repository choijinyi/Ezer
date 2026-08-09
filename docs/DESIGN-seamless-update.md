# DESIGN — ezer·ezer-agent 자동 업데이트 ("업데이트 버튼 하나" 모델)

> **목표**: 오너이 ezer 팩(디렉티브·스킬·스크립트) 또는 ezer-agent 앱(ezerd·ezer·ezer-app)에 **새 기능을 개발**하면, 사용자가 ezer-agent **업데이트 버튼**을 눌렀을 때 그 새 기능이 **자동 설치**되고, 그 과정에서 **작업이 끊기지 않는다(무손실)**. 오너 본인 + 다른 사용자 공통.
>
> **두 축**: ① 새 기능 자동 배포(주) ② 작업 무손실(부가, 당연 포함).
> **상태**: 적대검증 2라운드 반영. 근거는 코드 실측(file:line). ezer-agent repo = `~/dev/ezer-agent`.

---

## 1. 전체 파이프라인

```
[개발]   오너이 ezer-pack/(팩) 또는 src/(앱)에 새 기능 → git commit
[빌드]   pack.rs include_str! + build.rs(skills walk)가 팩을 ezer 바이너리에 컴파일타임 embed
         bundle-prep.sh가 ezer/ezerd를 src-tauri/binaries로 → tauri externalBin 동봉(.app)
[릴리스]  git tag vX.Y.Z → release.yml CI → 빌드·minisign 서명 → 공개 repo(ezer-agent) draft → 오너 Publish
[배포]   사용자 앱이 시작+6h마다 latest.json 체크 → 업데이트 버튼 → Tauri updater download_and_install → .app 통째 교체
[설치]   install_update가 pending-restore 마커 기록 → app.restart
[반영]   새 ezer-app setup → daemon-ready → spawn_event_forwarder(먼저) → maybe_apply_pending_update:
           ① ezer init-pack --no-install-hook → 새 팩(새 기능)을 ~/.ezer/pack에 반영 (성공 검사)
           ② 성공 시 ezer restore --include-master → 노드 session_id resume 재런칭 (작업 무손실)
```

★ 두 채널: **앱 바이너리**(ezerd/ezer/ezer-app)는 Tauri updater가 .app 통째 교체. **팩**(디렉티브·스킬)은 ezer 바이너리에 embed돼 함께 와서 init-pack으로 반영. 둘 다 "업데이트 버튼 하나"에 묶인다.

## 2. 현황 (실측 + 적대검증 2R)

| 항목 | 상태 | 근거 |
|---|---|---|
| 자동배포 — 앱 채널(Tauri updater 버튼·자동체크·서명·CI) | ✅ 인프라 | tauri.conf updater, release.yml |
| 자동배포 — 팩 embed | ✅ | pack.rs include_str!, build.rs PACK_SKILLS walk |
| 자동배포 — 팩 자동 반영(업데이트 후 init-pack) | ✅ 구현 | main.rs maybe_apply_pending_update |
| 자동복귀 #1 — topology 원자 쓰기 | ✅ 검증 | governance.rs write_json_atomic |
| 자동복귀 #2 — 업데이트 후 자동 restore | ✅ 검증 | main.rs + ezer.rs run_restore(기존) |
| 자동복귀 #4 — resume 중복주입 분기 | ✅ 검증 | ezer.rs boot_agent_on_surface |
| 갭B 침묵실패·백업파괴·반쪽부팅 (적대검증 fatal2·serious4·5·6) | ✅ 수정 | init-pack 성공검사·--no-install-hook·event-forwarder 선행 |

## 3. 미해결 — 출시 전 필수 (적대검증 BLOCK)

| 항목 | 문제 | 해결 | 주체 |
|---|---|---|---|
| **fatal-1 버전 드리프트** | 원격 latest.json 0.2.4 < 설치본 plist(0.3.0)·번들 ezer(0.4.1) → updater "이미 최신" → **업데이트 버튼 눌러도 전체 사슬 0 실행** | **0.4.1 발행** + 발행 전 3자(plist=ezer --version=tauri.conf) 일치 결정론 게이트 (수동 cp 사이드카 금지) | 🔒 오너 (비가역 외부발행) |
| **fatal-3 prune 없음** | pack.rs install에 prune/delete 경로 전무 → 오너이 기능(스킬·디렉티브) 삭제해도 사용자 디스크에 잔존, 폐기 기능 노드 노출 | install에 prune 단계: manifest에 있으나 embed에 없는 rel 중 **비수정(디스크해시=설치해시)만 remove**, *_DIRECTIVE.md·사용자 수정본 보존 | 신중 구현 (파일삭제 위험 → 오너 확인 권장) |
| **serious-7 pack_version 없음** | manifest는 rel→sha256만, 단조 비교 없음 → 구버전 ezer 롤백 시 구 팩이 '신버전'으로 비수정 파일 후퇴 | manifest에 pack_version(env! CARGO_PKG_VERSION) + 디스크≥embed면 비강제 skip | 단계적 |
| **#3 drain** | 재시작 직전 노드의 마지막 작업분 저장 — LLM 협조 의존이라 결정론 불가, best-effort | ezer mark-saved RPC(노드 명시 마커) 또는 transcript mtime 관찰 + bounded timeout. timeout 강행 시 손실 명시 | 후속 |

## 4. 구현된 코드 변경 (전부 가역·미커밋, 브랜치 feat/multi-master-formalization)

| 파일 | 변경 | 검증 |
|---|---|---|
| `src/bin/ezerd/governance.rs` | persist_topology 원자 쓰기 + write_json_atomic 헬퍼 | cargo check 0 |
| `src-tauri/src/main.rs` | install_update 마커 + maybe_apply_pending_update(init-pack 성공검사·--no-install-hook → restore) + event-forwarder 선행 | cargo check 진행 |
| `src/bin/ezer.rs` | boot_agent_on_surface resume 시 지침 중복주입 분기 | cargo check 0 |
| `scripts/version-check.sh` (신규) | 버전 SOT 6곳 일치 가드 | 실증 |
| `dist-win/ezer.wxs`·`ezer-x64.wxs` | 0.4.0→0.4.1 드리프트 정합 | 가드 통과 |
| `docs/DESIGN-seamless-update.md` | 본 설계 문서 | — |

## 5. 다른 사용자 이식 (제품화)

- **일반 사용자** (`~/.ezer/pack` 미수정): 새 팩 전부 갱신. 업데이트 버튼으로 새 기능 받음. ✅
- **오너/개발자** (`~/.ezer/pack` 직접 수정): preserve-gate가 수정 파일 보존 → 그 파일의 새 기능 미반영(비대칭, 적대검증 serious-6). → **ezer-pack(정본)에서 개발하고 `sync-pack.sh`로 정본화** 권장. 직접 수정은 개인 커스터마이즈로 의도된 불가침.
- **발행 신뢰 경계**: minisign 서명(위조 차단·비활성화 불가). Developer ID 미취득 → Gatekeeper 경고(updater 무결성은 minisign으로 별도 보장).
- **버전 단일 SOT**: `version-check.sh`로 6곳(Cargo×2·tauri.conf·ui/package.json·wxs×2) 일치 강제. release.yml build 첫 step 권장.

## 6. 오너 결정 사항

1. **발행** — `sh scripts/version-check.sh v0.4.1` 통과 후 `git tag v0.4.1 && git push` → CI draft → 공개 repo Publish. (비가역. 전제: feat 브랜치 main 머지 여부 + GitHub secrets TAURI_SIGNING_PRIVATE_KEY·RELEASES_REPO_TOKEN 설정 확인)
2. **prune 구현** — 기능 제거 배포를 위한 install prune. 비수정 파일만 삭제라 안전하나, 파일 삭제이므로 오너 확인 권장.
3. **자동복귀 유지** — 오너 "당연히 포함" 확인 → 유지.
4. **#3 drain 후속** — best-effort 추가 여부.

## 7. 검증 기준 (출시 전 end-to-end)

- 발행 후 설치본에서 `check_update`가 0.4.1을 strictly-newer로 반환하는가.
- 업데이트 버튼 → 마커 → 재시작 → init-pack(성공검사) → **노드가 새 디렉티브로 각성** → restore 복원, 을 노드 surface에서 1회 실측.
- init-pack 실패 주입 시: 마커 보존·복원 보류·update-error emit 확인.
- prune 구현 시: 폐기 파일이 비수정이면 삭제·수정본이면 보존 확인.
