# EZERagent 리브랜딩 — 배포 전 마무리 항목

EZERagent는 같은 저작자의 cys-terminal을 리브랜딩해 이어가는 제품이다. 식별자·경로·저장소
배선은 전부 교체됐다. **새 브랜드에는 새 서명 키페어를 발급했다** — 저작자가 기존 키를
보유하고 있으므로 재사용도 가능했지만, 별개 제품으로 배포 채널을 분리하는 편이 깨끗하다
(대신 기존 cys-terminal 설치본은 EZERagent 업데이트를 받지 않는다 — 의도된 분리다).

릴리스를 실제로 배포하기 전에 아래를 확인하라. 소스 업로드와 CI 빌드 자체는 이미 동작한다.

## 1. 서명키 (반영 완료 — 백업은 오너 몫)

EZERagent 자체 minisign 키페어를 생성해 배선했다. 업데이터 서명과 팩 서명이 **같은 키**를
쓴다 — `build.rs`가 `tauri.conf.json`의 pubkey와 `trusted-keys.json`의 key_id를 병합해
단일 키링을 만들기 때문이다.

- **새 key_id**: `1703EEA014899763` (업스트림 `39E60A702949D6C3` 대체)
- 배선한 곳: `src-tauri/tauri.conf.json`(pubkey) · `EZERagent-pack/trusted-keys.json`(key_id) ·
  `.github/workflows/release.yml`·`pack-release.yml`(KEY_ID) ·
  `src/packsig.rs`·`src/bin/EZERagent.rs`(키링 검증 테스트 핀)
- GitHub Secrets: `TAURI_SIGNING_PRIVATE_KEY` · `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`

### ★개인키 백업 (오너가 직접 해야 한다)

개인키는 저장소 밖 `~/.EZERagent-signing/` 에만 있다.

| 파일 | 내용 |
|---|---|
| `updater.key` | 개인키 — **절대 커밋 금지** |
| `updater.key.pub` | 공개키 (공개해도 무방) |
| `updater-key.password` | 개인키 암호 (32자 무작위) |

**이 폴더를 잃으면 기존 설치본이 받아들이는 업데이트를 영구히 발행할 수 없다.** 업데이터는
공개키 핀으로 서명을 검증하므로, 키를 새로 만들면 이미 배포된 설치본은 새 업데이트를
거부한다. 안전한 곳(암호 관리자·오프라인 매체)에 지금 백업하라.

## 2. 팩 서명 신뢰키

위 1번 키를 공유한다. `trusted-keys.json`의 `pubkey` 필드가 공개 저장소에서 비어 있는 것은
정상이다 — `build.rs`가 빌드 시 `tauri.conf.json`에서 주입한다. `not_after`(2030-01-01)는
그대로 두었다.

## 3. 저작자·연락처·홈페이지 (반영 완료)

오너 지정값으로 교체했다 — 저작자 **Choi jinyi**, 연락처 이메일 `ezer.agent` (gmail),
홈페이지 **www.kaea.ai.kr**.

| 위치 | 반영 내용 |
|---|---|
| `LICENSE` | Choi jinyi 단독 저작권 (저작자 본인이므로 업스트림 고지 병기 불요) |
| `README.md` · `README.en.md` · `SECURITY.md` | 연락처·취약점 신고처를 EZERagent 주소로 교체 |
| `src-tauri/src/main.rs` 호스트 허용목록 | `kaea.ai.kr` (정확일치 + 서브도메인이라 `www.` 포함) |
| `ui/src/main.ts`·`updateplan.ts`·`updateplan.test.ts` | 본체 수동 다운로드 안내를 `www.kaea.ai.kr`로 |
| `docs/RELEASE.md` | 배지 안내 문구의 홈페이지 주소 교체 |

남아 있는 `cysinsight` 문자열은 두 종류뿐이며 **연락처가 아니다**: ①`EZERagent-pack/bin/EZERagent_org.py`
등의 **테스트 픽스처 계정 핸들** ②`scripts/secret-scan.sh`의 **개인 프로필 탐지 패턴**.
둘 다 브랜드 표기가 아니라 동작 요소라 건드리지 않았다.

> 이 문서에 이메일 주소를 문자 그대로 적지 마라 — `scripts/secret-scan.sh`가 PUBLIC 발행 전
> 하드 게이트로 차단한다(허용은 `README.md`·`README.en.md`·`SECURITY.md`뿐).

## 4. 아이콘·브랜드 아트워크 (반영 완료)

`src-tauri/icons/*` 17종을 EZERagent 로고로 교체했다. 원본 로고가 가로 배너라
좌측 E 글리프만 떼어내(흰 배경 → 알파) 1024 정사각 캔버스에 78% 크기로 배치한 뒤
`tauri icon` 으로 세트를 생성했다. 로고를 바꾸려면 같은 절차를 반복한다.

## 5. pro 라이선스 발급키

`src/license.rs`는 verify-only다(발급키 미탑재 — 설계상 정상). 무료 기능은 전부 동작하며,
pro 티어 라이선스를 발급하려면 별도 서명키가 필요하다. 발급 계획이 없으면 그대로 두면 된다.

## 6. 레거시 식별자 (브랜드 아님 — 그대로 둠)

`AITERM_SOCKET` 환경변수와 `ui/package.json`의 패키지명 `aiterm-ui`는 cys 브랜드가 아니라
업스트림의 더 오래된 내부 이름이다. 동작에 영향이 없어 리네임하지 않았다.
