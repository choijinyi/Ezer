# EZERagent 터미널 설치 가이드

> EZERagent는 **AI 조직(에제르)이 거주하는 터미널**입니다. 코어 데몬(EZERagentd) + CLI(EZERagent) + GUI 앱(EZERagent.app)으로
> 구성되며, **받는 사람은 데몬을 따로 설치할 필요가 없습니다** — 앱·CLI가 자동으로 기동합니다.

> **이 문서는 두 종류의 독자를 위해 명시 분리되어 있습니다.**
> - 🧑 **[HUMAN]** 표시 = **사람이 직접** 해야 하는 단계(DMG 더블클릭·Gatekeeper·`sudo`). 에이전트는 자율 실행하지 말고 사람에게 위임합니다.
> - 🤖 **[AGENT]** 표시 = 에이전트(워커)가 부트 시 **결정론으로 따르는** 실행 스텝(`EZERagent boot`/`launch-agent` 등).
> - 🚧 **[BOUNDARY]** 표시 = 설치 중 **무조건 정지·오너 보고** 대상인 위험 명령(아래 "설치 경계" 섹션 참조).
>
> 한 줄이 사람용 복붙인지 에이전트 실행 스텝인지가 헷갈리면, 이 표시를 우선합니다.

## 무엇이 자동인가 (0.2.0+)

신규 머신에서 별도 설정 없이 동작합니다:

1. **데몬 자동 기동** — 앱을 열거나 `EZERagent` 명령을 처음 쓰면, 데몬이 없을 때 번들에 동봉된 `EZERagentd`를
   분리(detached) 프로세스로 자동 기동합니다. (옵트아웃: `EZERAGENT_NO_AUTOSTART=1`)
2. **Pack 자동 설치** — 데몬 첫 기동 시 `~/.EZERagent/pack`(디렉티브·스킬·스케줄·ACL)을 자동 설치합니다
   (보존 모드 — 기존 파일은 덮어쓰지 않음).
3. **pane 내 PATH 주입** — 데몬이 만드는 모든 pane의 `PATH` 선두에 `EZERagent` 바이너리 폴더가 들어가,
   pane 안의 AI가 `EZERagent identify`를 바로 쓸 수 있습니다(심링크 수동 생성 불요).
4. **오프라인 자기완결 pack** — DMG의 `EZERagent.app` 안에는 ⓐ `EZERagent`/`EZERagentd` 바이너리에 pack 전 트리가
   임베드되고, ⓑ 빌드 시(`bundle-prep.sh`) 동일성·콘텐츠 스캔 게이트를 통과한 **단일 `pack.tar.gz`
   (+`pack-manifest.json`)** 가 `Contents/Resources/` 에 동봉됩니다. 따라서 네트워크 없이도 첫 기동에
   pack을 설치할 수 있고(자기완결), 동봉본은 가시적이라 검수·핫스왑이 가능합니다. 동봉 대상은 raw
   스킬 트리가 아니라 **`EZERagent pack-manifest`(임베드 권위 SOT)가 지정한 파일집합만으로 만든 결정론 단일
   tar blob** 입니다 — 개인정보·미추적 쓰레기 파일 박제를 구조적으로 회피합니다.

5. **런타임 동봉(Node.js·Python·git·uv)** — 순정 머신엔 이 도구들이 없습니다. 설치본 안에
   `runtime/`(Windows) · `Contents/Resources/runtime/`(macOS)로 **Node.js(+npm/npx)·CPython·git·uv**가
   함께 들어가고, 데몬이 모든 pane의 `PATH` 선두에 주입합니다. **별도 설치가 필요 없습니다.**
6. **에이전트 CLI 자동설치(claude·gemini·codex)** — 첫 데몬 기동 시 백그라운드로 1회 수행합니다
   (동봉 npm 사용 · 로그: `~/.EZERagent/logs/cli-bootstrap.log`). `EZERagent boot`도 편성에 필요한
   CLI가 없으면 먼저 설치합니다. 수동 실행·재시도는 `EZERagent install-clis`.
   (옵트아웃: `EZERAGENT_NO_CLI_AUTOINSTALL=1` — 폐쇄망·CLI를 의도적으로 안 쓰는 환경)

→ 따라서 GUI만 쓰는 사용자는 **앱을 더블클릭하면 끝**입니다.

### 에이전트 CLI 자동설치 — 상세

| 대상 | 방식 | 설치 위치 |
|---|---|---|
| Node.js · npm · npx | **설치본에 동봉**(다운로드 없음) | `runtime/node` (앱 내부) |
| Claude Code | `npm i -g @anthropic-ai/claude-code` | Windows `%APPDATA%\npm` · macOS/Linux `~/.local/bin` |
| Gemini CLI | `npm i -g @google/gemini-cli` | 〃 |
| Codex CLI | `npm i -g @openai/codex` | 〃 |

