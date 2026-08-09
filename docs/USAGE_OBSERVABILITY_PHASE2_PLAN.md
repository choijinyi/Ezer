# T5 사용량 관측 — Phase 2·3 구현 계획서 (재접속 진입점)

> 작성: 2026-06-13 (Phase 1 완료 직후) · 오너 지시 "재접속 시 이어갈 수 있게 저장"
> Phase 1 커밋 체인: b8b5aa7(본체) · e699105(boot 틸드) · ab726f1(env scrub)
> 이 문서 = 재접속 후 Phase 2 착수의 **단일 실행 명세**. SESSION_STATE.md가 이 문서를 가리킨다.

---

## 0. 재접속 첫 5분 (복원 절차)

```bash
# 1) 복원 진실 읽기
cat _round/RECOVERY.md            # 프로토콜
cat _round/SESSION_STATE.md       # 현재 위치·노드 상태·다음 액션
cat docs/USAGE_OBSERVABILITY_PHASE2_PLAN.md   # 이 문서 (Phase 2 명세)

# 2) 시스템 생존 확인
pgrep -x ezerd && ezer ping         # 데몬 살아있나
ezer status --json | python3 -m json.tool | grep -E 'role|usage|ctx_pct'  # 배지 가동 확인
python3 "$HOME/.ezer/pack/bin/ezer_preflight.py"   # READY 확인

# 3) Phase 1 회귀 검증 (깨지지 않았나)
cargo test 2>&1 | grep "test result"   # 178 passed 기대
# E2E (샌드박스): docs/usage_e2e.py 참조 — 아래 "회귀 자산" 절
```

**Phase 1이 현재 무엇을 하는가** (재접속 시 이미 가동 중):
- ezerd가 2초 틱으로 claude 트랜스크립트(`~/.claude*/projects/<munged>/<sess>.jsonl`)와
  codex rollout(`~/.codex/sessions/.../rollout-*.jsonl`)을 증분 tail → `Surface.observed_usage` 갱신.
- claude: context%만 (rate limit은 로컬 파일에 없음 → **Phase 2-A가 채운다**).
- codex: context% + rate limit 5h/7d (이미 완성).
- agy: 배지 없음 (로컬 평문에 토큰 없음 → **Phase 2-B가 채운다**).
- pane 헤더 배지 `CTX n% · 5h n% · 7d n%`, `org.status`/`surface.list`에 usage 노출.
- `context.threshold` 이벤트가 자기보고/관측 공유 게이트(`Surface.ctx_threshold_armed`)로 1회 발화.

---

## 1. Phase 2-A — claude rate limit (statusline 래퍼) 【승인됨】

### 1.1 왜 필요한가 (실측 근거)
claude의 5시간/주간 rate limit 잔량은 **로컬 파일 어디에도 없다**(find ~/.claude로 확인됨).
유일한 공식 무간섭 채널은 **statusline 스크립트의 stdin JSON**이다. 공식 문서
https://code.claude.com/docs/en/statusline 의 stdin 스키마(실측·CLI 2.1.176):

```jsonc
{
  "model": {"id": "...", "display_name": "..."},
  "session_id": "...", "transcript_path": "...", "version": "...", "cwd": "...",
  "context_window": {
    "total_input_tokens": N, "total_output_tokens": N,
    "context_window_size": 200000,        // [1m] 모델은 1000000
    "used_percentage": 41.2, "remaining_percentage": 58.8,
    "current_usage": {"input_tokens":N,"output_tokens":N,
                      "cache_creation_input_tokens":N,"cache_read_input_tokens":N}
  },
  "exceeds_200k_tokens": false,
  "rate_limits": {                          // ★ Pro/Max 한정·세션 첫 API 응답 후 등장
    "five_hour": {"used_percentage": 41.0, "resets_at": 1781314865},
    "seven_day": {"used_percentage": 12.0, "resets_at": 1781781650}
  },
  "cost": {"total_cost_usd": 0.42, ...}
}
```
- statusline은 **assistant 메시지마다 + /compact 후 + 권한모드 변경 시** 실행(300ms 디바운스).
  `refreshInterval`(settings, 최소 1초)로 타이머 재실행 추가 가능.
- `used_percentage` 공식 = input + cache_creation + cache_read (output 제외) — Phase 1 transcript
  계산식과 동일. 즉 statusline은 transcript tail의 **상위 호환**(rate limit까지 줌·서버 진실값).

### 1.2 설계 — 새 RPC `usage.report` + 래퍼 스크립트 + preflight 설치
claude가 statusline을 실행할 때마다 stdin JSON을 받아 ezerd에 push하는 **tee 래퍼**를 settings에 건다.

