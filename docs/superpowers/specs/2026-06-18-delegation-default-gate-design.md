# 위임 강제 게이트 (Delegation-Default Gate) — 설계 문서

> 작성: 2026-06-18 · master · 오너 승인 완료
> 목적: master가 명시적 "워커 시켜" 명령 없이도 기능 개발을 직접 수행해
> "master 작업 중 → 회신 큐 적체"를 만드는 문제를 **결정론적 게이트로 근본 차단**.

## 1. 문제 정의

현재 위임 강제는 5개 층이 있으나 **평시에는 자연어 권고(CLAUDE.md)만 실질 작동**한다.

| 층 | 메커니즘 | 평시 작동 |
|---|---|---|
| L0 CLAUDE.md 지침 | 권고 | ⚠️ 위반 가능 |
| L1 `EZERagent_route.py` | 분류만, 수동 호출 | ❌ |
| L2 `guard.sh` (PreToolUse) | 자동 실행되나 `AUTOPILOT_ACTIVE` 플래그 있을 때만 STRICT. 평시(LOOSE)엔 Edit/Write 전부 허용 | ❌ 핵심 구멍 |
| L3 `task-prompt` 위임 티켓 | 수동 호출 | ❌ |
| L4 4자 수렴 게이트 | 위임 후행 | ❌ |

**근본 원인 ①(구조):** LLM은 요청을 받으면 "가장 마찰 적은 경로 = 즉시 직접 처리"로 흐른다. 위임은 추가 단계라 마찰이 크다. 자연어 권고는 이 경향을 구조적으로 이기지 못한다.

**근본 원인 ②(정책):** 현재 기본값이 "직접 수행=기본 / 위임=옵션". 오너 절대규칙은 정반대 — "위임=기본 / 직접=운영·메타 한정 예외".

## 2. 핵심 전환

**기본값 역전**을 자연어가 아니라 이미 PreToolUse hook으로 돌고 있는 `guard.sh`로 **결정론적 강제**한다. (오너 시스템 철학과 일치: preflight "스크립트 출력만이 사실, LLM 자연어 재추론 금지".)

## 3. 아키텍처 — 3층

### ① 예방층 — 진입 분류 (UserPromptSubmit hook)
- 요청 진입 시 `EZERagent_route.py` 자동 실행.
- `slow`/개발 의도 판정이면 컨텍스트에 `[위임 필수] 이 작업은 워커 대상입니다` 신호 주입.
- 강제가 아니라 예방 — master가 처음부터 위임 모드로 사고하도록 유도.

### ② 강제층 — 행동 차단 (guard.sh 평시 모드 강화) ← 근본 엔진
master surface에서 `Edit/Write/빌드성 Bash` 시도 시:
- 대상이 **운영/메타 allowlist** → ALLOW
- 그 외 **프로젝트 소스** → **DENY** + 위임 명령 안내
- **1회성 허가 토큰** 존재 → ALLOW (오너 예외)

### ③ 전환층 — deny 메시지 (마찰 최소)
차단 시 복붙 가능한 정확한 다음 명령을 출력:
```
이 작업은 워커 위임 대상입니다.
  EZERagent launch-agent --role worker --agent claude
  python3 EZERagent_orchestra.py task-prompt --task "<차단된 작업>" --to worker
```

## 4. 결정적 디테일 — 역할 구분 (실패하면 전체 붕괴)

guard.sh는 **master surface에서만** 개발 도구를 막아야 한다. **워커는 개발이 본업이므로 면제.**
→ hook이 호출 주체의 역할(master vs worker)을 판별해야 한다. `EZERagent identify`/`claim-role` 매핑을 guard.sh가 조회한다. (`register-worker.sh`·claim-role 인프라 기존재 확인.)

## 5. allowlist 경계 (master 직접 = 운영/메타만, 예외 없음)

```
ALLOW  _round/* (SESSION_STATE·*_TODO) · memory/* · MEMORY.md
       · 읽기 전체(Read/Grep/Glob) · EZERagent 명령 · git 읽기(status/log/diff)
       · EZERagent_route.py/EZERagent_orchestra.py 등 운영 스크립트 호출
       · docs/superpowers/specs/* (설계 문서)
DENY   src/ · ui/ · EZERagent-pack/bin/ · src-tauri/ 등 소스 Edit/Write
       · cargo/npm/bun 빌드·테스트 · 신규 기능 파일 생성
```

## 6. 1회성 예외 토큰 (오너 주권)

