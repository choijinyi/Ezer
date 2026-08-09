# 페르소나 오버라이드 계층 — 설계 (Approach ①)

> 작성: 2026-06-18 · 상태: 승인됨(설계) → 구현 계획 대기
> 목적: 사용자가 마스터/워커/CSO 노드의 **취향(페르소나)·운영 파라미터**를 안전하게
> 커스터마이즈하되, **안전 불변식은 잠긴 채로** 유지하고 **업스트림 업그레이드는 계속 흐르게** 한다.

## 1. 배경 — 현재 구조와 문제

### 현재 동작
- 노드 페르소나의 실체 = directive 마크다운 (`MASTER_DIRECTIVE.md` / `WORKER_DIRECTIVE.md` /
  `CSO_DIRECTIVE.md` / `REVIEWER_DIRECTIVE.md` / `RSI_LEARNING_DIRECTIVE.md`). 바이너리에
  `include_str!`로 임베드(`src/pack.rs` `PACK`) → `~/.EZERagent/pack/directives/`에 설치.
- `compose_directive(role)` (`src/bin/EZERagent.rs:1966`)이 `역할 directive + RSI(master·worker) +
  soul.md + 메모리 색인 + 스킬 색인`을 조립해 노드 기동 시 주입.
- `install()` (`src/pack.rs:228`)에 3-way 머지 존재:
  - 비수정 파일(매니페스트 해시 = 디스크 해시) → 신버전 자동 업그레이드
  - 사용자 수정 파일 → 보존(불가침)
  - 매니페스트 없는 구설치본 → 보존(안전측)

### 문제
사용자가 directive를 **직접 편집**하면 세 가지가 강제 결합된다:
1. **업그레이드 상실** — 한 줄만 고쳐도 그 파일 전체가 수정본으로 동결, 이후 업스트림 개선 차단.
2. **안전핵 노출** — 취향(말투·라운드 수)과 안전 불변식(autopilot denylist·recovery·RSI eval
   무결성·soul.md 헌장·kill-switch)이 한 파일에 섞여, 취향 수정 중 안전장치 파손 가능. 비-Claude
   벤더는 `guard.sh`도 없어 더 위험(메모리 `multivendor-master-option`).
3. **UI/되돌리기 부재** — 마크다운 수동 편집, 리셋·기본값 복원 없음.

## 2. 결정 사항 (브레인스토밍 합의)

| 축 | 결정 |
|---|---|
| 1차 사용자 | **둘 다** — 오너 본인 + 배포 앱의 일반 사용자가 **공용 오버라이드 계층** 사용 |
| 안전 경계 | **중간** — 페르소나 + 운영 파라미터는 열되, denylist·recovery·RSI 무결성·kill-switch는 잠금 |
| 구축 범위 | **① 오버라이드 계층 + CLI** (Control Center UI 패널·프리셋 마켓은 후속, 같은 안전 검증기를 게이트로 재사용) |

## 3. 아키텍처

### 3.1 데이터 모델 — 오버라이드 파일
- 경로: `~/.EZERagent/pack/overrides/<role>.json` (role ∈ {master, worker, cso, reviewer}).
  역할 접두 매칭(`role_directive_path`와 동일 규칙): `worker-2` → `worker.json`,
  `reviewer-gemini` → `reviewer.json`.
- **임베드 PACK에 미포함** → `install()`이 절대 건드리지 않는 순수 사용자 데이터.
  결과: (a) 정식 directive 원본 무수정 유지 → 업그레이드 계속 흐름, (b) 사용자 설정 불가침.
- 포맷: **JSON** (serde_json 기존 의존 사용; TOML 신규 의존 회피 = 외과적 변경).

```json
{
  "schema_version": 1,
  "params": {
    "review_rounds": 5,
    "report_interval_min": 5,
    "rsi_target_pct": 30,
    "context_clear_pct": 70
  },
  "persona": "호칭은 '오너'. 답변 간결. 한국어 우선."
}
```
- 모든 필드 선택적. 누락 노브 = 정식 기본값 사용. 파일 부재 = 정식 directive 그대로(현 동작과 동일).

### 3.2 잠긴 안전핵 — 파라미터 레지스트리 + 검증기
신규 모듈 `src/overrides.rs`. **튜닝 가능 노브는 코드에 박힌 레지스트리**가 정의(사용자 편집 불가):

