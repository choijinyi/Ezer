# EZERagent 에제르 네이티브 기능 제안서

- 작성일: 2026-06-12
- 전제: 기능 parity는 노선 (a) 기능 재구현 유지 (오너 확정). 본 제안은 parity와 별개로, **에제르 시스템이 거주하는 터미널**로서의 고유 기능을 다룬다.
- 방법론 (내부 2-cycle): 평가기준 선작성 → 1차 병렬 조사 2기(①디렉티브 전수 스캔으로 수동 의무 10건 추출 ②운영 기록 고고학으로 실제 사고 패턴 11건 발굴) + master 자체 발상 → 초안 15건 → 2차 적대 검증(red-team 에이전트가 코드 직접 대조 — 기각 1·유지 5·수정 9·누락 7건 추가 발굴) → 최종 19건.

---

## 0. 설계 철학

> **이 터미널은 사람이 쓰는 터미널이 아니다. AI 조직(에제르)이 거주하는 운영체제다.
> 따라서 디렉티브(절대지침)가 master·CSO에게 수동으로 시키는 모든 운영 의무는, 곧 터미널의 기능 결함 목록이다.**

세 원칙:

1. **디렉티브의 기계화** — "규약으로 강제"(잊히면 끝)를 "데몬이 보증"(기계적 불변)으로 내린다. 승인·60% clear·복원·노드 재기동·todo 공유·kill-switch가 전부 여기 해당.
2. **자기보고 우선, 화면 파싱은 fallback** — PTY 텍스트 스트림 파싱은 `\r` 리드로우에 안 잡히고 에이전트 CLI 업데이트마다 무음 파손된다(red-team 횡단 결함 1). 에이전트가 `EZERagent set-status`로 직접 신고하는 구조화 채널을 1차로, 파싱은 누락 시 보조로.
3. **자동화의 안전 등급** — alert(통지) → escalate(master 격상) → act(자동 조치)의 3단계. 오탐이 무해한 alert 체계에 조치를 바인딩하는 순간 오탐은 사고가 된다(red-team 횡단 결함 2). 자동 조치는 deny-by-default + 확신 게이트(연속 매칭·에코 제외) 통과 시에만.

평가기준 (선작성, 각 제안에 적용):
①수동 의무 제거 직결성 ②master 컨텍스트·토큰 절약 ③자율주행 기여 ④안전성(denylist 무침해) ⑤구현 효율(기존 이벤트 버스·watchdog·큐·feed에 자연 결합) ⑥parity 로드맵과 보완 관계.

---

## 1. 근거: 실제 사고 기록 (운영 고고학 발굴)

| 사고 | 일자 | 피해 | 본 제안의 차단 기능 |
|---|---|---|---|
| `bun server.ts` 36개 누적 → load 288 → 시스템 마비 → 워커 3개 401 연쇄 | 2026-06-05 | 치명 | (기구현 watchdog) + T4-16 헬스 조치 바인딩 |
| 워커 컨텍스트 470~525k 폭발, 1응답 9분, gemini 밤샘 정체 — master 능동 점검 부재 | 2026-06-05 | 높음 | T1-1 자기보고, T1-2 status 보드, T2-4 cycle-agent |
| 재부팅 후 PTY 미할당 → dispatch 불가 (외부 터미널 앱 버그) | 2026-06-06 | 높음 | T2 전체 (EZERagentd는 구조적으로 면역 + 토폴로지 복원) |
| 입력 버퍼 잔존 → `/clear` 명령 실패 ×2회 | 2026-05-12 | 중간 | T3-13 입력 안전 주입 |
| gemini 64GB 힙 hang(1h) — send-key 회생 불가, kill·재가동 유일 | — | 높음 | T2-5 에이전트 사망 감지 |
| 워커 401·hang → 현재 pane 복구 불가 반복 | 2~3회 | 높음 | T2-5 + T4-16 |
| hook 무한루프(`dirname '.'` 고정점) → 복원 메커니즘 사망 | — | 중간 | (pack 차원 — 부록 참조) |
| 승인 push 누락 → 리뷰어 무한 대기·라운드 교착 | 반복 | 중간 | T3-12 feed aging, T4-15 승인 격상 |

---

## 2. 최종 제안 19건 (Tier별)

### Tier 1 — 토대 (다른 제안들의 데이터 기반·보안 기반. 최우선)