**구현 단계 (체크리스트):**

- [ ] **(1) 새 RPC `usage.report`** — `src/bin/ezerd/handlers.rs`
  - params: `{surface_id, ctx_pct, ctx_tokens, ctx_window, rate:[{label,used_pct,resets_at}], cost_usd?}`
  - 소유 게이트 = `usage.register`와 **동형 복붙**(caller_sid != sid 거부, 익명 통과).
  - `Surface.observed_usage`를 `source:"statusline"`로 직접 갱신 (transcript tail보다 우선).
  - `usage.updated` 이벤트 발행 + 공유 게이트(`ctx_threshold_armed`)로 `context.threshold` 발화
    — **Phase 1과 동일한 게이트 함수를 호출**(중복 발화 방지). ★주의: 현재 게이트 로직이
    handlers.rs(status.set)·usage.rs(collect_for) 두 곳에 인라인 복제돼 있다. 3번째 복제 전에
    **`fn maybe_fire_context_threshold(daemon, surface, pct, threshold, source)` 헬퍼로 추출**
    하고 세 호출처가 공유하라 (R1 리뷰가 지적한 복제 부채 — 지금이 정리 시점).

- [ ] **(2) usage.rs 우선순위 병합** — `collect_for`
  - claude의 경우: `observed_usage.source == "statusline"`이고 신선(updated_at age < 60s)하면
    transcript tail이 **ctx를 덮어쓰지 않게** 한다(rate limit 유실 방지). statusline이 끊기면
    (age > 60s) transcript tail로 graceful 폴백.
  - 구현: collect_for 진입부에서 `prev.source=="statusline" && age<60` 이면 ctx 필드는 보존,
    rate는 statusline 것 유지. 또는 더 단순히 — claude는 statusline 경로가 있으면 transcript
    수집을 스킵(등록된 statusline이 더 정확). **단순안 권장**: `Surface`에 statusline 보고
    시각 기록 → collect_for가 claude+신선 statusline이면 skip.

- [ ] **(3) 래퍼 스크립트** `ezer-pack/hooks/ezer-statusline.sh` (pack 임베드 — `src/pack.rs` PACK 배열 추가)
  ```sh
  #!/bin/sh
  # Claude Code statusline: stdin JSON을 ezerd에 tee하고, 기존 statusline(있으면) 출력 위임.
  IN=$(cat)   # statusline은 stdin 1회 — 전량 읽어도 안전(후속 소비자 없음)
  [ -n "$EZER_SURFACE_ID" ] && command -v ezer >/dev/null 2>&1 && \
    printf '%s' "$IN" | ezer usage-report-stdin >/dev/null 2>&1   # 새 CLI(아래)
  # 사람이 보는 statusline 한 줄 (기존 체인 보존: EZER_PREV_STATUSLINE 있으면 위임)
  if [ -n "$EZER_PREV_STATUSLINE" ]; then printf '%s' "$IN" | sh -c "$EZER_PREV_STATUSLINE"
  else printf '%s' "$IN" | python3 -c 'import sys,json; d=json.load(sys.stdin); cw=d.get("context_window",{}); rl=d.get("rate_limits",{}); print(f"{d.get(\"model\",{}).get(\"display_name\",\"?\")} · CTX {cw.get(\"used_percentage\",0):.0f}% · 5h {rl.get(\"five_hour\",{}).get(\"used_percentage\",0):.0f}%")' 2>/dev/null
  fi
  ```
  - 새 CLI `ezer usage-report-stdin`: stdin JSON 파싱 → usage.report RPC. (Rust에서 파싱 —
    `src/bin/ezer.rs`에 `UsageReportStdin` 커맨드. surface는 EZER_SURFACE_ID.)
  - claude는 statusline command를 **셸로 실행**하므로 `$EZER_SURFACE_ID` env가 PTY에서 상속됨(확인 필요).

- [ ] **(4) preflight C28 — statusline 설치/검증** `ezer-pack/bin/ezer_preflight.py`
  - `discover_claude_settings()`(이미 ezer.rs에 있음 — Python 포팅 or ezer 서브커맨드 호출)로
    `~/.claude*/settings.json` 전부 찾아 `statusLine` 필드 설치:
    ```json
    "statusLine": {"type":"command","command":"sh $HOME/.ezer/pack/hooks/ezer-statusline.sh"}
    ```
  - **기존 statusLine 보존**: 이미 있으면 그 command를 `EZER_PREV_STATUSLINE` env로 래핑(체인).
    덮어쓰기 금지 — hook 설치(install_claude_hook)와 동일한 보존 철학.
  - `--fix`로 설치, 무인자로 검증(설치됨 READY / 미설치 WARN). symlink 거부·백업 등 install_claude_hook 패턴 재사용.
  - ★주의: settings.json 수정은 **claude 재시작 후 적용**. preflight 출력에 "재시작 필요" 명시.