오너이 "이건 네가 직접 해"라고 하시면:
- master가 `DELEGATION_OVERRIDE` 토큰 파일 생성(TTL 30분 · 1작업 한정).
- guard.sh가 확인 후 통과.
- 작업 직후 토큰 자동 제거.
- 기존 헌법편집토큰(`CONSTITUTION_EDIT_AUTHORIZED`) 패턴 재사용.

## 7. 구현 대상 파일 (워커 조사로 최종 확정)

- `~/CEO 프로필/settings.json` — UserPromptSubmit hook 추가(예방층), PreToolUse 매처 확인
- `~/Desktop/EZERagent/EZERagent-arp/_round/autopilot/guard.sh` — LOOSE 모드에 master 역할 한정 개발 도구 deny-by-default + allowlist + 토큰 + 안내 메시지
- `EZERagent-pack/bin/EZERagent_route.py`(소스) → `~/.EZERagent/pack/bin/`(배포) — 개발 의도 트리거 보강(필요 시), UserPromptSubmit 자동 실행 호환
- 역할 판별 helper — `EZERagent identify`/claim-role 매핑 조회 (기존 인프라 활용)

## 8. 검증 기준 (성공 = 결정론으로 증명)

1. master surface에서 `src/*` Edit 시도 → **DENY + 위임 명령 안내 출력** (E2E)
2. master surface에서 `_round/SESSION_STATE.md` Write → **ALLOW** (운영 면제)
3. worker surface에서 `src/*` Edit → **ALLOW** (워커 면제)
4. `DELEGATION_OVERRIDE` 토큰 존재 시 master `src/*` Edit → **ALLOW**, 작업 후 토큰 제거 확인
5. UserPromptSubmit에 개발 요청 → 컨텍스트에 `[위임 필수]` 신호 주입 확인
6. 헌법 파일(soul/CLAUDE/guard.sh 자신) 보호 불변 — 기존 rsi-gate 보호 회귀 없음
7. 평시 운영(EZERagent 명령·git 읽기·메모리 저장) 무회귀

## 9. 거버넌스 주의

- guard.sh/settings.json은 **집행기(헌법성)** — master 직접 감독 최대 강도.
- 이 변경은 기존 헌법 보호(rsi-gate)를 *건드리므로* 오너 명시 승인 하에서만 진행(완료).
- **구현 주체 = 워커**(이 설계의 정신을 스스로 실천). master는 위임·감독.
- 외부 발행(git push) 금지 — 로컬 커밋까지만(자율주행 denylist 준수).

## 10. 추가 발견 — guard.sh 인자/대상 미구분 과차단 (2026-06-18 실측)

master가 `EZERagent send`로 worker에게 "헌법 문서를 읽어라"는 메시지를 보낼 때, guard.sh의 LOOSE 헌법보호가 **명령 문자열의 substring**(헌법파일명)만 보고 차단했다(false positive). master는 그 파일을 *쓰는* 게 아니라 인자 텍스트로 *언급*했을 뿐이다.

→ 이번 구현에서 함께 교정:
- 헌법파일 보호는 **쓰기 도구(Write/Edit)의 대상 경로** 및 **Bash의 실제 리다이렉트/쓰기 대상**에만 적용.
- 단순 인자 텍스트 substring 매칭으로 인한 차단 제거.
- 검증 추가: master `EZERagent send`에 헌법파일명이 텍스트로 포함돼도 **통과**(쓰기 아님), 실제 `echo ... > <헌법파일>` 류는 **차단** 유지.

이 발견 자체가 본 설계의 명제를 강화한다 — 게이트는 강력하되 **"대상"과 "텍스트"를 정확히 구분**해야 운영을 마비시키지 않는다(allowlist 정밀성과 동일 원칙).

## 11. 자산 동기화 범위 — 모든 패키지 동일 업데이트 (오너 지시 2026-06-18)

### 11.1 자산 분포 실측 맵

| 자산 | 소스 | 배포본 | 임베드 | 동기 |
|---|---|---|---|---|
| **guard.sh** | (현재 EZERagent-arp/_round/autopilot/ 단일) | 없음 | ❌ 미등록 | ❌ 고립 |
| EZERagent_route.py | EZERagent-pack/bin/ | ~/.EZERagent/pack/bin/ | ✅ pack.rs | EZERagent rebuild |
| EZERagent_orchestra.py | EZERagent-pack/bin/ | ~/.EZERagent/pack/bin/ | ✅ pack.rs | EZERagent rebuild · ⚠️ **현재 DRIFT** |
| EZERagent_preflight.py | EZERagent-pack/bin/ | ~/.EZERagent/pack/bin/ | ✅ pack.rs | EZERagent rebuild |
| rsi-gate.sh | EZERagent-pack/bin/ | ~/.EZERagent/pack/bin/ | ✅ pack.rs | EZERagent rebuild |
| appbuild-gate.sh | EZERagent-pack/hooks/ | ~/.EZERagent/pack/hooks/ | ✅ pack.rs | EZERagent rebuild |
| route_triggers.json | EZERagent-pack/bin/ | ~/.EZERagent/pack/bin/ | ✅ pack.rs | EZERagent rebuild |
| settings.json | (없음) | ~/CEO 프로필/ | — | guard.sh 경로 하드코딩 |

