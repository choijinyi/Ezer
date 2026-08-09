# ezer 0.2.2

**오염된 프로필에 설치해도 안전** — ezer 마스터를 사용자 `~/.claude`(외부 터미널 체계·구 지침 오염
가능)로부터 **격리**해, 어떤 프로필 상태에서 설치해도 ezer가 깨끗이 부팅됩니다. (Apple Silicon arm64)

## 하이라이트

### ezer 전용 CLAUDE_CONFIG_DIR 격리 (근본 사고 차단)
다른 맥에 설치 시 표준 claude의 공용 `~/.claude`에 남은 **외부 터미널 체계·구 지침**이 마스터를
하이재킹해 외부 체계로 헛돌다 멈추는 사고가 있었습니다. 0.2.2는 이를 근본 차단합니다.

- **격리**: ezer가 띄우는 claude는 전용 `CLAUDE_CONFIG_DIR=~/.ezer/claude`로 기동 — 사용자
  `~/.claude`를 **읽지도, 지우지도 않습니다.**
- **자동 셋업**: pack 설치 시 `~/.ezer/claude/`에 ezer 라우터(`CLAUDE.md` → `~/.ezer/pack`
  디렉티브 라우팅)와 SessionStart hook(`settings.json`)을 보존 모드로 설치.
- **오염 환경 / 깨끗한 환경 동시 안전**: 오염돼 있으면 무시(안 읽음), 깨끗하면 새 디렉터리만
  추가(회귀 0). 사용자 프로필 **불가침** — 자동 삭제·덮어쓰기 없음.
- **인증 보존**: macOS 인증은 계정 단위 Keychain이라 격리해도 로그인이 유지됩니다.
- **preflight C31**: 격리 라우터 설치 확인 + 사용자 프로필의 외부 체계·구지침을 **감지·경고**
  (삭제는 사용자 선택).

## 설치

`docs/INSTALL.md` 참조. macOS(Apple Silicon): DMG 드래그 → 첫 실행은 우클릭→열기. 기존
사용자는 자동 업데이트로 수신. **마스터는 ezer 진입점**(ezer.app / `ezer launch-agent --role master`)
으로 기동하세요 — 전용 config dir로 격리됩니다.

## 검증

- `cargo test`·`cargo clippy --bins`·release build 통과
- `pack::` 격리 셋업·설치 불변식 8종 통과 · preflight C31 감지 로직 · 빌드 바이너리 `init-pack`
  격리 디렉터리 생성 end-to-end

## 알려진 한계

- 격리는 ezer 진입점으로 기동할 때 적용됩니다. 표준 `claude`를 직접 실행하면 여전히 사용자
  `~/.claude`를 읽습니다(비공식 경로) — preflight C31이 오염 시 경고합니다.
- macOS 미공증 — 첫 실행 우클릭→열기. Windows 빌드는 크로스컴파일(미검증, 스모크테스트 권장).
