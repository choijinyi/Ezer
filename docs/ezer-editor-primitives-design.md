# ezer 편집기 프리미티브 — 설계 명세 (W2-5 · 지금-설계·빌드-나중)

> OpenCut 연구(_research/OpenCut_박사급_연구보고서.md) Wave 2 산출. ezer가 타임라인 편집기를
> 키울 때 필요한 undo/커맨드·키바인딩 프리미티브를 **지금 명세**해 둔다(OpenMontage가 timeline-state를
> 미리 설계했듯) — 나중에 retrofit하지 않고 깨끗이 착륙시키기 위함. 본 문서는 *설계*이며 구현이 아니다.
> 근거: OpenCut classic `apps/web/src/commands/`·`core/managers/commands.ts`·`stores/keybindings-store.ts`.

## 1. Command 트레이트 — 스냅샷-교체 undo (T7-P3)

OpenCut의 결론(검증): 편집은 **diff-and-patch가 아니라 snapshot-and-replace**여야 한다 —
`undo()`가 저장된 pre-edit 상태를 통째로 복원하면 절대 드리프트하지 않는다. 구조적 공유로 저렴.

이미 `bin/ezer_timeline.py`(W1-1)가 *프로세스 밖 에이전트 편집*에 이 패턴을 구현했다(history.jsonl
스냅샷). 인-프로세스 Rust 편집기가 생기면 동형 트레이트로:

```rust
// 설계(미구현) — ezer-agent 크레이트의 leaf 모듈(primitives-vs-domains: socket/pty 무의존)
trait Command {
    fn execute(&mut self, state: &mut Timeline) -> Result<(), EditError>;
    fn undo(&mut self, state: &mut Timeline);   // 저장된 pre-snapshot 복원(스냅샷-교체)
}
struct BatchCommand(Vec<Box<dyn Command>>);     // LIFO 역순 undo(OpenCut batch-command.ts:21-25)
struct CommandManager {                          // 단일 실행 깔때기 — redo 스택·리액터 소유
    history: Vec<Box<dyn Command>>,
    redo: Vec<Box<dyn Command>>,
}
```

- **단일 깔때기**(OpenCut `commands.ts:21-45`): 모든 편집이 `CommandManager.execute()`를 지난다 —
  redo 스택 클리어·선택 패치·빈 트랙 GC·ripple 같은 가로지르는 관심사를 한 곳에서 처리.
- **preview-overlay/commit**(OpenCut `timeline-manager.ts:706-760`): 드래그/연속 미세편집을 1 undo
  단위로 합친다 — 에이전트가 여러 작은 편집을 하나로 collapse할 때 동형으로 필요.
- **ID-반환 핸들**: 커맨드 생성 시 UUID를 발급해 호출자가 새 element id를 동기 획득.
- **시간은 정수 틱**(W0-1 `MediaTime` 발상): `Timeline`의 in/out은 i64 틱(부동소수 금지).
- 경계: 인-프로세스 편집기는 미존재 — 이 트레이트는 *그 편집기가 생길 때* 착륙. 그 전까지
  에이전트 편집은 `ezer_timeline.py`(IR+history.jsonl)가 담당(병렬 모델 신설 금지).

## 2. 키바인딩 리졸버 규율 (T7-P4)

OpenCut `keybindings-store.ts:209-274`가 박제한 하드-원 정확성(Tauri 셸 편집기에 그대로 차용):

- **물리 `ev.code` 우선**(비-QWERTY 레이아웃 안정성) — 논리 키가 아니라 물리 위치로 바인딩.
- **macOS ⌘ → "ctrl" 정규화** — 한 바인딩이 크로스플랫폼.
- **타입 가능 요소 안 단축키 억제** + Shift-in-text-field 특례.
- **overlayDepth 카운터**(불리언 아님) — 중첩 모달이 단축키를 올바르게 무력화.
- **커맨드 팔레트**(OpenCut이 *안 만든* 도약): `ezer actions --json`(W2-1)을 인덱스로 팔레트를 얹어
  ezer의 최대 발견성 통증(에이전트·사람이 명령 표면을 모름)을 해소. OpenCut은 cmdk 선언만·사용 0.

## 3. ezer↔ezerd ABI 단일-옵션-구조체 불변식 (W2-6 · T1-P3)

OpenCut `#[export]` 매크로(`bridge/src/bridge.rs:24-39`)의 규율을 우리 소켓 경계에 일반화:

> **불변식**: 모든 `ezer`↔`ezerd` 소켓 메시지는 *단일 명명 JSON 객체*이며(위치 인자 금지), 모든
> 필드 추가는 `#[serde(default)]`로 한다 — additive-safe, 파라미터 추가가 호출부를 깨지 않는다.

- 현 상태: 52개 verb 전부 이미 단일 객체 params(handlers.rs `param_*` 헬퍼·배열 params 없음) →
  **이미 충족**. 프로토콜 churn 불요.
- 적용 시점(외과적): verb의 params가 비자명하게 커질 때만, ad-hoc `param_str` 룩업을 per-verb
  `#[derive(Deserialize)] struct <Verb>Params { #[serde(default)] … }`로 교체(컴파일 체크 회복) +
  serde 라운드트립 테스트로 wire 형태 박제(`bridge.rs:89-94` 발상). 신규 verb·변경 시에만.
- 이는 `REVIEWER_VERDICT_CONTRACT.md`가 리뷰어 verdict에 적용한 타입 계약을 *모든 코어↔셸 호출*로
  일반화한 것(동일 원리·다른 층위).

## 3.1 판별값 enum codegen 계약 — 미래 착륙 조건 (T1-1 · penpot ToJs 클린룸)