- [ ] **(5) 검증**
  - 단위: usage.report 소유 게이트 핀(usage_register와 동형 3종) + statusline JSON 파서 핀
    (rate_limits.five_hour/seven_day 추출, rate_limits 부재 시 ctx만).
  - E2E: 샌드박스에 가짜 statusline JSON을 `ezer usage-report-stdin`으로 흘려 배지에 5h/7d 노출 확인.
  - 라이브: settings 설치 → claude 노드 재기동 → 배지에 `CTX n% · 5h n% · 7d n%` 등장 실측.

### 1.3 리스크·결정 사항
- statusline 설치가 settings.json을 건드림 → 오너 **이미 승인**(preflight --fix 편입). 멀티 프로필
  7개 전부 설치 시 첫 배포에서 기존 statusLine 충돌 점검 필요(현재 미설정 실측 — 충돌 없을 가능성 높음).
- claude는 transcript(Phase 1)로 이미 ctx%가 나오므로, statusline이 추가하는 순가치는 **rate limit + 정밀 ctx + cost**. 즉 Phase 2-A 없이도 ctx 배지는 작동(현 상태).

---

## 2. Phase 2-B — agy(Antigravity) 쿼터 RPC 【승인됨 · graceful degrade 전제】

### 2.1 실측 근거 (Phase 1 조사 — ★재접속 시 먼저 라이브 프로브 필요)
- agy 실행 중 프로세스가 **127.0.0.1 고포트 LISTEN**(실측 당시 53509·53510). 포트는 매 실행 변동.
- 바이너리 strings 실측: `/exa.language_server_pb.LanguageServerService/GetUserStatus`,
  `/RetrieveUserQuotaSummary`, `QuotaSummaryBucket`. (Connect/gRPC-web 프로토콜 추정.)
- 커뮤니티 도구 3종(AntigravityQuotaWatcher·Henrik-3/AntigravityQuota·Antigravity-Context-Window-Monitor)이
  이 로컬 포트의 `GetUserStatus`를 **POST 폴링**해 모델별 쿼터·프롬프트 크레딧을 상태바에 표시 — 방식 검증됨.
- 대안(백엔드 직접): `cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary` /
  `:fetchAvailableModels`(remainingFraction·resetTime·isExhausted) / `:loadCodeAssist`
  (availablePromptCredits·planInfo). 인증 = `~/.gemini/oauth_creds.json` access_token(Bearer,
  실측 당시 만료 — refresh_token 갱신 필요). **비공식 v1internal — 스키마 변동 위험, 로컬 RPC가 더 안정.**

### 2.2 ★재접속 시 첫 작업 — 라이브 프로브 (구현 전 필수)
스키마를 직접 안 봤으므로 **추정 코드 금지**. agy 노드가 떠 있을 때:
```bash
# 1) agy 프로세스의 LISTEN 포트 찾기
AGY_PID=$(pgrep -f 'antigravity|/agy' | head -1)
lsof -p "$AGY_PID" -iTCP -sTCP:LISTEN -Fn 2>/dev/null   # n<port>
# 2) GetUserStatus 프로브 (Connect 프로토콜 — POST, JSON 또는 protobuf)
#    먼저 평문 JSON으로 시도, 실패 시 grpc-web 프레이밍
curl -s -X POST "http://127.0.0.1:<PORT>/exa.language_server_pb.LanguageServerService/GetUserStatus" \
  -H 'content-type: application/json' -d '{}' | head -c 2000
curl -s -X POST ".../RetrieveUserQuotaSummary" -H 'content-type: application/json' -d '{}' | head -c 2000
```
→ **응답 스키마를 실측해 기록한 뒤** 그 필드로 파서 작성. (이 단계가 끝나야 구현 시작.)

### 2.3 설계 (프로브 결과에 따라 조정)
- [ ] **(1) usage.rs에 agy 분기** — `collect_for`의 `match agent`에 `"gemini" =>` 추가.
  - 매 틱이 아니라 **저빈도 폴링**(예: 15초 — codex보다 무겁고 변동 느림). `attempts` 맵 재사용.
  - agy 프로세스 LISTEN 포트 발견(lsof, find_agent_descendant 패턴 재사용) → HTTP POST →
    파싱 → `ObservedUsage{rate:[{label:"quota:<model>", used_pct, resets_at}], source:"agy-rpc"}`.
  - context window는 agy가 안 주면 None (배지는 쿼터만 — `5h`/`7d` 대신 모델별 잔량).