### 11.2 오너 결정 — guard.sh 임베드 편입 (구조 통일)

가장 중요한 집행기 guard.sh만 임베드 파이프라인에서 빠져 EZERagent-arp 한 곳에 고립 → "모든 패키지 동일"이 구조적으로 깨짐. 다른 집행기(rsi-gate·appbuild-gate)와 **동일 파이프라인으로 통일**한다:

1. guard.sh를 **EZERagent-pack/bin/(또는 hooks/)** 소스로 편입.
2. **src/pack.rs**의 `PACK` 배열에 `include_str!`로 등록.
3. `EZERagent rebuild`/`init-pack`으로 **~/.EZERagent/pack/bin/guard.sh** 배포본 자동 생성.
4. **settings.json**의 PreToolUse hook 경로를 EZERagent-arp 하드코딩 → **배포본(~/.EZERagent/pack/bin/guard.sh)** 기준으로 변경.

### 11.3 통합 작업 범위 (worker)

- (1) 위임 게이트 본 구현 (§1–§10).
- (2) guard.sh 임베드 편입 (§11.2).
- (3) drift 복구 — EZERagent_orchestra.py 등 소스↔배포 일치(`EZERagent rebuild`).
- (4) 전 자산 소스↔배포본 **shasum 일관성 검증**.

### 11.4 ★리스크 (worker 계획에서 반드시 다룰 것)

- **EZERagent-arp 내 guard.sh 직접 참조처** — rsi-gate.sh 등 동일 디렉토리에서 상대경로로 guard.sh를 호출하거나, autopilot 시스템이 `EZERagent-arp/_round/autopilot/guard.sh`를 직접 가리킬 수 있다. 위치 편입 시 이 참조가 깨지지 않게 전수 조사·호환 유지.
- **AUTOPILOT_ACTIVE/PAUSED 플래그 경로** — guard.sh가 `EZERagent-arp/_round/autopilot/`에서 플래그 파일을 읽는다. 편입 후에도 플래그 탐지 경로가 일치해야 STRICT/PAUSE 모드·kill-switch가 보존된다.
- **이동 vs 사본** — 원본을 옮기면 EZERagent-arp 기존 경로가 빈다. 기존 경로 참조를 전부 갱신하거나, 편입 후 EZERagent-arp 경로를 배포본으로 일원화. worker가 안전한 방식을 계획에 제시.

### 11.5 검증 추가

8. 모든 임베드 자산 소스↔배포본 shasum **일치** (drift 0).
9. settings.json hook이 **배포본 guard.sh** 호출 + guard 기능 E2E **무회귀**(STRICT/LOOSE/PAUSE 모드·플래그 탐지 보존).
10. `EZERagent rebuild`(또는 cargo 빌드) **성공**.

## 12. 배포 범위 — EZERagent 배포용 (오너 결정 2026-06-18: 외부 릴리스까지)

오너 지시로 위임 게이트 수정을 **실제 배포 산출물까지 반영**한다. EZERagent 패키지(소스)=§11, EZERagent 배포용=본 §12.

### 12.1 배포 단계 (엄격한 순서 — 앞 단계 통과 후 진행)

1. 소스 반영 (§1–§11)
2. `cargo build` — EZERagent/EZERagentd 바이너리 (guard.sh 임베드 포함)
3. pack 재설치 — `~/.EZERagent/pack` (init-pack/rebuild)
4. `EZERagentd` 데몬 재기동 — **로컬 라이브 작동**
5. E2E·shasum 일관성·agy·codex 리뷰 **통과**
6. 버전 범프 + **로컬 커밋**(가역 — 허용)
7. 외부 릴리스 빌드·발행 — **★오너 최종확인 후에만**(비가역)

### 12.2 ★외부 릴리스 제약·리스크 (memory·런북 기반 — worker 현황 재조사 필수)