- 설치 위치를 앱 트리 **밖**으로 고정한 이유: 앱 업데이트가 `runtime/`을 재전개하므로 그 안에
  설치하면 업데이트마다 CLI가 사라집니다. 위 두 경로는 pane PATH 합성이 이미 포함합니다.
- **멱등**입니다 — 이미 있으면 건너뜁니다. 최신본 강제 재설치는 `EZERagent install-clis --force`.
- 일부만: `EZERagent install-clis --only claude,codex`
- 한 대상이 실패해도 나머지는 계속 설치합니다(부분 성공 허용).
- **로그인은 사람 단계**입니다 🧑 — 설치는 자동이지만 각 CLI의 최초 계정 인증(Claude/Google/OpenAI)은
  사용자가 직접 해야 합니다.

## 🚧 설치 경계 (Boundaries — 무조건 정지·오너 보고)

> 이 섹션은 **에이전트(워커)용 1급 경계**입니다. 아래 명령들은 부트·설치 중에 워커가 자율로 밟지 말고,
> 만나면 **무조건 중단하고 오너에게 보고**합니다. 거버넌스 일반 denylist(외부 발행·비가역 삭제는
> 무조건 중단·보고)는 이미 워커 절대지침으로 주입되며(근거: `directives/WORKER_DIRECTIVE.md §7`),
> 이 섹션은 **설치에 특화된 위험 명령**만 별도 열거해 보강합니다(directive가 담지 않는 부분).

| ID | 위험 명령 | 왜 경계인가 | 워커 처리 |
|---|---|---|---|
| INST-DENY-01 | `EZERagent daemon install --takeover` | **가동 중인 세션이 소멸**합니다(비가역 — 아래 "C. 상시 가동" line 참조). | 자율 실행 금지 → 정지·오너 보고 |
| INST-DENY-02 | `sudo ln -sf …` (심링크 덮어쓰기) | `sudo` = 오너 권한 단계 + `-f`로 기존 파일을 묻지 않고 덮어씀. | 사람(🧑)이 직접 실행 → 워커는 위임. **단, GUI "셸에 EZERagent 설치" 버튼은 사용자 명시 클릭 + osascript 1회 승격이라 이 경계를 위반하지 않음**(워커가 그 버튼을 자율 클릭하는 것은 여전히 금지). |
| INST-DENY-03 | `rm -rf ~/.EZERagent ~/.local/state/EZERagent` | pack·트랜스크립트·상태 **완전 삭제**(비가역). | 자율 실행 금지 → 정지·오너 보고 |
| INST-DENY-04 | DMG 우클릭·Gatekeeper "열기"·코드사이닝 | 사람 GUI/보안 결정 단계. | 사람(🧑)이 직접 → 워커는 위임 |

> 위 경계는 거버넌스 denylist의 **install 특화 투영**입니다(새 denylist 생성 아님). 일반 경계는
> `WORKER_DIRECTIVE.md §7`이 정본이며 여기서 재서술하지 않습니다 — 충돌·중복 표현형 방지.

## 선행조건 — git (기능별 필수)

기본 사용(DMG/MSI 설치 → 앱 더블클릭)에는 git이 **필요 없습니다**. 다만 아래 기능을 쓰려면 git이 있어야 합니다:

- **소스 기여·직접 빌드**: `git clone https://github.com/choijinyi/Ezer`
- **harness-creator 툴체인 자동 설치**: 부트 프리플라이트(`EZERagent_preflight.py --fix`)가 git으로 자동 클론합니다.
- **RSI 자기개선/자동 발행**: 라운드 산출물의 로컬 커밋·외부 push에 git을 씁니다.

프리플라이트가 git 유무를 결정론으로 점검합니다(`C30.git` — 부재 시 WARN으로 안내). 설치:

```bash
# 🧑 [HUMAN] macOS — Xcode Command Line Tools(권장) 또는 Homebrew
xcode-select --install        # 또는: brew install git
# 🧑 [HUMAN] Linux
sudo apt install git          # Debian/Ubuntu
sudo dnf install git          # Fedora/RHEL
# 🧑 [HUMAN] Windows — 공식 인스톨러
#   https://git-scm.com/download/win  (설치 후 새 터미널에서 git --version)
git --version                 # 설치 확인 (사람·에이전트 공통)
```

## macOS