- [ ] **(2) graceful degrade** — 포트 미발견·RPC 실패·파싱 실패 시 `observed_usage` 미갱신(배지 없음
  유지). 절대 패닉·스팸 금지. 실패를 `usage.probe_failed`(저빈도) 이벤트로만 1회 기록.
- [ ] **(3) HTTP 클라이언트**: ezerd에 이미 reqwest 있는지 확인(`Cargo.toml`). 없으면 ureq(경량·동기)
  추가 — 수집기는 동기 컨텍스트(blocking)라 ureq가 적합. **틱 블로킹 주의**: 타임아웃 2초 강제,
  실패 시 즉시 포기(수집기 태스크가 멈추면 안 됨 — Phase 1 패닉 격리와 별개로 타임아웃 필수).
- [ ] **(4) 검증**: 라이브 프로브 응답을 fixture로 단위 핀, agy 노드 떠 있을 때 배지 등장 실측.

### 2.4 리스크
- 비공식 API — agy 업데이트로 RPC명/스키마/포트 방식 변동 가능. graceful degrade가 안전망.
  source에 `agy-rpc` 명시로 신뢰등급 구분. CLI 버전 함께 기록(변동 추적).
- 토큰 컨텍스트는 안 나올 수 있음(쿼터만) — 배지를 `quota 73%` 형태로, ctx 없으면 생략.

---

## 3. Phase 2-C — 통합 사용량 대시보드 (UI) 【승인됨】

### 3.1 목적
pane별 배지(Phase 1)는 "지금 이 작업"용. 대시보드는 **전 계정 잔량을 한눈에** — 다중 터미널에서
"어느 계정이 곧 소진되나"를 작업 전환 없이 파악(오너 원래 고통의 핵심).

### 3.2 설계
- [ ] **(1) 데이터**: `org.status`의 각 surface `usage`를 **에이전트(계정)별 그룹핑**.
  - claude(전 프로필 합산? or 프로필별), codex, agy 각각의 최신 rate window.
  - 이미 org.status에 usage 다 있음 — UI 집계만. 새 RPC 불필요.
- [ ] **(2) UI 위치**: 좌측 워크스페이스 사이드바(최근 추가됨, 커밋 3291b24) 하단에 "사용량" 섹션,
  또는 우측 feed-panel 옆 토글 패널. **사이드바 하단 권장**(상시 가시).
  - `ui/src/main.ts`: refreshPaneTitles(3초)가 이미 list_surfaces 폴링 → 그 데이터로 대시보드 갱신.
  - 계정별 행: `claude  5h ▓▓▓▓░ 41%  7d ▓░ 12%` + reset 상대시각(`↻2h13m`).
  - 색상: Phase 1 sevClass 재사용(70/90). 가장 임박한 reset 강조.
- [ ] **(3) 스타일**: `ui/src/style.css`에 `.usage-dashboard` — 사이드바 톤과 일치(헤어라인 등 기존 톤).
- [ ] **(4) 빌드·검증**: `sh ui/build.sh` → ezer-app 재빌드 → 번들 교체 → 앱 재시작 후 육안 확인.
  - playwright-mcp로 스크린샷 회귀(`.playwright-mcp/` 이미 있음).

### 3.3 결정 사항 (재접속 시 오너께)
- claude 멀티 프로필(7개) 어떻게 보여줄까 — 합산 vs 프로필별 행. rate limit은 **계정(구독)별**이라
  같은 구독을 쓰는 프로필은 같은 5h 윈도우 공유. 프로필↔계정 매핑을 어떻게 아는가? → 미해결.
  1차는 "프로필별 행"으로 단순하게, 중복은 나중에.

---

## 4. Phase 3 — attribution + 라우팅 게이트 (Phase 2 이후)

### 4.1 attribution (어떤 작업이 컨텍스트를 먹나)
- transcript를 턴 단위로 tail → 턴별 ctx delta 계산 → 그 턴의 tool_use(Read/Bash/서브에이전트)
  기록과 대조 → "이 Read가 18k, 이 서브에이전트 결과가 30k" 귀속.
- v1: pane별 "최근 고소모 턴 top 5(원인 도구·파일)" — `usage.attribution` RPC + UI 팝업.
- transcript의 `message.usage`는 이미 있음(Phase 1). tool_use는 같은 라인 content에 있음 → 파싱 확장.