- **PUBLIC main push 금지** — 공개 릴리스는 별도 공개 repo로 relocate(최근 "옵션 A" 방식). main 직접 push 절대 금지.
- **코드사이닝·서명** — 최근 커밋이 "빈 APPLE_* env 제거 → 미서명 빌드로 코드사이닝 실패 해소". 서명 전략 현황 확인.
- **Windows 미비 3종** — GUI 빌드·latest.json windows 키·Authenticode. macOS 우선.
- **정답 인프라** = GitHub Actions tauri-action (로컬 dmg/서명/Windows 빌드 미완).
- **외부발행 = 비가역 = denylist** → 실제 `git push`/`gh release`는 worker 자동 금지, master 감독 + 오너 확인 2단계.

### 12.3 worker 범위 추가 (5번째)

(5) **배포** — 로컬 빌드·설치·데몬 반영(라이브 검증) + 외부 릴리스:
- (a) 먼저 **릴리스 인프라 준비도 현황조사** → "가능범위 vs 미비점"을 master에 보고.
- (b) 산출물 빌드·준비.
- (c) 실제 발행은 **자동 금지** — master 감독 + 오너 최종확인 게이트.

## 13. 인계(Handoff) — 2026-06-18 시스템 장애 중 master 재기동

> 오너이 시스템 복구를 위해 master를 재기동 중. **새 master는 이 §13으로 끊김 없이 이어받는다.**

### 13.1 오너 원래 과제 (이 작업의 출발점)
"master가 명시적 위임 명령 없이 직접 일해서 '회신 큐 적체'를 만드는 문제"의 근본 해결.

### 13.2 오너 확정 결정
- **위임 게이트 3축**: 진입분류(예방) + 행동차단(강제) / **운영·메타만 master 직접(예외 없음)** / 차단 + 정확한 위임명령 안내.
- **guard.sh 임베드 편입** (구조 통일 — §11).
- **배포: 외부 릴리스까지** (§12), 단 실제 발행은 오너 최종확인.

### 13.3 진행 상황
- 설계 §1–§12 박제 완료.
- worker 각성·통합티켓(5범위: 게이트구현/guard임베드편입/drift복구/일관성검증/배포) 전달 완료 → **통합 계획 push 대기 중**이었음.
- **구현 착수 전 시스템 장애 발생.**

### 13.4 시스템 장애 전모 (미해결 — 최우선 복구)
- 데몬 hang→사망. 오너 `rm`(stale lock/sock) 후 **앱이 앱번들 EZERagentd(74628) 재스폰**.
- EZERagent 바이너리 **16:29·16:58 반복 교체**(자동 메커니즘 의심) — 손상본은 SIGKILL(137). **작동본 = 앱번들 EZERagent shasum 9d757c7c…** (`/Applications/EZERagent.app/Contents/MacOS/EZERagent`).
- 오너 2차 `rm`으로 데몬 소켓 재삭제 → **통신 불가**.
- 노드 topology 소실. `EZERagent boot` 시 worker·cso(claude CLI `$HOME/.EZERagent/claude` 미설치)·codex 기동 실패. gemini(surface:203)만 성공.
- EZERagent 백업: `EZERagent.bak-launchfix`(14:02) · `EZERagent.bak-clearhs`(6/17) · `EZERagent.bak-20260614`.

### 13.5 오너 진행 중
- "이 작업 이전으로 되돌리기" 롤백 + master 재기동.
- **미확인(새 master가 오너께 물을 것)**: "이 작업"의 정확한 정체 + EZERagent를 16:29·16:58 계속 덮어쓰는 자동 교체원.

### 13.6 다음 액션 (복구 후 순서)
1. 시스템 안정화 — 데몬 소켓 재생성 · EZERagent 작동본(9d757c7c) 고정 · **자동 교체원 차단**(안 멈추면 재손상).
2. 노드 재기동(`EZERagent boot`) + worker·cso 각성(claude CLI 복구 선행).
3. worker에 **design doc 기반 위임 재개**(5범위).
4. ★**구현 주체 = worker. master 직접 금지.**

### 13.7 핵심 통찰 (오너 질문에 대한 답 — 영속)
근본 해결 = **① 위임 게이트(개발 차단) + ② 긴 운영·디버깅도 CSO에 위임 + ③ 노드 자동 생존·복구**. 이번 장애가 ②③의 필요성을 실증함 — **CSO가 죽어 master가 시스템 복구를 직접 수십 턴 삽질 → 오너 '큐 적체'가 정확히 재현**. 위임 게이트만으론 '긴 운영·디버깅' 사각지대가 남고, 위임 대상(노드)이 죽으면 강제 자체가 무너진다.

## 14. 복구 설계안 (2026-06-18 전수조사 17 agent·1.7M tok 기반 · adversarial 검증 반영)