#### T1-1. `EZERagent set-status` — 에이전트 자기보고 채널 ★아키텍처의 축
- **불편**: master가 워커 상태(작업중/대기/막힘, 컨텍스트%)를 알려면 read-screen 폴링뿐 — 토큰 소모·지연·오판(2026-06-05 525k 폭발 사고의 직접 원인).
- **기능**: `EZERagent set-status --state working|waiting|blocked|done --context 57 --task "3장 집필"` RPC. 데몬이 surface별 최신 상태 보관, 변화 시 `status.changed` 이벤트. 디렉티브에 신고 의무 명문화(작업 시작·체크포인트·턴 종료마다 1줄).
- **효과**: 화면 파싱 0줄로 컨텍스트·진행 추적 해결. 기능 parity #1(set-status/progress)과 **동일 기안으로 통합** — parity와 에제르 요구가 정확히 겹치는 지점.
- **안전**: 자기신고이므로 위조 가능 — 신뢰 등급 '참고'(검증은 T4-18 attest·기계 게이트 몫).

#### T1-2. `org.status` RPC + `EZERagent status` 통합 관제 보드
- **불편**: 능동 모니터링 의무 = 5분마다 노드 수×read-screen ≈ 시간당 수천 토큰 상시 소모.
- **기능**: 1콜로 전 노드 요약 — 1차 필드(데몬 보유: role·생존·idle 경과·큐 깊이·pending feed 수·health 최근 알림), 2차 필드(T1-1 자기보고: state·context%·task), 3차 필드(T3-9 todo 진행률). 필드별 출처·신선도(나이) 표기 — 파생 필드 깨져도 거짓 수치 대신 'stale' 표시.
- **효과**: read-screen 폴링 → 20줄 1콜. master 관제 비용 ~90% 절감.

#### T1-3. 발신자 신원 데몬 검증 + 송신 ACL (red-team 발굴 #17)
- **불편/위험**: 현재 `from` 태그는 클라이언트 자기신고 — 소켓에 닿는 누구든 master 포함 임의 pane stdin에 주입 가능, 발신자 위조 가능. 조직 거버넌스의 빠진 토대.
- **기능**: SO_PEERCRED(UDS peer credential)로 발신 프로세스→surface→role 역추적해 데몬이 `from`을 직접 도출. `role→role 송신 정책` 테이블(예: reviewer→master push 허용, reviewer→worker stdin 주입 차단). 위반 시 거부+`acl.denied` 이벤트.
- **효과**: 리뷰어의 master 조향·디렉티브 위조 주입 경로 차단. T4-18 attest의 전제. 외부 터미널의 소켓 비밀번호 인증보다 에제르에 적합한 모델(역할 기반).

### Tier 2 — 수명주기 자동화 (자율주행 축1·2·3의 기계화)

#### T2-4. `EZERagent cycle-agent --role X` — 컨텍스트 60% 사이클 집행기
- **불편**: 60% 룰(절대지침)이 완전 수동 — 감시·저장 지시·/clear·재주입·재개 전부 master/CSO 손. 누락 시 525k 폭발 재발.
- **기능**: 단일 명령이 시퀀스 집행: ①저장 지시 송신 → ②**SESSION_STATE/todo 파일 mtime>사이클 시작 + 내용 해시 변화 검증**(화면 마커 신뢰 금지 — reward-hack·stale 마커 차단, red-team 보강) → ③입력버퍼 선정리 → ④clear 명령(agents.json 어댑터 필드 — claude `/clear`, gemini·codex 각자 명령) → ⑤디렉티브 재주입 → ⑥SESSION_STATE 포인터 제시. `--verifier <role>` 2-phase handshake 내장: 검증자 부재 시 clear 거부(soul.md "CSO 부재 시 self-clear 금지" 기계화).
- **트리거**: T1-1 자기보고 context% ≥ 임계 → `context.threshold` 이벤트 → master가 cycle-agent 발동(완전 자동은 반자율 단계 이후).