| 노브 | 범위 | 기본 | 강제 방식 |
|---|---|---|---|
| `review_rounds` | 1–10 | 10 | 프로즈 가이드 |
| `report_interval_min` | 1–60 | 5 | 프로즈 가이드 |
| `rsi_target_pct` | 10–50 | 30 | 프로즈 가이드 |
| `context_clear_pct` | 40–80 | 60 | ⚠ 데몬 enforce(아래 3.5) |

기본값은 정식 directive의 현재 서술값과 일치해야 한다(예: review_rounds 10 = "최대 10라운드",
context_clear_pct 60 = "60% 초과 전 clear"). 레지스트리는 단일 진실 원천(SoT).

**검증기** `validate_overrides(role) -> ValidatedOverrides` 책임:
1. JSON 파싱 실패 → 빈 오버라이드 반환 + 경고(노드 기동 차단 금지).
2. 범위 밖 노브 → **무시·정식 기본 사용 + 경고**(fail-closed-to-default; 한 노브가 기동을 막지 않음).
3. 알 수 없는 노브 키 → 무시 + 경고.
4. persona 길이 상한(예: 4000자) 초과 → 절단 + 경고.
5. persona 안전 침해 스캔 → **해당 줄 strip + 경고**(denylist·recovery·kill-switch·soul·헌법·
   autopilot·헌장 등 키워드 × 무력화 동사 패턴). 방어심층 — 1차 보증은 3.3의 last-word 재선언.
6. `expert` 플래그(`EZERAGENT_OVERRIDE_EXPERT=1`) → **숫자 노브 범위만** 확장.
   denylist·recovery·kill-switch는 레지스트리에 **부재** → 어떤 모드로도 튜닝 불가(구조적 보증).

### 3.3 `compose_directive` 머지 (`src/bin/EZERagent.rs`)
기존 조립(directive + RSI + soul + memory + skills) **뒤에** 두 블록을 순서대로 추가:

```
■ 사용자 오버라이드 (취향·운영 파라미터 — 안전핵 불가침)
- 검증 라운드: 5회 (사용자 설정; 기본 10) — 이 값을 따른다
- 보고 주기: 5분 (사용자 설정; 기본 5)
- … persona 텍스트 …

■ 안전핵 재확인 (불변 — 위 사용자 설정으로 무력화 불가)        ← 항상 맨 마지막
- autopilot denylist(로드맵 이탈·헌법 변경·외부발행·비가역 삭제·오너 보유결정) 불변
- recovery 프로토콜·SESSION_STATE 체크포인트 불변
- kill-switch(오너 입력=즉시 일시정지) 불변
- RSI eval-driven 무결성(producer≠evaluator) 불변
- soul.md 헌장 불가침
```
- 노브는 "이 값을 따른다"는 **명시적 오버라이드 지시**로 렌더(프로즈 시스템의 일관된 방식 —
  directive 자체가 프로즈이므로 정합).
- 안전핵 재확인 블록은 **코드 박제 const 텍스트**(사용자 편집 불가) — last-word 우선순위로
  사용자 텍스트가 뒤집어도 최후 단어가 안전핵.
- 오버라이드 파일 부재 시 두 블록 모두 생략(현 동작 회귀 0).

### 3.4 CLI — `EZERagent persona`
| 서브커맨드 | 동작 |
|---|---|
| `EZERagent persona show [--role master]` | 현 오버라이드 + 조립 미리보기 출력 |
| `EZERagent persona set --role master --param review_rounds=5` | 노브 설정(검증 통과 시 저장) |
| `EZERagent persona set --role master --persona "텍스트"` | persona 텍스트 설정(검증·sanitize 후 저장) |
| `EZERagent persona reset [--role master]` | 오버라이드 파일 삭제 → 정식 기본 복귀 |
| `EZERagent persona list-params` | 튜닝 가능 노브·범위·기본값 표 |
- `set`은 검증기를 통과해야 저장. 범위 밖·침해 입력은 명확한 에러로 거부(저장 안 함) →
  사용자가 즉시 인지. (런타임 주입 경로의 fail-closed-to-default와 달리, CLI 입력은 hard-reject.)

