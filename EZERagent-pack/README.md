# EZERagent Pack — EZERagent 내장 멀티에이전트 운영체계

EZERagent 터미널을 설치하고 AI CLI(Claude Code 등)를 연결하면 **master–worker–CSO–reviewer 멀티에이전트
운영체계(에제르)**가 바로 구동되도록 하는 템플릿 팩이다. 터미널의 기계 기능(양방향 소켓·승인
Feed·자원 거버넌스·세션 영속)과 역할별 절대지침 문서가 한 몸으로 동작한다.

## 빠른 시작

```bash
EZERagent init-pack                 # ~/.EZERagent/pack 에 팩 설치 (이미 있으면 보존)
EZERagentd &                          # 코어 데몬

EZERagent launch-agent --role master --agent claude     # master 기동 (지침 자동 주입)
EZERagent launch-agent --role worker --agent claude     # 워커 기동
EZERagent launch-agent --role cso    --agent claude     # 시스템 운영자 (선택)
EZERagent launch-agent --role reviewer --agent gemini   # 외부 리뷰어 (gemini/codex/grok)
```

launch-agent는 ①surface 생성(EZERAGENT_ROLE 주입) ②에이전트 CLI 기동 ③해당 역할의 절대지침을
stdin으로 자동 주입 ④데몬 역할 레지스트리 등록까지 한 번에 수행한다. 이후 누구든
`EZERagent send --to master "..."`처럼 **역할 이름으로** 서로에게 push할 수 있다.

## 3층 구조

| 층 | 내용 | 출처 |
|---|---|---|
| 코어 (기계 기능) | 양방향 소켓·Feed 승인·watchdog/원장·이벤트 push·세션 영속 | EZERagent 터미널 코어 |
| EZERagent Pack (이 폴더) | 역할별 절대지침·운영 골격·어댑터 정의 | `EZERagent init-pack` |
| 개인 층 | soul.md 취향·장기메모리·프로젝트 컨텍스트 | **사용자가 사용하며 축적** |

soul.md와 memory/는 의도적으로 **최소 골격**이다. 운영 취향과 장기기억은 빌려 쓰는 것이 아니라
사용자 자신이 채워가는 것이 옳다는 설계 철학이다.

## 구성

- `soul.md` — 정체·우선순위 헌장의 최소 골격 (사용자가 채움)
- `directives/MASTER_DIRECTIVE.md` — master 절대지침
- `directives/WORKER_DIRECTIVE.md` — 워커 절대지침
- `directives/CSO_DIRECTIVE.md` — 시스템 운영(자원 거버넌스) 절대지침
- `directives/REVIEWER_DIRECTIVE.md` — 외부 리뷰어(gemini/codex/grok) 절대지침
- `CLAUDE.md.template` — 프로젝트 CLAUDE.md 골격
- `memory/MEMORY.md` — 장기메모리 색인 골격 (빈 상태에서 시작)
- `round/SESSION_STATE.md`, `round/RECOVERY.md` — 복원 체크포인트 골격
- `agents.json` — 에이전트별 어댑터(기동 명령·지침 주입 방법) 정의
- `hooks/session-start.sh` — (선택) Claude Code SessionStart hook: EZERAGENT_ROLE 기반 지침 주입
- `bin/EZERagent_route.py` + `bin/route_triggers.json` — 3단 사고 라우팅(fast/deliberate/slow)
  결정론 엔진. 우선순위 slow > deliberate > fast, 문장 경계 토큰 매칭, 토큰 없으면 fast
  (애매한 요청의 격상은 master 판단 몫). `--self-test` 내장(preflight C17이 부트마다 호출)
- `bin/EZERagent_memory.py` — 장기기억 증류 결정론 도구(slow 종료 게이트의 기계 검증부).
  `add`(파일+색인 원자적 생성·중복검사·잠금) · `verify`(색인↔파일 정합) · `recent`(증류 증거).
  MEMORY.md 손편집 금지의 대체 수단. `--self-test` 내장(preflight C18)

## Claude Code hook (선택, 비침습 기본)

기본 주입 방식은 stdin push(모든 에이전트 공통)다. Claude Code 한정으로 더 강한 주입을 원하면:

```bash
EZERagent init-pack --install-hook --claude-settings ~/.claude/settings.json
```

기존 설정은 `.bak`로 백업되며, hook은 `EZERAGENT_ROLE`이 설정된 세션에서만 발동한다(다른 세션 무영향).