#### T2-5. 에이전트 사망 감지 — `agent.exited` 이벤트 + 재기동 정책
- **불편**: 에이전트 프로세스만 죽고 셸이 살면 `surface.exited`도 안 뜨고 `pane.idle`(300초)이 잡을 때까지 무감지. gemini 64GB hang·401 사망의 늦은 발견 원인.
- **기능**: watchdog이 이미 5초마다 자식 트리를 수집(`collect_descendants`) — 증분 비용 0으로 "agents.json 등록 cmd 바이너리가 자식 트리에서 소멸" 감지 → `agent.exited` 즉시 발행. 정책 옵션: 자동 재기동(디렉티브 재주입 포함) + 3회 실패 시 escalation + **health 401 알림 동반 시 재기동 루프 차단**(로그인 깨진 채 무한 재기동 방지, red-team 보강). 크로스플랫폼 명세: tcgetpgrp 의존 금지, 자식 트리 휴리스틱으로(Windows 호환).
- parity #6(hibernation·resume)과 통합 기안.

#### T2-6. 토폴로지 스냅샷·`EZERagent restore` — 조직 복원 (RECOVERY 기계화)
- **불편**: RECOVERY.md 7단계 수동 프로토콜(5~10분), 재부팅 시 노드별 재기동·재주입 반복.
- **기능**: 데몬이 role→agent→cwd→디렉티브 매핑을 상시 영속(roles는 현재 in-memory). `EZERagent restore`가 ①죽은 노드 일괄 재기동 ②디렉티브 재주입 ③**에이전트별 resume 어댑터**(claude `--continue` 등 — 기억 복원의 본체, red-team 지적) ④SESSION_STATE 포인터 제시까지. **작업 자동 재개는 하지 않음** — 복원은 "기동+주입+포인터"까지, 재개는 master 판단(자율주행 denylist 정신 준수).
- parity #2(세션 복원)와 역할 분담: parity #2=PTY scrollback·레이아웃, 본 건=조직 편제. 동일 스냅샷 인프라 공유.

#### T2-7. 디렉티브 드리프트 감지·재주입 (red-team 발굴 #22)
- **불편**: 주입은 기동 시 1회뿐 — 수동 /clear·컨텍스트 압축으로 지침을 잃어도 감지 수단 없음. "워커가 절대지침 없이 단일 sub-agent로 수렴·치명에러 재발"(CLAUDE.md 🔒)의 런타임 구멍.
- **기능**: `EZERagent directive reinject --role X` + 각성 확인 핑(디렉티브에 응답 규약 포함 — 핑 수신 시 1줄 자기확인 응답, 무응답 N회 → `directive.drift` 이벤트).

#### T2-8. master dead-man 감지 (red-team 발굴 #21)
- **불편**: T2-5는 워커·리뷰어만 — 조직의 단일 장애점인 master 자신의 사망·hang은 아무도 안 본다.
- **기능**: master 역할 부재 또는 무출력 N분 → UI 최상위 경보 + (설정 시) 오너 외부 알림. 조직 복원력의 마지막 구멍 봉합.

### Tier 3 — 협업·운영 편의

#### T3-9. todo 파일 워치 — `todo.updated` 이벤트 + 진행률 집계
- **불편**: todo push 공유는 규약 의존 — 잊히면 master가 구식 정보로 판단(고고학 패턴 9).
- **기능**: 데몬이 설정된 round 디렉터리의 `*_TODO.md` mtime 폴링(워처 신규 의존성 불요) → 변경 시 이벤트 + 체크박스 집계를 T1-2 보드에 공급. 체크박스 포맷은 pack에 명세 고정.

#### T3-10. 원샷 타이머 — `EZERagent schedule add --in 20m --once`
- **불편**: schedule은 HH:MM+요일 반복뿐(코드 확인) — 자율주행 축3(작업단위 종료 후 자가 재기동 wakeup)에 필요한 상대시간·1회성이 없다.
- **기능**: 상대시간 파싱 + 발화 후 job 자동 삭제 + `--fresh` 병용 시 임시 surface TTL 명세(누수 차단, red-team 지적).

#### T3-11. 역할그룹 브로드캐스트 — `EZERagent send --to 'reviewer-*'`
- 초안의 '구조화 메시지함'은 red-team이 기각(send --queued·feed·이벤트의 재포장, '읽음확인'은 PTY 차원에서 거짓 보증). 유일한 비중복 조각인 글롭 확장만 send에 흡수.

#### T3-12. feed aging 재알림 (red-team 발굴 #18)
- **불편**: `feed --wait` timeout(120초) 후 pending이 무음 적체 — master 부재 중 승인 요청 유실이 큐 적체의 실제 원인.
- **기능**: pending N분 경과 → 재push + UI 뱃지 단계 상승. 워커 push 누락 사고(고고학 패턴) 직접 차단.