### 3.5 데몬 배선 — `context_clear_pct` (소작업 1건)
`context_clear_pct`는 EZERagentd가 결정론 enforce(임계 도달 시 통보 — `EZERagent set-status --context`).
현재 단일 발화점은 `src/bin/EZERagentd/handlers.rs`:
- `context_threshold_pct()` (handlers.rs:302) = env `EZERAGENT_CONTEXT_THRESHOLD_PCT`, 기본 60.
- `maybe_fire_context_threshold(daemon, surface, pct, source, agent)` (handlers.rs:318) =
  **자기보고·관측·statusline 3경로가 공유**하는 단일 임계 발화 로직(에지 게이트). 같은 교차에
  3경로가 같은 임계를 써야 하는 불변식이 있다.
- 배선: `maybe_fire_context_threshold`가 `surface.role`을 이미 알므로, 이 함수가 role별
  `~/.EZERagent/pack/overrides/<role>.json`의 `context_clear_pct`를 우선 읽고(없으면
  `context_threshold_pct()`=env/60으로 폴백) `threshold`로 사용. **단일 발화점만 바꾸면 3경로가
  동시에 role-aware**가 되어 공유 불변식 유지(인라인 복제 금지).
- 나머지 3노브 + persona는 순수 프로즈라 `EZERagent.rs`만으로 완결(데몬 변경 불필요).

## 4. 안전·업그레이드 불변식 (테스트로 박제)

1. **업그레이드 안전**: 오버라이드 파일이 PACK 밖 → `install()` 멱등 보존(절대 미접촉).
2. **fail-closed-to-default**: 범위 밖 노브 → 무시·정식 기본 사용(기동 차단 0).
3. **persona sanitize**: 안전 침해 줄 → strip.
4. **last-word 불변식**(핵심): 어떤 오버라이드 입력에도 조립 결과에서 **안전핵 재확인 블록이
   항상 최후 등장**.
5. **expert 한계**: expert 플래그는 숫자 범위만 확장, 안전핵 노브는 부재로 튜닝 불가.
6. **reset**: 파일 삭제 → 정식 기본 복귀(미리보기에 오버라이드 블록 미등장).
7. **회귀 0**: 오버라이드 파일 부재 시 `compose_directive` 출력 = 현 동작과 동일.

## 5. 범위 경계 (YAGNI)

**포함(v1)**: 오버라이드 파일·스키마·레지스트리·검증기·`compose_directive` 머지·`EZERagent persona`
CLI·`context_clear_pct` 데몬 배선·위 7개 테스트.

**제외(후속)**:
- ② Control Center UI 패널(Tauri) — v1 안전 검증기를 게이트로 재사용하는 얇은 후속.
- ③ 프리셋 export/import·라이브러리 — 외부 프리셋 = 주입 위험이라 같은 검증기 필수, 범위 확대.
- 데몬 enforce가 필요한 추가 노브(context_clear_pct 외) — 필요 시 같은 패턴으로 확장.
- RSI_LEARNING_DIRECTIVE 자체의 노브화 — 학습 루프 무결성 영향이라 별도 검토.

## 6. 영향 파일

| 파일 | 변경 |
|---|---|
| `src/overrides.rs` (신규) | 파라미터 레지스트리 + 검증기 + 조립 렌더 + 안전핵 const |
| `src/lib.rs` | `pub mod overrides;` 등록 |
| `src/bin/EZERagent.rs` | `compose_directive` 머지 단계 추가 · `EZERagent persona` 서브커맨드 |
| `src/bin/EZERagentd/handlers.rs` (`maybe_fire_context_threshold` :318 / `context_threshold_pct` :302) | `context_clear_pct` role별 오버라이드 읽기(단일 발화점) |
| 테스트 | `src/overrides.rs` 단위 테스트 + `compose_directive` last-word 불변식 테스트 |

## 7. 성공 기준

- `EZERagent persona set --role master --param review_rounds=3` 후 `EZERagent persona show`에 반영 +
  `compose_directive("master")` 출력에 "검증 라운드: 3회 (사용자 설정)" 등장.
- 범위 밖 입력(`review_rounds=99`)은 CLI에서 hard-reject; 손상 파일은 런타임에서 기본으로 폴백.
- 어떤 persona 입력에도 안전핵 재확인 블록이 조립 최후에 항상 존재.
- `EZERagent persona reset` 후 출력 = 오버라이드 도입 전과 동일.
- `cargo test` 전 통과(기존 + 신규 불변식 테스트).