### 🧑 A. 설치파일 (DMG) — 권장 [HUMAN — 사람이 직접]
1. `EZERagent-0.2.0-macos-arm64.dmg`를 열고 `EZERagent.app`을 `Applications`로 드래그.
2. 첫 실행 시 Gatekeeper 경고가 나오면: 우클릭 → "열기"(미서명 빌드의 경우). 🚧 [BOUNDARY INST-DENY-04 — 사람 보안 결정]
   서명·공증된 빌드라면 바로 열립니다.
3. 끝. 앱이 데몬을 자동 기동합니다.

#### 받는 분(비기술자)께 — 1페이지 (D6 제품 모드 패키징)
> 터미널을 한 번도 안 열어도 오너 대표 산출물(통찰보고서·문체 글)을 클릭으로 받을 수 있습니다.
1. `EZERagent.app`을 `Applications`로 드래그(설치 끝).
2. 더블클릭 → 열림(공증 빌드면 경고 없음). "손상됨"이 뜨면 보낸 사람에게 **"공증 빌드"**를 요청하세요(미공증은 다른 맥에서 차단됩니다 — RELEASE.md §1 ★Apple 서명·공증).
3. 우상단 **Control Center → "스킬 보드"** 탭 → "통찰보고서 만들기" 클릭 → 본문 붙여넣기 → 미리보기 확인 → PDF를 받습니다.
4. ⚠ 산출물은 **"AI 보조 생성 · 오너 검수 전"**입니다. 외부 공유 전 반드시 검수를 받으세요(과대약속 금지).
5. **청중 맞춤**: `~/.EZERagent/profile.json`의 `audience`를 바꾸면(예: `pastor`·`student`) 그 청중에 맞춰 산출됩니다(기본 `custom`=전체보기).

### 🧑 B. CLI도 외부 터미널에서 쓰려면 (선택)
앱 번들 안의 EZERagent·EZERagentd를 PATH(`/usr/local/bin`)에 노출합니다. **권장: 앱 안에서 1클릭.**

1. **권장 — GUI 1클릭(1회 관리자 승인):** Control Center 헤더 → **"셸에 EZERagent 설치"** 클릭 →
   macOS 비밀번호 1회 입력. `/usr/local/bin/EZERagent`·`/usr/local/bin/EZERagentd` 심볼릭이 생기고,
   새 터미널에서 `EZERagent`가 바로 동작합니다. (앱 업데이트에도 경로 유지 — 심볼릭이라 자동 추종.)
2. **폴백 — 수동 sudo(에이전트 자율 금지):** GUI를 못 쓰는 환경에서만.
```sh
# 🧑 [HUMAN] 🚧 [BOUNDARY INST-DENY-02] sudo 심링크 — 사람이 직접
sudo ln -sf /Applications/EZERagent.app/Contents/MacOS/EZERagent  /usr/local/bin/EZERagent
sudo ln -sf /Applications/EZERagent.app/Contents/MacOS/EZERagentd /usr/local/bin/EZERagentd
```
(pane *안*에서는 PATH가 자동 주입되므로 이 단계는 **앱 밖 터미널**에서 `EZERagent`를 칠 때만 필요)

### 🧑 C. 24/365 상시 가동 (선택 — 헤드리스/무인 운영) [HUMAN]
재부팅 후에도 데몬이 자동으로 살아 있게 launchd에 등록:
```sh
# 🧑 [HUMAN] 상시 가동 등록 (가역)
EZERagent daemon install            # 로그인 시 자동 기동 + 사망 시 자동 재기동(KeepAlive)
EZERagent daemon status             # 등록·가동 상태 확인
EZERagent daemon uninstall          # 해제
```
- 이미 데몬이 떠 있으면 `EZERagent daemon install`은 안전을 위해 거부합니다(flock 충돌 방지).
  기존 세션을 정리하고 launchd로 소유권을 넘기려면 `EZERagent daemon install --takeover`
  **🚧 [BOUNDARY INST-DENY-01] ⚠ 가동 중인 세션이 소멸합니다(비가역) — 워커 자율 실행 금지·정지·오너 보고. 사람은 `EZERagent list`로 먼저 확인.**

## Windows

> 코어(named pipe·ConPTY·DSR)는 검증 완료(docs/WINDOWS_VALIDATION.md). GUI 앱(Tauri)의 Windows
> 빌드는 별도 트랙입니다. 현재 Windows 배포는 **CLI+데몬(MSI/ZIP)** 중심입니다.

### 🧑 A. MSI 설치파일 [HUMAN]
1. 아키텍처에 맞는 파일 실행: `EZERagent-0.2.0-windows-x64.msi` 또는 `...-arm64.msi`.
2. 설치 시 `EZERagent.exe`·`EZERagentd.exe`가 PATH에 등록됩니다.
3. `EZERagent list` — 데몬이 없으면 자동 기동됩니다.