### 4.2 task-prompt 잔량 게이트 (계정 라우팅)
- `ezer_orchestra.py task-prompt`(워커 생존 게이트)에 **rate limit 잔량 게이트** 한 줄 추가:
  위임 직전 대상 계정의 5h 잔량이 임계(예: 90%) 초과면 경고/차단 → "여유 큰 계정으로 라우팅".
- org.status usage를 ezer_orchestra가 읽어 판단(이미 노출됨).

---

## 5. 회귀 자산 (재접속 시 검증용 — 영구 보존)

- **E2E 스크립트**: `docs/usage_e2e.py` (원본 /tmp/ezer-e2e-usage.py — /tmp는 재부팅 소실되므로 docs로 복사).
  샌드박스 데몬 기동 후 실행 → 20/20 PASS 기대. 실행법은 파일 상단 docstring + 아래.
  ```bash
  SOCK=/tmp/ezer-e2e-$$.sock
  EZER_SOCKET=$SOCK EZER_PACK_DIR=/tmp/ezer-e2e-pack EZER_USAGE_POLL_SECS=1 ./target/debug/ezerd &
  # docs/usage_e2e.py 상단 SOCK= 를 위 값으로 맞추고:
  python3 docs/usage_e2e.py
  ```
- **단위 테스트**: `src/bin/ezerd/usage.rs` mod tests (파서·tail·munge), `handlers.rs` usage_register_* 3종,
  `ezer.rs` expand_tilde, `main.rs` env_scrub. `cargo test` 178 passed.
- **적대 리뷰 요약**: `scratch/r3_review_summary.txt` (R1 발견·수정 내역).

## 6. 핵심 파일 지도 (Phase 2 작업 위치)

| 작업 | 파일 | 진입 지점 |
|---|---|---|
| usage.report RPC | `src/bin/ezerd/handlers.rs` | `"usage.register" =>` 블록 바로 아래에 복제 |
| 게이트 헬퍼 추출 | `src/bin/ezerd/handlers.rs` + `usage.rs` | context.threshold 발화 3곳 → 1 헬퍼 |
| agy/statusline 수집 | `src/bin/ezerd/usage.rs` | `collect_for`의 `match agent` |
| CLI 커맨드 | `src/bin/ezer.rs` | `UsageRegister` 커맨드 옆 |
| 래퍼 스크립트 임베드 | `src/pack.rs` PACK 배열 + `ezer-pack/hooks/` | session-start.sh 패턴 |
| preflight C28 | `ezer-pack/bin/ezer_preflight.py` | C03(hook) 검사 패턴 |
| UI 대시보드 | `ui/src/main.ts` + `style.css` | refreshPaneTitles·사이드바 |
| 배포 | (런북) | memory `ezer-agent-deploy-runbook` — pgrep -x ezerd·os.replace·denylist |

## 7. 배포 절차 (Phase 1에서 확립 — memory에도 박제)
1. `cargo test` 통과 → `sh scripts/bundle-prep.sh`(UI+release ezer/ezerd) → `cargo build --release -p ezer-app`.
2. python `os.replace`로 `/Applications/ezer.app/Contents/MacOS/{ezer,ezerd,ezer-app}` 원자 교체(.bak-<tag>).
3. `pgrep -x ezerd`로 정확한 pid kill → `ezer ping` 자동 재기동 → `ezer boot`.
4. ★데몬 재기동 전 `ezer status --json`으로 전 노드 idle 확인 — 워커 장기 턴 중 강행 금지.
5. preflight READY · 라이브 배지 실측 · SESSION_STATE 갱신.

---
## 현황 주석 (2026-07-03 · CC 전수조사 후속)
- Phase 2-A(statusline 우선 병합): 가동 — 단 **소비 적재는 statusline과 무관하게 항상 수행**하도록 교정(구현이 관측 skip에 소비까지 말려들던 결함 수정, usage.rs collect_for).
- Phase 2-B(agy 쿼터 RPC): 미착수 — agy는 rate 쿼터만 수집, 토큰 소비는 로컬 데이터원 부재로 미적재(알려진 한계로 명문화).
- codex: rollout `token_count`(last_token_usage)+`turn_context`(model) 기반 소비 적재 **완료** — by_agent에 codex 등장.
- 컨텍스트 창: statusline이 준 서버 진실 ctx_window를 세션 내 기억해 트랜스크립트 폴백의 200k 하드코딩을 교정(1M 세션 조기 임계 오발 방지).