#### T3-13. 입력 안전 주입
- **불편**: 입력 버퍼 잔존 → `/clear` 실패 ×2회(2026-05-12). 사람 타이핑 중 push 도착 → 입력 오염.
- **기능**: ①`--clear-first`(Ctrl-U 선행)는 **agents.json 등록 에이전트 한정**(포그라운드 앱마다 Ctrl-U 의미가 달라 무차별 제공 금지, red-team 지적) ②타이핑 충돌 가드 — UI 키입력도 데몬 경유이므로(검증 완료) 최근 N초 내 사람 입력 감지 시 원격 주입을 강제 큐잉.
- **구현(2026-06-14 원자화)**: `--clear-first`를 데몬 단일 `WriteReq::Inject{clear_first}`로 집행 — Ctrl-U 선정리 → settle(`EZERAGENT_CLEAR_SETTLE_MS`,기본150) → bracketed paste → CR을 **한 writer arm에서 원자 처리**(다른 주입 비끼어듦·부분 전달 차단). 구 클라측 2-RPC(send_key C-u+150ms sleep+send_text, 비원자)는 폐기. **권위 전달은 자동 제출(CR 포함)** — 별도 Return 금지(이중 제출). agent 등록 게이트는 데몬 집행(`clear_first_unsupported`), `--queued`와 결합 불가(`invalid_params`). 잔존텍스트 오염·비원자 split·race를 동시 제거. RLM·surface·SOT 모델 불변(transport 계층 한정).

#### T3-14. 델타 읽기·완료 대기 — `read-screen --since` + `EZERagent watch --until`
- **기능**: surface별 단조 라인 카운터 신설(메모리 scrollback FIFO엔 안정 커서 없음 — red-team 지적 반영) + 데몬측 블로킹 regex 대기. **plain-line 마커 규약 전제 명시**: `\r` 리드로우 줄은 라인 스트림에 없으므로 완료 마커는 echo 줄로 출력하도록 디렉티브에 규약화. parity #4(tmux 호환 wait-for 상당)와 통합.

### Tier 4 — 안전·무결성

#### T4-15. 네이티브 kill-switch — `EZERagent pause / resume`
- **기능**: 데몬 플래그 + 영속. pause 시: 큐 배달 동결·스케줄 발화 차단·`autopilot.paused` 이벤트·UI 배지·preflight RPC(`system.gate_check` — 에이전트가 매 action 전 확인). **pause 중 feed --wait 타이머 동결**(timeout-deny 연쇄 낙하 방지, red-team 보강).
- **한계 명시(중요)**: pause는 "조직 간 신경 차단"이지 "행동 정지"가 아니다 — 이미 실행 중인 에이전트의 자체 도구 호출은 계속된다. UI·문서에 명시해 오신뢰 차단.

#### T4-16. 승인 격상 엔진 (자동 응답은 원칙 금지)
- **수정된 설계**(red-team 안전 결함 반영): ①구조화 채널 우선 — Claude Code는 이미 PreToolUse hook→`feed push --wait` 경로 존재, 이를 gemini·codex 어댑터로 확장 ②화면 파싱 경로는 **자동 응답 금지·feed 격상 전용**(deny-by-default) ③말줄임(…)·줄바꿈 잘린 대화상자 감지 시 자동 응답 절대 금지(잘린 뒷부분에 `&& rm -rf` 은닉 경로) ④에이전트 버전 변경으로 선택지 순서 바뀌면 "1"/"y" 오발 — 자동 키 전송 자체를 보수적으로.
- master가 받는 것: `approval.request` 구조화 이벤트(선택지 포함) — 판단·승인은 master(또는 명시 정책)가, 감지·전달은 데몬이.

#### T4-17. 헬스룰→조치 바인딩 (확신 게이트 필수)
- **수정된 설계**: ①조치는 **queued 배달 정지만** — master 직접 steer는 통과(복구 명령 /login·C-c까지 막는 자가당착 방지) ②**에코 입력 라인 매칭 제외**(타 노드가 "rate limited" 문자열 주입 → victim 송신 정지되는 DoS 경로 차단) ③연속 N회 매칭 게이트(rate limit에 *관한* 코드를 cat만 해도 매칭되는 오탐의 사고화 방지). 전부 충족 못 하면 alert-only 유지.

