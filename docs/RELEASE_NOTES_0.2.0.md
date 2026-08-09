# EZERagent 0.2.0

**AI 조직(에제르)이 거주하는 터미널** — 에제르 네이티브 기능 19건 + 신규 머신 zero-setup 온보딩.

## 하이라이트

### 에제르 네이티브 기능 19건 (디렉티브 수동 의무의 기계화)
master·CSO가 손으로 하던 운영 의무를 데몬이 1급 기능으로 흡수했습니다.

- **관제**: `EZERagent status`(전 노드 1콜 보드), `EZERagent set-status`(에이전트 자기보고)
- **수명주기**: `EZERagent cycle-agent`(컨텍스트 60% 사이클 집행 — 파일 해시 게이트·2-phase handshake),
  에이전트 사망 즉시 감지+자동 재기동, `EZERagent restore`(조직 복원), `EZERagent reinject`(디렉티브 드리프트)
- **안전·무결성**: `EZERagent pause/resume`(kill-switch), 승인 격상(자동응답 없음), 헬스룰 조치 바인딩,
  `EZERagent attest`(트랜스크립트 해시체인 — 변조 검출), 발신자 신원 커널 검증 + role→role ACL
- **협업**: todo 워치, 원샷 타이머(`schedule --in`), 역할 글롭 브로드캐스트, feed aging, 입력 타이핑 가드

전체 표·설계 근거: `docs/EZERagent-native-features-proposal-2026-06-12.md`, `README.md`.

### 신규 머신 zero-setup 온보딩
받는 사람이 데몬을 따로 설치할 필요가 없습니다.
- **CLI/앱 자동 기동** — 데몬이 없으면 동봉된 `EZERagentd`를 분리 프로세스로 자동 기동(옵트아웃 `EZERAGENT_NO_AUTOSTART=1`)
- **Pack 자동 설치** — 첫 기동 시 `~/.EZERagent/pack` 자동 설치(보존 모드)
- **pane 내 PATH 주입** — pane 안의 AI가 `EZERagent`를 즉시 사용(심링크 불요)
- **`EZERagent daemon install`** — 재부팅 후 24/365 상시 가동(macOS launchd KeepAlive / Windows 작업 스케줄러)

## 설치

`docs/INSTALL.md` 참조. macOS: DMG 드래그 설치. Windows: MSI/ZIP(CLI+데몬).

## 검증

- `cargo build --release`·`cargo clippy --bins`(0경고)·`cargo test` 통과
- 격리 데몬 스모크 23항목 + 신규 머신 시뮬레이션(자동기동·자동설치·PATH·daemon install 가드) 통과
- 실데몬 0.2.0 교체·가동 확인

## 알려진 한계

- GUI 앱(Tauri)의 Windows 빌드는 잔여 — 현재 Windows는 CLI+데몬 중심
- macOS 빌드 미서명 시 Gatekeeper 우회 필요(우클릭→열기) — 서명·공증은 RELEASE.md 참조
- 실에이전트 대상 `cycle-agent` 풀 E2E, master dead-man(900s)·retention prune(6h) 타이머는 코드 검증만 수행