### 14.1 근본원인 — 실측 확정, 3중 독립 결함 + 트리거
- **(A) iCloud 동기화 [장애5 직접·유일 원인]**: `~/Desktop`가 iCloud 'Desktop & Documents' 동기화 영역(xattr `com.apple.CloudDocs.iCloudDriveFileProvider` 실측). 편집/빌드와 File Provider 경합 → `' 2'` 충돌사본 양산. `fileproviderd` 88.8% CPU·진행형.
- **(B) 수동 swap 루프 [장애2]**: 매 라운드 `cargo build` → `scratch/deploy_*_swap.py`가 `/opt/homebrew/bin/{EZERagent,EZERagentd}`·앱번들 덮어씀. EZERagent↔EZERagentd 빌드세대 스큐 + 미서명(ad-hoc). 8세대 `.bak` 누적.
- **(C) 수동 rm(sock·lock) [장애3·트리거]**: 데몬 split-brain — EZERagentd `74628`(orphan) + `90238`(live lock-holder) 공존. main.rs 싱글톤 가드가 inode 의존이라 lock 재생성 시 우회.
- **정정**: 데몬 hang(장애1) 원인 vt100 poison은 **이미 `f462d73`로 수정·실행바이너리 반영**(EZERagentd.log는 Jun 14 stale 로그 오판). 'claude CLI 미설치'(장애4)는 **오기술 → 실제 folder-trust 미수락**(`hasTrustDialogAccepted=False`). codex=dangling brew symlink(npm본으로 정상 해석).

### 14.2 오너 'GitHub 덮어쓰기' 판정 — 무효·역효과 (실측)
**0/5 장애 해결 + 비가역 신규 피해**: ①' 2'는 iCloud 디스크레벨 산물(소스 무관·재발) ②바이너리 교체는 산출물 문제(소스로 못 바꿈) ③vt100 fix(f462d73)는 로컬에만 — origin이 **8커밋 뒤**라 덮으면 fix 회귀 ④소켓 rm은 런타임. **결정타**: 미push 8커밋 + uncommitted 10파일 + 인계 design doc(로컬 SOT) 전소실.

### 14.3 복구 순서 (검증 corrections 반영 — 복제원·교체원 먼저 정지)
1. **보전(가역·최우선)**: uncommitted 10 + untracked 산출물·인계문서 로컬 커밋. ★`git add -A` 금지(dry-run상 ' 2' 6종 staging됨) → **명시적 pathspec 열거 + `git add -u`**, 커밋 후 `git status --porcelain | grep ' 2'`가 여전히 `??`인지 assertion.
2. **iCloud 복제원 정지(오너 택1)**: ①폴더 이전 `~/dev` ②sync 해제 ③.nosync+target 분리. ★**sibling `EZERagent-arp`도 iCloud**(guard.sh 생성원)라 함께 처리.
3. **swap 루프 봉인**: `deploy_*_swap.py` 비활성(게이트 스크립트 도입 전).
4. **split-brain 정리**: zombie `74628` **SIGKILL**(90238 생존). ★kill 전 결정론 검증(start-time==sock mtime + lock-holder=90238 live·74628=orphan), **SIGTERM 금지**(cleanup이 산 소켓 unlink), post-kill `EZERagent ping`/`list` 필수.
5. **충돌사본 정리**: ' 2' 6종 rm(보전 후·md5 identical 확인·오너 승인·guard 우회).
6. **바이너리 정합**: boot extract_bin 수정 반영 EZERagentd 재빌드. ★**build dir iCloud-free xattr 게이트**(아니면 차단)·step4 이후 barrier.
7. **노드 기동 결함**: folder-trust 수락 + codex symlink 정리 → `EZERagent boot`.
8. **영구 재발방지(별도 라운드)**: 게이트 배포 스크립트(codesign+스모크+원자 동시교체+롤백)·launchd 감독·inode 가드·trust 다중앵커·busy_timeout.

### 14.4 오너 결정 필요 (비가역)
- iCloud 처리 방식(폴더이전/sync해제/.nosync) — EZERagent-arp 포함 범위.
- 충돌사본·소켓 정리 rm 승인 경로(guard hook이 'rm' substring 광범위 차단).
- push 여부(8커밋 — 본 복구 범위 밖·별도).

### 14.5 담당
구현=**worker 위임**. split-brain 정리·노드 부트스트랩만 통신단절 시 master 직접. 비가역(rm·폴더이전·push)은 오너 확인. 검증 verdict=NEEDS_REVISION→위 ★corrections 전부 반영 완료.