### 🧑 B. ZIP (수동) [HUMAN]
`EZERagent-0.2.0-windows-x64.zip`을 풀고 폴더를 PATH에 추가하거나, 그 폴더에서 직접 `EZERagent.exe` 실행.

### 🧑 C. 상시 가동 (선택) [HUMAN]
```
EZERagent daemon install     # 로그온 시 자동 기동 (작업 스케줄러 ONLOGON)
EZERagent daemon status
EZERagent daemon uninstall
```
※ Windows는 작업 스케줄러에 사망-시-재기동이 없어, CLI 자동기동이 이를 보완합니다.

## 🤖 빠른 시작 (설치 후 공통) [AGENT — 에이전트 실행 스텝]

> 아래는 설치가 끝난 뒤 **에이전트(워커)가 결정론으로 따르는** 부트 스텝입니다. 각 스텝에
> **Goal / verify**가 붙어 있어, "사람용 한 줄"과 달리 워커가 자율로 실행·검증합니다.
> 위 🚧 설치 경계(INST-DENY-01~04)는 이 스텝에서도 그대로 유효합니다.

**Goal(부트 완료의 단일 정의)**: 4종 의무 노드(worker·CSO·reviewer×2)가 생존하고, 프리플라이트가
GREEN이며, 역할 주소가 등록된 상태.

```sh
# 🤖 [AGENT] Step 1 — 관제 보드 (현재 노드 상태 확인)
EZERagent status                                   # 전 노드 1콜 관제 보드
#   verify: 출력에 데몬 가동·노드 목록이 보이면 OK

# 🤖 [AGENT] Step 2 — 역할 에이전트 기동 (디렉티브 자동 주입)
EZERagent launch-agent --role master --agent claude  # 역할 에이전트 기동 + 디렉티브 자동 주입
#   verify: launch-agent가 ①surface 생성 ②CLI 기동 ③절대지침 stdin 주입 ④레지스트리 등록 완료

# 🤖 [AGENT] Step 3 — 일괄 부트 (worker + reviewers)
EZERagent boot                                     # 설치된 CLI 자동 감지 → worker+reviewers 일괄 기동
#   verify: python3 "${EZERAGENT_PACK_DIR:-$HOME/.EZERagent/pack}/bin/EZERagent_orchestra.py" check  → 4종 생존 GREEN
#   on_fail: python3 "${EZERAGENT_PACK_DIR:-$HOME/.EZERagent/pack}/bin/EZERagent_preflight.py" --fix  (처방 내장 진단)
```

`agents.json`(`~/.EZERagent/pack/agents.json`)에서 각 에이전트의 기동 명령을 환경에 맞게 수정하세요
(claude/gemini/codex/grok 어댑터 정의).

## 🧑 제거 [HUMAN — 비가역 단계 포함]

```sh
# 🧑 [HUMAN] 상시 가동 해제 (가역)
EZERagent daemon uninstall                         # 상시 가동 해제(설치했다면)
# 🧑 [HUMAN] macOS: Applications에서 EZERagent.app 삭제 + /usr/local/bin/EZERagent{,d} 심링크 제거
# 🧑 [HUMAN] Windows: 제어판에서 MSI 제거
# 🧑 [HUMAN] 🚧 [BOUNDARY INST-DENY-03] ⚠ 비가역 완전 삭제 — 워커 자율 실행 금지·정지·오너 보고
rm -rf ~/.EZERagent ~/.local/state/EZERagent             # pack·트랜스크립트·상태 완전 삭제(선택)
```

## 환경 변수 (요약)

`EZERAGENT_SOCKET` · `EZERAGENT_NO_AUTOSTART`(1=데몬 자동기동 끔) ·
`EZERAGENT_NO_CLI_AUTOINSTALL`(1=에이전트 CLI 자동설치 끔) · `EZERAGENT_PACK_DIR` ·
거버넌스: `EZERAGENT_LOAD_THRESHOLD`·`EZERAGENT_PROC_THRESHOLD`·`EZERAGENT_DUP_THRESHOLD`·`EZERAGENT_AUTOKILL_DUP`·`EZERAGENT_IDLE_SECONDS` ·
에제르: `EZERAGENT_TYPING_GUARD_SECS`·`EZERAGENT_FEED_REMIND_SECS`·`EZERAGENT_MASTER_DEADMAN_SECS`·`EZERAGENT_AGENT_AUTORESTART`·`EZERAGENT_RECALL_RETAIN_DAYS`·`EZERAGENT_TODO_DIRS`
(상세는 README.md)
