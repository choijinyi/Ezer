# RSI 학습 루프 — 설계 스펙 (Phase 0)

> 오너 2026-06-18 지시: "재귀적 자기개선을 ezer-agent 기본 기능으로 탑재."
> 핵심 = 워커가 **인터넷 검색으로 직전보다 나은 방법론을 스스로 찾고 배운다**.
> 이 문서는 구현(Phase 2~6)의 단일 청사진. 리뷰어(gemini·codex) 라운드(Phase 1)의 검토 대상.

---

## 0. 범위

오너 풀 탑재 승인(2026-06-18):
- 5단계 학습 루프를 결정론 엔진(`ezer_learn.py`)으로 박제
- 사람 명령(`ezer learn`) + master 자율추천(3트리거→사람 승인) **이중 트리거**
- Control Center '학습' 탭으로 가시화

**재사용(이미 제품에 있음)**: ③평가=`ezer_rsi.py`(producer≠evaluator·retention·rollback) · ④저장=`ezer_memory.py`(원자적 add·증류 게이트)
**신규**: ①검색 ②추출 ⑤harness화 + 루프 폐쇄 + 자율추천 + 빠진 강제자 `rsi-gate.sh`

---

## 1. 오너 5단계 — 조작적 정의

| 단계 | 정의 | 산출(구조화) |
|---|---|---|
| ① 검색·탐색 | 인터넷 검색으로 직전보다 나은 방법론 후보 수집. 학습지식 단독 금지. | `candidates[]` = {source_url, claim, retrieved_at} (citation 필수) |
| ② 패턴·철학 추출 | 후보에서 재사용 가능한 패턴·철학 추출 | `pattern` = {domain, condition, action, rationale, evidence_ref} |
| ③ 객관·근거 평가 | 직전(baseline) 대비 **우리 실측 eval에서** 더 나은지 판정 | `verdict` = improved\|regressed\|flat (ezer_rsi 주입) |
| ④ 문서·지침 저장 | 통과 시에만 연관 memory/directive에 영속 | `ezer_memory add` 결과(원자적) |
| ⑤ skill/harness 제작·발전 | 배운 것을 쓰는 skill/harness 신설 또는 기존 발전 | `harness_ref` + retention 채택/rollback |

루프 폐쇄: ⑤에서 발전된 harness로 다음 라운드 ①~⑤ 재시도(매 라운드 baseline 갱신은 **locked ref 기준**, drift 차단).

---

## 2. 4안전장치 — 코드 배선

| 안전장치 | 함정(막는 것) | 배선 |
|---|---|---|
| **평가자 분리** | producer=evaluator → 자기채점 reward-hack | ③ score 산출자 = master locked-eval launcher(워커≠평가자). ezer_rsi는 주입만 |
| **출처+실측 게이트** | 검색 환각·"최신=더 나음" 거짓 | ①은 citation 필수. "더 낫다"는 외부 주장 아닌 **§9 benchmark eval 실측 우위**로만 확정 |
| **baseline+rollback** | 발전이 개악(회귀)·skill bloat | ⑤는 retention gate(이겨야 채택)·실패 시 `ezer_rsi rollback`(현 HEAD를 rsi-abandoned 브랜치 박제 후 reset) |
| **budget/denylist** | 무한 학습루프·헌법 임의변경 | `rsi-gate.sh`(§5) + "자율추천은 propose까지, ④저장·⑤채택은 사람 승인" |

**R1 리뷰어 보강(2026-06-18 gemini·codex)** — 4안전장치에 다음 3축 추가:

