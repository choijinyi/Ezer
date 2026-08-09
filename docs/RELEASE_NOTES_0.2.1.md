# ezer 0.2.1

**구독 없이도 쓰는 에제르** — agy·codex 구독·CLI가 없는 사용자를 위한 리뷰어 무구독 폴백과,
PUBLIC repo 발행 안전 가드레일을 추가했습니다. (Apple Silicon arm64 빌드)

## 하이라이트

### 리뷰어 무구독 폴백 (agy·codex 없이도 RSI 라운드 가동)
agy(Antigravity)·codex는 검증·반박 리뷰어의 *기본 전제*일 뿐 절대 전제가 아닙니다. 구독·CLI가
없으면 master가 그 자리에 **Claude 대체 리뷰어를 자동 기동**합니다 — 부트가 멈추지 않습니다.

- **결정론 감지**: `ezer_orchestra.py boot-reviewers` 가 리뷰어 CLI를 스크립트로 감지(자연어
  재추론 금지). 2층 폴백 — ① 미설치 즉시 대체 ② 설치됐으나 각성 실패 시 2차 대체.
- **Claude 대체 모드**(REVIEWER_DIRECTIVE §6): `reviewer-claude-1`=반증 페르소나 ·
  `reviewer-claude-2`=교차 렌즈 · 익명화 peer-review · 불일치는 master 독립 재유도.
  벤더 다양성이 약해지는 한계는 **"동급 아님"으로 정직히 라벨링**.
- 부트 시퀀스(MASTER_DIRECTIVE §0 ④-b)·`check` 유효 로스터·`ezer_boot_node` 대체 역할 반영.

### PUBLIC repo 발행 안전 가드레일 4종
오픈소스 공개 저장소에 개인정보 유출 없이 "전부 올리기"를 지속 가능하게 만드는 장치입니다.

- **.gitignore 강화** — `ezer-pack/memory/*` 차단(색인·템플릿만 allowlist) + `*.bak-*`:
  `git add -A`로 개인 기억·계정이 공개되는 전방 위험을 영구 차단.
- **scripts/secret-scan.sh** — 개인경로·프로필·이메일·토큰 fail-closed 게이트(deny-by-default·
  스캐너 self-skip·정적매칭 근본한계 명문화). pre-commit 훅으로 설치 가능.
- **scripts/sync-pack.sh** — 배포본→정본 정제 동기화(개인 산출 제외·게이트 경유·dry-run 기본·
  자동 커밋/push 없음) — 드리프트 제거.

### git 온보딩
- 부트 프리플라이트 **`C30.git`** — git 결정론 점검 + OS별 설치 안내(부재는 WARN — 일반 사용자
  기본 기능엔 불필요, 기여·harness-creator·RSI엔 필수).
- `README.md`·`README.en.md`·`docs/INSTALL.md`에 git 설치법(macOS/Linux/Windows + clone) 추가.

### 배포 무결성 수정
- `src/pack.rs` 임베드 목록에 `ezer_boot_node.py` 추가 — repo엔 있으나 `include_str!` 누락으로
  배포본에 안 실리던 결함 수정(리뷰어 폴백이 신규 머신에서 깨지는 것을 방지).

## 설치

`docs/INSTALL.md` 참조. macOS(Apple Silicon): DMG 드래그 설치. 기존 0.2.0 사용자는 자동
업데이트로 수신(사용자가 수정하지 않은 pack 파일은 매니페스트 기반으로 자동 갱신).

## 검증

- `cargo build --release`·`cargo clippy --bins`·`cargo test` 통과
- `ezer_orchestra`/`ezer_boot_node` self-test · `pack::` 임베드·설치 불변식 8종 통과
- secret-scan 전수 clean · 신규 머신 시뮬(빈 HOME pack 자동설치 — boot_node 포함) 검증

## 알려진 한계

- Claude 대체 리뷰어는 보편적이나 **벤더(모델 패밀리) 다양성이 약함** — 교차벤더가 필요하면
  리뷰어 한 칸을 로컬 모델(Ollama)·Qwen OAuth로 교체 권고(REVIEWER_DIRECTIVE §6).
- macOS 미공증 시 Gatekeeper 우회 필요(우클릭→열기) — 서명·공증은 RELEASE.md 참조.
- 이번 빌드는 Apple Silicon(arm64) 단일 — Intel(x86_64)·Windows 빌드는 별도.