#### T4-18. 트랜스크립트 해시체인 + `EZERagent attest`
- **불편**: eval-driven 원칙(producer≠evaluator·암호학적 핀)의 터미널 기반 부재 — 현재 트랜스크립트는 평문 SQLite, 변조 감지 0.
- **수정된 설계**: ①체인은 **무필터 완성 라인 스트림**에 (현행 recall은 3자 미만·중복 스킵 — 필터된 스트림 봉인은 '발췌 봉인'에 불과, red-team 지적) ②**T1-3 신원 검증 선행 필수**(from이 위조 가능하면 봉인의 증명력 0) ③위협 모델 명시: 사후 변조 방어 — 데몬 자체 오염은 범위 외.
- **효과**: RSI eval에서 "워커가 자기 트랜스크립트를 증거로 제출"할 때 master가 seq+hash 핀으로 대조 — 자기채점 금지 원칙의 기계적 토대.

#### T4-19. transcripts.db 보존 정책 (red-team 발굴 #19)
- recall DB에 retention 전무 → 무한 성장. "자원 거버넌스 1급" 표방과 모순되는 자기 자신의 디스크 누수. 일자 기반 정리 + 용량 상한.

---

## 3. 기각·축소 기록 (2차 검증 결과의 투명 보존)

| 초안 | 판정 | 사유 |
|---|---|---|
| 구조화 메시지함 `EZERagent msg` | **기각** | send --queued(quiet-window 배달)·feed --wait(ack)·queue.delivered(배달 확인)의 재포장. '읽음확인'은 PTY 차원에서 정의 불가 — 거짓 보증 판매가 됨. 글롭 브로드캐스트만 T3-11로 발췌 |
| 컨텍스트 화면 파싱 (단독) | 축소 | `\r` 리드로우는 라인 스트림에 부재 + 폴링 금지 원칙과 자기모순 + 어댑터 regex의 버전 취약성 → T1-1 자기보고의 fallback으로 강등 |
| 승인 자동 응답 allowlist | 축소 | 말줄임 은닉·선택지 순서 변경·가짜 프롬프트 인쇄의 3중 자동 승인 사고 경로 → 격상 전용(T4-16) |

---

## 4. parity 로드맵과의 통합 매핑

| 본 제안 | parity 항목 | 관계 |
|---|---|---|
| T1-1, T1-2 | #1 알림·상태 표면 | **동일 기안 통합** — 에제르 요구가 parity 1순위와 정확히 일치 |
| T2-6 | #2 세션 복원 | 보완 (parity=PTY/레이아웃, 본건=조직 편제) — 스냅샷 인프라 공유 |
| T2-5 | #6 에이전트 훅·hibernation | 통합 기안 |
| T3-14 | #4 tmux 호환(wait-for) | 통합 |
| T4-16 | #6 에이전트 훅 | hook 어댑터 공유 |

→ parity 작업과 에제르 네이티브 작업은 별도 트랙이 아니라 **하나의 로드맵**으로 합쳐야 이중 기안이 없다.

## 5. 권장 구현 순서

1. **Phase 1 (토대)**: T1-1 set-status → T1-2 status 보드 → T3-10 원샷 타이머 (셋 다 난이도 하·즉효)
2. **Phase 2 (수명주기)**: T2-5 사망 감지 → T2-4 cycle-agent → T3-12 feed aging → T3-13 입력 안전
3. **Phase 3 (보안 토대)**: T1-3 신원·ACL → T4-15 kill-switch → T4-19 retention
4. **Phase 4 (고급)**: T2-6 restore → T2-7 드리프트 → T4-16 승인 격상 → T4-18 attest → T3-14 델타/watch → T2-8 dead-man → T3-9 todo 워치 → T4-17 조치 바인딩 → T3-11 글롭

## 부록 — 터미널 범위 외 발견 (pack·디렉티브 차원 과제)
- hook 등록 전 견고성 검증(무한루프·타임아웃 가드) — pack의 `hooks/` 차원
- eval 저장소 LOCKED 관리·metric 버전 관리 — `_round/eval/` 운영 규약 차원 (단 T4-18 attest가 터미널측 토대 제공)
- git 루트 혼동·원고 마크다운 오염 — hookify 영역 (기존 경고 유지)