penpot render-wasm는 Rust WASM ↔ CLJS가 ~30개 enum을 **독립 직렬화**하며 손동기 드리프트가 발생해,
`#[repr(u8)]` 판별값 enum을 Rust 단일정의 → TS/JSON으로 **build.rs 코드젠**해 드리프트를 소멸시킨다
(`render-wasm/macros/src/lib.rs:167-183 generate_js_for_enum`의 계약: kebab 정규화 + 판별값 정수강제
+ 판별값 정렬 직렬화). 이 *계약/패턴*만 개념으로 차용한다(코드복사 0 · MPL-2.0 파일전염 회피).

★STEP 2 실측: ezer에는 이 codegen이 풀 문제 자체가 없다. **경계를 건너는 판별값 enum = 0개.**

| 측정 | 명령/위치 | 결과 |
|---|---|---|
| `#[repr(u8/u16/u32/i32)]` enum 전수 | `grep -rn "repr(u" src/` | **0건** |
| ezer↔ezerd 이벤트 wire 형태 | `src/bin/ezerd/events.rs` | 문자열-키 JSON (`"type":"event"`, 문자열 `name`/`category`) |
| 유일 TS 소비자 | `ui/src/main.ts:318-319` | `r.verdict`를 **문자열**로 읽어 패스스루 — 판별값 정수 디코드 없음 |

ezer wire는 전부 문자열-키 JSON이라 정수 판별값 드리프트 표면이 0. penpot이 codegen으로 푸는 다중-enum
손동기 드리프트가 **ezer에 존재하지 않으므로**, build.rs enum→TS/JSON 코드젠은 *짓지 않는다*(추측 기반
추상화 금지 — directive 2). 대신 미래 착륙 조건을 불변식으로 박제한다:

> **불변식 INV-ABI-ENUM**: ezer↔ezerd 경계를 건너는 enum이 `#[repr(u8)]` 정수 판별값을 지니고 TS
> 소비자가 그 정수를 디코드하게 되는 순간(현재 0개), `build.rs`가 그 enum 단일정의를
> `OUT_DIR/ezer_shared.{ts,json}`으로 코드젠한다 — kebab 정규화 + 판별값 정수강제 + 판별값 정렬
> 직렬화(penpot ToJs 계약의 클린룸 등가). **그 전까지: 미빌드.**

- **buildsOn(신규 메커니즘 도입 0)**: codegen 착륙 시 `build.rs:28-47`의 *기존* 디렉터리스캔→`OUT_DIR`
  코드젠 패턴(`pack_skills.rs` 생성, `fs::write` 단발)을 그대로 재사용한다.
- **truncate-once 차이**: penpot은 per-derive-macro 확장마다 append하며 `INIT: sync::Once`로 첫 호출만
  truncate한다. ezer `build.rs`는 `main` **1회 실행**이라 `sync::Once` 불요(`fs::write` 단발로 충분).
- **append-only 규율**(판별값 결번보존·재배열금지)은 codegen 착륙과 *동시* 도입한다(미리 짓지 않음).
- **verdict는 이 codegen 대상이 아니다**: verdict(ACCEPT|REVISE|BLOCK|ESCALATE)는 판별값 없는 **문자열
  집합**이고 penpot `parse_discriminant_value`(`lib.rs:157-164`)가 정수 판별값을 하드 요구하므로 메커니즘상
  codegen 불가 — verdict 4-리터럴 드리프트는 별도 문자열-동치 preflight **C43.verdict-literals**가 차단한다
  (`ezer_verdict.py:32 VERDICT_ENUM` ↔ `REVIEWER_DIRECTIVE.md` 계약 텍스트).

## 4. primitives-vs-domains 리프 규칙 — ★owner 승인·적용됨 (W2-6 · T1-P4 · 2026-06-24)

OpenCut `notes/primitives-vs-domains.md`의 판정 규칙을 워커 디렉티브에 흡수. 디렉티브 변경은 owner
토큰 게이트(autopilot denylist)였고, **오너이 "1을 시행한다"로 승인하여 적용 완료** —
`ezer-pack/directives/WORKER_DIRECTIVE.md §5 외과적 변경`에 1줄 추가(빌드·배포로 서명 팩 반영).

- 적용 문구(WORKER_DIRECTIVE §5): *"새 공유 로직은 ezer 도메인 개념
  (surface·agent·governance·pack)을 명명하지 않고 상위 의존(socket/pty/governance/pack)이 없으면
  leaf(primitive)다 — domain 모듈 안이 아니라 leaf로 배치하라. accretion은 deliberate, bulk-move 금지."*
- 착륙 조건: 실제 공유 모듈(예: 인-프로세스 `time` 코어·broll 배치 수학)이 *계획될 때* 적용 —
  현재 ezer-agent은 단일 크레이트라 가설적 냄새를 지키는 규칙(과조기 도입 금지).
- 근거(verbatim 검증): `:13-16`(primitive 판정), `:30-34`("의존성 그래프가 거짓말한다"), `:42-44`
  (deliberate 이동). 단일 소비자 과장·미검증 인용은 제거(적대검증 반영).

## 상태
- W2-5(본 §1·§2): **설계 완료·빌드 보류**(인-프로세스 편집기 착수 시 구현). 에이전트 편집은 W1-1로 충족 중.
- W2-6 §3 ABI: 이미 충족·다음 변경 시 점진 적용(코드 변경 없음).
- W2-6 §4 primitives-vs-domains: **owner 승인·적용 완료**(2026-06-24 오너 승인 → WORKER_DIRECTIVE §5 1줄 추가·배포).