| 안전장치 | 함정(막는 것) | 배선 |
|---|---|---|
| **실행 안전** | evaluate가 후보 코드 실행 시 샌드박스 탈옥(gemini 3.3) · 검색콘텐츠 프롬프트 인젝션(gemini 3.2) | evaluate는 **격리 실행**(별도 프로세스·네트워크 차단·제한 권한·임시 cwd). 검색 콘텐츠는 **데이터로만**(명령 해석 금지), ②추출은 구조화 스키마 강제. ※완전 커널/HW 샌드박스는 위협모델 범위 밖(신뢰된 워커 산출 평가) |
| **메모리 무결성** | store 누적으로 의미론적 오염=나쁜 방법론 참값화(gemini 3.4) | store는 retention 품질 게이트 통과분만 **confirmed**, 나머지 **provisional**(참조 우선순위 낮춤). 주기 `ezer_memory audit`로 오염 후보 격리 |
| **복구수단 불변** | `.git`/refs/rsi·롤백스크립트 직접 변조로 복구 마비(gemini 3.5) | `rsi-gate.sh` invariant를 **복구수단 보호**로 확장: 루프가 refs/rsi/*·rollback 스크립트·.git 메타를 수정하면 무조건 DENY |

**R2 리뷰어 보강(2026-06-18 gemini 독립검증 REVISE → master 수용)** — 이종 모델이 codex 사각(common-mode 회피 실증)에서 발견한 봉쇄망 붕괴 위협 6축:

| 안전장치 | 함정(막는 것) | 배선 |
|---|---|---|
| **오프라인 격리 대안** | net 차단 격리(§2 실행안전) vs 이종 모델 검증(§6 공통모드) 구조적 모순=오프라인 데드락(gemini 1) | ★근본: 격리 대상은 '후보 코드 실행'이지 '검증 LLM 호출'이 아니다 — net 가능 환경은 후보 코드만 샌드박스(net 차단)·이종 모델 호출은 격리 밖(모순 비성립). 폐쇄망 차선(외부 API 불가): 동일 로컬 모델 + 시스템 프롬프트 격리 + 랜덤 시드 편차 + 상이 양자화(Q4_K_M↔Q8_0) 분기로 추론 다변화 |
| **스냅샷 해시 바인딩** | 생산자가 로컬 스냅샷 위조(쿼트+문맥 동반)로 결정론 substring·entailment 우회(gemini 2) | WebFetch 완료 즉시 원문 SHA-256 ledger 기록·읽기전용 격리폴더·검증 전 해시 무결성 검사 강제(불일치=hard fail) |
| **canonical 결정론화** | whitelist 정적=신규 프레임워크 학습 불가 / 동적=가짜 권위 우회(gemini 3) | 2단계: whitelist(공식 도메인·표준화기구·1차 문서) 우선 통과 + whitelist 밖=동적 후보로 강등(confidence:low·provisional만) |
| **고위험 조작적 정의** | "고위험=인간 서명"의 고위험 메트릭 미정의→승인 피로 또는 저위험 위장 백도어(gemini 4) | ①파일 쓰기/삭제 I/O ②네트워크 소켓·외부 쉘 스킬 ③soul/directive 변조=무조건 고위험·인간 서명. 그 외=저위험(독립 팩트체커 서명) |
| **판정 JSON 스키마** | 자연어 평가서→pass/fail 파싱 한계·파싱 실패 데드락(gemini 논쟁1) | 이종 모델 응답=`{"verdict":"PASS"\|"FAIL","reason":"..."}` structured output 강제·파싱 실패=fail-safe FAIL |
| **검증 오버헤드 제어** | 매 검증 2+ 이종 모델 호출 비용/latency 급증(gemini 논쟁2) | 5차원 게이트 단계별 단락: 결정론(기계) 먼저→실패 시 즉시 중단(고비용 이종 모델 생략)→통과분만 의미·논리 라우팅. '부분통과=전체중단' 가드는 불변 |

**R3 리뷰어 보강(2026-06-18 codex 재확인 REVISE → master 수용)** — gemini ACCEPT 사각에서 발견한 2축:

| 안전장치 | 함정(막는 것) | 배선 |
|---|---|---|
| **fallback confirmed 차단** | 폐쇄망 차선(로컬모델 시드/양자화 분기)이 '다른 모델 패밀리' 원칙을 약화하나 confirmed 차단 조건 부재(codex 1) | fallback 모드(단일 모델 변형) 검증물은 **provisional만·confirmed 승격 불가**(진짜 이종 모델 패밀리 가용 시 5차원 full recheck로만 승격) |
| **고위험 4번째 축** | 고위험 정의가 evaluator/benchmark/ledger/rsi-gate 변경을 빠뜨려 저위험 위장 경로 잔존(codex 2) | 고위험 ④=**검증·게이트 인프라 변경**(evaluator·benchmark·ledger·rsi-gate·locked-eval)=무조건 인간 서명 |

---

## 3. 자율추천 3트리거 (오너 선택: 막힘·종료게이트·ceiling)

| 트리거 | 신호원 | 발동 |
|---|---|---|
| 막힘·반복실패 | `governance.rs` watchdog / 워커 동일문제 N회 실패 | `ezer_learn propose --reason stuck` |
| 작업 종료 게이트 | `ezer_orchestra` slow 종료 게이트에 학습점검 1단 추가 | `propose --reason gate` |
| eval ceiling | `ezer_rsi progress` verdict=flat N연속 | `propose --reason ceiling` |

`propose`는 후보+근거만 만들어 **pending feed approval item**으로 등록(자율추천만). 사람이 **`ezer feed reply <id> allow`**(또는 feed 패널)로 승인할 때만 ①~⑤ 착수. 거부=무실행. manual(`ezer learn`)은 사람 직접 명령이라 즉시 착수(게이트 없음). (오너 구상의 "자율 추천→사람 승인"과 정합)

---

## 4. `ezer_learn.py` — 7서브명령 계약

`ezer-pack/bin/ezer_learn.py`. 기존 도구에 위임(중복 구현 금지): ③→ezer_rsi, ④→ezer_memory.

```
propose  --reason <stuck|gate|ceiling> --topic <S> [--json]
    트리거 신호를 받아 학습 후보·근거를 산출 → pending feed approval item 등록(ezer feed reply <id> allow로 승인).
    승인 전엔 검색·저장·채택 일절 안 함(추천만). 출력: {topic, reason, evidence[], feed_id}

search   --topic <S> [--k N]              # ① — WebSearch 게이트. citation 없는 결과 거부.
    출력: candidates[] = {source_url, claim, retrieved_at}. 출처0이면 hard fail(학습지식 단독 금지).

extract  --from <candidates.json>          # ② — 패턴·철학 구조화
    출력: pattern = {domain, condition, action, rationale, evidence_ref}. evidence_ref 없으면 거부.

evaluate --round <id> --pattern <p.json> --score F   # ③ — ezer_rsi에 위임
    score는 §9 locked-eval launcher가 산출(이 명령은 받기만). 내부적으로:
      ezer_rsi checkpoint(첫 회 baseline) / progress(비교) 호출.
    출력: verdict. ★score 자체생성 금지(ezer_rsi 불변 계승).

store    --round <id> --pattern <p.json> --type <feedback|reference|project>   # ④
    verdict=improved AND 사람승인 플래그일 때만 ezer_memory add 위임. 아니면 거부.

harness  --round <id> --pattern <p.json> [--evolve <skill_name>]   # ⑤
    skill/harness 신설 또는 기존 발전. retention: 새 harness가 baseline eval 못 이기면
      ezer_rsi rollback(dry-run 먼저). 채택은 사람 승인.

status   [--json]                          # UI 데이터원 — 라운드·verdict·채택/rollback·발견 누적
```

상태 파일: `_round/learn/state.json` + `ledger.jsonl` (ezer_rsi 패턴 답습 — os.replace 원자교체).

---

## 5. `rsi-gate.sh` — 빠진 강제자

`ezer-pack/bin/rsi-gate.sh`. eval-driven 스킬이 참조하나 미구현이던 Tier-2 강제자.

- **불변 차단**: 한 학습 루프가 자신의 evaluator / rollback / denylist / locked-eval을 **같은 루프에서 수정** → 무조건 DENY (invariant-3)
- **budget cap**: 라운드당 토큰·시간 상한 초과 → 중단·보고
- **denylist preflight**: ④저장이 soul/CLAUDE/directive를 건드리면 → 사람 승인 없이는 DENY(헌법 변경)
- 종료코드: 0=allow, 1=deny(사유 출력)

---

## 6. RPC/CLI 계약

**RPC** (`src/bin/ezerd/handlers.rs` dispatch에 분기 추가):
- `learn.propose` {reason, topic} → ezer_learn propose 결과
- `learn.status` → ezer_learn status (UI 폴링용)
- `learn.history` {round} → ledger 조회

**CLI** (`src/bin/ezer.rs` Command enum):
- `ezer learn <topic>` — 사람 직접 명령. RPC learn.propose(reason=manual 우회=즉시착수) 또는 워커에 학습 티켓 디스패치.
- `ezer learn --status` — 현재 학습 라운드 상태.

자율추천 배선: 3트리거가 pending feed approval item을 등록 → 사람이 `ezer feed reply <id> allow`(또는 feed 패널)로 승인(기존 feed 패널 재사용·non-wait).

---

## 7. UI — Control Center '학습' 탭

`ui/src/main.ts` ccTab에 `learn` 추가 + `control.*` 패턴으로 `learn.status` 폴링.
- 학습 라운드 타임라인(topic·reason·verdict)
- 채택/rollback 리본(retention 결과)
- **발견 누적**(오너 Discovery 차원): 새 기능·관점·지식 카운터
- 자율추천 대기 배지(feed pending → 승인 버튼)

`src-tauri/src/main.rs`에 `#[tauri::command] learn_status` 브릿지. `ui/src/style.css` 탭 스타일.

---

## 8. directive — `RSI_LEARNING_DIRECTIVE.md` (Phase 2, 🔒오너 승인)

5번째 directive. `ezer-pack/directives/` + `pack.rs` PACK 배열 + role 매핑(master·worker 주입).
내용: §1 5단계 조작적 정의 · §2 4안전장치 · §3 자율추천 3트리거 · §4 "자율추천은 추천까지, 저장·채택은 사람 승인" 경계 · §5 도구 사용법(ezer_learn 7명령).

---

## 9. ★설계 난제 — producer≠evaluator로 "방법론"을 어떻게 평가하나

ezer_rsi는 score를 주입만 받는다(자체생성 금지). 그럼 "더 나은 방법론인가"의 score는 누가/어떻게?

**해결**: "방법론이 낫다"를 추상적으로 주장하지 않는다 — **benchmark task에 적용한 산출의 실측 우위**로 환원한다.
1. 학습 대상 방법론마다 **고정 benchmark task**(우리 실제 작업의 대표 사례)와 **locked eval**(성공기준) 지정.
2. baseline 방법론 적용 산출 → eval score `C_old`. 후보 방법론 적용 산출 → `C_new`.
3. score 산출자 = master의 **locked-eval launcher**(검색·추출한 워커가 아님 = 평가자 분리). ezer_rsi에 주입.
4. 채택 keep-rule(eval-driven 스킬 계승): `C_new ≥ C_old + g·(1−C_old)` (예 g=0.30). 미달=rollback.
5. ceiling(C_new가 더 안 오름) → 점수향상 주장 중단, **eval 진화**(real-headroom metric 추가)로 전환.

→ "검색으로 찾은 더 나은 방법론"이 **우리 작업에서 실측으로 더 나아야만** 학습으로 인정. 출처 게이트와 평가자 분리를 동시 충족.

**R1 리뷰어 라운드 보강(2026-06-18 codex)** — §9의 결정적 빈틈(평가세트 거버넌스) 해결:
1. **benchmark pre-registration**: benchmark suite와 success criteria를 **검색 전(최소 추출 전) freeze**하고 ledger에 기록. producer가 benchmark를 사후에 고르거나 바꿀 수 없다(reward-hack 차단).
2. **held-out evaluation**: 공개 benchmark 외 **hidden/holdout task**를 두어 특정 task 과적합 차단.
3. **출처 품질 게이트**: citation 수가 아니라 primary source 우선·**독립 출처 2개+**·recency/replication/contradiction check.

**§11 추상 학습 객관화 — 해결(codex 제안 수용)**: 철학·관점·교차도메인 통찰은 pattern으로 바로 저장하지 않고 **`behavioral_claim`(관찰 가능 행동)으로 변환**한다.
- 예: "더 비판적으로 리뷰한다"(측정 불가) → "리뷰 시 failure mode 3개+를 독립 근거·반증 가능 조건과 함께 제시한다"(관찰 가능).
- 변환된 claim을 **과거 작업 샘플·교차도메인 샘플·역사례 샘플**에서 **blind evaluator**가 baseline 대비 결함발견률·false-positive율·재작업감소로 비교 → §9 benchmark 환원과 동일 경로로 객관화.

---

## 10. Phase별 검증·게이트

| Phase | 검증 | 게이트 |
|---|---|---|
| 0 스펙 | 5단계·4안전장치·3트리거·난제(§9) 전부 명문 | 가역 |
| 1 리뷰어 | gemini·codex verdict=ACCEPT(REVIEWER_VERDICT_CONTRACT) | RSI 규약 |
| 2 directive | 5단계 규약 명문 | 🔒 헌법=오너 승인 |
| 3 엔진 | `docs/learn_e2e.py` 통과(propose→search→extract→evaluate→store→harness→rollback) | 로컬 |
| 4 RPC/CLI | learn.* 응답·`ezer learn` 동작·3트리거 발동 실측 | 로컬 |
| 5 UI | 탭 렌더·status 폴링·승인 배지 | 로컬 |
| 6 배포 | cargo·E2E·pack install·앱 재실행 가시 | 🔒 오너 확인 |

---

## 11. 미해결(리뷰어·오너 결정 대기)

- ✅ **§9/§11 추상 학습 객관화 — R1 해결**: behavioral_claim 변환 + blind evaluator(§9).
- ✅ **benchmark 거버넌스 — R1 해결**: pre-registration·freeze·held-out(§9).
- ✅ **오프라인 격리 데드락 — R2 해결**: 격리 대상=후보 코드 실행(검증 LLM 호출 아님)·폐쇄망 차선=로컬모델 시드/양자화 분기(§2·§12).
- ✅ **스냅샷 위변조 — R2 해결**: SHA-256 ledger 잠금·읽기전용 격리·검증 전 무결성 검사(§2·§12).
- ✅ **canonical 결정론·고위험 조작적 정의·논리판정 JSON 스키마 — R2 해결**(§2·§12).
- benchmark/holdout 라이브러리 + pre-registration ledger 위치(`_round/learn/benchmarks/`?) — 구현 시 확정.
- 자율추천 빈도 상한(막힘 트리거가 과민하면 승인 피로) — budget cap과 연동.
- evaluate 격리 실행의 구체 메커니즘(별도 프로세스 vs 컨테이너) — Phase 3 구현 시 결정.

---

## 12. 할루시네이션 원천 봉쇄장치 (오너 2026-06-18 명령 · directive §6 대응)

**존재 이유**: 할루시네이션 자료로 학습하면 시스템 전체가 붕괴한다. RSI는 학습물이 다음 라운드 baseline·harness로 **재귀 증폭**되므로, 환각 1건이 누적·증폭되어 전 시스템을 무너뜨린다(자기오염 붕괴). 봉쇄 = 입구 전면 차단(**부분 통과 = 전체 중단**).

**5차원 검증 (모두 통과 필수 — 오너 명령 · R3 보강)**:

| 차원 | 검증 | 검증 방식 | 봉쇄 대상 |
|---|---|---|---|
| **출처** | fetch URL+스냅샷(**SHA-256 ledger 잠금**)·독립 2개+·**공식 원천성(canonical 2단계: whitelist 우선+밖은 provisional 강등)** | 결정론(호출 로그·해시 무결성)+원천성 규칙 | "검색했다 치고"·가짜 권위 출처·스냅샷 위변조 |
| **사실검증** | 교차 출처·contradiction·1차 자료 추적 | 독립 모델 대조·단일출처 confirmed 불가 | 그럴듯한 거짓 |
| **근거자료** | **해시 잠금 스냅샷**에서 literal quote + **문맥 window entailment** 대조 | 결정론(해시검사→substring)+entailment | out-of-context fabrication·스냅샷 위조 |
| **논리평가** | 형식 오류 / **비형식 오류** | 결정론 체크리스트 / **독립 모델 adversarial(JSON `{verdict,reason}` 강제·파싱실패=FAIL·ledger 박제)** | 논리적 환각 |
| **내용우수성** | 직전 대비 실측 우위(§9) | eval artifact 해시 | 측정 없는 "더 나음" |

**집행 — 검증 계층 분리**: 기계검증=결정론(fetch로그·substring·해시) · 의미·논리=**생산자와 다른 모델 패밀리**(ezer=agy·codex) adversarial+ledger 박제(단일 모델 신뢰 금지) · **공통모드 차단**(팩트체커 다른 모델 패밀리+독립 source/query/tool) · 하나라도 미통과면 **학습 중단** · **confirmed 승격**=5차원 full recheck+새 스냅샷 해시+독립 팩트체커 서명+ledger(고위험 인간서명) · 약한 정박 confidence:low. ★**R2 보강(gemini)**: ①오프라인 데드락 해소=격리 대상은 후보 코드 실행이지 검증 LLM 호출 아님(net 환경=코드만 샌드박스·모델 호출은 격리 밖)·폐쇄망 차선=로컬모델 시드편차+양자화(Q4_K_M↔Q8_0) 분기 ②**고위험 조작적 정의**(무조건 인간서명)=파일 쓰기/삭제 I/O·네트워크소켓/외부쉘 스킬·soul/directive 변조 ③**오버헤드 제어**=결정론 게이트 선행 단락(실패 시 고비용 이종모델 생략·통과분만 라우팅·'부분통과=전체중단' 가드 불변). ★**R3 보강(codex)**: ④**fallback confirmed 차단**=폐쇄망 차선(단일 모델 변형)은 공통모드 방어 약화이므로 fallback 검증물은 provisional만·confirmed 승격 불가 ⑤**고위험 4번째 축**=evaluator·benchmark·ledger·rsi-gate·locked-eval 등 검증·게이트 인프라 변경=무조건 인간서명(저위험 위장 백도어 차단).

**배선**: `ezer_learn` 각 단계 5차원 게이트(실패=hard fail). `citation-gate` 확장 + 결정론 스크립트(fetch-log·quote-substring·entailment·artifact-hash) + **의미·논리는 독립 모델 패밀리 라우팅**(agy/codex).

**R3→R4 반영 완료**: canonical 원천성 · 문맥 entailment · 논리 하이브리드(결정론+독립모델) · 공통모드 모델 다양성 · 승격 프로토콜.

**R2 라운드 반영 완료(2026-06-18 gemini REVISE→master 수용·producer worker-3)**: 오프라인 격리 대안(후보 코드만 샌드박스·시드/양자화 차선) · 스냅샷 SHA-256 해시 바인딩 · canonical 2단계 결정론화 · 고위험 조작적 정의 · 비형식오류 JSON 스키마·fail-safe FAIL · 팩트체커 오버헤드 단락 제어.

**R3 라운드 반영 완료(2026-06-18 codex 재확인 REVISE→master 수용·producer worker-3)**: fallback 모드 confirmed 승격 차단(provisional만) · 고위험 4번째 축(evaluator·benchmark·ledger·rsi-gate·locked-eval 등 검증·게이트 인프라 변경=인간서명). → gemini·codex 재검증 라운드 대기.
